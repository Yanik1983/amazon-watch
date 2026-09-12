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

# Polls between repeated warnings while failures continue; 24 polls = one day at hourly cadence.
FAIL_REWARN_EVERY = 24

# ntfy.sh notification settings, all from repository secrets / variables.
NTFY_SERVER = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_EMAIL = os.environ.get("NTFY_EMAIL", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

# Where the workflow that polls lives, so the status page can offer a manual run.
REPO_URL = "https://github.com/Yanik1983/amazon-watch"
WORKFLOW_URL = f"{REPO_URL}/actions/workflows/poll.yml"

# Seconds between polls. The workflow sets INTERVAL_SECONDS for its loop, so reading it
# here keeps the "next check" line on the status page honest without a second constant.
POLL_INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS") or 3600)

# Timestamps on the status page are shown in this zone as well as in UTC.
DISPLAY_TZ = "Asia/Jerusalem"

# Files committed back to the repository by the poll workflow.
STATE_PATH = "state.json"
HISTORY_PATH = "history.json"
PAGE_PATH = "docs/index.html"
