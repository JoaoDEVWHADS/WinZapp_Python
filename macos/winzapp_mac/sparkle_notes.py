"""What Sparkle's update window says about the release it offers.

The appcast carries one text per release and locale, written when the
release is published: it cannot know which version the reader runs, so an
alpha's notes were the whole "V2.1.0.0" section, the same opening paragraphs
every alpha, and a tester could not tell what was new. WinZapp's own updater
had the same problem and solved it for Windows in #488 (core/release_notes.py);
this is that text for the Mac, between the tag the app runs and the tag
Sparkle offers:

1. The changelog of the user's language at the offered tag, compared in words
   with the one this app shipped (core/changelog_diff.py).
2. For an alpha, the GitHub notes of every alpha of the official repository
   between the two tags, newest first, made readable (pull request titles).

Both come from the official repository, the same one provenance checks the
tag against, never from the repository the Mac builds are published in. The
order of versions is provenance's (bundle_version()), the order Sparkle and
the offer-time check use. Pure: the download (`fetch(url) -> str`) and the
shipped changelog (`installed(locale) -> str`) are the caller's, so this is
tested on every platform (tests/test_macos_sparkle_notes.py); sparkle_mac
calls it off the main thread and hands the text to Sparkle's window. "" when
neither part could be made: the appcast's own notes stay.
"""

import json
import logging

from core import release_notes

from . import provenance

RELEASES_URL = f"https://api.github.com/repos/{provenance.OFFICIAL_REPO}/releases?per_page=100"


def _order(version):
    """A sort key for a version spelled without its "v", in provenance's order."""
    bundle = provenance.bundle_version("v" + version)
    return tuple(int(part) for part in bundle.split(".")) if bundle else ()


def _is_alpha(release):
    tag = release.get("tag_name", "")
    return provenance.is_release_tag(tag) and tag.endswith("alpha")


def _releases(fetch):
    """The official repository's newest releases, or [] when they could not
    be read (the changelog part is still worth showing)."""
    try:
        data = json.loads(fetch(RELEASES_URL))
    except Exception:
        logging.warning("[sparkle_notes] could not read the official releases", exc_info=True)
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def offer_notes(running_tag, offered_tag, locale, t, fetch, installed):
    """The text of Sparkle's window for an update from *running_tag* to
    *offered_tag*, in *locale* (en-US when the tag has no changelog in it),
    or "" when there is nothing to say beyond the appcast's notes."""
    if not provenance.tag_is_newer(offered_tag, running_tag):
        return ""
    changes = ""
    fetched = release_notes.changelog_at(fetch, provenance.OFFICIAL_REPO, offered_tag, locale)
    if fetched is not None:
        code, offered = fetched
        changes = release_notes.changelog_changes(installed(code), offered, t)
    github = ""
    if offered_tag.endswith("alpha"):
        github = release_notes.github_notes(
            _releases(fetch), _is_alpha,
            lambda version: provenance.tag_is_newer("v" + version, running_tag),
            lambda version: not provenance.tag_is_newer("v" + version, offered_tag),
            t, _order)
    return release_notes.compose(changes, github, t)
