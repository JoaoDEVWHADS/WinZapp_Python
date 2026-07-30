# WinZapp (Fork)

> **This repository is a [fork of the original repository by Gabriel Haberkamp](https://github.com/gabrielhhaber/WinZapp_Python).**  
> All credits for the initial development and project architecture belong to the original author. This fork focuses on stabilization, build automation, accessibility bug fixes, and restructuring the update system for the WPPConnect Server backend.

---

WinZapp is a **free, self-hosted, open-source desktop WhatsApp client for Windows**, built primarily for **accessibility for blind and low-vision users**.
It is designed from the ground up to work with screen readers (NVDA, JAWS, Narrator) through [accessible-output2](https://github.com/accessibleapps/accessible_output2), with a fully keyboard-navigable interface built on plain wxPython controls rather than custom-drawn UI.

The application is split into two processes that run together locally:
1. **Client (Python 3.13 + wxPython):** all UI, business logic, local storage, notifications, and sounds.
2. **WPPConnect Server (Node.js):** a locally-run WhatsApp Web automation gateway, built from the upstream [wppconnect-team/wppconnect-server](https://github.com/wppconnect-team/wppconnect-server) project with a small set of patches WinZapp maintains on top. The client talks to it over local HTTP (`http://127.0.0.1:6300/api/...`) and Socket.IO.

---

<<<<<<< HEAD
## 🛠️ Improvements in this Fork

Since the original fork, a deep restructuring has been performed in the following areas:

### 1. WPPConnect Server Integration
* **API Framework Switch:** Restructured the startup launchers (`start.js`), configuration setup (`setup_api.py`), and Python controllers to support a compiled, highly responsive WPPConnect Server backend instead of Evolution API.
* **Port Uniformity:** Shifted default API ports to `6300` throughout client configurators and launcher scripts to guarantee reliable out-of-the-box local connections.

### 2. Auto-Updater Redesign (Zero Conflicts)
* **Direct GitHub Integration:** Removed the reliance on static files in the repository. The updater now queries the GitHub Releases API directly to pull notes and version info.
* **Release of File Locks:** Resolved update-time access denied errors by adding netstat port scanners in the updater batch script. The updater dynamically terminates processes bound to port **6300** (WPPConnect Server) and port **5433** (Postgres) and kills remaining node processes before overwriting client files.

### 3. @lid JID Resolution & Cache Overhaul
* **Background Profiles Resolution:** Integrated background queries leveraging the `/contact/fetchProfile` endpoint to map linked secondary device JIDs (`@lid`) to standard phone numbers and contact names, resolving blank list items.
* **Encrypted JID Cache:** Implemented local `_lid_to_phone` mappings that are encrypted and cached directly in the local database (`messages.dat`) on exit.
* **Real-time Deduplication:** Merges messages and unread counts from `@lid` chats directly into standard `@s.whatsapp.net` chats on startup and on incoming events.
* **Placeholder Exclusions:** Prevents placeholder names (e.g. "Contato sem nome") from polluting JID resolution.
* **Brazilian 9-Digit Interchangeability:** Added support for matching and resolving Brazilian phone number JIDs interchangeably with and without the 9th digit (e.g. 55XX9YYYYYYYY vs 55XXYYYYYYYY).

### 4. Advanced UX & NVDA Accessibility Safeguards
* **NVDA COMError & Stuttering Fixes:** Added virtual focus guards (`list_has_focus` and sync status checks) to prevent NVDA/JAWS screen readers from stuttering or entering announcement loops when rebuilding chat lists. Also cleared selection states before deletions to prevent COMErrors.
* **Debounced Local Writes:** Wrapped the disk writer in a thread-safe `_save_lock` and debounced disk access (`150ms` delay) to prevent `messages.dat` file corruption when receiving bulk message logs.
* **Silent Disconnection Loop:** Adopted upstream's Socket.IO reconnection loop and silent status bar indicators for network glitches to avoid locking the UI with blocking popup dialogs.
* **PTT Voice Note Audio Controls:** Added the upstream visual playback controls for playing voice notes directly within the conversation UI.
* **Group Mentions Routing:** Integrated upstream's `@mention` lists and `mentioned_jids` parameters, routing them to WPPConnect's specialized `/api/:session/send-mentioned` endpoint.

### 5. Persistent & High Verbosity Logging
* **Full Debug Tracing:** Configured persistent client logging under `logs/log.log` at the `DEBUG` level. This captures HTTP headers, Socket.IO websocket payloads, and thread exceptions.
=======
## Key Features

### Accessibility
* Built entirely from standard wx controls (`wx.ListCtrl`, `wx.TextCtrl`, standard dialogs/menus) so screen readers read them reliably, instead of custom-drawn or owner-drawn UI.
* List updates are batched so a screen reader receives one accessibility event per change instead of a flood during bulk updates (e.g. syncing history).
* Dialog titles and list items resolve to human-readable contact/group names rather than raw phone numbers or WhatsApp JIDs.
* Playback controls for voice notes directly inside the conversation view.

### Messaging
* Text, voice notes, images, videos, documents, contacts, replies/quotes, @mentions, reactions, message edits and deletes, read receipts, and typing/recording indicators.
* Local message history stored in an encrypted SQLite database (`messages.db`), with a background-managed connection so the UI never blocks on disk I/O.
* Outgoing sends go through a background queue with automatic retry and duplicate-delivery protection for ambiguous network failures.

### JID handling
WhatsApp uses several different identifier formats for the same contact (`@s.whatsapp.net`, the legacy `@c.us`, and `@lid` for linked/multi-device identities). WinZapp normalizes these to a single canonical form per contact, bridges `@lid` identities to phone numbers as they are resolved, and handles the Brazilian 8/9-digit mobile number variants transparently.

### Auto-updater
* Checks GitHub Releases for new versions and can download and install updates automatically.
* Before overwriting files, it stops any stray WPPConnect Server (port 6300) or PostgreSQL (port 5433) processes still holding a lock on them.

### Security
* The WhatsApp session token and local message payloads are encrypted at rest with a per-install Fernet key.
* Downloaded release assets and the portable Node.js runtime are checksum-verified before use.
>>>>>>> upstream/main

---

## Development Environment

### Prerequisites
* **Python 3.13**
* **Node.js** (used by `setup_api.py` to build the WPPConnect Server; a portable copy can also be placed at `client/node/`)
* **Git**
* For building the installer locally only: **GCC** and **windres** (available via [MSYS2](https://www.msys2.org/), UCRT64 toolchain)

<<<<<<< HEAD
### Steps to Run Locally:
=======
### Steps to run locally

>>>>>>> upstream/main
```powershell
# 1. Clone the repository
git clone https://github.com/JoaoDEVWHADS/WinZapp_Python.git
# Or for WPPConnect server setup:
python setup_api.py

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

<<<<<<< HEAD
# 3. Install the dependencies
=======
# 3. Install dependencies
>>>>>>> upstream/main
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds pytest and friends, for running tests

<<<<<<< HEAD
# 4. Start the client in development mode
=======
# 4. Set up the WPPConnect Server (clones and builds client/api/)
python setup_api.py

# 5. Start the client in development mode
>>>>>>> upstream/main
cd client
python main.py
```

`setup_api.py` clones WPPConnect Server into `client/api/`, restores WinZapp's own patched files on top, then installs its Node dependencies and builds it. Re-run it whenever `client/api/` needs to be rebuilt from scratch — it preserves `node_modules` across re-clones.

### Running tests

```powershell
pytest                                   # full suite, from the repository root
pytest tests/test_database.py            # a single file
pytest tests/test_database.py::TestChats::test_upsert_chat_creates_record  # a single test
```

Tests cover the async SQLite storage layer and the pure-logic pieces of the client (name resolution, notification formatting, message classification, etc.) using small stand-in objects, since the wxPython UI classes cannot be instantiated without a running `wx.App`.

Every release build is gated on the full test suite passing (see [.github/workflows/release.yml](.github/workflows/release.yml)) — a failing test suite deletes the release instead of shipping it.

---

<<<<<<< HEAD
## 📦 Local Compilation (Build)

To compile and generate the `WinZappInstaller.exe` installer and the portable `WinZapp.zip` version locally on your Windows machine:

```powershell
# With the virtual environment active and C tools (GCC/windres) in your PATH:
python build.py
```

The final compiled files will be generated in the `dist/` directory at the root of the project.
=======
## Building

### Automated (recommended)

Creating a GitHub release triggers the [release workflow](.github/workflows/release.yml), which runs the test suite and, if it passes, builds `WinZappInstaller.exe` and `WinZapp.zip` on GitHub's own servers and attaches them to the release.

To publish a new release (requires the [GitHub CLI](https://cli.github.com/)):

```powershell
gh release create v1.2.3 --title "v1.2.3" --notes "Release notes here"
```

### Local build (fallback)

Requires the portable Node.js runtime placed at `client/node/` and the WPPConnect Server built at `client/api/dist/server.js` (via `setup_api.py`). The default onedir build additionally requires MSYS2 with GCC/windres in `PATH`, used to compile the C installer/uninstaller stubs.

```powershell
# With the virtual environment active (and GCC/windres in PATH for the onedir build):
python build.py             # onedir build: WinZappInstaller.exe + WinZapp.zip
python build.py --onefile   # single-file build: WinZapp.exe + WinZapp.zip (no GCC/windres needed)
```

The resulting files are written to the `dist/` directory.
>>>>>>> upstream/main

---

## License and Disclaimer

<<<<<<< HEAD
WinZapp is a project licensed under the GPL. It relies on reverse engineering of the WhatsApp Web protocol. Use of the software is at your own risk. This repository is not affiliated with, maintained, or sponsored by Meta Platforms, Inc.
=======
WinZapp is licensed under the GNU General Public License v3.0 (see [LICENSE](LICENSE)). It works by automating the WhatsApp Web interface and is not built on any official WhatsApp/Meta API. Use of this software is at your own risk. This project is not affiliated with, maintained by, or endorsed by Meta Platforms, Inc.
>>>>>>> upstream/main
