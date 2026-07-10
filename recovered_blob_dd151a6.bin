# WinZapp

> ** Work in progress — WinZapp is under active development.**
> Features may be incomplete, unstable, or change without notice.
> Use at your own risk in non-critical environments.

---

WinZapp is a **free, self-hosted, open-source WhatsApp desktop client for Windows**, built primarily with **accessibility in mind for blind users**.
It integrates with screen readers (NVDA, JAWS, Narrator, and others) through
[accessible-output2](https://github.com/accessibleapps/accessible_output2) and exposes a fully keyboard-navigable interface powered by [wxPython](https://wxpython.org/).

The application consists of two components that run side by side:

| Component | Technology | Role |
|-----------|-----------|------|
| **Client** | Python 3.13 + wxPython | Desktop GUI, audio, notifications |
| **Evolution API** | Node.js (auto-downloaded) | Local WhatsApp gateway via WebSocket |

The Evolution API is downloaded and compiled automatically on first run — no manual Node.js setup is required by end users.

---

## Setting up a development environment

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| **Python** | 3.13 | Install to `C:\python313` or any path; add to `PATH` |
| **Visual Studio Build Tools** | 2022 | Required by Nuitka (C++ compiler). Install the **"Desktop development with C++"** workload via the VS Installer |
| **Git** *(optional)* | any | Only needed to clone the repo |

> Node.js does **not** need to be installed globally. The application bundles a portable Node.js runtime under `client/node/`.

### Steps

```powershell
# 1. Clone the repository
git clone https://github.com/your-org/winzapp.git
cd winzapp

# 2. Create and activate a virtual environment
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install all Python dependencies
pip install -r requirements.txt

# 4. Run the application in development mode
cd client
py main.py
```

On first launch the app will automatically:
1. Download the **Evolution API** source from GitHub and compile it (this can take a few minutes).
2. Prompt you to pair your WhatsApp account via a pairing code or QR code.

Subsequent launches skip the setup and start in seconds.

### Project layout (client/)

```
client/
├── main.py                  # Entry point
├── status_panel.py          # Status tab panel
├── app_paths.py             # Path helpers (dev vs. compiled)
├── version.py               # Version string
├── requirements.txt         # (root) Python dependencies
├── core/                    # Utilities, i18n, audio, networking
├── ui/
│   ├── conversations.py     # Main conversation panel
│   ├── navigation.py        # Tab navigation
│   ├── accessible.py        # Custom accessible wx controls
│   └── dialogs/             # All modal dialogs
├── languages/               # JSON translation files (pt-BR, en-US, es-ES)
├── sounds/                  # OGG sound effects
├── lib/                     # Bundled native libraries (BassAudio, etc.)
├── api/                     # Evolution API source (auto-downloaded)
└── node/                    # Bundled portable Node.js runtime
```

---

## Building the executable (.exe)

WinZapp is compiled into a **single self-contained `.exe`** using
[Nuitka](https://nuitka.net/) in `--onefile` mode.
The resulting file bundles the entire Python runtime, all dependencies, the
Evolution API, the bundled Node.js runtime, sounds, and language files.

### Additional prerequisites for building

In addition to the development prerequisites above:

| Tool | Notes |
|------|-------|
| **Nuitka 4.0.8** | Already in `requirements.txt`; installed by `pip install -r requirements.txt` |
| **Visual Studio Build Tools 2022** | Same C++ workload used for Nuitka compilation |
| **Ordered Nuitka cache** *(optional)* | Speeds up incremental rebuilds significantly |

### Build command

Run from the repository root (with the virtualenv activated):

```powershell
cd client

python -m nuitka `
  --onefile `
  --standalone `
  --windows-console-mode=disable `
  --enable-plugin=multiprocessing `
  --windows-arch=x86_64 `
  --onefile-tempdir-spec="{CACHE_DIR}\WinZapp" `
  --onefile-windows-static-runtime `
  --include-data-dir=languages=languages `
  --include-data-dir=sounds=sounds `
  --include-data-dir=lib=lib `
  --include-data-dir=node=node `
  --include-data-dir=api=api `
  --output-dir=..\build `
  --output-filename=WinZapp.exe `
  main.py
```

> **Note:** The first build downloads Nuitka's C backend and compiles all
> 880+ Python modules to C. Expect **10–30 minutes** on first run.
> Subsequent builds are much faster thanks to Nuitka's incremental cache.

### What the build produces

```
build/
├── WinZapp.exe         ← final self-contained installer/launcher
└── staging/            ← intermediate directory used during the build
    ├── WinZapp.exe     ← inner extracted executable
    ├── node/           ← bundled portable Node.js
    ├── api/            ← bundled Evolution API
    ├── languages/      ← translation files
    ├── sounds/         ← sound effects
    └── lib/            ← native libraries
```

The outer `build/WinZapp.exe` extracts itself to
`%LOCALAPPDATA%\WinZapp\` on first run and then launches the inner
executable from there on every subsequent start.

### Compiler notes

- Nuitka requires a **64-bit MSVC compiler** (`x64` target). Make sure the
  `x64 Native Tools Command Prompt` or `vcvars64.bat` is in your environment,
  or install the **"Desktop development with C++"** workload from the
  Visual Studio Installer.
- The build uses `--onefile-windows-static-runtime` so the resulting `.exe`
  does not require the Visual C++ Redistributable to be installed on end-user
  machines.
- Python **3.13** must be used. Other versions are not tested and may produce
  runtime errors with the bundled native extensions (wxPython, sounddevice,
  sound-lib).

---

## Disclaimer

WinZapp is **not** affiliated with, endorsed by, or officially supported by
Meta Platforms, Inc. It relies on a reverse-engineered WhatsApp Web protocol
implementation. Use responsibly and at your own risk.
