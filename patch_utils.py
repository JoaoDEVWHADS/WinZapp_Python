import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


PATCH_VERSION = "1.0.0"


@dataclass
class PatchDef:
    target: Path
    old_candidates: List[bytes]
    new_bytes: bytes
    label: str
    manifest_key: str = ""


@dataclass
class ManifestEntry:
    manifest_key: str
    file_path: str
    original_hash: str
    patched_hash: str
    timestamp: float
    patch_version: str
    label: str
    status: str = "applied"


class PatchManifest:
    def __init__(self, path: Path):
        self.path = path
        self._entries: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = data.get("patches", {})
            except (json.JSONDecodeError, KeyError):
                self._entries = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "patch_version": PATCH_VERSION,
            "updated_at": time.time(),
            "patches": self._entries,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def has(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> Optional[dict]:
        return self._entries.get(key)

    def register(self, entry: ManifestEntry):
        self._entries[entry.manifest_key] = asdict(entry)
        self._save()

    def remove(self, key: str):
        self._entries.pop(key, None)
        self._save()

    def status(self, key: str) -> str:
        e = self._entries.get(key)
        return e.get("status", "unknown") if e else "missing"

    def all_applied(self) -> bool:
        if not self._entries:
            return False
        return all(e.get("status") == "applied" for e in self._entries.values())

    def clear(self):
        self._entries = {}
        self._save()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


MANIFEST_PATH = Path(__file__).parent / "client" / "api" / ".baileys_patches.json"


def apply_patches(defs: List[PatchDef], manifest_path: Path = MANIFEST_PATH) -> bool:
    manifest = PatchManifest(manifest_path)
    ok = True

    for pdef in defs:
        key = pdef.manifest_key or pdef.label.lower().replace(" ", "_").replace("/", "_")
        path = pdef.target

        if not path.exists():
            print(f"[SKIP]  {pdef.label}: file not found — {path}")
            continue

        data = path.read_bytes()
        current_hash = hash_bytes(data)

        if pdef.new_bytes in data:
            manifest.register(ManifestEntry(
                manifest_key=key,
                file_path=str(path),
                original_hash=current_hash,
                patched_hash=current_hash,
                timestamp=time.time(),
                patch_version=PATCH_VERSION,
                label=pdef.label,
                status="applied",
            ))
            print(f"[OK]    {pdef.label}: already patched ({path.name})")
            continue

        old = None
        for candidate in pdef.old_candidates:
            if candidate in data:
                old = candidate
                break

        if old is None:
            print(
                f"[WARN]  {pdef.label}: expected pattern not found — patch may be "
                f"outdated or file has changed ({path.name})"
            )
            ok = False
            manifest.register(ManifestEntry(
                manifest_key=key,
                file_path=str(path),
                original_hash=current_hash,
                patched_hash=current_hash,
                timestamp=time.time(),
                patch_version=PATCH_VERSION,
                label=pdef.label,
                status="failed",
            ))
            continue

        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)

        patched_data = data.replace(old, pdef.new_bytes, 1)
        patched_hash = hash_bytes(patched_data)
        path.write_bytes(patched_data)

        manifest.register(ManifestEntry(
            manifest_key=key,
            file_path=str(path),
            original_hash=current_hash,
            patched_hash=patched_hash,
            timestamp=time.time(),
            patch_version=PATCH_VERSION,
            label=pdef.label,
            status="applied",
        ))
        print(f"[DONE]  {pdef.label}: patched {path.name}  (backup -> {backup.name})")

    return ok


def revert_patches(defs: List[PatchDef], manifest_path: Path = MANIFEST_PATH) -> bool:
    manifest = PatchManifest(manifest_path)
    ok = True

    for pdef in defs:
        key = pdef.manifest_key or pdef.label.lower().replace(" ", "_").replace("/", "_")
        path = pdef.target
        backup = path.with_suffix(path.suffix + ".bak")

        if not backup.exists():
            print(f"[SKIP]  {pdef.label}: no backup found — {backup.name}")
            continue

        shutil.copy2(backup, path)
        backup.unlink()
        manifest.remove(key)
        print(f"[DONE]  {pdef.label}: restored {path.name}")

    return ok


def check_patches(defs: List[PatchDef], manifest_path: Path = MANIFEST_PATH) -> bool:
    manifest = PatchManifest(manifest_path)
    all_ok = True

    for pdef in defs:
        key = pdef.manifest_key or pdef.label.lower().replace(" ", "_").replace("/", "_")
        path = pdef.target
        entry = manifest.get(key)

        if not path.exists():
            print(f"[FAIL]  {pdef.label}: file not found — {path}")
            all_ok = False
            continue

        data = path.read_bytes()
        is_patched = pdef.new_bytes in data
        manifest_status = manifest.status(key)

        if is_patched and manifest_status == "applied":
            print(f"[PASS]  {pdef.label}: patched and verified")
        elif is_patched and manifest_status != "applied":
            print(f"[WARN]  {pdef.label}: patched but manifest says '{manifest_status}'")
        elif not is_patched and manifest_status == "applied":
            print(f"[FAIL]  {pdef.label}: manifest says applied but file is NOT patched (npm update?)")
            all_ok = False
        else:
            print(f"[FAIL]  {pdef.label}: NOT patched (status: {manifest_status})")
            all_ok = False

    return all_ok


def get_status(defs: List[PatchDef], manifest_path: Path = MANIFEST_PATH) -> dict:
    manifest = PatchManifest(manifest_path)
    results = {}

    for pdef in defs:
        key = pdef.manifest_key or pdef.label.lower().replace(" ", "_").replace("/", "_")
        path = pdef.target
        entry = manifest.get(key)

        data = path.read_bytes() if path.exists() else b""
        is_patched = pdef.new_bytes in data if data else False

        results[key] = {
            "label": pdef.label,
            "file": str(path),
            "file_exists": path.exists(),
            "is_patched": is_patched,
            "manifest_status": manifest.status(key),
            "manifest_entry": entry,
        }

    return results


def add_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--revert", action="store_true",
        help="Restore original files from backups"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Verify that patches are applied correctly (no changes)"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current patch status"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-apply even if already patched"
    )


def run_main(defs: List[PatchDef], description: str, manifest_path: Path = MANIFEST_PATH):
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_args(parser)
    args = parser.parse_args()

    if args.status:
        statuses = get_status(defs, manifest_path)
        for key, info in statuses.items():
            icon = "PASS" if info["is_patched"] and info["manifest_status"] == "applied" else "FAIL"
            print(f"[{icon}] {info['label']}")
            print(f"       File: {info['file']}")
            print(f"       Exists: {info['file_exists']}")
            print(f"       Patched: {info['is_patched']}")
            print(f"       Manifest: {info['manifest_status']}")
            print()
        return

    if args.check:
        success = check_patches(defs, manifest_path)
        sys.exit(0 if success else 1)
        return

    if args.revert:
        print(f"Reverting patches ({description})...")
        success = revert_patches(defs, manifest_path)
    else:
        print(f"Applying patches ({description})...")
        success = apply_patches(defs, manifest_path)

    if not success:
        sys.exit(1)
    print("Done.")
