# Amazon watcher: add and remove from the status page: design

Date: 2026-09-12. Status: approved in chat, ready for implementation.

Extends `2026-09-12-amazon-watch-multi-product-design.md`. The `manage` workflow
stays exactly as it is; this adds a second way in, from the page itself.

## Goal

Add and remove watched products from the status page, with no visit to GitHub and
no credential in the page. The page is static HTML on GitHub Pages, so it has no
server of its own; the watcher's own long-running job becomes the server.

## The problem with the obvious approaches

A static page cannot start a GitHub workflow without a credential, and a
credential in a public page is readable by anyone who opens it. GitHub also
revokes tokens it finds in public repositories, so embedding one does not even
work. A proxy holding the token (a Cloudflare Worker or similar) is the standard
answer but needs a new account and a deploy. Neither was wanted.

## Approach: a signed mailbox on ntfy

The poll job already runs continuously for about six hours at a time. It gains a
mailbox it checks every minute while it waits. The page drops signed notes in.

```
status page (public, static)
   |  POST {cmd, sig}            no credential in the page
   v
ntfy.sh/<topic derived from the passphrase>
   ^
   |  GET ?poll=1&since=...      once a minute while the poll job sleeps
poll job  -->  products.json  -->  commit, push, re-render
```

### The passphrase is the only secret

One passphrase, held in the repository secret `CMD_PASSPHRASE` and typed once
per browser by the user. Everything else is derived from it, so nothing secret is
ever written into the page or transmitted.

- **Topic name**: `amzcmd-` + the first 24 hex characters of
  `HMAC-SHA256(passphrase, "topic")`. The mailbox address is therefore
  unguessable and does not appear in the page source. A stranger reading the
  page's JavaScript learns the *method*, not the address.
- **Signature**: `HMAC-SHA256(passphrase, canonical)` where `canonical` is
  `"<action>\n<product>\n<label>\n<ts>\n<nonce>"`. The passphrase is never sent,
  so reading a message off the topic does not reveal it.

### Message format

The page POSTs one JSON object as `text/plain` (which keeps it a CORS simple
request, so no preflight):

```json
{
  "cmd": {"action": "add", "product": "B07W1P15GL", "label": "Ladle",
          "ts": 1789567890, "nonce": "9f2c...", "v": 1},
  "sig": "4e1d..."
}
```

`ts` is seconds since the epoch, `nonce` is 16 random hex characters.

### What the watcher accepts

A note is applied only if all of these hold. Anything else is ignored silently,
because a public topic can be written to by anyone and noise must be free:

- the JSON parses and carries `cmd` and `sig`, with `cmd.v == 1`
- the signature matches, compared with `hmac.compare_digest`
- `ts` is within `COMMAND_MAX_AGE` (600 seconds) of now, in either direction
- the nonce has not been seen before

Seen nonces live in `state.json` under `command_nonces`, capped at the most
recent `NONCE_MEMORY` (200) entries. That cap is what bounds replay protection:
a note older than 600 seconds is rejected by the timestamp check anyway, so the
nonce list only has to cover that window, and 200 is far more than a minute's
worth of legitimate traffic.

### Replies

After acting, the watcher publishes a reply to the same topic so the page can
say what happened rather than leaving the user guessing:

```json
{"reply": "<nonce>", "ok": true, "message": "add: B07W1P15GL (2 products watched)"}
```

Replies are not signed. They are advisory text for the page; nothing acts on
them, and a forged reply can only mislead the person who sent the command, who
sees the truth on the next page refresh.

The page polls the topic for up to 90 seconds looking for its own nonce, shows
the message, and then reloads itself so the new card appears.

## Components

### `commands.py` (new)

```python
COMMAND_VERSION = 1
COMMAND_MAX_AGE = 600     # seconds a note stays valid
NONCE_MEMORY = 200        # nonces remembered, which bounds replay protection
FETCH_LIMIT = 50          # notes read per check, so a flooded topic cannot stall the poll

def topic_for(passphrase: str) -> str
def sign(passphrase: str, cmd: dict) -> str
def verify(passphrase: str, cmd: dict, sig: str) -> bool
def apply_commands(passphrase, products_path, state, now, get=..., post=...) -> bool
```

`apply_commands` returns True when `products.json` changed. It never raises: a
network failure, a rate limit, or a malformed note is logged and skipped, because
a mailbox problem must not stop the watcher from watching.

It reads `https://ntfy.sh/<topic>/json?poll=1&since=<n>s`, where `n` covers the
time since the last check plus a margin, capped at `COMMAND_MAX_AGE`. ntfy
returns one JSON object per line.

### `state.py`

Two fields are added to the top level, beside `last_checked`:

- `command_nonces`: list of applied nonces, newest last, capped at `NONCE_MEMORY`
- `last_command_check`: ISO timestamp of the last mailbox check

### `main.py`

A new entry point beside `run`:

```python
def tick(now=None, ...) -> dict   # check the mailbox, poll if due, persist, render
```

The workflow calls one of two module entry points each minute. Keeping the
mailbox check and the Amazon poll in separate functions is what lets the mailbox
be checked every minute while Amazon stays hourly.

### `render.py`

Below the cards, a form:

- a passphrase field, shown only when the browser has not stored one, with a
  "forget passphrase" link once it has
- add or remove, a product field taking an ASIN or an Amazon link, an optional
  label, and a Send button
- a status line that reports what the watcher replied

The JavaScript is inline, uses WebCrypto for HMAC, and stores the passphrase in
`localStorage` under `amazon-watch-passphrase`. It never contacts GitHub.

The "Manage products" button stays below the form as the fallback for a lost
passphrase, and "Check now" stays as it is.

## Workflow

`poll.yml`'s loop changes shape. Instead of sleeping an hour between polls, it
ticks every `TICK_SECONDS` (60):

```
loop:
  sync to origin/main
  python -m watch.tick        # applies commands; polls Amazon if due
  commit and push if anything changed
  sleep TICK_SECONDS
```

"If due" means `INTERVAL_SECONDS` has passed since `last_checked`, which is read
from the state file, so the hourly Amazon cadence survives a job restart. A
command that changes the product list forces the next tick to poll, so a newly
added product appears on the page within about a minute rather than at the next
hour.

`CMD_PASSPHRASE` joins the environment of that step. With the secret unset the
mailbox check is skipped entirely and the watcher behaves exactly as it does
today.

## Cost

One ntfy GET per minute per running job, about 350 per job, against ntfy.sh's
per-visitor allowance of roughly 720 an hour. A rate-limited check is skipped and
retried on the next tick. Amazon sees no extra traffic at all.

## Testing

No network. `apply_commands` takes its `get` and `post` as parameters.

- `test_commands`: the topic is derived from the passphrase and changes with it;
  a signed note verifies and a tampered one does not; a note older than
  `COMMAND_MAX_AGE` is rejected; a replayed nonce is applied once; a note with a
  bad signature, bad version, bad JSON or an unknown action is ignored; add and
  remove change `products.json`; a failing `get` returns False without raising; a
  reply is posted for an applied note and for a rejected one that was correctly
  signed; the nonce list stays capped.
- `test_main`: a tick with a due poll polls, a tick without one does not, and a
  command that changes the list forces a poll on the same tick.
- `test_render`: the form is present, the passphrase field is there, the page
  contains no topic name and no GitHub token.

## Out of scope

Editing a label from the page, reordering, per-product settings, signed replies,
and any second transport if ntfy.sh is down.
