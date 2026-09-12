# Amazon free-shipping-to-Israel watcher: design

Date: 2026-09-12. Status: approved in chat, ready for implementation planning.

## Goal

Poll one Amazon.com product page once an hour and send a push notification the
moment the product becomes eligible for AmazonGlobal free shipping to Israel
("FREE international delivery on orders over $49"). A public status page shows
the current state and the history of flips.

## Decisions

| Question | Decision |
|---|---|
| Hosting | New GitHub repo `amazon-watch`, GitHub Actions long-running loop, same pattern as `aliathon-watch`. Fallback if the Actions IP is captcha-blocked: local script on the user's PC via Task Scheduler (separate decision, not designed here). |
| Notification channel | ntfy.sh, same topic as the Aliathon watcher (secret `NTFY_TOPIC`), optional email copy (`NTFY_EMAIL`, `NTFY_TOKEN`). |
| Poll interval | 60 minutes. |
| Price tracking | None. Eligibility only. |
| Alert direction | Push only when eligibility changes from paid to FREE. The reverse flip is recorded in history and on the page but does not push. |
| Status page | Yes. Static HTML committed to `docs/index.html`, served by GitHub Pages. |
| Code shape | Port of the Aliathon skeleton: small modules under `watch/`, pytest with saved HTML fixtures. |

## Target product

- ASIN `B07W1P15GL`, "DI ORO Silicone Ladle - Soup & Serving, 600F Heat Resistant, Black".
- URL `https://www.amazon.com/dp/B07W1P15GL`.
- State on 2026-09-12 with ship-to Israel: not free ("ILS 58.91 delivery").

## Verified fetch method (2026-09-12, home IP)

1. Plain `requests` with a browser User-Agent gets a captcha page (HTTP 200, about 3.7 KB body
   containing "captcha"). Not usable.
2. `curl_cffi` with `impersonate="chrome"` returns the full page (about 2.7 MB).
3. Ship-to country is set without login:
   - GET the product page, extract the anti-CSRF token with
     `anti-csrftoken-a2z(?:"|&quot;)\s*(?::|value=)\s*(?:"|&quot;)([^"&]+)`.
   - POST `https://www.amazon.com/portal-migration/hz/glow/address-change?actionSource=glow`
     with form fields `locationType=COUNTRY`, `countryCode=IL`, `deviceType=web`,
     `storeContext=generic`, `pageType=Detail`, `actionSource=glow` and headers
     `anti-csrftoken-a2z`, `Referer` (product URL), `X-Requested-With: XMLHttpRequest`.
   - Response JSON contains `"isAddressUpdated":1`. A second GET of the product page then shows
     `id="glow-ingress-line2"` containing "Israel".
4. Eligibility signal: inside the delivery block (`#deliveryBlockMessage`, container
   `mir-layout-DELIVERY_BLOCK`) the first span carrying `data-csa-c-delivery-price` holds the
   delivery price. Paid: a currency string such as `ILS 58.91`. Free: `FREE`. A second span with
   `fastest` describes the paid express option and is ignored. Text fallbacks: "FREE international
   delivery" means eligible, "Shipping & Import Fees Deposit" means not eligible.
5. Not yet verified: whether GitHub Actions runner IPs get the captcha page. This is checked
   first, before the rest is built.

## Components

All code lives in `watch/` as a package, run with `python -m watch.main`.

### `config.py`

Constants and environment lookups: `ASIN = "B07W1P15GL"`, `COUNTRY = "IL"`,
`PRODUCT_URL`, `FAIL_ALERT_AT = 3`, `NTFY_TOPIC`, `NTFY_EMAIL`, `NTFY_TOKEN`,
`NTFY_SERVER` (default `https://ntfy.sh`), `STATE_PATH = "state.json"`,
`HISTORY_PATH = "history.json"`, `PAGE_PATH = "docs/index.html"`.

### `client.py`

`fetch_product(asin: str, session=None) -> str` returns the product page HTML with the
ship-to country set to Israel. Steps: create a `curl_cffi` session impersonating Chrome with
`Accept-Language: en-US,en;q=0.9`; GET the page; extract the token; POST the address change;
GET the page again; return the body.

Raises `FetchError` when: any response is not HTTP 200; a page body is shorter than
`MIN_PAGE_CHARS` (20,000 characters, against a real page of about 2.7 million and a captcha
page under 4,000); a body contains "captcha" (case-insensitive) within its first
`CAPTCHA_SCAN_CHARS` (5,000) characters; the token regex does not match; the address-change
response does not match `"isAddressUpdated"\s*:\s*1(?!\d)`, a pattern that a value such as
10 cannot satisfy; or the final page does not contain "Israel" in the glow ingress line. Every
failure message names the step that failed. All three requests share the `TIMEOUT` constant
(30 seconds).

The session is injectable so tests use a fake with canned responses. No network in tests.

### `parser.py`

`parse(html: str) -> Product` where `Product` is a frozen dataclass:
`title: str`, `free: bool`, `delivery_text: str`, `merchant: str`.

- `title`: text of `#productTitle`, whitespace collapsed; empty string if missing. The
  element's text is read with a nesting-aware scan (`_element_text`) rather than a lazy
  regex, so nested spans do not truncate it; an element that does not close within
  `ELEMENT_WINDOW` characters yields an empty string.
- `delivery_text`: value of the first `data-csa-c-delivery-price` attribute, HTML-unescaped, that
  is not `fastest` (case-insensitive; `fastest` spans describe the paid express option and are
  skipped). The search is scoped to `html[anchor:anchor + DELIVERY_BLOCK_WINDOW]` when the
  `mir-layout-DELIVERY_BLOCK` anchor is present, otherwise the whole document.
- `free`: the normalised value, upper-cased, is one of `FREE`, `$0.00`, `0.00`, `ILS 0.00`. If
  every `data-csa-c-delivery-price` match is `fastest` (or the attribute is missing), the
  delivery block text is checked instead for "FREE international delivery".
- `merchant`: text of `#merchantInfo` (or `#sellerProfileTriggerId`), read with the same
  nesting-aware scan, whitespace collapsed; empty string if missing. Informational only,
  shown on the page. The real page for the watched ASIN carries neither element.

Raises `ParseError` when neither the `data-csa-c-delivery-price` attribute nor the
`mir-layout-DELIVERY_BLOCK` container is present. Parsing uses regular expressions on the
raw HTML, no HTML parser dependency.

### `jsonio.py`

`read_json(path, default, what)` returns the parsed file or `default`, logging a warning
naming `what` when the file is missing or unreadable. `write_json(path, data, sort_keys=False)`
writes to a sibling temporary file and renames it over the target with `os.replace`, so a poll
cancelled mid-write never leaves a half-written file. `state.py` and `history.py` both use it.

### `state.py`

Default state:

```json
{
  "last_checked": null,
  "last_success": null,
  "fail_count": 0,
  "last_error": null,
  "product": null
}
```

`product` holds the last successfully parsed `Product` as a dict plus `checked_at`.

### `history.py`

`load(path) -> list[dict]`, `save(path, entries)`, `append_flip(entries, when, free, delivery_text)`,
all built on `jsonio`.
Each entry: `{"at": ISO UTC, "free": bool, "delivery_text": str}`. The first successful poll
appends the initial observation so the page has a starting row.

### `notify.py`

`send(title, body, click=None, priority="high", tags=...)` posts to `NTFY_SERVER/NTFY_TOPIC`,
adds `Authorization` when `NTFY_TOKEN` is set, adds `Email` when `NTFY_EMAIL` is set. Returns
`True` on HTTP 200. Default tags `package,tada`.

Header values are folded to ASCII first (`unicodedata.normalize` then `encode("ascii",
"replace")`), because HTTP headers cannot carry a Hebrew or typographic character that a
product title may contain; the body is sent as UTF-8 bytes and keeps the original text. When
the server answers with a non-200 and an `Email` header was sent, the message is retried once
without that header, since ntfy.sh rejects anonymous email relay with HTTP 400. A transport
failure, where no answer arrives at all, is not retried; the next poll tries again.

### `render.py`

`render_page(state, history, now) -> str`. Static HTML, no JavaScript, no password card.
Timestamps are rendered in `config.DISPLAY_TZ` (Asia/Jerusalem) with the UTC time beside them,
falling back to UTC alone where no time zone database is installed. The page carries a
"Check now" button linking to `config.WORKFLOW_URL`, the workflow's Run page on GitHub, and a
"Next automatic check" line one `config.POLL_INTERVAL_SECONDS` after the last check. A button
that triggered the run without leaving the page would need a GitHub token in a public page, so
the link is used instead.
Contents: product title linking to the product URL; a large badge reading "FREE shipping to
Israel" or "Paid shipping" followed by the delivery text; merchant line; last checked and last
success timestamps in UTC; a warning line with `fail_count` and `last_error` when
`fail_count > 0`; a table of flips (time, state) newest first; `<meta http-equiv="refresh"
content="600">`. Inline CSS, readable on a phone.

### `main.py`

`run(fetch=fetch_product, notifier=notify.send, state_path, history_path, page_path, now=None) -> dict`:

1. Load state and history.
2. Call `fetch(config.ASIN)` then `parse`.
3. On `FetchError` or `ParseError`: increment `fail_count`, store `last_error`, and when
   `fail_count == FAIL_ALERT_AT` send one push titled "Amazon watcher failing" with priority
   `default` and tag `warning`. While failures continue, the warning repeats every
   `FAIL_REWARN_EVERY` (24) polls. Keep the previous `product`. Go to step 6.
4. On success: reset `fail_count` to 0, clear `last_error`, set `last_success`. Compare
   `product.free` with the previous `product["free"]`:
   - no previous product (first ever poll, or a lost `state.json`): append the initial
     history entry, and push if the product is already free;
   - previous `False`, now `True`: append a history entry and push "Amazon: free shipping to
     Israel!" with body `<title>` newline `<delivery_text>`, click URL = product URL,
     priority `high`;
   - previous `True`, now `False`: append a history entry, log, no push;
   - unchanged: nothing.
5. Store the new product in state.
6. Set `last_checked`, save state, save history if it changed, render and write the page.
   Return the state.

`main()` configures logging, calls `run()`, logs any unexpected exception and always returns 0
so the workflow commit step still runs.

## Workflow: `.github/workflows/poll.yml`

Copy of the Aliathon loop with these values: `INTERVAL_SECONDS: 3600`, `LOOP_MINUTES: 350`,
`timeout-minutes: 358`, cron `13 */3 * * *`, plus `workflow_dispatch` and `push` to `main` on
paths `watch/**`, `requirements.txt`, `.github/workflows/poll.yml`. `concurrency: group: poll,
cancel-in-progress: true`. Python 3.11, `pip install -r requirements.txt`. Each iteration runs
`python -m watch.main`, commits `state.json history.json docs/index.html` with message
`chore: poll <UTC time> [skip ci]`, rebases on `origin/main` with generated files winning, and
pushes. Secrets passed as env: `NTFY_TOPIC`, `NTFY_EMAIL`, `NTFY_TOKEN`; variable `NTFY_SERVER`.

## Repository setup

- `git init`, default branch `main`, GitHub repo `Yanik1983/amazon-watch`, public.
- Secrets set with `gh secret set` using the same values as `aliathon-watch`.
- GitHub Pages: source `main`, folder `/docs`.
- `requirements.txt`: `curl_cffi`, `requests`. `requirements-dev.txt`: `pytest`.
- `.gitignore`: `__pycache__/`, `.pytest_cache/`, `*.pyc`.
- README: what is watched, how it works, setup steps, how to change the ASIN.

## Build order

1. Repo, config, client, workflow, minimal main that only fetches and logs the delivery text.
2. Push, run one manual dispatch, read the log. If the runner gets the captcha page, stop and
   report; the fallback (local Task Scheduler) is a separate decision.
3. Parser with fixtures, state, history, notify, render, full main, tests.
4. Secrets, Pages, first real poll, confirm the page renders and the state file is committed.

## Testing

pytest, no network. Fixtures under `tests/fixtures/`:

- `not_free.html`: the delivery block, title and merchant sections captured from the real page
  on 2026-09-12, trimmed to the relevant elements (about 20 KB).
- `free.html`: the same structure with `data-csa-c-delivery-price="FREE"` and the "FREE
  international delivery" wording, taken from a real ASIN that currently shows FREE if one is
  found, otherwise hand-edited from `not_free.html`.
- `captcha.html`: the small captcha body.

Test cases:

- `test_parser`: not-free fixture gives `free=False` and `delivery_text="ILS 58.91"`; free fixture
  gives `free=True`; title and merchant extracted; missing delivery block raises `ParseError`.
- `test_client`: token regex on a saved snippet; captcha body raises `FetchError`; short body
  raises; address-change failure raises; glow line without "Israel" raises; happy path returns
  the second page body. Uses a fake session recording calls.
- `test_main`: first poll records history and does not push; paid to FREE pushes once with the
  product URL as click; FREE stays FREE no push; FREE to paid appends history and does not push;
  three consecutive failures send exactly one warning; a failure keeps the previous product in
  state; page and state files are written.
- `test_state`, `test_notify`: ported from the Aliathon watcher.
- `test_history`: append and load round-trip.
- `test_render`: page contains badge text, timestamps, history rows, refresh meta.

## Out of scope

Price tracking, multiple ASINs, login, password-gated page features, retry within a single poll.
