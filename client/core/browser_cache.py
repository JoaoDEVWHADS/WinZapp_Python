"""Reuse complete Puppeteer browser builds during API reinstalls.

The Puppeteer CLI still selects the version required by the new dependencies.
Copying a build into its canonical cache location lets the CLI skip its
download; an older build never stands in for the requested version.
"""

import logging
import os
import re
import shutil

from core.browser_payload import payload_problem


def _binary_for(version_dir: str, product: str, platform: str) -> str:
    folder = f"{product}-{'linux64' if platform == 'linux' else platform}"
    binary = product + (".exe" if platform.startswith("win") else "")
    return os.path.join(version_dir, folder, binary)


def _versions(cache_dir: str, product: str):
    """Known Windows/Linux layouts only; leave other cache entries alone."""
    root = os.path.join(cache_dir, product)
    if not os.path.isdir(root) or os.path.islink(root):
        return
    for name in os.listdir(root):
        match = re.fullmatch(r"(win32|win64|linux)-\d+(?:\.\d+){3}", name)
        version_dir = os.path.join(root, name)
        if match and os.path.isdir(version_dir) and not os.path.islink(version_dir):
            # A junction must never redirect cleanup outside the browser cache.
            if os.path.commonpath((os.path.realpath(cache_dir),
                                   os.path.realpath(version_dir))) != os.path.realpath(cache_dir):
                continue
            yield name, version_dir, _binary_for(version_dir, product, match[1])


def _complete(binary: str) -> bool:
    return (os.path.isfile(binary) and os.path.getsize(binary) > 0
            and payload_problem(binary) is None)


def prepare_browser_cache(cache_dir: str, product: str,
                          source_cache: str | None = None) -> None:
    """Repair incomplete builds and copy usable ones from a live API cache.

    Only the destination is modified. Staging receives independent copies,
    so cancelling or repairing it cannot change the running browser.
    Legacy .cache/puppeteer layouts are copied into the canonical tree too.
    """
    if product not in ("chrome", "chrome-headless-shell"):
        raise ValueError(f"Unsupported browser product: {product}")
    product_dir = os.path.join(cache_dir, product)
    if os.path.commonpath((os.path.realpath(cache_dir), os.path.realpath(product_dir))) != os.path.realpath(cache_dir):
        raise ValueError("Browser cache product directory leaves the cache")
    for _name, version_dir, binary in _versions(cache_dir, product):
        if not _complete(binary):
            logging.info("[browser-cache] Removing incomplete browser build: %s", version_dir)
            shutil.rmtree(version_dir)

    if not source_cache:
        return
    for source in (source_cache, os.path.join(source_cache, "puppeteer")):
        for name, version_dir, binary in _versions(source, product):
            destination = os.path.join(cache_dir, product, name)
            if os.path.exists(destination) or not _complete(binary):
                continue
            try:
                shutil.copytree(version_dir, destination)
                logging.info("[browser-cache] Reused browser build: %s", name)
            except OSError:
                logging.exception("[browser-cache] Could not copy browser build: %s", name)
                # A half-copy must not make Puppeteer skip the actual download.
                if os.path.isdir(destination):
                    shutil.rmtree(destination)
