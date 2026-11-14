#!/usr/bin/env python3
"""setup_neonize.py — Prepare the Neonize bridge for building WinZapp.

Replaces the old setup.py step in builder.py. The client build no longer
compiles the WPPConnect API; the app installs those modules on demand when the
user picks the WPPConnect engine (client/ui/dialogs/api_setup.py). What the
build still needs is the Neonize bridge, which this script prepares:

1. Installs the native toolchain (Go + 64-bit MinGW via winget on Windows).
2. Runs neonize_bridge/prepare.py, which creates neonize_bridge/.venv and
   installs WinZapp's build of neonize (official neonize + neonize_patches/,
   compiled by build_neonize.py or downloaded when a release is published).

Equivalent to `python -m winzapp_tools.cli setup_neonize`.
"""

import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def _log(msg: str) -> None:
    print(f"[SETUP-NEONIZE] {msg}", flush=True)


def _ensure_native_toolchain() -> None:
    """Install Go and 64-bit MinGW via winget on Windows so the Neonize bridge
    can be compiled from source (build_neonize.py needs Go + a 64-bit gcc)."""
    from winzapp_tools.neonize_setup import ensure_build_tools

    _log("Ensuring native build tools (Go + 64-bit MinGW via winget)...")
    ensure_build_tools()


def main() -> None:
    _log("=== Preparing the Neonize bridge ===")

    _ensure_native_toolchain()

    _log("Running neonize_bridge/prepare.py (create .venv, install/build neonize)...")
    res = subprocess.run(
        [sys.executable, os.path.join(ROOT_DIR, "neonize_bridge", "prepare.py")],
        cwd=ROOT_DIR,
    )
    if res.returncode != 0:
        _log("ERROR: neonize_bridge/prepare.py failed!")
        sys.exit(res.returncode)

    _log("=== Neonize bridge ready ===")


if __name__ == "__main__":
    main()
