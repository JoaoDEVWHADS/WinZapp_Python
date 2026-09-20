"""Dynamic discovery of WinZapp API patch files.

client/api_patches/ is the source of truth. Files belonging to the
wppconnect-server overlay are discovered automatically. package.json is
handled separately because WinZapp merges only its owned dependencies, and
subdirectories named after dependencies (currently wppconnect/) hold patches
for those packages rather than for wppconnect-server itself.
"""

from __future__ import annotations

import os

SPECIAL_SERVER_FILES = {"package.json"}
DEPENDENCY_PATCH_ROOTS = {"wppconnect"}


def iter_patch_files(patches_dir: str) -> list[str]:
    """Return every patch file below *patches_dir* as a sorted POSIX path."""
    if not os.path.isdir(patches_dir):
        return []

    result: list[str] = []
    for root, dirs, files in os.walk(patches_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            absolute = os.path.join(root, name)
            relative = os.path.relpath(absolute, patches_dir).replace(os.sep, "/")
            result.append(relative)
    return sorted(result)


def server_patch_files(patches_dir: str) -> list[str]:
    """Return files that should overlay the wppconnect-server checkout."""
    dependency_prefixes = tuple(
        name.rstrip("/") + "/" for name in sorted(DEPENDENCY_PATCH_ROOTS)
    )
    return [
        relative
        for relative in iter_patch_files(patches_dir)
        if relative not in SPECIAL_SERVER_FILES
        and not relative.startswith(dependency_prefixes)
    ]


def dependency_patch_files(patches_dir: str, dependency: str) -> list[str]:
    """Return files below api_patches/<dependency>/ relative to that root."""
    prefix = dependency.strip("/") + "/"
    return [
        relative[len(prefix) :]
        for relative in iter_patch_files(patches_dir)
        if relative.startswith(prefix)
    ]
