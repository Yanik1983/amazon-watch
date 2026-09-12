# Amazon free-shipping-to-Israel watcher

Polls one Amazon.com product page once an hour and sends a push notification the
moment it becomes eligible for AmazonGlobal free shipping to Israel ("FREE
international delivery on orders over $49"). A public status page shows the current
state and every change observed so far.

**Watching:** ASIN `B07W1P15GL`, DI ORO Silicone Ladle. Change `ASIN` in
`watch/config.py` to watch a different product.

## How it works

1. `watch/client.py` fetches the product page with `curl_cffi` impersonating Chrome
   (plain HTTP clients get a captcha page), sets the ship-to country to Israel through
   Amazon's address-change endpoint, and fetches the page again.
2. `watch/parser.py` reads the delivery block. The first `data-csa-c-delivery-price`
   attribute is `FREE` when the product is eligible, otherwise a price such as `ILS 58.91`.
3. `watch/main.py` compares the result with `state.json`. When the product goes from paid
   to free it sends one ntfy push (high priority) with a link to the product. The reverse
   change is recorded but does not push. Every change is appended to `history.json`.
4. `docs/index.html` is re-rendered on every poll and served by GitHub Pages.
5. If three polls in a row fail (captcha, network, layout change), one warning push is sent.

The GitHub Actions job is one long loop (poll, commit, sleep 60 minutes) that runs for
about 5 h 50 m. A fresh job starts every 3 hours and on every code push, cancelling the
previous one.

## Setup

1. Install the [ntfy](https://ntfy.sh/) app and subscribe to a topic. Treat the topic
   name as a password.
2. Repository secrets (Settings > Secrets and variables > Actions):
   - `NTFY_TOPIC`: the topic name (required)
   - `NTFY_EMAIL`: address for an email copy (optional)
   - `NTFY_TOKEN`: ntfy.sh access token, needed only for the email copy (optional)
3. GitHub Pages: source `main`, folder `/docs`.
4. Run the `poll` workflow manually once (Actions > poll > Run workflow) or push a change.

## Local development

```
python -m pip install -r requirements-dev.txt
python -m pytest
python -m watch.main          # one real poll from this machine
python scripts/capture_fixture.py   # refresh tests/fixtures/not_free.html
```

Tests never use the network.
