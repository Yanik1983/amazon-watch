# Handoff: Amazon free-shipping-to-Israel watcher

Written 2026-09-12. Status: brainstorming, nothing built yet. No code, no repo, no approval given for any design.

## Goal

Monitor one Amazon.com product and send a push notification when its eligibility for
AmazonGlobal free shipping to Israel ("FREE international delivery on orders over $49")
changes. The user wants to know the moment the flag flips (either direction).

## Target product

- Short link given by user: https://a.co/d/07Wuw755
- Resolves to: https://www.amazon.com/dp/B07W1P15GL
- ASIN: `B07W1P15GL`
- Title: "DI ORO Silicone Ladle - Soup & Serving, 600F Heat Resistant, Black"
- State on 2026-09-12 with ship-to = Israel: **not free**. Delivery block read
  "ILS 58.91 delivery Thursday, October 15".

## Feasibility findings (verified 2026-09-12 from the user's home IP)

1. Plain `requests` with a Chrome User-Agent gets a captcha page immediately
   (200 status, ~3.7 KB body containing "captcha"). Unusable.
2. `curl_cffi` with `impersonate="chrome"` gets the full product page (~2.7 MB). Works.
3. Ship-to country can be set without login:
   - GET the product page, extract the token with regex
     `anti-csrftoken-a2z(?:"|&quot;)\s*(?::|value=)\s*(?:"|&quot;)([^"&]+)`
   - POST `https://www.amazon.com/portal-migration/hz/glow/address-change?actionSource=glow`
     with form fields `locationType=COUNTRY, countryCode=IL, deviceType=web,
     storeContext=generic, pageType=Detail, actionSource=glow` and headers
     `anti-csrftoken-a2z: <token>`, `Referer: <product url>`, `X-Requested-With: XMLHttpRequest`.
   - Response JSON had `"isAddressUpdated":1,"successful":1`. After that, a second GET of the
     product page showed `id="glow-ingress-line2"` = "Israel".
4. Eligibility signal: inside `#deliveryBlockMessage` there is a span with attribute
   `data-csa-c-delivery-price`. Currently `"ILS 58.91"`. When eligible it should read `"FREE"`
   (there is a second span with `"fastest"` for the paid express option; ignore it).
   Fallback text signals: "FREE international delivery" (eligible) vs
   "Shipping & Import Fees Deposit" (not eligible). Container id `mir-layout-DELIVERY_BLOCK`.
5. Not yet checked: whether GitHub Actions datacenter IPs get captcha'd. This is the main
   open risk for hosting on Actions. Also not checked: `#merchantInfo` (sold by / shipped by),
   which may matter because the promo generally applies only to items shipped by Amazon.

Probe script used (throwaway, run from a temp dir):

```python
import re, html
from curl_cffi import requests
s = requests.Session(impersonate="chrome")
s.headers.update({"Accept-Language": "en-US,en;q=0.9"})
url = "https://www.amazon.com/dp/B07W1P15GL"
t = s.get(url, timeout=30).text
tok = re.search(r'anti-csrftoken-a2z(?:"|&quot;)\s*(?::|value=)\s*(?:"|&quot;)([^"&]+)', t).group(1)
s.post("https://www.amazon.com/portal-migration/hz/glow/address-change?actionSource=glow",
       data={"locationType": "COUNTRY", "countryCode": "IL", "deviceType": "web",
             "storeContext": "generic", "pageType": "Detail", "actionSource": "glow"},
       headers={"anti-csrftoken-a2z": tok, "Referer": url, "X-Requested-With": "XMLHttpRequest"},
       timeout=30)
t = s.get(url, timeout=30).text
print(re.findall(r'data-csa-c-delivery-price="([^"]*)"', t))
```

## Reference implementation to copy from

The user already has a working watcher with the same shape (poll, diff, notify, persist,
render status page): the Aliathon Aegean availability watcher.

- Local checkout: `C:\VS Code Projects\Aliathon scraper`
- GitHub: https://github.com/Yanik1983/aliathon-watch (public)
- Layout: `watch/{config,client,parser,finder,confirm,state,history,notify,render,pagecrypt,main}.py`,
  `tests/` (pytest), `.github/workflows/poll.yml`, `state.json`, `history.json`, `docs/index.html`
  served via GitHub Pages.
- Workflow pattern worth reusing verbatim: one long Actions job loops the poll every
  `INTERVAL_SECONDS` (600) for `LOOP_MINUTES` (350); cron `7 */3 * * *` plus push and
  `workflow_dispatch` start a new job; `concurrency: group: poll, cancel-in-progress: true`
  kills the previous one. This was needed because a plain `*/10` cron fired only ~3 times in 8 h.
- Notifications: ntfy.sh. Existing secrets on aliathon-watch: `NTFY_TOPIC`
  (`aliathon-7f3a9c2e5b1d4a80`), `NTFY_EMAIL` (yan.korgozki@gmail.com). `NTFY_TOKEN` was still
  unset as of 2026-09-10, so ntfy email relay is skipped there. `watch/notify.py` in that repo
  is directly reusable.
- The user's `gh` token has `workflow` scope.

## Open design questions (asked, not yet answered)

Question 1, hosting. Options presented to the user:

- A (recommended): new GitHub repo `amazon-watch`, same Actions loop pattern, ntfy push on flip.
  Verify with one manual dispatch that Amazon does not captcha the Actions runner before
  building the rest; if it does, fall back to B.
- B: local script on the user's Windows PC via Task Scheduler. Stable home IP, but only runs
  while the PC is on.
- C: add a second watcher inside the aliathon-watch repo. Least setup, mixes unrelated things.

Not yet asked:

- Same ntfy topic as Aliathon or a new one?
- Poll interval (Aliathon uses 10 min; Amazon may deserve slower, e.g. 30 to 60 min, to
  limit bot detection).
- Also track and chart the item price, or eligibility only?
- Alert on both directions of the flip, or only when it becomes free?
- Should a status page (GitHub Pages) exist, or is push notification enough?

## Suggested minimal design once questions are answered

- `watch/config.py`: ASIN list (start with one), country `IL`, ntfy env vars, paths.
- `watch/client.py`: `curl_cffi` session, address-change once per session, GET product page,
  raise `FetchError` on captcha (detect small body containing "captcha") or non-200.
- `watch/parser.py`: return `Eligibility(free: bool, delivery_price: str, merchant: str,
  title: str)` from the HTML; unit-test against saved fixtures (one eligible, one not).
- `watch/main.py`: fetch, parse, compare with `state.json`, notify on change, persist.
  Alert after N consecutive fetch failures, same as Aliathon `FAIL_ALERT_AT = 3`.
- Dependencies: `curl_cffi`, nothing else beyond stdlib. `requests` is not sufficient.
- Fixture capture: save the current not-free page HTML once for tests; an eligible fixture
  can be captured from any other ASIN that currently shows `data-csa-c-delivery-price="FREE"`.

## Process notes

- The session was running the superpowers brainstorming skill on the "architectural" path
  (new project). Next step after the user answers the questions: propose 2 to 3 approaches,
  present the design in sections, write the spec to `docs/superpowers/specs/`, then invoke
  writing-plans.
- The user communicates tersely; caveman mode was active in chat. Persisted files use normal prose.
