# Amazon Free-Shipping Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll one Amazon.com product hourly from GitHub Actions and push an ntfy notification when it becomes eligible for free shipping to Israel, with a static status page on GitHub Pages.

**Architecture:** A small Python package `watch/` with one module per responsibility (config, client, parser, state, history, notify, render, main), run once per iteration by a long-running GitHub Actions job that commits `state.json`, `history.json` and `docs/index.html` back to the repo. The fetch uses `curl_cffi` to impersonate Chrome and sets the ship-to country to Israel through Amazon's address-change endpoint before reading the delivery block.

**Tech Stack:** Python 3.11, `curl_cffi` (page fetch), `requests` (ntfy only), `pytest`, GitHub Actions, GitHub Pages, ntfy.sh.

**Spec:** `docs/superpowers/specs/2026-09-12-amazon-watch-design.md`

## Global Constraints

- Python 3.11 on `ubuntu-latest`; code must also run on the user's Windows PC for local tests.
- Runtime dependencies: `curl_cffi>=0.7`, `requests>=2.31`. Dev: `pytest>=8`. Nothing else.
- Tests never touch the network. Every HTTP client is injectable and faked in tests.
- Watched product: ASIN `B07W1P15GL`, ship-to country `IL`.
- Poll interval 3600 s, loop length 350 min, cron `13 */3 * * *`.
- Push only on the paid-to-FREE flip. Never push on the FREE-to-paid flip or on the first observation.
- Failure warning push exactly once when `fail_count` reaches 3.
- `python -m watch.main` always exits 0.
- Committed generated files: `state.json`, `history.json`, `docs/index.html`.
- Files persisted to the repo use normal prose (README, docstrings, commit messages).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Working directory for every command: `C:\VS Code Projects\amazon-watch` (already a git repo on `main` with the spec committed).

## File Structure

| Path | Responsibility |
|---|---|
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore` | Project scaffold. |
| `watch/__init__.py` | Empty package marker. |
| `watch/config.py` | Constants and environment lookups. No logic. |
| `watch/client.py` | `fetch_product()`: curl_cffi session, address change, captcha/size checks. Raises `FetchError`. |
| `watch/parser.py` | `parse(html) -> Product`. Regex extraction of title, delivery price, merchant. Raises `ParseError`. |
| `watch/state.py` | Load/save `state.json`. |
| `watch/history.py` | Load/save/append `history.json` (list of flips). |
| `watch/notify.py` | ntfy push with optional email copy and token. |
| `watch/render.py` | `render_page(state, history, now) -> str` static HTML. |
| `watch/main.py` | One poll cycle: fetch, parse, compare, notify, persist, render. |
| `.github/workflows/poll.yml` | Long-running poll loop. |
| `tests/` | One test module per source module, fixtures under `tests/fixtures/`. |
| `README.md` | What it watches, how it works, setup. |

---

### Task 1: Scaffold and config

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `watch/__init__.py`, `watch/config.py`
- Test: `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.ASIN: str`, `config.COUNTRY: str`, `config.BASE_URL: str`, `config.PRODUCT_URL: str`, `config.ADDRESS_CHANGE_URL: str`, `config.FAIL_ALERT_AT: int`, `config.NTFY_SERVER`, `config.NTFY_TOPIC`, `config.NTFY_EMAIL`, `config.NTFY_TOKEN` (all `str`), `config.STATE_PATH`, `config.HISTORY_PATH`, `config.PAGE_PATH` (all `str`).

- [ ] **Step 1: Create scaffold files**

`requirements.txt`:
```
curl_cffi>=0.7
requests>=2.31
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
```

`pytest.ini`:
```
[pytest]
testpaths = tests
```

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

`watch/__init__.py` and `tests/__init__.py`: empty files.

- [ ] **Step 2: Install dev dependencies**

Run: `python -m pip install -r requirements-dev.txt`
Expected: `curl_cffi`, `requests`, `pytest` installed without error.

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:
```python
from watch import config


def test_product_url_uses_asin():
    assert config.ASIN == "B07W1P15GL"
    assert config.PRODUCT_URL == "https://www.amazon.com/dp/B07W1P15GL"


def test_address_change_url():
    assert config.ADDRESS_CHANGE_URL == (
        "https://www.amazon.com/portal-migration/hz/glow/address-change?actionSource=glow"
    )


def test_defaults():
    assert config.COUNTRY == "IL"
    assert config.FAIL_ALERT_AT == 3
    assert config.STATE_PATH == "state.json"
    assert config.HISTORY_PATH == "history.json"
    assert config.PAGE_PATH == "docs/index.html"
    assert config.NTFY_SERVER.startswith("https://")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'config'` or `ModuleNotFoundError`.

- [ ] **Step 5: Write config**

`watch/config.py`:
```python
"""Constants and environment configuration for the Amazon watcher."""
from __future__ import annotations

import os

# Product being watched. Change ASIN here to watch a different item.
ASIN = "B07W1P15GL"
COUNTRY = "IL"

BASE_URL = "https://www.amazon.com"
PRODUCT_URL = f"{BASE_URL}/dp/{ASIN}"
ADDRESS_CHANGE_URL = f"{BASE_URL}/portal-migration/hz/glow/address-change?actionSource=glow"

# Send one warning push when this many consecutive polls have failed.
FAIL_ALERT_AT = 3

# ntfy.sh notification settings, all from repository secrets / variables.
NTFY_SERVER = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_EMAIL = os.environ.get("NTFY_EMAIL", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

# Files committed back to the repository by the poll workflow.
STATE_PATH = "state.json"
HISTORY_PATH = "history.json"
PAGE_PATH = "docs/index.html"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini .gitignore watch/__init__.py watch/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffold and configuration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Client that fetches the page with ship-to Israel

**Files:**
- Create: `watch/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `config.BASE_URL`, `config.ADDRESS_CHANGE_URL`, `config.ASIN`, `config.COUNTRY`.
- Produces: `class FetchError(Exception)`, `fetch_product(asin: str = config.ASIN, session=None, country: str = config.COUNTRY) -> str`, `new_session()` (returns a `curl_cffi.requests.Session`), constants `TOKEN_RE`, `GLOW_RE`, `MIN_PAGE_BYTES = 20_000`, `CAPTCHA_WINDOW = 5_000`.
- A session object must provide `get(url, timeout=...)` and `post(url, data=..., headers=..., timeout=...)` returning objects with `.status_code` and `.text`.

- [ ] **Step 1: Write the failing tests**

`tests/test_client.py`:
```python
import pytest

from watch import client, config
from watch.client import FetchError, fetch_product


class R:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class FakeSession:
    """Returns canned responses in order and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.responses.pop(0)


def page(glow="Israel", token="tok123", size=client.MIN_PAGE_BYTES):
    head = (
        '<html><input name="anti-csrftoken-a2z" value="%s">'
        '<span id="glow-ingress-line2" class="nav-line-2">%s</span>' % (token, glow)
    )
    return head + "x" * size + "</html>"


ADDRESS_OK = R('{"isAddressUpdated":1,"successful":1}')


def test_happy_path_returns_second_page_and_posts_address_change():
    second = page(glow="Israel") + "<!-- second -->"
    s = FakeSession([R(page()), ADDRESS_OK, R(second)])
    out = fetch_product("B07W1P15GL", session=s)
    assert out == second
    assert [c[0] for c in s.calls] == ["GET", "POST", "GET"]
    assert s.calls[0][1] == "https://www.amazon.com/dp/B07W1P15GL"
    method, url, kw = s.calls[1]
    assert url == config.ADDRESS_CHANGE_URL
    assert kw["data"]["countryCode"] == "IL"
    assert kw["data"]["locationType"] == "COUNTRY"
    assert kw["headers"]["anti-csrftoken-a2z"] == "tok123"
    assert kw["headers"]["Referer"] == "https://www.amazon.com/dp/B07W1P15GL"
    assert kw["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_token_regex_matches_json_and_attribute_forms():
    assert client.TOKEN_RE.search('"anti-csrftoken-a2z":"abc+/="').group(1) == "abc+/="
    assert client.TOKEN_RE.search('name="anti-csrftoken-a2z" value="xyz"').group(1) == "xyz"
    assert client.TOKEN_RE.search("&quot;anti-csrftoken-a2z&quot;:&quot;q1&quot;").group(1) == "q1"


def test_non_200_raises():
    s = FakeSession([R(page(), status_code=503)])
    with pytest.raises(FetchError, match="first GET: HTTP 503"):
        fetch_product(session=s)


def test_captcha_page_raises():
    body = "<html><body>Enter the characters you see below (captcha)</body></html>"
    s = FakeSession([R(body)])
    with pytest.raises(FetchError, match="captcha"):
        fetch_product(session=s)


def test_small_body_raises():
    s = FakeSession([R(page(size=100))])
    with pytest.raises(FetchError, match="body too small"):
        fetch_product(session=s)


def test_missing_token_raises():
    body = "<html>" + "x" * client.MIN_PAGE_BYTES + "</html>"
    s = FakeSession([R(body)])
    with pytest.raises(FetchError, match="token"):
        fetch_product(session=s)


def test_address_change_not_updated_raises():
    s = FakeSession([R(page()), R('{"isAddressUpdated":0}')])
    with pytest.raises(FetchError, match="address-change"):
        fetch_product(session=s)


def test_address_change_http_error_raises():
    s = FakeSession([R(page()), R("nope", status_code=400)])
    with pytest.raises(FetchError, match="address-change: HTTP 400"):
        fetch_product(session=s)


def test_glow_not_israel_raises():
    s = FakeSession([R(page()), ADDRESS_OK, R(page(glow="United States"))])
    with pytest.raises(FetchError, match="Israel"):
        fetch_product(session=s)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'watch.client'`.

- [ ] **Step 3: Write the client**

`watch/client.py`:
```python
"""Fetch an Amazon product page with the ship-to country set to Israel.

Plain HTTP clients get a captcha page from Amazon. curl_cffi impersonating Chrome
gets the real page. The ship-to country is changed without login by POSTing to
the "glow" address-change endpoint with the page's anti-CSRF token.
"""
from __future__ import annotations

import logging
import re

from watch import config

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(
    r'anti-csrftoken-a2z(?:"|&quot;)\s*(?::|value=)\s*(?:"|&quot;)([^"&]+)'
)
GLOW_RE = re.compile(r'id="glow-ingress-line2"[^>]*>\s*([^<]*)<', re.S)

# A real product page is around 2.7 MB; a captcha page is under 5 KB.
MIN_PAGE_BYTES = 20_000
CAPTCHA_WINDOW = 5_000


class FetchError(Exception):
    """Raised when the product page could not be fetched in the Israel context."""


def new_session():
    """A curl_cffi session that presents Chrome's TLS and header fingerprint."""
    from curl_cffi import requests  # imported lazily so tests never need it

    s = requests.Session(impersonate="chrome")
    s.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return s


def _check_page(resp, step: str) -> str:
    if resp.status_code != 200:
        raise FetchError(f"{step}: HTTP {resp.status_code}")
    text = resp.text
    if "captcha" in text[:CAPTCHA_WINDOW].lower():
        raise FetchError(f"{step}: captcha page returned")
    if len(text) < MIN_PAGE_BYTES:
        raise FetchError(f"{step}: body too small ({len(text)} bytes)")
    return text


def fetch_product(asin: str = config.ASIN, session=None, country: str = config.COUNTRY) -> str:
    """Return the product page HTML rendered for a shopper in `country`."""
    s = session or new_session()
    url = f"{config.BASE_URL}/dp/{asin}"

    first = _check_page(s.get(url, timeout=30), "first GET")
    m = TOKEN_RE.search(first)
    if not m:
        raise FetchError("token: anti-csrftoken-a2z not found in page")
    token = m.group(1)

    resp = s.post(
        config.ADDRESS_CHANGE_URL,
        data={
            "locationType": "COUNTRY",
            "countryCode": country,
            "deviceType": "web",
            "storeContext": "generic",
            "pageType": "Detail",
            "actionSource": "glow",
        },
        headers={
            "anti-csrftoken-a2z": token,
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise FetchError(f"address-change: HTTP {resp.status_code}")
    if '"isAddressUpdated":1' not in resp.text.replace(" ", ""):
        raise FetchError(f"address-change: not updated: {resp.text[:200]}")

    second = _check_page(s.get(url, timeout=30), "second GET")
    g = GLOW_RE.search(second)
    if not g or "israel" not in g.group(1).lower():
        found = g.group(1).strip() if g else "(no glow line)"
        raise FetchError(f"glow: ship-to country is not Israel: {found}")
    log.info("fetched %s in Israel context (%d bytes)", asin, len(second))
    return second
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add watch/client.py tests/test_client.py
git commit -m "feat: fetch product page with ship-to Israel via curl_cffi

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Workflow, minimal main, GitHub repo, and the Actions captcha gate

This task proves the GitHub Actions runner can fetch the page before the rest is built. It ends with a manual dispatch and a human-readable verdict.

**Files:**
- Create: `.github/workflows/poll.yml`, `watch/main.py` (minimal, replaced in Task 8)

**Interfaces:**
- Consumes: `client.fetch_product`, `client.FetchError`.
- Produces: nothing reused later. `watch/main.py` is fully rewritten in Task 8.

- [ ] **Step 1: Write minimal main**

`watch/main.py`:
```python
"""Temporary poll entry point: fetch the page and log what the delivery block says.

Replaced by the full poll cycle once the parser and persistence modules exist.
"""
from __future__ import annotations

import logging
import re
import sys

from watch.client import FetchError, fetch_product

log = logging.getLogger("watch")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        html = fetch_product()
        prices = re.findall(r'data-csa-c-delivery-price="([^"]*)"', html)
        log.info("delivery prices on page: %s", prices)
    except FetchError as e:
        log.error("fetch failed: %s", e)
    except Exception:  # never fail the workflow
        log.exception("unexpected error")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it locally once**

Run: `python -m watch.main`
Expected: a log line like `delivery prices on page: ['ILS 58.91', 'fastest']` (values may differ). If it logs `captcha page returned` from the home IP, wait ten minutes and retry once; if it still fails, stop and report.

- [ ] **Step 3: Write the workflow**

`.github/workflows/poll.yml`:
```yaml
name: poll

# One long-running job polls every hour for ~5h50m. A new job starts every
# 3 hours (or on a code push) and cancels the previous one, so polling is
# continuous even when GitHub delays scheduled runs.
on:
  schedule:
    - cron: "13 */3 * * *"
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - "watch/**"
      - "requirements.txt"
      - ".github/workflows/poll.yml"

permissions:
  contents: write

concurrency:
  group: poll
  cancel-in-progress: true

env:
  LOOP_MINUTES: 350
  INTERVAL_SECONDS: 3600

jobs:
  poll:
    runs-on: ubuntu-latest
    timeout-minutes: 358
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Poll loop
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          NTFY_EMAIL: ${{ secrets.NTFY_EMAIL }}
          NTFY_TOKEN: ${{ secrets.NTFY_TOKEN }}
          NTFY_SERVER: ${{ vars.NTFY_SERVER }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          end=$(( $(date +%s) + LOOP_MINUTES * 60 ))
          n=0
          while [ "$(date +%s)" -lt "$end" ]; do
            n=$((n + 1))
            echo "::group::poll #$n $(date -u +'%Y-%m-%d %H:%M UTC')"
            python -m watch.main || echo "poll exited non-zero"
            git add --all -- state.json history.json docs/index.html || true
            if git diff --cached --quiet; then
              echo "no changes"
            else
              git commit -q -m "chore: poll $(date -u +'%Y-%m-%d %H:%M UTC') [skip ci]"
            fi
            git fetch -q origin main
            if [ "$(git rev-list --count origin/main..HEAD)" -gt 0 ]; then
              # Generated files always win over whatever landed upstream meanwhile.
              local_head=$(git rev-parse HEAD)
              if ! git pull -q --rebase -X theirs origin main; then
                git rebase --abort || true
                git reset -q --hard origin/main
                git checkout "$local_head" -- state.json history.json docs/index.html
                git commit -q -m "chore: poll $(date -u +'%Y-%m-%d %H:%M UTC') [skip ci]"
              fi
              git push -q origin HEAD:main || echo "push failed; will retry next iteration"
            fi
            echo "::endgroup::"
            remaining=$(( end - $(date +%s) ))
            [ "$remaining" -le "$INTERVAL_SECONDS" ] && break
            sleep "$INTERVAL_SECONDS"
          done
          echo "loop finished after $n poll(s)"
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/poll.yml watch/main.py
git commit -m "feat: poll workflow and minimal fetch entry point

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: Create the GitHub repo and push**

Run:
```bash
gh repo create Yanik1983/amazon-watch --public --source . --push --description "Watches an Amazon product for free shipping to Israel"
```
Expected: repo created, `main` pushed. The push triggers the `poll` workflow.

- [ ] **Step 6: Watch the first run and read the verdict**

Run:
```bash
gh run list --repo Yanik1983/amazon-watch --workflow poll --limit 1
```
Note the run id, then:
```bash
gh run watch <run-id> --repo Yanik1983/amazon-watch --exit-status --interval 15
```
The job loops for hours, so do not wait for it to finish. After about two minutes, read the log:
```bash
gh run view <run-id> --repo Yanik1983/amazon-watch --log 2>&1 | grep -E "delivery prices|fetch failed|unexpected error" | head -5
```

Verdict rules:
- `delivery prices on page: [...]` present: the runner is not blocked. Continue with Task 4.
- `fetch failed: first GET: captcha page returned` (or any other `fetch failed`): the runner is blocked. Cancel the run with `gh run cancel <run-id> --repo Yanik1983/amazon-watch`, then STOP THE PLAN and report to the user. The fallback (a local Task Scheduler job) is a separate decision the user must make.

---

### Task 4: Fixtures and parser

**Files:**
- Create: `tests/fixtures/not_free.html`, `tests/fixtures/free.html`, `tests/fixtures/captcha.html`, `watch/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `class ParseError(Exception)`, `@dataclass(frozen=True) class Product(title: str, free: bool, delivery_text: str, merchant: str)`, `parse(html: str) -> Product`.

- [ ] **Step 1: Capture the real not-free page into a trimmed fixture**

Save this as `scripts/capture_fixture.py` (kept in the repo so the fixture can be refreshed later):

```python
"""Fetch the watched product page from this machine and save a trimmed test fixture.

Usage: python scripts/capture_fixture.py [output path]
Keeps only the sections the parser reads: product title, glow ingress line,
delivery block, merchant info. The full page is about 2.7 MB; the fixture is small.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from watch.client import fetch_product

SECTIONS = [
    (r'<span id="productTitle".*?</span>', re.S),
    (r'<span id="glow-ingress-line2".*?</span>', re.S),
    (r'id="mir-layout-DELIVERY_BLOCK"', 0),
    (r'id="merchantInfo"', 0),
]
WINDOW = 6000  # bytes kept after an id-only anchor


def trim(html: str) -> str:
    parts = ["<html><body>"]
    for pattern, flags in SECTIONS:
        m = re.search(pattern, html, flags)
        if not m:
            parts.append(f"<!-- missing: {pattern} -->")
            continue
        if pattern.startswith("id="):
            parts.append("<div " + html[m.start(): m.start() + WINDOW])
        else:
            parts.append(m.group(0))
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/not_free.html")
    html = fetch_product()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(trim(html), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("delivery prices:", re.findall(r'data-csa-c-delivery-price="([^"]*)"', html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `python scripts/capture_fixture.py`
Expected: `wrote tests/fixtures/not_free.html (... bytes)` and `delivery prices: ['ILS 58.91', 'fastest']` (the price may differ; it must not be `FREE`).

Open `tests/fixtures/not_free.html` and confirm it contains `id="productTitle"`, `data-csa-c-delivery-price="ILS`, `mir-layout-DELIVERY_BLOCK`, and `id="merchantInfo"`. If `merchantInfo` is reported missing, that is acceptable; the parser returns an empty merchant.

- [ ] **Step 2: Derive the free fixture and write the captcha fixture**

Run this Python one-off from the repo root:
```python
import re
from pathlib import Path
src = Path("tests/fixtures/not_free.html").read_text(encoding="utf-8")
free = re.sub(r'data-csa-c-delivery-price="[^"]*"', 'data-csa-c-delivery-price="FREE"', src, count=1)
free = free.replace("Shipping &amp; Import Fees Deposit", "FREE international delivery", 1)
Path("tests/fixtures/free.html").write_text(free, encoding="utf-8")
print(re.findall(r'data-csa-c-delivery-price="([^"]*)"', free))
```
Expected output: `['FREE', 'fastest']`.

`tests/fixtures/captcha.html`:
```html
<html><head><title>Amazon.com</title></head>
<body>
<h4>Enter the characters you see below</h4>
<p>Sorry, we just need to make sure you're not a robot.</p>
<form action="/errors/validateCaptcha"><input type="text" name="field-keywords"></form>
</body></html>
```

- [ ] **Step 3: Write the failing tests**

`tests/test_parser.py`:
```python
from pathlib import Path

import pytest

from watch.parser import ParseError, Product, parse

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_not_free_fixture():
    p = parse(load("not_free.html"))
    assert isinstance(p, Product)
    assert p.free is False
    assert p.delivery_text.startswith("ILS")
    assert "Ladle" in p.title


def test_free_fixture():
    p = parse(load("free.html"))
    assert p.free is True
    assert p.delivery_text == "FREE"


def test_free_by_text_fallback_when_attribute_missing():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK"><span>FREE international delivery '
        "on orders over $49</span></div>"
    )
    p = parse(html)
    assert p.free is True
    assert p.delivery_text == ""


def test_paid_by_text_fallback_when_attribute_missing():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK"><span>$12.34 Shipping &amp; Import '
        "Fees Deposit to Israel</span></div>"
    )
    assert parse(html).free is False


def test_title_and_merchant_whitespace_collapsed():
    html = (
        '<span id="productTitle" class="a-size-large">\n   DI ORO   Ladle \n</span>'
        '<div id="mir-layout-DELIVERY_BLOCK"><span data-csa-c-delivery-price="ILS 58.91"></span></div>'
        '<div id="merchantInfo">Sold by <a>DI ORO</a>\n and shipped by  Amazon</div>'
    )
    p = parse(html)
    assert p.title == "DI ORO Ladle"
    assert p.merchant == "Sold by DI ORO and shipped by Amazon"


def test_missing_delivery_block_raises():
    with pytest.raises(ParseError):
        parse("<html><body><span id='productTitle'>x</span></body></html>")


def test_captcha_page_raises_parse_error():
    with pytest.raises(ParseError):
        parse(load("captcha.html"))


def test_delivery_text_is_html_unescaped():
    html = '<div id="mir-layout-DELIVERY_BLOCK"><span data-csa-c-delivery-price="&#8362;58.91"></span></div>'
    assert parse(html).delivery_text == "\u20aa58.91"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'watch.parser'`.

- [ ] **Step 5: Write the parser**

`watch/parser.py`:
```python
"""Extract the free-shipping eligibility from an Amazon product page."""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

DELIVERY_PRICE_RE = re.compile(r'data-csa-c-delivery-price="([^"]*)"')
DELIVERY_BLOCK_ANCHOR = 'id="mir-layout-DELIVERY_BLOCK"'
DELIVERY_BLOCK_WINDOW = 6000  # bytes of HTML read after the anchor for text fallbacks
TITLE_RE = re.compile(r'id="productTitle"[^>]*>(.*?)</span>', re.S)
MERCHANT_RE = re.compile(r'id="merchantInfo"[^>]*>(.*?)</div>', re.S)
SELLER_RE = re.compile(r'id="sellerProfileTriggerId"[^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


class ParseError(Exception):
    """Raised when the page does not contain a recognisable delivery block."""


@dataclass(frozen=True)
class Product:
    title: str
    free: bool
    delivery_text: str
    merchant: str


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return " ".join(html_mod.unescape(TAG_RE.sub(" ", fragment)).split())


def parse(html: str) -> Product:
    price = DELIVERY_PRICE_RE.search(html)
    anchor = html.find(DELIVERY_BLOCK_ANCHOR)
    if price is None and anchor < 0:
        raise ParseError("no delivery block found on page")

    if price is not None:
        delivery_text = html_mod.unescape(price.group(1)).strip()
        free = delivery_text.upper() == "FREE"
    else:
        delivery_text = ""
        block = _text(html[anchor: anchor + DELIVERY_BLOCK_WINDOW])
        free = "free international delivery" in block.lower()

    t = TITLE_RE.search(html)
    title = _text(t.group(1)) if t else ""

    m = MERCHANT_RE.search(html) or SELLER_RE.search(html)
    merchant = _text(m.group(1)) if m else ""

    return Product(title=title, free=free, delivery_text=delivery_text, merchant=merchant)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_parser.py -v`
Expected: 8 passed. If `test_not_free_fixture` fails on the title assertion, open the fixture and check the title text; adjust the assertion to a word that is actually in the title.

- [ ] **Step 7: Commit**

```bash
git add scripts/capture_fixture.py tests/fixtures watch/parser.py tests/test_parser.py
git commit -m "feat: parse free-shipping eligibility from the product page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: State and history persistence

**Files:**
- Create: `watch/state.py`, `watch/history.py`
- Test: `tests/test_state.py`, `tests/test_history.py`

**Interfaces:**
- Produces: `state.default_state() -> dict` with keys `last_checked`, `last_success`, `fail_count`, `last_error`, `product`; `state.load(path) -> dict`; `state.save(path, st) -> None`.
- Produces: `history.load(path) -> list[dict]`; `history.save(path, entries) -> None`; `history.append_flip(entries, when: datetime, free: bool, delivery_text: str) -> None`. Entry shape: `{"at": "<ISO UTC>", "free": bool, "delivery_text": str}`.

- [ ] **Step 1: Write the failing state tests**

`tests/test_state.py`:
```python
import json

from watch import state


def test_load_missing_returns_default(tmp_path):
    s = state.load(tmp_path / "nope.json")
    assert s == state.default_state()
    assert s["fail_count"] == 0
    assert s["product"] is None
    assert s["last_checked"] is None
    assert s["last_error"] is None


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = state.default_state()
    s["fail_count"] = 2
    s["product"] = {"free": False, "delivery_text": "ILS 58.91", "title": "Ladle", "merchant": ""}
    state.save(p, s)
    assert json.loads(p.read_text(encoding="utf-8"))["fail_count"] == 2
    assert state.load(p) == s


def test_load_corrupt_returns_default(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert state.load(p) == state.default_state()


def test_load_fills_missing_keys(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"fail_count": 1}', encoding="utf-8")
    s = state.load(p)
    assert s["fail_count"] == 1
    assert s["product"] is None
```

- [ ] **Step 2: Write the failing history tests**

`tests/test_history.py`:
```python
import json
from datetime import datetime, timezone

from watch import history

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def test_load_missing_returns_empty(tmp_path):
    assert history.load(tmp_path / "nope.json") == []


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("[oops", encoding="utf-8")
    assert history.load(p) == []


def test_append_and_roundtrip(tmp_path):
    p = tmp_path / "h.json"
    entries = history.load(p)
    history.append_flip(entries, NOW, free=False, delivery_text="ILS 58.91")
    history.append_flip(entries, NOW.replace(hour=11), free=True, delivery_text="FREE")
    history.save(p, entries)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == [
        {"at": "2026-09-12T10:00:00+00:00", "free": False, "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T11:00:00+00:00", "free": True, "delivery_text": "FREE"},
    ]
    assert history.load(p) == raw
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_state.py tests/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError` for `watch.state` and `watch.history`.

- [ ] **Step 4: Write state and history**

`watch/state.py`:
```python
"""Persist watcher state between polls as JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def default_state() -> dict:
    return {
        "last_checked": None,   # ISO datetime (UTC) of the last poll attempt
        "last_success": None,   # ISO datetime (UTC) of the last successful fetch + parse
        "fail_count": 0,        # consecutive failed polls
        "last_error": None,     # message of the most recent failure, cleared on success
        "product": None,        # dict of the last parsed Product plus "checked_at"
    }


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return default_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("state file unreadable (%s); starting fresh", e)
        return default_state()
    base = default_state()
    if isinstance(data, dict):
        base.update(data)
    return base


def save(path: str | Path, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

`watch/history.py`:
```python
"""Record every change of free-shipping eligibility as a list of flips."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("history file unreadable (%s); starting fresh", e)
        return []
    return data if isinstance(data, list) else []


def save(path: str | Path, entries: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def append_flip(entries: list[dict], when: datetime, free: bool, delivery_text: str) -> None:
    entries.append({"at": when.isoformat(), "free": bool(free), "delivery_text": delivery_text})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py tests/test_history.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add watch/state.py watch/history.py tests/test_state.py tests/test_history.py
git commit -m "feat: state and flip history persistence

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: ntfy notifications

**Files:**
- Create: `watch/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `config.NTFY_SERVER`, `config.NTFY_TOPIC`, `config.NTFY_EMAIL`, `config.NTFY_TOKEN`.
- Produces: `notify.send(title: str, body: str, click: str | None = None, priority: str = "high", tags: str = "package,tada", post=requests.post) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notify.py`:
```python
from watch import notify


class R:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def test_send_posts_to_topic(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_SERVER", "https://ntfy.example")
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "secret-topic")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "me@example.com")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append((url, data, headers))
        return R()

    sent = notify.send("Title here", "body text", click="https://x/y", post=fake_post)
    assert sent is True
    url, data, headers = calls[0]
    assert url == "https://ntfy.example/secret-topic"
    assert data == b"body text"
    assert headers["Title"] == "Title here"
    assert headers["Priority"] == "high"
    assert headers["Click"] == "https://x/y"
    assert headers["Email"] == "me@example.com"
    assert headers["Tags"] == "package,tada"


def test_send_without_email_omits_header(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(headers)
        return R()

    notify.send("t", "b", post=fake_post)
    assert "Email" not in calls[0]
    assert "Click" not in calls[0]
    assert "Authorization" not in calls[0]


def test_send_with_token_adds_bearer(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "tk_abc")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(headers)
        return R()

    notify.send("t", "b", post=fake_post)
    assert calls[0]["Authorization"] == "Bearer tk_abc"


def test_send_retries_without_email_when_rejected(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "me@example.com")
    monkeypatch.setattr(notify.config, "NTFY_TOKEN", "")
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(dict(headers))
        return R(status_code=400 if "Email" in headers else 200)

    assert notify.send("t", "b", post=fake_post) is True
    assert len(calls) == 2
    assert "Email" in calls[0] and "Email" not in calls[1]


def test_send_without_topic_is_noop(monkeypatch):
    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "")
    called = []
    assert notify.send("t", "b", post=lambda *a, **k: called.append(1)) is False
    assert called == []


def test_send_returns_false_on_exception(monkeypatch):
    import requests

    monkeypatch.setattr(notify.config, "NTFY_TOPIC", "t")
    monkeypatch.setattr(notify.config, "NTFY_EMAIL", "")

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    assert notify.send("t", "b", post=boom) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'watch.notify'`.

- [ ] **Step 3: Write notify**

`watch/notify.py`:
```python
"""Send push (and optional email copy) notifications through ntfy."""
from __future__ import annotations

import logging

import requests

from watch import config

log = logging.getLogger(__name__)


def send(
    title: str,
    body: str,
    click: str | None = None,
    priority: str = "high",
    tags: str = "package,tada",
    post=requests.post,
) -> bool:
    """POST a message to the configured ntfy topic. Returns True if sent."""
    if not config.NTFY_TOPIC:
        log.info("NTFY_TOPIC not set; would send: %s / %s", title, body)
        return False
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
    if config.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {config.NTFY_TOKEN}"
    if config.NTFY_EMAIL:
        headers["Email"] = config.NTFY_EMAIL
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"

    ok = _post(post, url, body, headers)
    if not ok and "Email" in headers:
        # ntfy.sh rejects anonymous email sending (HTTP 400). Push still matters:
        # retry once without the email copy rather than losing the alert.
        log.warning("retrying notification without email copy")
        headers = {k: v for k, v in headers.items() if k != "Email"}
        ok = _post(post, url, body, headers)
    return ok


def _post(post, url: str, body: str, headers: dict) -> bool:
    try:
        resp = post(url, data=body.encode("utf-8"), headers=headers, timeout=20)
    except requests.RequestException as e:
        log.error("ntfy send failed: %s", e)
        return False
    if getattr(resp, "status_code", 0) != 200:
        log.error("ntfy returned %s: %s", resp.status_code, getattr(resp, "text", ""))
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notify.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add watch/notify.py tests/test_notify.py
git commit -m "feat: ntfy push notifications

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Status page renderer

**Files:**
- Create: `watch/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `config.PRODUCT_URL`, `config.ASIN`; state dict shape from Task 5; history entry shape from Task 5.
- Produces: `render.render_page(state: dict, history: list[dict], now: datetime) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:
```python
from datetime import datetime, timezone

from watch import state as state_mod
from watch.render import render_page

NOW = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)


def base_state(free=False):
    st = state_mod.default_state()
    st["last_checked"] = "2026-09-12T10:00:00+00:00"
    st["last_success"] = "2026-09-12T10:00:00+00:00"
    st["product"] = {
        "title": "DI ORO Silicone Ladle <Black>",
        "free": free,
        "delivery_text": "FREE" if free else "ILS 58.91",
        "merchant": "Sold by DI ORO and shipped by Amazon",
        "checked_at": "2026-09-12T10:00:00+00:00",
    }
    return st


def test_paid_state_renders_badge_and_details():
    page = render_page(base_state(free=False), [], NOW)
    assert "Paid shipping" in page
    assert "ILS 58.91" in page
    assert "DI ORO Silicone Ladle &lt;Black&gt;" in page  # escaped
    assert "https://www.amazon.com/dp/B07W1P15GL" in page
    assert "Sold by DI ORO" in page
    assert "2026-09-12 10:00 UTC" in page
    assert '<meta http-equiv="refresh" content="600">' in page


def test_free_state_renders_free_badge():
    page = render_page(base_state(free=True), [], NOW)
    assert "FREE shipping to Israel" in page
    assert "Paid shipping" not in page


def test_no_data_yet():
    page = render_page(state_mod.default_state(), [], NOW)
    assert "No data yet" in page


def test_failure_warning_shown_when_fail_count_positive():
    st = base_state()
    st["fail_count"] = 2
    st["last_error"] = "first GET: captcha page returned"
    page = render_page(st, [], NOW)
    assert "2 consecutive failed polls" in page
    assert "captcha page returned" in page


def test_history_rows_newest_first():
    hist = [
        {"at": "2026-09-10T08:00:00+00:00", "free": False, "delivery_text": "ILS 58.91"},
        {"at": "2026-09-12T09:00:00+00:00", "free": True, "delivery_text": "FREE"},
    ]
    page = render_page(base_state(free=True), hist, NOW)
    assert page.index("2026-09-12 09:00 UTC") < page.index("2026-09-10 08:00 UTC")
    assert page.count("<tr>") == 3  # header + 2 rows
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'watch.render'`.

- [ ] **Step 3: Write the renderer**

`watch/render.py`:
```python
"""Render the static status page committed to docs/index.html."""
from __future__ import annotations

from datetime import datetime
from html import escape

from watch import config

STYLE = """
body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem 1rem; max-width: 40rem;
       margin-inline: auto; color: #222; background: #fafafa; }
h1 { font-size: 1.25rem; margin: 0 0 .5rem; }
h1 a { color: inherit; }
.badge { display: inline-block; padding: .6rem 1rem; border-radius: .5rem; font-size: 1.4rem;
         font-weight: 700; margin: .5rem 0; }
.free { background: #d8f5d0; color: #0b5a1e; }
.paid { background: #fde3d0; color: #7a2e00; }
.unknown { background: #e8e8e8; color: #444; }
.meta { color: #555; font-size: .95rem; }
.warn { background: #fff3c4; border: 1px solid #e0c060; padding: .5rem .75rem;
        border-radius: .4rem; margin: 1rem 0; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ddd; }
"""


def _fmt(iso: str | None) -> str:
    if not iso:
        return "never"
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")


def render_page(state: dict, history: list[dict], now: datetime) -> str:
    product = state.get("product") or {}
    free = product.get("free")
    if free is True:
        cls, badge = "free", "FREE shipping to Israel"
    elif free is False:
        cls, badge = "paid", "Paid shipping"
    else:
        cls, badge = "unknown", "No data yet"

    title = escape(product.get("title") or f"ASIN {config.ASIN}")
    delivery = escape(product.get("delivery_text") or "")
    merchant = escape(product.get("merchant") or "")

    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        '<meta http-equiv="refresh" content="600">',
        "<title>Amazon free-shipping watch</title>",
        f"<style>{STYLE}</style></head><body>",
        f'<h1><a href="{escape(config.PRODUCT_URL)}">{title}</a></h1>',
        f'<div class="badge {cls}">{badge}</div>',
    ]
    if delivery:
        parts.append(f'<p class="meta">Delivery: {delivery}</p>')
    if merchant:
        parts.append(f'<p class="meta">{merchant}</p>')
    parts.append(
        f'<p class="meta">Last checked: {_fmt(state.get("last_checked"))}<br>'
        f'Last success: {_fmt(state.get("last_success"))}<br>'
        f'Page rendered: {now.strftime("%Y-%m-%d %H:%M UTC")}</p>'
    )
    fails = int(state.get("fail_count") or 0)
    if fails > 0:
        err = escape(str(state.get("last_error") or ""))
        parts.append(f'<div class="warn">{fails} consecutive failed polls. Last error: {err}</div>')

    parts.append("<h2>History</h2>")
    if history:
        parts.append("<table><tr><th>When</th><th>State</th><th>Delivery</th></tr>")
        for e in reversed(history):
            label = "FREE" if e.get("free") else "Paid"
            parts.append(
                f"<tr><td>{_fmt(e.get('at'))}</td><td>{label}</td>"
                f"<td>{escape(str(e.get('delivery_text') or ''))}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<p class="meta">No observations recorded yet.</p>')
    parts.append("</body></html>")
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_render.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add watch/render.py tests/test_render.py
git commit -m "feat: static status page renderer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Full poll cycle

**Files:**
- Modify: `watch/main.py` (replace the Task 3 version entirely)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `client.fetch_product`, `client.FetchError`, `parser.parse`, `parser.ParseError`, `parser.Product`, `state.load/save`, `history.load/save/append_flip`, `notify.send`, `render.render_page`, `config.*`.
- Produces: `main.run(fetch=fetch_product, notifier=notify.send, state_path=config.STATE_PATH, history_path=config.HISTORY_PATH, page_path=config.PAGE_PATH, now: datetime | None = None) -> dict` and `main.main() -> int`. `fetch` is called as `fetch(asin: str) -> str`. `notifier` is called as `notifier(title, body, click=..., priority=..., tags=...)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py`:
```python
"""One poll cycle with fake fetch and fake notifier. No network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watch import config
from watch.client import FetchError
from watch.main import run
from watch.state import load as load_state

FIX = Path(__file__).parent / "fixtures"
NOT_FREE = (FIX / "not_free.html").read_text(encoding="utf-8")
FREE = (FIX / "free.html").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, title, body, click=None, priority="high", tags=""):
        self.sent.append({"title": title, "body": body, "click": click, "priority": priority, "tags": tags})
        return True


def fetch_returning(html):
    return lambda asin: html


def fetch_failing(asin):
    raise FetchError("first GET: captcha page returned")


def paths(tmp_path):
    return dict(
        state_path=tmp_path / "state.json",
        history_path=tmp_path / "history.json",
        page_path=tmp_path / "docs" / "index.html",
    )


def test_first_poll_records_without_push(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **paths(tmp_path))
    assert n.sent == []
    assert st["product"]["free"] is False
    assert st["product"]["checked_at"] == NOW.isoformat()
    assert st["last_success"] == NOW.isoformat()
    assert st["fail_count"] == 0
    assert (tmp_path / "docs" / "index.html").exists()
    assert load_state(tmp_path / "state.json") == st
    import json
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(hist) == 1 and hist[0]["free"] is False


def test_paid_to_free_pushes_once(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert len(n.sent) == 1
    msg = n.sent[0]
    assert msg["title"] == "Amazon: free shipping to Israel!"
    assert msg["click"] == config.PRODUCT_URL
    assert msg["priority"] == "high"
    assert "FREE" in msg["body"]
    # stays free: no second push
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW + timedelta(hours=2), **p)
    assert len(n.sent) == 1


def test_free_to_paid_records_history_without_push(tmp_path):
    import json
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    assert n.sent == []
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [e["free"] for e in hist] == [True, False]


def test_unchanged_state_adds_no_history(tmp_path):
    import json
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW + timedelta(hours=1), **p)
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(hist) == 1


def test_failures_alert_once_at_threshold_and_reset(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    for i in range(1, 5):
        st = run(fetch=fetch_failing, notifier=n, now=NOW, **p)
        assert st["fail_count"] == i
        assert "captcha" in st["last_error"]
    assert len(n.sent) == 1
    assert n.sent[0]["title"] == "Amazon watcher failing"
    assert n.sent[0]["priority"] == "default"
    st = run(fetch=fetch_returning(NOT_FREE), notifier=n, now=NOW, **p)
    assert st["fail_count"] == 0
    assert st["last_error"] is None


def test_failure_keeps_previous_product(tmp_path):
    n = FakeNotifier()
    p = paths(tmp_path)
    run(fetch=fetch_returning(FREE), notifier=n, now=NOW, **p)
    st = run(fetch=fetch_failing, notifier=n, now=NOW + timedelta(hours=1), **p)
    assert st["product"]["free"] is True
    assert st["last_checked"] == (NOW + timedelta(hours=1)).isoformat()
    assert st["last_success"] == NOW.isoformat()
    page = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "1 consecutive failed polls" in page


def test_parse_error_counts_as_failure(tmp_path):
    n = FakeNotifier()
    st = run(fetch=fetch_returning("<html>no delivery block</html>"), notifier=n, now=NOW, **paths(tmp_path))
    assert st["fail_count"] == 1
    assert "delivery block" in st["last_error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ImportError: cannot import name 'run' from 'watch.main'`.

- [ ] **Step 3: Replace main with the full poll cycle**

`watch/main.py` (overwrite the whole file):
```python
"""One poll cycle: fetch the page, parse eligibility, notify on flip, persist, render."""
from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watch import config, history as history_mod, notify, state as state_mod
from watch.client import FetchError, fetch_product
from watch.parser import ParseError, Product, parse
from watch.render import render_page

log = logging.getLogger("watch")

Fetch = Callable[[str], str]
Notifier = Callable[..., bool]


def _finish(st: dict, history: list[dict], history_changed: bool,
            state_path, history_path, page_path, now: datetime) -> dict:
    st["last_checked"] = now.isoformat()
    state_mod.save(state_path, st)
    if history_changed:
        history_mod.save(history_path, history)
    page = render_page(st, history, now)
    p = Path(page_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return st


def run(
    fetch: Fetch = fetch_product,
    notifier: Notifier = notify.send,
    state_path: str | Path = config.STATE_PATH,
    history_path: str | Path = config.HISTORY_PATH,
    page_path: str | Path = config.PAGE_PATH,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    st = state_mod.load(state_path)
    history = history_mod.load(history_path)

    try:
        product: Product = parse(fetch(config.ASIN))
    except (FetchError, ParseError) as e:
        st["fail_count"] = int(st.get("fail_count", 0)) + 1
        st["last_error"] = str(e)
        log.error("poll failed (%d in a row): %s", st["fail_count"], e)
        if st["fail_count"] == config.FAIL_ALERT_AT:
            notifier(
                "Amazon watcher failing",
                f"{st['fail_count']} consecutive polls failed. Last error: {e}",
                priority="default",
                tags="warning",
            )
        return _finish(st, history, False, state_path, history_path, page_path, now)

    st["fail_count"] = 0
    st["last_error"] = None
    st["last_success"] = now.isoformat()
    previous = st.get("product") or None
    prev_free = previous.get("free") if previous else None

    history_changed = False
    if prev_free is None:
        history_mod.append_flip(history, now, product.free, product.delivery_text)
        history_changed = True
        log.info("first observation: free=%s (%s)", product.free, product.delivery_text)
    elif product.free != prev_free:
        history_mod.append_flip(history, now, product.free, product.delivery_text)
        history_changed = True
        if product.free:
            notifier(
                "Amazon: free shipping to Israel!",
                f"{product.title}\n{product.delivery_text}",
                click=config.PRODUCT_URL,
                priority="high",
            )
            log.info("notified: became free")
        else:
            log.info("became paid again (%s); no push", product.delivery_text)
    else:
        log.info("unchanged: free=%s (%s)", product.free, product.delivery_text)

    st["product"] = {**asdict(product), "checked_at": now.isoformat()}
    return _finish(st, history, history_changed, state_path, history_path, page_path, now)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        st = run()
        log.info("done: fail_count=%s free=%s", st["fail_count"], (st.get("product") or {}).get("free"))
    except Exception:  # never fail the workflow; page/state may still be committed
        log.exception("unexpected error in poll")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -v`
Expected: all tests pass (3 config + 9 client + 8 parser + 4 state + 3 history + 6 notify + 5 render + 7 main = 45 passed).

- [ ] **Step 5: Run one real poll locally and inspect outputs**

Run: `python -m watch.main`
Expected log: `first observation: free=False (ILS 58.91)` (price may differ) then `done: fail_count=0 free=False`. Files `state.json`, `history.json`, `docs/index.html` now exist. Open `docs/index.html` in a browser: badge "Paid shipping", one history row.

- [ ] **Step 6: Commit code and the first generated files**

```bash
git add watch/main.py tests/test_main.py state.json history.json docs/index.html
git commit -m "feat: full poll cycle with flip detection, history and status page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: README, secrets, Pages, and first live poll

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: everything. No new code.

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
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
```

- [ ] **Step 2: Commit and push**

```bash
git add README.md
git commit -m "docs: README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 3: Set repository secrets**

The Aliathon watcher's values are reused (decided in the spec). `NTFY_TOKEN` is not set on either repo yet, so skip it.

```bash
gh secret set NTFY_TOPIC --repo Yanik1983/amazon-watch --body "aliathon-7f3a9c2e5b1d4a80"
gh secret set NTFY_EMAIL --repo Yanik1983/amazon-watch --body "yan.korgozki@gmail.com"
```
Expected: two `Set Actions secret ...` confirmations.

- [ ] **Step 4: Enable GitHub Pages from `docs/`**

```bash
gh api --method POST repos/Yanik1983/amazon-watch/pages -F "source[branch]=main" -F "source[path]=/docs"
```
Expected: JSON with `"html_url": "https://yanik1983.github.io/amazon-watch/"`. If the API answers 409 (already enabled), that is fine.

- [ ] **Step 5: Trigger a live poll and verify the commit and page**

```bash
gh workflow run poll --repo Yanik1983/amazon-watch
```
Wait about three minutes, then:
```bash
gh run list --repo Yanik1983/amazon-watch --workflow poll --limit 1
git pull origin main
git log --oneline -3
```
Expected: a new `chore: poll <time> [skip ci]` commit from `github-actions[bot]` only if state changed; on the very first live run `state.json` already exists from Task 8, so the commit appears when `last_checked` changes, which it does on every poll. `state.json` shows `"fail_count": 0` and a fresh `last_checked`.

Then open `https://yanik1983.github.io/amazon-watch/` (Pages can take a few minutes on first publish). Expected: "Paid shipping" badge, delivery price, one history row.

- [ ] **Step 6: Send one test push to confirm the topic works**

From the repo root, with the real topic in the environment for this one command only:
```bash
NTFY_TOPIC=aliathon-7f3a9c2e5b1d4a80 python -c "from watch import notify; print(notify.send('Amazon watcher online', 'Watching B07W1P15GL for free shipping to Israel.', click='https://yanik1983.github.io/amazon-watch/', priority='default', tags='white_check_mark'))"
```
Expected: prints `True` and the phone shows the notification. Tell the user the watcher is live and give them the Pages URL.

---

## Self-review notes

- Spec coverage: config (T1), client incl. every FetchError condition (T2), workflow values and gate (T3), parser incl. fallbacks and ParseError (T4), state keys and history shape (T5), notify with token/email/retry (T6), page contents incl. refresh meta and warning line (T7), main flow steps 1 to 6 incl. alert-once and no-push-on-first (T8), README, secrets, Pages, build order (T3 gate before T4, T9 last).
- Names used consistently: `fetch_product`, `FetchError`, `parse`, `ParseError`, `Product`, `default_state`, `append_flip`, `render_page`, `run`, `config.PRODUCT_URL`, `config.FAIL_ALERT_AT`.
- Test count expectation in Task 8 Step 4 assumes every earlier task's tests are present; adjust the number if a test was renamed.
