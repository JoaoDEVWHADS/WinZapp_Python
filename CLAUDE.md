# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WinZapp is a free, self-hosted Windows desktop WhatsApp client built specifically for **accessibility** (blind/low-vision users via NVDA/JAWS/Narrator through `accessible_output2`). It's a hybrid app: a Python 3.13 + wxPython GUI process drives a locally-run **WPPConnect Server** (Node.js, cloned/built from the upstream `wppconnect-team/wppconnect-server` repo) that acts as the actual WhatsApp Web gateway. The two processes talk over local HTTP REST (`http://127.0.0.1:6300/api/...`) and Socket.IO (real-time events).

## Commands

### Dev setup
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds pytest, pytest-cov, pytest-asyncio
python setup_api.py                   # clones + builds client/api/ (WPPConnect Server) — one-time, requires Node
```
`setup_api.py` clones WPPConnect Server into `client/api/`, restores WinZapp's custom patched files (`start.js`, `package.json`, `config.json`, a handful of `src/**/*.ts` controllers), then runs `npm install` and `npm run build` inside `client/api/`. Re-run it any time `client/api/` needs to be rebuilt — it preserves `node_modules` and the custom files across re-clones.

### Run the client in dev mode
```powershell
cd client
python main.py
```
Entry point is `client/main.py`, guarded by `if __name__ == "__main__":` near the bottom of the file. There is no separate "start the API server" dev command — `main.py` launches/manages the local Node WPPConnect Server process itself.

### Tests
```powershell
pytest                                   # from repo root; pytest.ini sets pythonpath=client, asyncio_mode=auto
pytest tests/test_database.py            # single file
pytest tests/test_database.py::TestChats::test_upsert_chat_creates_record  # single test
```
Tests cover `client/core/database.py` and `client/core/database_bridge.py` (async SQLite layer + its sync façade) and small islands of pure logic pulled out of `main.py`/`core/notification_manager.py`/`ui/conversations.py` (e.g. `tests/test_sender_names.py`, `tests/test_notifications.py`, `tests/test_delivery_status.py`, `tests/test_send_jid_resolution.py`, `tests/test_message_bookmarks.py`) by binding their unbound methods onto a plain stub object — `MainWindow`/`ConversationsPanel` are wx.Frame/wx.Panel and can't be instantiated without a running wx.App, so the stub carries only the attributes the method under test actually touches. There are no tests for the wx UI in bulk. Async tests use `pytest-asyncio` in `auto` mode — no `@pytest.mark.asyncio` decorator needed, just declare test functions `async def`. **New functions/features should come with a test in this style as part of the same change.**

### Building the distributable
```powershell
venv\Scripts\python.exe build.py             # onedir: WinZappInstaller.exe + WinZapp.zip
venv\Scripts\python.exe build.py --onefile   # single-file WinZapp.exe + WinZapp.zip
```
Requires, in addition to the venv: `client/node/` (portable Windows x64 Node.js extracted there), `client/api/dist/server.js` built (via `setup_api.py`), and — for `--onedir` only — `gcc`/`windres` in `PATH` (MSYS2 UCRT64) to compile the C installer/uninstaller stubs in `installer/`. `client/api/` and `client/node/` are git-ignored and must be prepared locally before building; see `.github/workflows/release.yml` for the exact CI sequence if reproducing a release build.

## Architecture

### Two-process split
- **`client/` (Python/wxPython)** — all UI, business logic, local persistence, notifications, sounds. This is what you'll be editing almost all of the time.
- **`client/api/` (Node/TypeScript, vendored via `setup_api.py`, not committed)** — WPPConnect Server, a Puppeteer-driven WhatsApp Web automation server. WinZapp keeps a small set of patched files on top of upstream (`start.js`, `package.json`, `config.json`, a few `src/**/*.ts` controllers) — `setup_api.py` re-applies these after every clone/checkout. Treat this directory as mostly third-party; only touch the specific patched files WinZapp owns.
- `client/api2/` is a small standalone Puppeteer/Chrome auto-install helper script, unrelated to the main WPPConnect flow above.

### `client/main.py` — the god object
Almost everything (WebSocket/HTTP calls to WPPConnect, JID normalization, chat/contact state, sync, sound/notification dispatch, menu wiring, update checks) lives on the single `MainWindow(wx.Frame)` class in `client/main.py` (~11,700 lines). When making a change, `grep` this file first — the method you need very likely already exists here rather than in a smaller module.

### Message/data pipeline
1. **`client/core/websocket_client.py`** (`WebSocketClient`) connects to WPPConnect's Socket.IO and normalizes raw WPPConnect/Baileys event payloads into WinZapp's canonical message dict shape: `{"key": {"remoteJid", "fromMe", "id", "participant"?}, "message": {...}, "messageType": "...", "messageTimestamp": ..., "pushName": "..."}`. All downstream code (`main.py`, `core/database.py`, `ui/conversations.py`) assumes this shape.
2. **`MainWindow.on_new_message()`** (live messages) and **`on_historical_message()`** (history-sync backfill) in `main.py` are the two funnels every incoming/echoed message passes through: they resolve `@lid`↔phone duplicates, match echoes of our own sends against locally-registered "pending" virtual messages, update in-memory `self.chats`, and schedule a debounced persist. Both — plus `_extract_lid_mapping()`, which `WebSocketClient.on_messages_upsert()` also calls directly on the Socket.IO thread, bypassing the other two entirely — are gated by `MainWindow._live_events_ready()`: a reused pairing WebSocket can start delivering events before `prepare_sync()` has created `self.db`, or before the initial sync has actually started, and processing a message that early either crashes (attribute doesn't exist yet) or lets a live event sneak a chat into the list ahead of the sync about to fetch the authoritative state. `is_countable_message()` (module-level in `main.py`) further excludes WhatsApp/WPPConnect system events (`groupNotification`, `protocolMessage` — group join/leave, settings changes, revokes) from ever bumping a chat's sort position, incrementing its unread badge, or firing a notification; they're still stored and shown as a timeline entry when the conversation is opened.
3. **Outgoing sends**: UI code in `client/ui/conversations.py` builds a "virtual" pending message dict (`_local_pending: True`, `_local_id: <uuid4>`) shown immediately in the UI, and hands it to **`client/core/message_queue.py`**'s `MessageQueue` (one background thread). The queue calls the matching `send_*` method on `MainWindow` (`send_text_message`, `send_audio_message`, `send_media_attachment`, `send_contact_attachment`), which POSTs to a WPPConnect REST endpoint and returns the real WhatsApp message ID. A send failure is classified before it's retried: an explicit "Disconnected" response leaves the message queued untouched, a timeout/dropped connection is treated as *ambiguous* (WhatsApp Web may have accepted it into its own outbox already) and is handed off without a resend, and only a definite server-side failure retries — at most 4 times. This exists because retrying an ambiguous failure used to duplicate real sends when connectivity flapped. Separately, the *same* sent message also arrives back through the WebSocket echo path (`on_new_message`, `from_me=True`) — since WPPConnect gives no client-side correlation ID on that echo, it's matched against pending virtual messages **by message type** (text/audio/image/etc.), not by content. Be careful here: matching the wrong pending message swaps real WhatsApp IDs between unrelated messages (wrong status, wrong audio file playback).
4. **`client/core/database.py`** (`DatabaseManager`) is a fully async `aiosqlite` layer — single serialized connection, WAL mode, per-write `asyncio.Lock`. Indexed columns (`jid`, `timestamp`) are plaintext; payload columns (`message_json`, `last_message_json`) are Fernet-encrypted with a per-install key (`data/secret.key`). Storage is SQLite-only (`messages.db`) — there is no `messages.dat` fallback or migration path any more; that legacy format was retired.
5. **`client/core/database_bridge.py`** (`DatabaseBridge`) is the sync façade `main.py` actually calls: it runs a dedicated background asyncio event loop in its own thread and dispatches every `DatabaseManager` call via `asyncio.run_coroutine_threadsafe(...).result(timeout=...)`, blocking the calling (wx/worker) thread until the call finishes or the timeout elapses. This exists because wx and the rest of the app are synchronous/thread-based, but the DB layer is async. The timeout (and `close()` refusing new calls / waiting briefly for in-flight ones to drain before stopping the loop) exist specifically to keep a stuck coroutine from freezing the whole app forever — that used to be the most commonly reported "WinZapp stopped responding" symptom.

### JID handling — the recurring source of bugs
WhatsApp JIDs come in several forms and normalizing them wrong is the single most common bug source in this codebase:
- `@s.whatsapp.net` — modern phone JID (canonical form WinZapp normalizes everything to).
- `@c.us` — legacy phone JID format some WPPConnect responses still use; normalized to `@s.whatsapp.net` on load (`MainWindow.deduplicate_chats`, `_normalize_jid`).
- `@lid` — a linked/multi-device identifier (not a phone number). Must be bridged to a phone JID via the `_lid_to_phone` / `_phone_to_lid` caches (`main.py`) before it's usable for display, sending, or contact lookup. Brazilian numbers additionally need 8/9-digit interchangeability handling.
- `@g.us` — group JID. **Not trustworthy on its own**: WPPConnect/Baileys can emit a self-chat echo (seen with self-sent documents) whose `remoteJid` is built from a participant's own `@lid` digits but suffixed `@g.us` — i.e. a fake "group" whose JID equals a participant's JID, which real WhatsApp groups never do. `MainWindow.deduplicate_chats()` has a guard pass for this; `on_new_message()` redirects it at the source. If you touch group-detection logic, keep this invariant (`group_jid` digits are never a participant's digits) in mind.
- `@broadcast` — status/stories, routed to `_store_status_update`, never a normal conversation.
- `@newsletter` — WhatsApp channels; explicitly ignored.

### Pairing flow — nested modal dialogs
`Connect.show_connection_dial()` and `show_pairing_dial()` (`client/ui/dialogs/connect.py`) are both shown via `ShowModal()`, with `pairing_dial` nested inside `connection_dial`'s own modal loop (opened from a button handler running inside it). `WebSocketClient.on_pairing_complete()` (`core/websocket_client.py`) closes them once pairing succeeds — but wx only allows `EndModal()` on the loop that is actually running, and `EndModal()` doesn't unwind its loop immediately (it only signals it; that loop keeps dispatching pending events, including any `wx.CallAfter` queued from inside it). So `connection_dial` can only be closed from `show_pairing_dial()` itself, right after its own `ShowModal()` call has genuinely returned — not from `on_pairing_complete()`, inline or via a chained `CallAfter`, which both hit a `wx._core.wxAssertionError` ("IsRunning() failed") on the still-suspended parent loop. Getting this wrong reproduces as: pairing appears to succeed (connected sound plays), but the main window and tray icon never appear, sync never starts, and nothing is logged unless you instrument `EndModal()` calls directly — `MainWindow.__init__` just never returns from `show_connection_dial()`.

### Paths, config, i18n
- `client/app_paths.py` abstracts dev-mode vs. frozen (PyInstaller onedir/onefile, and legacy Nuitka onefile) path resolution — always go through `resource_path()` (read-only bundled assets: sounds/, languages/, lib/) and `data_path()`/`log_path()` (writable runtime data next to the exe) rather than hardcoding paths.
- `client/config.py` loads an optional `.env` next to the exe (or repo root in dev) for overrides like `WINZAPP_GITHUB_REPO` (used by the auto-updater).
- `client/languages/{pt-BR,pt-PT,en-US,es-ES}.json` + `client/core/i18n.py` (`I18n.t(key)`) — pt-BR is the default/fallback locale. **When adding any user-facing string, add the key to all four files**, not just one.
- Runtime data (`data_path()`): `messages.db` (SQLite), `secret.key` (Fernet key), `settings.json` (seeded from `client/data/settings_default.json`), `voice_messages/`, `media/`.
- Logging (`log_path()`): a single `log.log`, truncated at the start of every launch (plain `logging.FileHandler(mode="w")`, not a `RotatingFileHandler` — there are deliberately no `log.log.1`/`.2` backups). `setup_logging()` runs only after the single-instance mutex is acquired, so a second launch while WinZapp is already running never wipes the log of the instance actually doing the work. When diagnosing anything startup/pairing-related, this file's breadcrumb `logging.info(...)` calls (`[prepare_sync]`, `[init_UI]`, `[show_connection_dial]`, `[show_pairing_dial]`, `[on_pairing_complete]`, ...) are the fastest way to pinpoint exactly which step never happened — always ask for the current run's `log.log` rather than guessing.

### Accessibility constraints
This is the app's core differentiator, not an afterthought: UI is built from plain wx controls (`wx.ListCtrl`, `wx.TextCtrl`, standard menus/dialogs) specifically because screen readers can read them reliably — avoid custom-drawn/owner-drawn controls. Batch list mutations inside `Freeze()`/`Thaw()` so screen readers get one accessibility event instead of a flood. Dialog titles and list items must resolve human-readable names (contact/group name) rather than raw JIDs — NVDA will otherwise read out raw phone-number/JID digits.

### Auto-updater (`client/updater.py`)
`UpdateChecker` polls the GitHub Releases API (repo from `config.GITHUB_REPO`), compares `version.__version__` against the latest tag, and on acceptance downloads the release's ZIP asset, extracts it, and hands off to a generated `.bat` script that waits for the current process to exit, kills stray WPPConnect/Postgres processes on ports 6300/5433, copies files over the install dir, and relaunches — because Windows won't let a running process overwrite its own files.

### Packaging (`build.py`, `installer/`)
`build.py` runs PyInstaller (via CLI args with `--collect-all`, not the checked-in `client/WinZapp.spec`, which is stale/unused) to compile `client/main.py`, then for onedir builds also compiles the C installer/uninstaller stubs in `installer/` (gcc + windres), zips the staged app as a `ZIP_STORED` payload, and appends it to the installer stub to produce a single self-extracting `dist/WinZappInstaller.exe`, plus a plain `dist/WinZapp.zip` portable build. `client/api/` and `client/node/` are excluded from git and must exist on disk before running it.
