# WinZapp (Fork)

> **This repository is a [fork of the original repository by Gabriel Haberkamp](https://github.com/gabrielhhaber/WinZapp_Python).**  
> All credits for the initial development and project architecture belong to the original author. This fork focuses on stabilization, build automation, accessibility bug fixes, and restructuring the update system.

---

WinZapp is a **free, self-hosted, open-source desktop WhatsApp client for Windows**, developed primarily with a focus on **accessibility for blind or low-vision users**.  
It integrates seamlessly with screen readers (such as NVDA, JAWS, Narrator, and others) through the [accessible-output2](https://github.com/accessibleapps/accessible_output2) ecosystem, offering a fully keyboard-navigable interface using wxPython.

The application runs in a hybrid manner:
1. **Graphical Client:** Written in Python 3.13 + wxPython (responsible for the GUI, audio alerts, and screen-reading capabilities).
2. **Evolution API:** Running locally on Node.js (with an embedded PostgreSQL database), acting as the communication gateway.

---

## 🛠️ Improvements in this Fork

Since the original fork, a deep restructuring has been performed in the following areas:

### 1. CI/CD & Releases Automation (GitHub Actions)
* **Automated Release Pipeline:** The [release.yml](file:///.github/workflows/release.yml) workflow was created to run on Windows Server. On every `git push` to the `main` branch:
  * A version based on the UTC date and time is automatically generated (`YYYY.MM.DD.HHMM`, e.g., `2026.06.17.2208`).
  * The [version.py](file:///client/version.py) file is updated and committed to GitHub while avoiding recursive loops (`[skip ci]`).
  * The entire build process is executed (configuring MSYS2 for GCC/windres, downloading portable Node.js, compiling Evolution API, and running PyInstaller).
  * A GitHub Release is created and the ready-to-run executable binaries are published.
* **Advanced Caches:** Structured caching was implemented for the MSYS2 compiler, `pip` packages (Python), Node.js binaries, and Evolution API `node_modules`, drastically reducing cloud build times.
* **Concurrency Control:** Configured workflow concurrency to automatically cancel any in-progress runs when a new commit is pushed, preventing duplicate builds and resource conflicts.

### 2. Auto-Updater Redesign (Zero Conflicts)
* **Direct GitHub Integration:** The dependency on static JSON and TXT files in the repository was removed. The updater now queries the GitHub Releases API directly, fetching the latest version and changelogs natively from the platform.
* **Resolution of File Locks:** The old updater failed silently because the PostgreSQL database and the Evolution API remained running, locking the files in the installation folder. This was fixed in the update script by introducing dynamic port detection:
  * The updater identifies and terminates processes bound to ports **3417** (Evolution API) and **5433** (PostgreSQL) using the active connection table (`netstat` + `taskkill`). This ensures that 100% of the locks are released and the update is completed without access denied errors.

### 3. Compiler Migration to PyInstaller
* The old compilation method (done via Nuitka) was replaced with a robust structure based on **PyInstaller** (`build.py`).
* Packaging of critical dynamic audio DLLs (BASS DLLs) and screen reader DLLs (`accessible-output2`), which were previously discarded and caused executable crashes, was fixed.
* The build now bundles everything in a clean folder layout (`_internal/` and sibling directories) and generates the native Windows installer (`WinZappInstaller.exe`) using a stub binary compiled via GCC.

### 4. Critical App Bug Fixes
* **Resolution of 401 (Unauthorized) Failures:** The local API boot script ([start.js](file:///client/api/start.js)) and the Python client were adjusted to synchronize and preserve the `AUTHENTICATION_API_KEY` environment variable (using registered license keys without overwriting the local token).
* **Connection Initialization Crash Fix:** A crash occurring during connection setup (`TypeError: Cannot read properties of undefined (reading 'state')`) was resolved by implementing a defensive patch for the Baileys auth state and enabling PostgreSQL local database persistence by default.
* **Persistent Client Logging:** A persistent client-side logging system was added to store runtime traces and diagnostics under `logs/log.log`, facilitating troubleshooting of connection and auto-updater failures.
* **Compatibility with Linked Devices (LID):** Empty contact names and chats caused by JIDs linked to secondary devices (`@lid`) were fixed.
* **Dialog Stabilization:** An `AttributeError` in the client when attempting to reconnect or when destroying graphical elements during sudden disconnections was fixed.
* **Group Filtering:** WhatsApp group JIDs are no longer incorrectly formatted as standard phone numbers.

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
cd WinZapp_Python

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
