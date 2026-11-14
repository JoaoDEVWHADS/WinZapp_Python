"""The running version of a Mac release build is its release tag.

A Mac release is built from a clean checkout of an official tag
(provenance.py, build_app.py), where client/version.py is the unstamped
placeholder ("2.1.0.0"): CI stamps it only at build, and the Mac build may
not touch a tracked file. Left alone, About and the updater's
User-Agent would show that placeholder, and UpdateChecker would
compare it against the latest release, offer the very release that is
running on every check, and then fail its install with "release is not
newer than the running version".

So version.__version__ becomes the tag in Info.plist (WinZappReleaseTag) —
the same version the Mac updater already trusts. It must run before any
WinZapp module does ``from version import __version__``, which binds a copy
at import (updater, main, main_window.settings, main_window.window_chrome).
A development build (not frozen, or no valid tag) keeps version.py.
"""

import logging
import sys

from . import provenance, updater_mac


def install():
    if not getattr(sys, "frozen", False):
        return
    ver = provenance.tag_version(provenance.running_release_tag(updater_mac._info()))
    if not ver:
        return
    import version
    version.__version__ = ver
    logging.info("[version_mac] running version %s (Info.plist %s)", ver,
                 provenance.RELEASE_TAG_KEY)
