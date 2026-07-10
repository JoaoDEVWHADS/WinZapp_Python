#!/usr/bin/env python3
"""
baileys_apply_patch_auth_state.py
----------------------------------
Patches the Evolution API to prevent connection crash when authState is undefined.

Usage:
    python baileys_apply_patch_auth_state.py           # apply patch
    python baileys_apply_patch_auth_state.py --revert  # restore originals
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
        b"creds: this.instance.authState.state.creds,",
        b"creds: this.instance.authState?.state?.creds || (this.instance.authState as any)?.creds,",
        "TypeScript source (creds)",
    ),
    (
        BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts",
        b"keys: makeCacheableSignalKeyStore(this.instance.authState.state.keys, P({ level: 'error' }) as any),",
        b"keys: makeCacheableSignalKeyStore((this.instance.authState?.state?.keys || (this.instance.authState as any)?.keys) || {}, P({ level: 'error' }) as any),",
        "TypeScript source (keys)",
    ),
    (
        BASE / "dist/main.js",
        b"this.instance.authState.state.creds",
        b"this.instance.authState?.state?.creds",
        "compiled main.js (creds)",
    ),
    (
        BASE / "dist/main.js",
        b"this.instance.authState.state.keys",
        b"this.instance.authState?.state?.keys",
        "compiled main.js (keys)",
    ),
    (
        BASE / "dist/main.mjs",
        b"this.instance.authState.state.creds",
        b"this.instance.authState?.state?.creds",
        "compiled main.mjs (creds)",
    ),
    (
        BASE / "dist/main.mjs",
        b"this.instance.authState.state.keys",
        b"this.instance.authState?.state?.keys",
        "compiled main.mjs (keys)",
    ),
]

BACKUP_SUFFIX = ".auth_state_patch_backup"


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
        if not backup.exists():
            shutil.copy2(path, backup)
            print(f"  Backup created: {backup.name}")
        path.write_bytes(data.replace(old, new, 1))
        print(f"[DONE]  {label}: patched {path.name}")

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
        print("Reverting auth-state crash patch…")
        success = revert_patches()
    else:
        print("Applying auth-state crash patch...")
        success = apply_patches()

    if not success:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
