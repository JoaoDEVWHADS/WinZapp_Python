# Changelog (WinZapp Fork)

All notable changes to this fork of WinZapp are documented in this file.

# V2026.06.17.2228

## Critical App Bug Fixes
* **Connection Initialization Crash:** Resolved a startup crash (`TypeError: Cannot read properties of undefined (reading 'state')`) by applying a defensive patch to the Baileys auth state and enabling PostgreSQL local database persistence by default.
* **Force Update Feedback:** Fixed silent failures during manual update checks (Help > Force Update) to display a dialog explaining the network error or GitHub rate limits.

## Database & API Integration
* **Local Database Persistence:** Enabled database saving by default in the API boot script (`start.js`) so that instance credentials and chat history persist correctly in PostgreSQL (`DATABASE_SAVE_DATA_INSTANCE=true`).
* **Automated Patching:** Integrated all Baileys and Evolution API patch scripts (quoted context, pairing time, mark read, auth state) into the automated GitHub Actions release workflow.

## Client Logging System
* **Persistent Logs:** Added a client logging module writing to `logs/log.log` to track runtime traces, request errors, and detailed updater exception tracebacks for troubleshooting.

## CI/CD & Automation
* **Workflow Concurrency Control:** Added concurrency settings in GitHub Actions to automatically cancel any in-progress runs when a new push is received, preventing duplicate builds and race conditions.

---

# V2026.06.17.2208

## CI/CD & Automation
* **Automated Release Pipeline:** Implemented a full GitHub Actions workflow (`release.yml`) running on Windows Server to compile and publish ready-to-run releases on every push to the `main` branch.
* **Date-Based Versioning:** Switched to automatic UTC date/time versioning (`YYYY.MM.DD.HHMM`, e.g., `2026.06.17.2208`) to prevent loop updates.
* **Structured Action Caches:** Added cache scopes for MSYS2, Python pip dependencies, Node.js binaries, and `node_modules` to speed up remote compilation.

## User Interface
* **Interface Cleanup:** Removed the "What's New" dialog (`WhatsNewDialog`) and changelog buttons from the updater interface to streamline startup.

---

# V0.11.0.1

## Auto-Updater System
* **GitHub Release Integration:** Re-engineered the updater to query GitHub Releases API directly, fetching tags and release notes natively without needing extra files.
* **File Lock Resolution:** Added dynamic process termination routines in the updater script to close PostgreSQL (port 5433) and Evolution API (port 3417) connections, preventing "Access Denied" errors during files overwrite.

## Compilation & Packaging
* **PyInstaller Migration:** Replaced the legacy Nuitka compiler with PyInstaller (`build.py`) for builds packaging.
* **Library DLL Bundling:** Restructured packaging of critical dynamic sound DLLs (BASS) and screen readers (`accessible-output2`) to prevent runtime crashes.
* **Custom Installer Stub:** Optimized the C stub installer (`installer.c`) to extract payload files and register uninstallation entries on Windows.

## Development Setup
* **Dependencies Preservation:** Updated `setup_api.py` to preserve the `node_modules` folder, maintaining a local NPM cache during checkout operations.

---

# V0.10.0.0

## Client Stabilization
* **Dialogue Error Fix:** Fixed an `AttributeError` in the connection dialog (`connection_dial`) occurring during WebSocket disconnections.
* **LID JID Compatibility:** Added support for linked device JIDs (`@lid`), resolving blank contact and conversation names.
* **Group Formatting:** Prevented group JIDs from being incorrectly parsed as standard phone numbers.
* **Updater Redirection:** Updated all download endpoints to target `JoaoDEVWHADS/WinZapp_Python`.
