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
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return str(iso)


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
