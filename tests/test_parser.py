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
    assert parse(html).delivery_text == "₪58.91"


def test_delivery_text_nbsp_normalized_to_space():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="ILS&nbsp;58.91"></span></div>'
    )
    assert parse(html).delivery_text == "ILS 58.91"


def test_anchor_inside_comment_does_not_count():
    with pytest.raises(ParseError):
        parse('<!-- id="mir-layout-DELIVERY_BLOCK" --><p>x</p>')


def test_merchant_anchor_inside_comment_ignored():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="FREE"></span></div>'
        '<!-- id="merchantInfo" --><div>junk</div>'
    )
    p = parse(html)
    assert p.merchant == ""


def test_price_outside_block_ignored_when_block_present():
    html = (
        '<span data-csa-c-delivery-price="FREE"></span>'
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="ILS 58.91"></span></div>'
    )
    p = parse(html)
    assert p.free is False
    assert p.delivery_text == "ILS 58.91"


def test_fastest_value_skipped():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="fastest"></span>'
        '<span data-csa-c-delivery-price="FREE"></span></div>'
    )
    p = parse(html)
    assert p.free is True
    assert p.delivery_text == "FREE"


def test_zero_dollar_counts_as_free():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="$0.00"></span></div>'
    )
    p = parse(html)
    assert p.free is True


def test_only_fastest_falls_back_to_text():
    html = (
        '<div id="mir-layout-DELIVERY_BLOCK">'
        '<span data-csa-c-delivery-price="fastest"></span>'
        'FREE international delivery</div>'
    )
    p = parse(html)
    assert p.free is True
    assert p.delivery_text == ""
