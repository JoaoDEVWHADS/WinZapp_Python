# WinZapp (Fork)

> **This repository is a [fork of the original repository by Gabriel Haberkamp](https://github.com/gabrielhhaber/WinZapp_Python).**  
> All credits for the initial development and project architecture belong to the original author. This fork focuses on stabilization, build automation, accessibility bug fixes, and restructuring the update system for the WPPConnect Server backend.

---

WinZapp is a **free, self-hosted, open-source desktop WhatsApp client for Windows**, developed primarily with a focus on **accessibility for blind or low-vision users**.  
It integrates seamlessly with screen readers (such as NVDA, JAWS, Narrator, and others) through the [accessible-output2](https://github.com/accessibleapps/accessible_output2) ecosystem, offering a fully keyboard-navigable interface using wxPython.

The application runs in a hybrid manner:
1. **Graphical Client:** Written in Python 3.13 + wxPython (responsible for the GUI, audio alerts, and screen-reading capabilities).
2. **WPPConnect Server:** Running locally on Node.js, acting as the communication gateway.

---

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

---

## 💻 Development Environment

### Prerequisites
* **Python 3.13** installed on the system.
* **Git** for version control.
* For local installer builds: **GCC** and **windres** (available via MSYS2).

### Steps to Run Locally:
```powershell
# 1. Clone the repository
git clone https://github.com/JoaoDEVWHADS/WinZapp_Python.git
# Or for WPPConnect server setup:
python setup_api.py

# 2. Create and activate the virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install the dependencies
pip install -r requirements.txt

# 4. Start the client in development mode
cd client
python main.py
```

---

## 📦 Local Compilation (Build)

To compile and generate the `WinZappInstaller.exe` installer and the portable `WinZapp.zip` version locally on your Windows machine:

```powershell
# With the virtual environment active and C tools (GCC/windres) in your PATH:
python build.py
```

The final compiled files will be generated in the `dist/` directory at the root of the project.

---

## 📄 License and Disclaimer

WinZapp is a project licensed under the GPL. It relies on reverse engineering of the WhatsApp Web protocol. Use of the software is at your own risk. This repository is not affiliated with, maintained, or sponsored by Meta Platforms, Inc.
