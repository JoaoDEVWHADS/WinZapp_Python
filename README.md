# WinZapp

WinZapp is a **free, self-hosted, open-source desktop WhatsApp client for Windows**, developed primarily with a focus on **accessibility for blind or low-vision users**.  
It integrates seamlessly with screen readers (such as NVDA, JAWS, Narrator, and others) through the [accessible-output2](https://github.com/accessibleapps/accessible_output2) ecosystem, offering a fully keyboard-navigable interface using wxPython.

The application runs in a hybrid manner:
1. **Graphical Client:** Written in Python 3.13 + wxPython (responsible for the GUI, audio alerts, and screen-reading capabilities).
2. **WPPConnect Server:** Running locally on Node.js, acting as the communication gateway.

---

## ✨ Key Features

### WPPConnect Server Integration
* **API Framework:** Uses the WPPConnect Server backend with a compiled distribution. Startup launchers (`start.js`), configuration setup (`setup_api.py`), and Python controllers are all tuned for the WPPConnect stack.
* **Port Uniformity:** Default API port is `6300` throughout client configurators and launcher scripts for reliable out-of-the-box local connections.
* **Auto-install:** Node.js modules are downloaded and installed automatically on first run — no manual `npm install` needed by the end user.

### Auto-Updater
* **Direct GitHub Integration:** Queries the GitHub Releases API directly to pull release notes and version info.
* **Release of File Locks:** Resolves update-time access denied errors by scanning for processes bound to port **6300** (WPPConnect Server) and port **5433** (Postgres) and terminating them before overwriting client files.

### @lid JID Resolution & Cache
* **Background Profile Resolution:** Background queries via `/contact/fetchProfile` map linked secondary device JIDs (`@lid`) to standard phone numbers and contact names, resolving blank list items.
* **Encrypted JID Cache:** Local `_lid_to_phone` mappings encrypted and cached in the local database (`messages.dat`).
* **Real-time Deduplication:** Merges messages and unread counts from `@lid` chats into standard `@s.whatsapp.net` chats on startup and on incoming events.
* **Brazilian 9-Digit Interchangeability:** Matches and resolves Brazilian phone number JIDs with and without the 9th digit (e.g. 55XX9YYYYYYYY ↔ 55XXYYYYYYYY).

### Accessibility Safeguards
* **NVDA/JAWS Guards:** Virtual focus guards (`list_has_focus` and sync status checks) prevent screen readers from stuttering or entering announcement loops when rebuilding chat lists.
* **Debounced Local Writes:** Thread-safe `_save_lock` with a 150 ms debounce prevents `messages.dat` corruption under bulk message loads.
* **Silent Reconnection:** Socket.IO reconnection loop with silent status bar indicators for network glitches — no blocking popup dialogs.
* **PTT Voice Note Controls:** Playback controls for voice notes directly within the conversation UI.
* **Group Mentions:** `@mention` lists and `mentioned_jids` routing to WPPConnect's `/api/:session/send-mentioned` endpoint.

### Logging
* **Full Debug Tracing:** Persistent client logging under `logs/log.log` at `DEBUG` level, capturing HTTP headers, Socket.IO payloads, and thread exceptions.

---

## 💻 Development Environment

### Prerequisites
* **Python 3.13** installed on the system.
* **Git** for version control.
* For local installer builds: **GCC** and **windres** (available via MSYS2).

### Steps to Run Locally

```powershell
# 1. Clone the repository
git clone https://github.com/gabrielhhaber/WinZapp_Python.git
cd WinZapp_Python

# 2. Create and activate the virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set up the WPPConnect Server (clones and configures client/api/)
python setup_api.py

# 5. Start the client in development mode
cd client
python main.py
```

---

## 📦 Building

### Automated (recommended)

When a GitHub release is created, the [release workflow](.github/workflows/release.yml) automatically builds `WinZappInstaller.exe` and `WinZapp.zip` on GitHub's servers and attaches them to the release.

To publish a new release (requires [GitHub CLI](https://cli.github.com/)):

```powershell
gh release create v1.2.3 --title "v1.2.3" --notes "Release notes here"
```

### Local build (fallback)

Requires MSYS2 with GCC/windres, the portable Node.js placed at `client/node/`, and the WPPConnect Server built at `client/api/dist/server.js`.

```powershell
# With the virtual environment active and GCC/windres in PATH:
python build.py
```

The final files are generated in the `dist/` directory.

---

## 📄 License and Disclaimer

WinZapp is licensed under the GPL. It relies on reverse engineering of the WhatsApp Web protocol. Use of the software is at your own risk. This repository is not affiliated with, maintained, or sponsored by Meta Platforms, Inc.
