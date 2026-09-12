from watch import config


def test_product_url_uses_asin():
    assert config.DEFAULT_ASIN == "B07W1P15GL"
    assert config.product_url("B07W1P15GL") == "https://www.amazon.com/dp/B07W1P15GL"
    assert config.PRODUCTS_PATH == "products.json"
    assert config.MANAGE_WORKFLOW_URL.endswith("/actions/workflows/manage.yml")


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
