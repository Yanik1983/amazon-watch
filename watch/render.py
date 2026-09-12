"""Render the static status page committed to docs/index.html."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from watch import config

try:  # zoneinfo needs tzdata on some platforms; the page still renders without it
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo(config.DISPLAY_TZ)
except Exception:  # pragma: no cover - only on a system with no time zone database
    LOCAL_TZ = None

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
.check { display: block; margin: 1.2rem 0 .3rem; padding: .85rem 1rem; border-radius: .5rem;
         background: #1f6feb; color: #fff; font-weight: 700; font-size: 1.05rem;
         text-align: center; text-decoration: none; }
.check:active { background: #174ea6; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ddd; }
"""


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


def _local(when: datetime) -> str:
    """Timestamp in the display zone, or in UTC when no zone database is available."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if LOCAL_TZ is None:
        return when.strftime("%Y-%m-%d %H:%M UTC")
    return when.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def _fmt(iso: str | None) -> str:
    """Local time with the UTC value beside it, for the page's detail lines."""
    when = _parse(iso)
    if when is None:
        return "never" if not iso else str(iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return f"{_local(when)} ({when.astimezone(timezone.utc).strftime('%H:%M')} UTC)"


def render_page(state: dict, history: list[dict], now: datetime) -> str:
    product = (state.get("products") or {}).get(config.DEFAULT_ASIN) or {}
    free = product.get("free")
    if free is True:
        cls, badge = "free", "FREE shipping to Israel"
    elif free is False:
        cls, badge = "paid", "Paid shipping"
    else:
        cls, badge = "unknown", "No data yet"

    title = escape(product.get("title") or f"ASIN {config.DEFAULT_ASIN}")
    delivery = escape(product.get("delivery_text") or "")
    merchant = escape(product.get("merchant") or "")

    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        '<meta http-equiv="refresh" content="600">',
        "<title>Amazon free-shipping watch</title>",
        f"<style>{STYLE}</style></head><body>",
        f'<h1><a href="{escape(config.product_url(config.DEFAULT_ASIN))}">{title}</a></h1>',
        f'<div class="badge {cls}">{badge}</div>',
    ]
    if delivery:
        parts.append(f'<p class="meta">Delivery: {delivery}</p>')
    if merchant:
        parts.append(f'<p class="meta">{merchant}</p>')

    last_checked = _parse(state.get("last_checked"))
    next_line = ""
    if last_checked is not None:
        nxt = last_checked + timedelta(seconds=config.POLL_INTERVAL_SECONDS)
        next_line = f"Next automatic check: about {_local(nxt)}<br>"
    parts.append(
        f'<p class="meta">Last checked: {_fmt(state.get("last_checked"))}<br>'
        f'Last success: {_fmt(product.get("last_success"))}<br>'
        f'{next_line}'
        f'Page rendered: {_fmt(now.isoformat())}</p>'
    )
    parts.append(
        f'<a class="check" href="{escape(config.WORKFLOW_URL)}">Check now</a>'
        '<p class="meta">Opens GitHub Actions. Tap "Run workflow" there, then reload this page '
        'in about a minute. A manual run also restarts the hourly cycle.</p>'
    )
    fails = int(product.get("fail_count") or 0)
    if fails > 0:
        err = escape(str(product.get("last_error") or ""))
        parts.append(f'<div class="warn">{fails} consecutive failed polls. Last error: {err}</div>')

    parts.append("<h2>History</h2>")
    if history:
        parts.append("<table><tr><th>When</th><th>State</th><th>Delivery</th></tr>")
        for e in reversed(history):
            label = "FREE" if e.get("free") else "Paid"
            when = _parse(e.get("at"))
            shown = _local(when) if when else escape(str(e.get("at") or ""))
            parts.append(
                f"<tr><td>{shown}</td><td>{label}</td>"
                f"<td>{escape(str(e.get('delivery_text') or ''))}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<p class="meta">No observations recorded yet.</p>')
    parts.append(
        f'<p class="meta">Times are {escape(config.DISPLAY_TZ.split("/")[-1])} local unless '
        'marked UTC.</p>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)
