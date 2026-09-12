"""Constants and environment configuration for the Amazon watcher."""
from __future__ import annotations

import os

# The product the watcher falls back to: it seeds products.json on a fresh checkout
# and owns any data written before the watcher understood more than one product.
# What is actually watched lives in products.json.
DEFAULT_ASIN = "B07W1P15GL"
COUNTRY = "IL"

BASE_URL = "https://www.amazon.com"
ADDRESS_CHANGE_URL = f"{BASE_URL}/portal-migration/hz/glow/address-change?actionSource=glow"


def product_url(asin: str) -> str:
    return f"{BASE_URL}/dp/{asin}"

# Send one warning push when this many consecutive polls have failed.
FAIL_ALERT_AT = 3

# Polls between repeated warnings while failures continue; 24 polls = one day at hourly cadence.
FAIL_REWARN_EVERY = 24

# ntfy.sh notification settings, all from repository secrets / variables.
NTFY_SERVER = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_EMAIL = os.environ.get("NTFY_EMAIL", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

# Passphrase the status page signs its add/remove commands with. Unset means the
# page cannot change anything and the watcher simply never looks for commands.
CMD_PASSPHRASE = os.environ.get("CMD_PASSPHRASE", "")

# Seconds between mailbox checks while the poll job waits for its next Amazon poll.
TICK_SECONDS = int(os.environ.get("TICK_SECONDS") or 60)

# Where the workflow that polls lives, so the status page can offer a manual run.
REPO_URL = "https://github.com/Yanik1983/amazon-watch"
WORKFLOW_URL = f"{REPO_URL}/actions/workflows/poll.yml"
MANAGE_WORKFLOW_URL = f"{REPO_URL}/actions/workflows/manage.yml"

# Seconds between polls. The workflow sets INTERVAL_SECONDS for its loop, so reading it
# here keeps the "next check" line on the status page honest without a second constant.
POLL_INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS") or 3600)

# How soon to try again when every watched product failed its last poll. A total
# failure is usually a transient block rather than a reason to serve stale data
# for a whole hour, and retrying only in that case adds no traffic when things
# are working. It also brings the first failure warning forward to about 45
# minutes (FAIL_ALERT_AT polls) instead of three hours.
RETRY_INTERVAL_SECONDS = 900

# Timestamps on the status page are shown in this zone as well as in UTC.
DISPLAY_TZ = "Asia/Jerusalem"

# Files committed back to the repository. products.json is written only by
# watch/manage.py; the poll reads it and never changes it.
PRODUCTS_PATH = "products.json"
STATE_PATH = "state.json"
HISTORY_PATH = "history.json"
PAGE_PATH = "docs/index.html"
