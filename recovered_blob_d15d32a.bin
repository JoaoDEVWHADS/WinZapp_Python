#!/usr/bin/env python3
"""
baileys_apply_patch_pairing_time.py
------------------------------------
Patches the Evolution API / Baileys configuration to extend the pairing-code
(and QR code) rotation interval from 45 s to 180 s (3 minutes).

Background
----------
When a user connects via phone number, Evolution API requests a pairing code
from WhatsApp via Baileys and rotates it every time a new QR-code cycle fires.
The rotation interval is controlled by the `qrTimeout` option passed to
`makeWASocket()` in:

    client/api/src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts

That TypeScript source is compiled to:

    client/api/dist/main.js
    client/api/dist/main.mjs

This script patches all three files so that users have 3 minutes (instead of
45 s) to enter the 8-digit pairing code — critical for blind users who rely on
screen readers.

Usage
-----
    python baileys_apply_patch_pairing_time.py           # apply patch
    python baileys_apply_patch_pairing_time.py --revert  # restore originals
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).parent / "client" / "api"

# ---------------------------------------------------------------------------
# Patch definitions
# Each entry: (file_path, old_bytes, new_bytes, description)
# ---------------------------------------------------------------------------
PATCHES = [
    (
        BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts",
        b"qrTimeout: 45_000,",
        b"qrTimeout: 180_000,",
        "TypeScript source",
    ),
    (
        BASE / "dist/main.js",
        b"qrTimeout:45e3,",
        b"qrTimeout:18e4,",
        "compiled main.js",
    ),
    (
        BASE / "dist/main.mjs",
        b"qrTimeout:45e3,",
        b"qrTimeout:18e4,",
        "compiled main.mjs",
    ),
]

BACKUP_SUFFIX = ".pairing_patch_backup"


def apply_patches() -> bool:
    ok = True
    for path, old, new, label in PATCHES:
        if not path.exists():
            print(f"[SKIP]  {label}: file not found — {path}")
            continue

        data = path.read_bytes()

        if new in data:
            print(f"[OK]    {label}: already patched ({path.name})")
            continue

        if old not in data:
            print(
                f"[WARN]  {label}: expected pattern not found — patch may be "
                f"outdated or file has changed ({path.name})"
            )
            ok = False
            continue

        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        shutil.copy2(path, backup)
        path.write_bytes(data.replace(old, new, 1))
        print(f"[DONE]  {label}: patched {path.name}  (backup -> {backup.name})")

    return ok


def revert_patches() -> bool:
    ok = True
    for path, _old, _new, label in PATCHES:
        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        if not backup.exists():
            print(f"[SKIP]  {label}: no backup found — {backup.name}")
            continue
        shutil.copy2(backup, path)
        backup.unlink()
        print(f"[DONE]  {label}: restored {path.name}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--revert", action="store_true", help="Restore original files from backups")
    args = parser.parse_args()

    if args.revert:
        print("Reverting pairing-time patch…")
        success = revert_patches()
    else:
        print("Applying pairing-time patch (45 s -> 180 s)...")
        success = apply_patches()

    if not success:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
