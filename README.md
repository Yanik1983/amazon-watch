# Amazon free-shipping-to-Israel watcher

Polls a list of Amazon.com product pages once an hour and sends a push notification
the moment one becomes eligible for AmazonGlobal free shipping to Israel ("FREE
international delivery on orders over $49"). A public status page shows the current
state of every watched product and every change observed so far.

**Status page:** https://yanik1983.github.io/amazon-watch/

**Watched products:** `products.json`. Change it through the `manage` workflow
(below) rather than by hand.

## How it works

1. `watch/products.py` reads `products.json`, the list of ASINs being watched.
2. `watch/client.py` sets the ship-to country to Israel once per cycle, through
   Amazon's address-change endpoint, and then fetches each product page on that
   same session. The fetch uses `curl_cffi` impersonating Chrome, because plain
   HTTP clients get a captcha page. A cycle costs two requests for the handshake
   plus one per product.
3. `watch/parser.py` reads the delivery block of each page. Inside it, the first
   `data-csa-c-delivery-price` attribute that is not the "fastest" express option holds
   the delivery price: `FREE` (or a zero amount) when the product is eligible, otherwise
   a price such as `ILS 58.91`. Amazon shows that price in the caller's own currency, so
   the same product reads `ILS 58.91` from a home connection and `$19.28` from a GitHub
   runner. Only the free values decide eligibility, so the currency does not matter.
4. `watch/main.py` compares each product with `state.json`. It sends one ntfy push
   (high priority, linking to the product) whenever a product becomes free, and also
   when the first observation already finds it free, which covers a lost `state.json`.
   Going back to paid is recorded but does not push. Every change is appended to
   `history.json`.
5. `docs/index.html` is re-rendered on every poll and served by GitHub Pages. It shows
   one card per product, free ones first, when the next automatic check is due, a
   "Check now" button and a "Manage products" button. Timestamps are Jerusalem local
   time with UTC beside them.
6. If three polls in a row fail for a product (captcha, network, layout change), a
   warning push is sent for it and repeated once a day while the failures continue.
   When every watched product fails at once — a captcha or a network problem rather
   than a product problem — one combined warning is sent instead of one per product.

The GitHub Actions job is one long loop (poll, commit, sleep 60 minutes) that runs for
about 5 h 50 m. A fresh job starts every 3 hours and on every code push, cancelling the
previous one.

## Adding and removing products

Actions > **manage** > Run workflow:

- **action**: `add` or `remove`
- **product**: an ASIN (`B07W1P15GL`) or any Amazon product link (`.../dp/B07W1P15GL...`)
- **label**: optional. It names the product on the status page and in its notifications.
  Left empty, the product's own page title is used.

The workflow commits `products.json` and then starts the `poll` workflow, so the new
product is checked and shown on the status page about a minute later. Editing
`products.json` and pushing it by hand does the same thing.

## Notifications

One ntfy topic carries everything. Each push is tagged with the product it belongs to
— `package,ladle` for a free-shipping alert, `warning,ladle` for a failure — so the
ntfy app can filter or mute a single product without touching the repository. The topic
name is the only secret protecting it; treat it as a password.

## Setup

1. Install the [ntfy](https://ntfy.sh/) app and subscribe to a topic.
2. Repository secrets (Settings > Secrets and variables > Actions):
   - `NTFY_TOPIC`: the topic name (required)
   - `NTFY_EMAIL`: address for an email copy (optional)
   - `NTFY_TOKEN`: ntfy.sh access token, needed only for the email copy (optional)
3. GitHub Pages: source `main`, folder `/docs`.
4. Run the `poll` workflow manually once (Actions > poll > Run workflow) or push a change.

## Data files

| File | Written by | Holds |
|---|---|---|
| `products.json` | `manage` only | what is watched: ASIN, label, when it was added |
| `state.json` | the poll | the last reading and failure count per product |
| `history.json` | the poll | every eligibility change, per product, never pruned |
| `docs/index.html` | the poll | the rendered status page |

`state.json` and `history.json` written by the single-product version of the watcher
are migrated automatically on first read; nothing needs doing by hand.

## Local development

```
python -m pip install -r requirements-dev.txt
python -m pytest
python -m watch.main                         # one real poll from this machine
python -m watch.manage --action add --product B07W1P15GL --label "Name"
python scripts/capture_fixture.py            # refresh tests/fixtures/not_free.html
```

Tests never use the network.
