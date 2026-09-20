"""Apply source-level patches to the installed WPPConnect dependency."""

from __future__ import annotations

import os
import shutil

from core.api_patch_manifest import dependency_patch_files


DEPENDENCY_PATCH_NAME = "wppconnect"
DEPENDENCY_PACKAGE_PARTS = ("@wppconnect-team", "wppconnect")


def wppconnect_package_dir(api_dir: str) -> str:
    return os.path.join(api_dir, "node_modules", *DEPENDENCY_PACKAGE_PARTS)


def sync_wppconnect_source_patches(api_dir: str, patches_dir: str) -> tuple[str, list[str]]:
    """Copy changed source patches into node_modules/@wppconnect-team/wppconnect.

    Returns (package_dir, changed_relative_paths). Unchanged files are skipped so
    callers can avoid recompiling the dependency on every application startup.
    """
    package_dir = wppconnect_package_dir(api_dir)
    if not os.path.isdir(package_dir):
        raise FileNotFoundError(
            "Installed @wppconnect-team/wppconnect package was not found: "
            + package_dir
        )

    patch_root = os.path.join(patches_dir, DEPENDENCY_PATCH_NAME)
    changed: list[str] = []
    for rel_path in dependency_patch_files(patches_dir, DEPENDENCY_PATCH_NAME):
        source = os.path.join(patch_root, rel_path.replace("/", os.sep))
        target = os.path.join(package_dir, rel_path.replace("/", os.sep))
        if not os.path.isfile(source):
            continue

        same = False
        if os.path.isfile(target):
            try:
                with open(source, "rb") as src, open(target, "rb") as dst:
                    same = src.read() == dst.read()
            except OSError:
                same = False
        if same:
            continue

        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        changed.append(rel_path)

    return package_dir, changed
