# Inspecting a live session

> How to look inside the session the user's WinZapp is running right now,
> on each connection engine. It is the user's real account: read freely, act
> (send, delete, mark read, leave, block...) only when the user asked for that
> action and named the chat. Never print a secret, a token, or an unredacted
> JID, number or name (`docs/traps/log-pii.md`).

## WPPConnect: Chrome DevTools Protocol

WhatsApp Web runs in WinZapp's own Chrome, so the page can be read and
evaluated over CDP, far cheaper than a restart and a log line.

- WinZapp's Chrome is `HeadlessChrome` on a loopback remote-debugging port.
  Find the port with `netstat` against the `chrome.exe` PIDs, and confirm it
  with `/json/version` (it must say `HeadlessChrome`) **before** listing
  targets, so a personal Chrome's tabs are never read.
- `Runtime.evaluate` in the WhatsApp Web target reaches `WPP.*`, the stores and
  `window.require('__debug').modulesMap` (what that can and cannot show:
  `docs/traps/send-contract.md`).
- Worked examples: `docs/traps/voice-calls.md` (VoIP statistics, call state,
  a renderer that stopped answering), `docs/traps/sync-completion.md` (a
  missing CDP result is not an empty ChatStore), `docs/traps/whatsapp-web-version-pin.md`.
- One CDP connection carries everything the client sends to the page: a burst
  of evaluates from several threads queues behind it.

## Neonize: there is no CDP

The Neonize engine (`neonize_bridge/`) has no browser and no page. whatsmeow
(Go, compiled into neonize's DLL) speaks WhatsApp's protocol directly inside
a Python process, so there is nothing to attach a debugger to and no
JavaScript to evaluate. What there is instead:

### The bridge's HTTP API

The same WPPConnect routes the client calls (`neonize_bridge/COVERAGE.md`
lists them), on `127.0.0.1:6300`. `/health` answers without credentials;
every `/api/...` route needs the session's token:

- the session name is the account id, listed in `neonize_bridge/data/active.json`;
- the secret is `neonize_bridge/data/secret`;
- the token is `<name>:<HMAC-SHA256(secret, name)>`
  (`authentication.session_token`), and the URL `/api/<token>/<route>`.

Run from `neonize_bridge/` with its own interpreter:

```python
# .venv\Scripts\python.exe -I -   (stdin), from neonize_bridge/
import json, sys, urllib.request
sys.path.insert(0, ".")
import authentication as auth

secret = open("data/secret", encoding="utf-8").read().strip()
name = json.load(open("data/active.json"))[0]
token = f"{name}:{auth.session_token(secret, name)}"

def call(route, body=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:6300/api/{token}/{route}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

print(call("status-session")["status"])        # CONNECTED, QRCODE, CLOSED...
```

`list-chats` (POST `{}`), `get-messages/<jid>`, `all-groups`,
`status-session` and the other reads answer exactly what the client gets.
Print counts and the last digits of a JID (`"..." + jid[-9:]`), never the
whole answer. Find a chat by the name the user gave, not by guessing a JID.

### `bridge.log`

`neonize_bridge/run/bridge.log` (past 5 MB, the next start keeps the old one as
`bridge.log.1`) is
the bridge's stdout and logging, already redacted (`redaction.py`). A failed
route logs `log.exception("<route>")` with the full traceback: grep `ERROR`
first. It is the Neonize counterpart of `wppconnect.log`; the client's own
`log.log` is unchanged. `server.py --log-state` adds app-state events, but
WinZapp does not pass it: it needs a bridge started by hand, which is not the
user's.

### `bridge.db` and `session.db`

Each session folder `neonize_bridge/data/<account id>/` holds these SQLite files:

- `bridge.db` is the bridge's own store (`chats`, `contacts`, `msgs`,
  `pinned`, `votes`, `reactions`, `receipts`, `comments`). Open it read-only
  while the bridge runs: `sqlite3.connect("file:<path>?mode=ro", uri=True)`.
- `carts.json` holds the account's carts, one per seller (`commerce_cart.py`);
  `labels.json` the labels the bridge created.
- `app_state.db` (`app_state_mirror.py`) is the bridge's copy of the app state
  entries whatsmeow has no event for: labels and custom lists, status privacy.
  `bridge.log` names each kind of mutation once
  (`app state: regular label_edit v3 set`, the server of an address in
  brackets, never its digits): that is how a new index is found.
- `session.db` is whatsmeow's device state: the keys that *are* the login.
  Never open, copy, print or attach it.

### What you cannot do

- **Connect a second client to the same session.** A device has one
  connection; a second neonize process on the same `session.db` fights the
  user's live one. Never start another bridge on `neonize_bridge/data/`.
- **Evaluate code inside the bridge.** To learn what neonize does, read its
  source, Go side included, in the workspace `build_neonize.py prepare`
  makes (`neonize_bridge/neonize_build/neonize/`, `whatsmeow/`, `meowcaller/`;
  `docs/reference/neonize-build.md`). To try a behaviour,
  reproduce it against a fake client (`test_*_server.py` drive `create_app`
  that way).

### Finding a stanza the bridge does not know yet

whatsmeow has no function for many things WhatsApp Web does (catalogs,
community joins, channel edits...). The reference is WhatsApp Web itself: with
the account also linked on WPPConnect, switch the engine, and over CDP read the
page's modules. A module's source is in the scripts the page loaded (fetch
them in the page from the HTTP cache and split them at `__d("Name",`): the
`modulesMap` drops a factory once it ran. A lazily loaded module (a modal's
job) is loaded with `require("Bootloader").loadModules([...])`, which only
fetches code and shows nothing. Look for the `WASmaxOut...Request` (the
stanza), the `...Job` (what it is sent with and how the answer is read) and,
for app state, the `...Sync` module (collection, index, version). Read only:
never call a job. The bridge sends what you found with `send_iq` / `send_mex`
(`raw_queries.py`) or `app_state_mirror.send`.

### Your change is not running yet

WinZapp starts the bridge and the last window to close stops it; nothing
restarts it in between. A bridge started before your commit runs the old
code: compare `neonize_bridge/run/bridge.pid`'s time with the commit's. Only
restarting WinZapp loads the new code, and that is the user's live session:
ask them, never kill the bridge yourself.
