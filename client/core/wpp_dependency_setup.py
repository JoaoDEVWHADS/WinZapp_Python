"""Shared dependency setup policy for the generated WPPConnect API."""

from __future__ import annotations

import json
import os
import shutil
import tempfile

GITHUB_DEPENDENCIES = {
    "@wppconnect-team/wppconnect": "git+https://github.com/wppconnect-team/wppconnect.git",
    "@wppconnect/wa-js": "git+https://github.com/wppconnect-team/wa-js.git",
    "@wppconnect/wa-version": "git+https://github.com/wppconnect-team/wa-version.git",
}

PATCHED_DEPENDENCY_KEYS = (
    "prom-client",
    "zod",
    "@ffmpeg-installer/ffmpeg",
    *GITHUB_DEPENDENCIES,
)

STALE_LOCKFILES = (
    "yarn.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
)


def merge_dependency_patches(api_dir: str, patches_dir: str) -> int:
    """Merge only WinZapp-owned dependencies into upstream's package.json."""
    package_path = os.path.join(api_dir, "package.json")
    patch_path = os.path.join(patches_dir, "package.json")
    if not (os.path.isfile(package_path) and os.path.isfile(patch_path)):
        return 0

    with open(package_path, encoding="utf-8") as stream:
        package = json.load(stream)
    with open(patch_path, encoding="utf-8") as stream:
        patch = json.load(stream)

    dependencies = package.setdefault("dependencies", {})
    patch_dependencies = patch.get("dependencies", {})
    applied = 0
    for name in PATCHED_DEPENDENCY_KEYS:
        if name in patch_dependencies:
            dependencies[name] = patch_dependencies[name]
            applied += 1

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".package.",
        suffix=".tmp",
        dir=api_dir,
    )
    os.close(descriptor)
    try:
        with open(temporary_path, "w", encoding="utf-8") as stream:
            json.dump(package, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, package_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

    return applied


def reset_dependency_state(api_dir: str) -> list[str]:
    """Remove generated locks and modules so npm resolves the current manifest."""
    removed = []
    for name in STALE_LOCKFILES:
        path = os.path.join(api_dir, name)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(name)

    modules_path = os.path.join(api_dir, "node_modules")
    if os.path.isdir(modules_path):
        shutil.rmtree(modules_path)
        removed.append("node_modules")

    return removed
