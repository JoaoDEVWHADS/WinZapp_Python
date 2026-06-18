#!/usr/bin/env python3
"""
baileys_apply_patch_lid_resolution.py
--------------------------------------
Patches the Evolution API to resolve LID numbers (@lid) to phone numbers (@s.whatsapp.net)
in fetchProfile responses.

Usage:
    python baileys_apply_patch_lid_resolution.py           # apply patch
    python baileys_apply_patch_lid_resolution.py --revert  # restore originals
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).parent / "client" / "api"

# ---------------------------------------------------------------------------
# TypeScript source patch
# ---------------------------------------------------------------------------
TS_ORIGINAL = b"""    let phoneJid = jid;

    try {
      if (number) {"""

TS_PATCHED = b"""    let phoneJid = jid;
    if (jid.endsWith('@lid')) {
      try {
        const mapped = await this.client.signalRepository.lidMapping.getPNForLID(jid);
        if (mapped) {
          phoneJid = mapped;
        }
      } catch (err) {
        this.logger.error(`Error resolving LID mapping for ${jid}: ${err.message}`);
      }
    }

    try {
      if (number) {"""

# ---------------------------------------------------------------------------
# Compiled main.js patch
# ---------------------------------------------------------------------------
JS_ORIGINAL = b"""(await this.whatsappNumber({numbers:[o]}))?.shift();if(!r.exists)throw new y(r);try{"""

JS_PATCHED = b"""(await this.whatsappNumber({numbers:[o]}))?.shift();if(!r.exists)throw new y(r);let phoneJid=o;if(o.endsWith("@lid")){try{let a=await this.client.signalRepository.lidMapping.getPNForLID(o);a&&(phoneJid=a)}catch(a){this.logger.error(`Error resolving LID mapping for ${o}: ${a.message}`)}}try{"""

# ---------------------------------------------------------------------------
# Compiled main.mjs patch
# ---------------------------------------------------------------------------
MJS_ORIGINAL = b"""(await this.whatsappNumber({numbers:[o]}))?.shift();if(!r.exists)throw new y(r);try{"""

MJS_PATCHED = b"""(await this.whatsappNumber({numbers:[o]}))?.shift();if(!r.exists)throw new y(r);let phoneJid=o;if(o.endsWith("@lid")){try{let a=await this.client.signalRepository.lidMapping.getPNForLID(o);a&&(phoneJid=a)}catch(a){this.logger.error(`Error resolving LID mapping for ${o}: ${a.message}`)}}try{"""

BACKUP_SUFFIX = ".lid_resolution_patch_backup"

PATCHES = [
    (
        BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts",
        TS_ORIGINAL,
        TS_PATCHED,
        "TypeScript source",
    ),
    (
        BASE / "dist/main.js",
        JS_ORIGINAL,
        JS_PATCHED,
        "compiled main.js",
    ),
    (
        BASE / "dist/main.mjs",
        MJS_ORIGINAL,
        MJS_PATCHED,
        "compiled main.mjs",
    ),
]


def apply_patches() -> bool:
    ok = True
    for path, original, patched, label in PATCHES:
        if not path.exists():
            print(f"[SKIP]  {label}: file not found -- {path}")
            continue

        data = path.read_bytes()

        if patched in data:
            print(f"[OK]    {label}: already patched ({path.name})")
            continue

        if original not in data:
            print(
                f"[WARN]  {label}: expected pattern not found -- patch may be "
                f"outdated or file has changed ({path.name})"
            )
            # We don't fail the build if it's only the compiled files, because npm run build
            # runs after this script in release.yml. But TypeScript source MUST be patched.
            if "TypeScript source" in label:
                ok = False
            continue

        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(path, backup)
            print(f"  Backup created: {backup.name}")
        path.write_bytes(data.replace(original, patched, 1))
        print(f"[DONE]  {label}: patched {path.name}")

    return ok


def revert_patches() -> bool:
    ok = True
    for path, _original, _patched, label in PATCHES:
        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        if not backup.exists():
            print(f"[SKIP]  {label}: no backup found -- {backup.name}")
            continue
        shutil.copy2(backup, path)
        backup.unlink()
        print(f"[DONE]  {label}: restored {path.name}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--revert", action="store_true", help="Restore original files from backups"
    )
    args = parser.parse_args()

    if args.revert:
        print("Reverting LID resolution patch...")
        success = revert_patches()
    else:
        print("Applying LID resolution patch...")
        success = apply_patches()

    if not success:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
