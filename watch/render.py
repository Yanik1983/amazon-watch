"""Render the static status page committed to docs/index.html."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from watch import commands, config, history as history_mod, products

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
.asin { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: .85rem; color: #666; margin: -.2rem 0 .4rem; user-select: all; }
.empty { color: #555; font-style: italic; margin: 1.5rem 0; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ddd; }
form.manage { background: #fff; border: 1px solid #e2e2e2; border-radius: .6rem;
              padding: .9rem 1rem; margin: 1.5rem 0 .5rem; }
form.manage h2 { font-size: 1.05rem; margin: 0 0 .6rem; }
form.manage label { display: block; font-size: .9rem; color: #555; margin: .6rem 0 .2rem; }
form.manage input, form.manage select { width: 100%; box-sizing: border-box;
              padding: .6rem .5rem; font-size: 1rem; border: 1px solid #ccc;
              border-radius: .4rem; background: #fff; color: #222; }
form.manage button { width: 100%; margin-top: .9rem; padding: .85rem 1rem;
              border: 0; border-radius: .5rem; background: #1f6feb; color: #fff;
              font-weight: 700; font-size: 1.05rem; }
form.manage button:disabled { background: #9ab; }
#cmd-status { margin: .7rem 0 0; font-size: .95rem; min-height: 1.2rem; }
#cmd-status.ok { color: #0b5a1e; }
#cmd-status.bad { color: #7a2e00; }
details { margin: 1rem 0; }
summary { cursor: pointer; }
"""

# The form talks only to ntfy. It holds no credential: the passphrase the user
# types stays in this browser and is used to derive the mailbox address and sign
# each note, so the page can be public without letting a stranger change anything.
FORM = """
<form class="manage" id="cmd-form" autocomplete="off">
<h2>Add or remove a product</h2>
<div id="phrase-row" hidden>
  <label for="cmd-phrase">Passphrase</label>
  <input type="password" id="cmd-phrase" autocomplete="current-password"
         placeholder="typed once, then remembered on this device">
</div>
<label for="cmd-action">What to do</label>
<select id="cmd-action">
  <option value="add">Add a product</option>
  <option value="remove">Remove a product</option>
</select>
<label for="cmd-product">ASIN or Amazon link</label>
<input type="text" id="cmd-product" inputmode="url"
       placeholder="B07W1P15GL or https://www.amazon.com/dp/...">
<p class="meta">Each colour and size is a separate product on Amazon, with its own
price and its own shipping. Choose the one you want on Amazon first, then copy the
link from the address bar.</p>
<label for="cmd-label">Name to show (optional)</label>
<input type="text" id="cmd-label" placeholder="left empty, the page title is used">
<button type="submit" id="cmd-send">Send</button>
<p id="cmd-status" class="meta"></p>
<p class="meta" id="phrase-note"></p>
</form>
"""

SCRIPT = """
<script>
(function () {
  var NTFY = "__NTFY__", VERSION = __VERSION__, KEY = "amazon-watch-passphrase";
  var form = document.getElementById("cmd-form");
  var statusEl = document.getElementById("cmd-status");
  var phraseRow = document.getElementById("phrase-row");
  var phraseInput = document.getElementById("cmd-phrase");
  var phraseNote = document.getElementById("phrase-note");
  var sendBtn = document.getElementById("cmd-send");

  function stored() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function store(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }
  function forget() { try { localStorage.removeItem(KEY); } catch (e) {} }

  function say(text, cls) { statusEl.textContent = text; statusEl.className = cls || "meta"; }

  function showPhraseState() {
    var have = stored();
    phraseRow.hidden = !!have;
    phraseNote.innerHTML = have
      ? 'Passphrase remembered on this device. <a href="#" id="forget">Forget it</a>.'
      : "The passphrase never leaves this device. It signs the request so only you can change the list.";
    var f = document.getElementById("forget");
    if (f) f.onclick = function (e) { e.preventDefault(); forget(); showPhraseState(); say(""); };
  }

  function hex(buf) {
    return Array.prototype.map.call(new Uint8Array(buf),
      function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  async function hmac(phrase, message) {
    var enc = new TextEncoder();
    var key = await crypto.subtle.importKey("raw", enc.encode(phrase),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    return hex(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
  }

  function nonce() {
    var a = new Uint8Array(8);
    crypto.getRandomValues(a);
    return hex(a.buffer);
  }

  // Wait for the watcher's reply on the same topic. It arrives within about a
  // minute, which is how often the poll job looks in the mailbox.
  async function awaitReply(topic, id, deadline) {
    while (Date.now() < deadline) {
      await new Promise(function (r) { setTimeout(r, 3000); });
      var left = Math.round((deadline - Date.now()) / 1000);
      say("Sent. Waiting for the watcher to pick it up (" + left + "s)…");
      var resp;
      try {
        resp = await fetch(NTFY + "/" + topic + "/json?poll=1&since=300s");
      } catch (e) { continue; }
      if (!resp.ok) continue;
      var lines = (await resp.text()).split("\\n");
      for (var i = 0; i < lines.length; i++) {
        if (!lines[i].trim()) continue;
        var note, body;
        try { note = JSON.parse(lines[i]); body = JSON.parse(note.message); } catch (e) { continue; }
        if (body && body.reply === id) return body;
      }
    }
    return null;
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!window.crypto || !crypto.subtle) {
      return say("This browser cannot sign the request. Use the manage workflow below.", "bad");
    }
    var phrase = stored() || phraseInput.value.trim();
    if (!phrase) return say("Enter the passphrase first.", "bad");
    var product = document.getElementById("cmd-product").value.trim();
    if (!product) return say("Enter an ASIN or an Amazon link.", "bad");

    var cmd = {
      action: document.getElementById("cmd-action").value,
      product: product,
      label: document.getElementById("cmd-label").value.trim(),
      ts: Math.floor(Date.now() / 1000),
      nonce: nonce(),
      v: VERSION
    };
    var topic = "amzcmd-" + (await hmac(phrase, "topic")).slice(0, 24);
    var canonical = [cmd.action, cmd.product, cmd.label, cmd.ts, cmd.nonce].join("\\n");
    var payload = JSON.stringify({ cmd: cmd, sig: await hmac(phrase, canonical) });

    sendBtn.disabled = true;
    say("Sending\\u2026");
    try {
      var resp = await fetch(NTFY + "/" + topic, { method: "POST", body: payload });
      if (!resp.ok) throw new Error("ntfy returned " + resp.status);
    } catch (err) {
      sendBtn.disabled = false;
      return say("Could not reach the mailbox: " + err.message, "bad");
    }
    if (!stored()) { store(phrase); phraseInput.value = ""; showPhraseState(); }

    var reply = await awaitReply(topic, cmd.nonce, Date.now() + 90000);
    sendBtn.disabled = false;
    if (!reply) {
      return say("No answer yet. The watcher may be between jobs; it will pick this up "
                 + "within ten minutes. Reload later to check.", "bad");
    }
    if (!reply.ok) return say(reply.message, "bad");
    say(reply.message + " \\u2014 the page updates in a minute or two.", "ok");
    document.getElementById("cmd-product").value = "";
    document.getElementById("cmd-label").value = "";
    setTimeout(function () { location.reload(); }, 90000);
  });

  showPhraseState();
})();
</script>
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
        # The ASIN is what identifies a product to the form, and colour variants of
        # one item share a label but not an ASIN, so the card has to show it.
        f'<p class="asin">{escape(asin)}</p>',
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
    parts.append(FORM)
    parts.append(
        SCRIPT.replace("__NTFY__", config.NTFY_SERVER)
              .replace("__VERSION__", str(commands.COMMAND_VERSION))
    )
    parts.append(
        f'<details><summary class="meta">Lost the passphrase?</summary>'
        f'<p class="meta">Add and remove products on GitHub instead: '
        f'<a href="{escape(config.MANAGE_WORKFLOW_URL)}">the manage workflow</a>. '
        'Tap "Run workflow", choose add or remove, and paste an ASIN or an Amazon link.'
        '</p></details>'
    )
    parts.append(
        f'<p class="meta">Times are {escape(config.DISPLAY_TZ.split("/")[-1])} local unless '
        'marked UTC.</p>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)
