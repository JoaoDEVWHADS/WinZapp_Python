"""Keep Node's compilation cache outside the API replaced by updates."""

import logging
import os


def cache_environment(environment, cache_dir):
    child = dict(environment)
    if child.get("NODE_COMPILE_CACHE"):
        return child  # Respect an explicitly configured cache.
    try:
        os.makedirs(cache_dir, exist_ok=True)
        child["NODE_COMPILE_CACHE"] = os.path.abspath(cache_dir)
        logging.info("[node-cache] Persistent compile cache enabled")
    except OSError:
        logging.warning("[node-cache] Compile cache unavailable; starting without it")
    return child
