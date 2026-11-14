"""Help > Usage guide: pick the guide file for the user's language and open it.

The guides are client/data/help_guide/<language>.html, built from
docs/user-guide. They open in the default browser, where the screen reader
browses them like any web page and the browser's own window handling applies.
"""

import logging
import os

from app_paths import resource_path

_FALLBACK_LANGUAGE = "pt-BR"


def find_help_guide_path(language, path_for=resource_path, exists=os.path.isfile):
    """Return the guide file for `language`, falling back to pt-BR, or None."""
    for candidate in (language, _FALLBACK_LANGUAGE):
        path = path_for("data", "help_guide", f"{candidate}.html")
        if exists(path):
            return path
    return None


def open_help_guide(language, open_file=None):
    """Open the guide in the default browser. False when it cannot be opened."""
    path = find_help_guide_path(language)
    if path is None:
        logging.warning(
            "[help_guide] No guide HTML found for %s or %s.",
            language, _FALLBACK_LANGUAGE,
        )
        return False
    try:
        (open_file or os.startfile)(path)
    except OSError:
        logging.warning("[help_guide] The guide could not be opened.", exc_info=True)
        return False
    return True
