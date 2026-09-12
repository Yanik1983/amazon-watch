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
