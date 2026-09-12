"""Render the static status page committed to docs/index.html."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from watch import config, history as history_mod, products

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
.card { background: #fff; border: 1px solid #e2e2e2; border-radius: .6rem;
        padding: .9rem 1rem; margin: 1rem 0; }
.card h2 { font-size: 1.05rem; margin: 0 0 .4rem; }
.card h2 a { color: inherit; }
.card .badge { font-size: 1.1rem; }
.empty { color: #555; font-style: italic; margin: 1.5rem 0; }
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


def _badge(free) -> tuple[str, str]:
    if free is True:
        return "free", "FREE shipping to Israel"
    if free is False:
        return "paid", "Paid shipping"
    return "unknown", "No data yet"


def _card(entry: dict, ps: dict, rows: list[dict]) -> str:
    """One product: what it costs to ship now, and every change seen so far."""
    asin = entry.get("asin", "")
    label = escape(products.display_label(entry, ps.get("title") or ""))
    cls, badge = _badge(ps.get("free"))
    out = [
        '<div class="card">',
        f'<h2><a href="{escape(config.product_url(asin))}">{label}</a></h2>',
        f'<div class="badge {cls}">{badge}</div>',
    ]
    delivery = escape(ps.get("delivery_text") or "")
    if delivery:
        out.append(f'<p class="meta">Delivery: {delivery}</p>')
    merchant = escape(ps.get("merchant") or "")
    if merchant:
        out.append(f'<p class="meta">{merchant}</p>')
    out.append(f'<p class="meta">Last good reading: {_fmt(ps.get("last_success"))}</p>')
    fails = int(ps.get("fail_count") or 0)
    if fails > 0:
        err = escape(str(ps.get("last_error") or ""))
        out.append(f'<div class="warn">{fails} consecutive failed polls. Last error: {err}</div>')
    if rows:
        out.append("<table><tr><th>When</th><th>State</th><th>Delivery</th></tr>")
        for e in reversed(rows):
            when = _parse(e.get("at"))
            shown = _local(when) if when else escape(str(e.get("at") or ""))
            out.append(
                f"<tr><td>{shown}</td><td>{'FREE' if e.get('free') else 'Paid'}</td>"
                f"<td>{escape(str(e.get('delivery_text') or ''))}</td></tr>"
            )
        out.append("</table>")
    out.append("</div>")
    return "\n".join(out)


def render_page(state: dict, history: list[dict], product_list: list[dict],
                now: datetime) -> str:
    entries = state.get("products") or {}
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        '<meta http-equiv="refresh" content="600">',
        "<title>Amazon free-shipping watch</title>",
        f"<style>{STYLE}</style></head><body>",
        "<h1>Free shipping to Israel</h1>",
    ]

    # Free first, then the order the products were added: whatever is buyable now
    # is what the page is for, so it goes at the top where a phone shows it.
    ordered = sorted(
        enumerate(product_list),
        key=lambda item: (
            0 if (entries.get(item[1].get("asin")) or {}).get("free") is True else 1,
            item[0],
        ),
    )
    if ordered:
        for _, entry in ordered:
            asin = entry.get("asin", "")
            parts.append(_card(entry, entries.get(asin) or {},
                               history_mod.for_asin(history, asin)))
    else:
        parts.append('<p class="empty">No products are being watched.</p>')

    last_checked = _parse(state.get("last_checked"))
    next_line = ""
    if last_checked is not None:
        nxt = last_checked + timedelta(seconds=config.POLL_INTERVAL_SECONDS)
        next_line = f"Next automatic check: about {_local(nxt)}<br>"
    parts.append(
        f'<p class="meta">Last checked: {_fmt(state.get("last_checked"))}<br>'
        f'{next_line}'
        f'Page rendered: {_fmt(now.isoformat())}</p>'
    )
    parts.append(
        f'<a class="check" href="{escape(config.WORKFLOW_URL)}">Check now</a>'
        '<p class="meta">Opens GitHub Actions. Tap "Run workflow" there, then reload this page '
        'in about a minute. A manual run also restarts the hourly cycle.</p>'
    )
    parts.append(
        f'<a class="check" href="{escape(config.MANAGE_WORKFLOW_URL)}">Manage products</a>'
        '<p class="meta">Opens GitHub Actions. Tap "Run workflow", choose add or remove, and '
        'paste an ASIN or an Amazon link. The next check starts by itself.</p>'
    )
    parts.append(
        f'<p class="meta">Times are {escape(config.DISPLAY_TZ.split("/")[-1])} local unless '
        'marked UTC.</p>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)
