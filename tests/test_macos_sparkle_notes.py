"""The release notes Sparkle's window shows on the Mac
(macos/winzapp_mac/sparkle_notes.py).

The appcast's notes for an alpha were the whole "V2.1.0.0" section, the same
paragraphs every alpha, so testers could not tell what one changed: the
Windows updater's problem of #488. The window now says what changed between
the tag the app runs and the tag offered, from the official repository: the
changelog compared in words, and for an alpha the pull requests of every
alpha in between. Pure: the download and the shipped changelog are fakes.
"""

import json
import pathlib
import sys

import pytest

_MACOS = pathlib.Path(__file__).resolve().parents[1] / "macos"

pytestmark = pytest.mark.skipif(not (_MACOS / "winzapp_mac" / "sparkle_notes.py").is_file(),
                                reason="no macOS layer in this checkout")

if str(_MACOS) not in sys.path:
    sys.path.insert(0, str(_MACOS))

from winzapp_mac import sparkle_notes as N  # noqa: E402

from tests.test_release_notes import INSTALLED, OFFERED, t  # noqa: E402

RUNNING = "v2.1.0.4365alpha"
OFFER = "v2.1.0.4391alpha"
RELEASES = [
    {"tag_name": "v2.1.0.4391alpha", "body": "* Offered by @a in https://x/pull/3"},
    {"tag_name": "v2.1.0.4370alpha", "body": "* Between by @a in https://x/pull/2"},
    {"tag_name": "v2.1.0.4365alpha", "body": "* Running by @a in https://x/pull/1"},
    {"tag_name": "v2.1.0.4400alpha", "body": "* Newer than offered by @a in https://x/pull/4"},
    {"tag_name": "v2.1.0.0", "body": "* A stable by @a in https://x/pull/5"},
]


def _fetch(asked, changelog=OFFERED, releases=RELEASES):
    def fetch(url):
        asked.append(url)
        if url == N.RELEASES_URL:
            if isinstance(releases, Exception):
                raise releases
            return json.dumps(releases)
        if isinstance(changelog, Exception):
            raise changelog
        return changelog
    return fetch


def test_an_alpha_says_what_changed_since_the_running_tag():
    asked, installed = [], []
    text = N.offer_notes(RUNNING, OFFER, "pt-BR", t, _fetch(asked),
                         lambda locale: installed.append(locale) or INSTALLED)
    assert text.startswith("Release notes:\n\nVersion 2.1.0.0\n\nNew in the section WHAT'S NEW:"
                           "\n- Communities are listed.")
    github = text[text.index("On GitHub:"):]
    assert github.index("Version 2.1.0.4391alpha") < github.index("Version 2.1.0.4370alpha")
    assert "Offered (pull request 3)" in github and "Between (pull request 2)" in github
    for gone in ("Running", "Newer than offered", "A stable"):
        assert gone not in text
    # The official repository at the offered tag, in the user's language; the
    # shipped changelog of that same language to compare it with.
    assert asked[0] == ("https://raw.githubusercontent.com/gabrielhhaber/WinZapp_Python/"
                        f"{OFFER}/client/changelog_pt-BR.txt")
    assert N.RELEASES_URL.startswith("https://api.github.com/repos/gabrielhhaber/WinZapp_Python/")
    assert installed == ["pt-BR"]


def test_a_stable_release_has_no_github_part_and_asks_no_api():
    asked = []
    text = N.offer_notes("v2.1.0.0", "v2.1.0.1", "en-US", t, _fetch(asked), lambda locale: INSTALLED)
    assert "Communities are listed." in text and "On GitHub" not in text
    assert N.RELEASES_URL not in asked


def test_the_changelog_falls_back_to_english_and_is_compared_with_the_shipped_english():
    installed = []

    def fetch(url):
        if "changelog_pl" in url:
            raise OSError("404")
        return OFFERED if "changelog" in url else "[]"

    text = N.offer_notes(RUNNING, OFFER, "pl", t, fetch, lambda locale: installed.append(locale) or INSTALLED)
    assert installed == ["en-US"] and "Communities are listed." in text


def test_releases_that_cannot_be_read_leave_the_changelog_part():
    for releases in (OSError("rate limited"), {"message": "API rate limit exceeded"}):
        text = N.offer_notes(RUNNING, OFFER, "en-US", t, _fetch([], releases=releases),
                             lambda locale: INSTALLED)
        assert "Communities are listed." in text and "On GitHub" not in text


def test_offline_there_is_nothing_and_the_appcasts_notes_stay():
    text = N.offer_notes(RUNNING, OFFER, "en-US", t,
                         _fetch([], changelog=OSError("offline"), releases=OSError("offline")),
                         lambda locale: INSTALLED)
    assert text == ""


@pytest.mark.parametrize("offered", [RUNNING, "v2.1.0.4300alpha", "not a tag"])
def test_nothing_is_fetched_for_a_release_that_is_not_newer(offered):
    asked = []
    assert N.offer_notes(RUNNING, offered, "en-US", t, _fetch(asked), lambda locale: INSTALLED) == ""
    assert asked == []


def test_versions_are_ordered_as_provenance_orders_tags():
    # an alpha is older than the beta and the stable of the same number
    assert N._order("2.1.0.4391alpha") < N._order("2.1.0.4391beta") < N._order("2.1.0.4391")
    assert N._order("2.1.0.4391") < N._order("2.1.0.4392alpha")
