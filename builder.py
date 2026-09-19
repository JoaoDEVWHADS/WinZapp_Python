#!/usr/bin/env python3
"""
builder.py — System & Environment Pre-Flight Orchestrator for WinZapp.

Responsible for:
1. Ensuring Python virtual environment (venv) and installing requirements.txt.
2. Checking MSYS2 GCC compiler installation and PATH configuration on Windows.
3. Ensuring audio DLLs (bassopus.dll) exist in client/lib/.
"""

import os
import shutil
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_LIB_DIR = os.path.join(ROOT_DIR, "client", "lib")
VENV_DIR = os.path.join(ROOT_DIR, "venv")
REQUIREMENTS_FILE = os.path.join(ROOT_DIR, "requirements.txt")


def _log(msg: str) -> None:
    print(f"[BUILDER] {msg}", flush=True)


def ensure_python_version() -> None:
    """Verify and log Python version and architecture."""
    major, minor, micro = sys.version_info[:3]
    bitness = 64 if sys.maxsize > 2**32 else 32
    _log(f"Detected Python Environment: {major}.{minor}.{micro} ({bitness}-bit) [{sys.executable}]")
    if major != 3 or minor < 10:
        _log(f"WARNING: Recommended Python version is 3.10+ (Current: {major}.{minor}.{micro}).")


def ensure_bassopus_dll() -> None:
    """Ensure bassopus.dll is present in client/lib/."""
    os.makedirs(CLIENT_LIB_DIR, exist_ok=True)
    bassopus_target = os.path.join(CLIENT_LIB_DIR, "bassopus.dll")
    bass_opus_source = os.path.join(CLIENT_LIB_DIR, "bass_opus.dll")

    if os.path.isfile(bassopus_target):
        _log("bassopus.dll is present in client/lib/.")
        return

    if os.path.isfile(bass_opus_source):
        try:
            shutil.copy2(bass_opus_source, bassopus_target)
            _log("bassopus.dll copied from bass_opus.dll in client/lib/.")
            return
        except Exception as exc:
            _log(f"WARNING: Failed to copy bass_opus.dll to bassopus.dll: {exc}")

    _log("WARNING: bassopus.dll not found in client/lib/ — OGG Opus audio playback may fail!")


def ensure_python_venv() -> None:
    """Ensure Python virtual environment (venv) exists and pip requirements are installed."""
    _log("Checking Python virtual environment (venv)...")
    
    pip_exe = os.path.join(VENV_DIR, "Scripts", "pip.exe") if sys.platform == "win32" else os.path.join(VENV_DIR, "bin", "pip")
    python_exe = os.path.join(VENV_DIR, "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(VENV_DIR, "bin", "python")

    if not os.path.isfile(python_exe):
        _log("Virtual environment (venv) not found. Attempting creation...")
        res = subprocess.run([sys.executable, "-m", "venv", VENV_DIR], cwd=ROOT_DIR)
        if res.returncode != 0:
            _log("WARNING: Could not create local venv (ensurepip absent). Using current Python environment.")
            pip_exe = shutil.which("pip3") or shutil.which("pip") or "pip"

    if os.path.isfile(REQUIREMENTS_FILE) and os.path.isfile(pip_exe):
        _log("Installing/Upgrading Python dependencies from requirements.txt...")
        subprocess.run([pip_exe, "install", "--upgrade", "pip"], cwd=ROOT_DIR, check=False)
        res_req = subprocess.run([pip_exe, "install", "-r", REQUIREMENTS_FILE], cwd=ROOT_DIR, check=False)
        if res_req.returncode == 0:
            _log("Python requirements successfully verified and installed.")


def ensure_msys2_gcc() -> None:
    """Check MSYS2 GCC installation and auto-install via pacman if missing on Windows."""
    if sys.platform != "win32":
        return

    _log("Checking MSYS2 GCC compiler configuration...")
    msys2_default_gcc = r"C:\msys64\ucrt64\bin"
    gcc_exe = shutil.which("gcc")

    if gcc_exe:
        _log(f"GCC compiler found in PATH: {gcc_exe}")
        return

    if os.path.isdir(msys2_default_gcc):
        os.environ["PATH"] = f"{msys2_default_gcc};{os.environ.get('PATH', '')}"
        _log(f"Added MSYS2 GCC to PATH: {msys2_default_gcc}")
        return

    pacman_exe = r"C:\msys64\usr\bin\pacman.exe"
    if not os.path.isfile(pacman_exe):
        _log("MSYS2 not found at C:\\msys64. Downloading MSYS2 base installer...")
        import urllib.request
        msys_url = "https://github.com/msys2/msys2-installer/releases/download/nightly-x86_64/msys2-base-x86_64-latest.sfx.exe"
        tmp_sfx = os.path.join(ROOT_DIR, "msys2_installer.exe")
        try:
            urllib.request.urlretrieve(msys_url, tmp_sfx)
            _log("Extracting MSYS2 base to C:\\msys64...")
            subprocess.run([tmp_sfx, "-y", "-oC:\\"], check=True)
        except Exception as exc:
            _log(f"WARNING: Could not auto-download MSYS2 installer: {exc}")
        finally:
            if os.path.exists(tmp_sfx):
                try: os.remove(tmp_sfx)
                except: pass

    if os.path.isfile(pacman_exe):
        _log("Installing MSYS2 GCC compiler packages (gcc & binutils)...")
        cmd = [pacman_exe, "-S", "--noconfirm", "--needed", "mingw-w64-ucrt-x86_64-gcc", "mingw-w64-ucrt-x86_64-binutils"]
        res = subprocess.run(cmd, check=False)
        if res.returncode == 0 and os.path.isdir(msys2_default_gcc):
            os.environ["PATH"] = f"{msys2_default_gcc};{os.environ.get('PATH', '')}"
            _log(f"MSYS2 GCC installed successfully and added to PATH: {msys2_default_gcc}")
            return

    _log("WARNING: GCC compiler not found. If building custom C extensions, please install MSYS2 GCC.")


def run_setup() -> None:
    """Run setup.py to prepare Node.js, MinGit and WPPConnect API for source execution."""
    _log("Executing setup.py for source environment setup...")
    setup_script = os.path.join(ROOT_DIR, "setup.py")
    res = subprocess.run([sys.executable, setup_script], cwd=ROOT_DIR)
    if res.returncode != 0:
        _log("ERROR: setup.py execution failed!")
        sys.exit(res.returncode)


def main() -> None:
    _log("=== WinZapp Compiler & Release Builder (builder.py) ===")
    
    # 0. Check Python Environment Version
    ensure_python_version()

    # 1. Ensure audio DLLs in client/lib/
    ensure_bassopus_dll()

    # 2. Configure MSYS2 GCC on Windows
    ensure_msys2_gcc()

    # 3. Ensure Python venv and requirements
    ensure_python_venv()

    # 4. Delegate Source & API setup to setup.py
    run_setup()

    _log("=== Builder Compiler Execution Completed Successfully! ===")


if __name__ == "__main__":
    main()
