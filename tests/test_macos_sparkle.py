"""What the macOS app lets Sparkle offer and install (macos/winzapp_mac/sparkle_policy.py).

Against the threat model of macos/README.md, "Commit provenance", the one
guarantee the releases repository cannot fake is the official repository's:
the release is an existing tag of gabrielhhaber/WinZapp_Python pointing at
its declared commit, newer than the running tag. So an appcast item reaches
the user only when it stands for exactly such a release (its versions name
the tag, its enclosure is that tag's zip, no deltas, an application). An
update downloaded in the background installs when the app quits, gated by
that offer-time check; at "Ready to Install", after a download the user
started, the official repository is asked again and every other answer than
a fresh yes cancels the prepared installer.
Each test below is one way past that. The module is pure standard library
and is tested on every platform; the Cocoa side is
macos/tests/test_sparkle_mac.py.
"""

import pathlib
import sys

import pytest

_MACOS = pathlib.Path(__file__).resolve().parents[1] / "macos"

pytestmark = pytest.mark.skipif(not (_MACOS / "winzapp_mac" / "sparkle_policy.py").is_file(),
                                reason="no macOS layer in this checkout")

if str(_MACOS) not in sys.path:
    sys.path.insert(0, str(_MACOS))

from winzapp_mac import provenance as P, sparkle_policy as S  # noqa: E402

REPO = "rocco-labs/WinZapp_Python"
RUNNING = "v2.1.0.4250alpha"
TAG = "v2.1.0.4258alpha"
KEY = "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE="


def _item(tag=TAG, arch="arm64", **over):
    item = {"version": P.bundle_version(tag), "display_version": P.tag_version(tag),
            "url": S.zip_url(REPO, tag, arch), "deltas": False, "installation_type": "application"}
    item.update(over)
    return item


def _decide(item=None, verdict=None, running=RUNNING, arch="arm64"):
    return S.decide(item or _item(), REPO, arch, running, verdict)


class TestTheVeto:
    def test_the_official_repository_is_asked_before_anything_is_shown(self):
        assert _decide() == (S.VERIFY, TAG, "")

    def test_a_release_the_official_repository_confirms_proceeds(self):
        assert _decide(verdict=(True, "ok")) == (S.PROCEED, TAG, "ok")

    def test_a_release_it_does_not_confirm_is_refused_with_its_reason(self):
        action, tag, detail = _decide(verdict=(False, "could not verify commit provenance: x"))
        assert (action, tag) == (S.REFUSE, TAG) and "provenance" in detail

    @pytest.mark.parametrize("url", [
        S.zip_url("someone-else/WinZapp_Python", TAG, "arm64"),     # another repository
        S.zip_url(REPO, TAG, "x86_64"),                             # the other Mac's zip
        S.zip_url(REPO, "v2.1.0.4257alpha", "arm64"),               # another release
        S.zip_url(REPO, TAG, "arm64").replace("https://", "http://"),
        S.zip_url(REPO, TAG, "arm64") + ".delta", "",
        "https://evil.example/WinZapp-macOS-arm64.zip",
    ])
    def test_an_item_pointing_anywhere_else_is_refused_even_when_confirmed(self, url):
        """The tag was confirmed for this tag's zip in the releases
        repository, over https; anything else is not that release."""
        assert _decide(_item(url=url), verdict=(True, "ok"))[0] == S.REFUSE

    @pytest.mark.parametrize("over", [
        {"display_version": "2.1.0.42581"},          # no shortVersionString: Sparkle falls back
        {"version": "2.1.0.4258"},                   # versions that disagree
        {"version": P.bundle_version("v2.1.0.4259alpha")},
        {"display_version": "2.1.0.4258rc"}, {"display_version": None}, {"version": None},
    ])
    def test_an_item_that_does_not_name_one_release_tag_is_refused(self, over):
        assert _decide(_item(**over), verdict=(True, "ok"))[0] == S.REFUSE

    @pytest.mark.parametrize("tag", [RUNNING, "v2.1.0.4249alpha", "v2.0.0.0", "v2.1.0.4250alpha"])
    def test_a_downgrade_or_the_running_release_is_refused(self, tag):
        assert _decide(_item(tag=tag), verdict=(True, "ok"))[0] == S.REFUSE

    @pytest.mark.parametrize("over", [{"deltas": True}, {"installation_type": "package"},
                                      {"installation_type": "interactive-package"},
                                      {"installation_type": ""}])
    def test_deltas_and_anything_but_an_application_are_refused(self, over):
        """Only the full zip of the release is what the tag stands for."""
        assert _decide(_item(**over), verdict=(True, "ok"))[0] == S.REFUSE

    def test_a_build_without_its_release_tag_is_refused(self):
        assert _decide(running="", verdict=(True, "ok"))[0] == S.REFUSE


class TestTheLastStepBeforeInstalling:
    """sparkle_policy.install_choice(): Sparkle's "Ready to Install" (and an
    install it resumes) proceeds only on Install with a fresh yes; Skip is
    the answer that cancels the prepared installer."""

    def test_install_with_a_fresh_yes_installs(self):
        assert S.install_choice(S.CHOICE_INSTALL, (True, "ok")) == S.CHOICE_INSTALL

    @pytest.mark.parametrize("verdict", [
        (False, "could not verify commit provenance: the official repository has no such tag"),
        (False, "could not verify commit provenance: GitHub unreachable or rate-limited, try again later"),
        None,
    ])
    def test_install_without_a_fresh_yes_cancels(self, verdict):
        """A tag withdrawn or moved since the offer, or GitHub unreachable:
        fail closed, the update is offered again at the next check."""
        assert S.install_choice(S.CHOICE_INSTALL, verdict) == S.CHOICE_SKIP

    @pytest.mark.parametrize("choice", [S.CHOICE_DISMISS, S.CHOICE_SKIP, 7])
    def test_anything_but_install_cancels(self, choice):
        assert S.install_choice(choice, (True, "ok")) == S.CHOICE_SKIP

    def test_sparkles_enum_values(self):
        """SPUUserUpdateState.h:29-60, SUErrors.h: the values Sparkle 2.10.0
        compiles in; a wrong one would answer Install for Skip."""
        assert (S.CHOICE_SKIP, S.CHOICE_INSTALL, S.CHOICE_DISMISS) == (0, 1, 2)
        assert (S.STAGE_NOT_DOWNLOADED, S.STAGE_DOWNLOADED, S.STAGE_INSTALLING) == (0, 1, 2)
        assert (S.SILENT_ABORT, S.REFUSED, S.NO_UPDATE) == (4007, 4009, 1001)


class TestChannels:
    """WinZapp's "check for alpha updates" is Sparkle's alpha channel; the
    default channel (stable) is always allowed."""

    @pytest.mark.parametrize("settings,want", [
        ({"general": {"alpha_updates_enabled": True}}, ["alpha"]),
        ({"general": {"alpha_updates_enabled": False}}, []),
        ({"general": {}}, []), ({}, []), (None, []),
        ({"general": {"alpha_updates_enabled": "yes"}}, []),    # hand-edited: not opted in
    ])
    def test_alpha_only_when_explicitly_on(self, settings, want):
        assert S.allowed_channels(settings) == want

    @pytest.mark.parametrize("settings,want", [
        ({"general": {"updates_enabled": False}}, False),
        ({"general": {"updates_enabled": True}}, True), ({}, True), (None, True),
    ])
    def test_automatic_checks_follow_the_updates_setting(self, settings, want):
        assert S.updates_enabled(settings) is want


class TestInfoPlist:
    def test_the_keys_of_a_sparkle_build(self):
        keys = S.plist_keys(KEY, "https://rocco-labs.github.io/WinZapp_Python", "x86_64",
                            ["pt-BR", "pt-PT", "en-US", "es-ES", "pl", "tr-TR", "ro"])
        # Sparkle's windows in WinZapp's languages (its own pt-BR.lproj, es.lproj...)
        assert keys["CFBundleLocalizations"] == ["en", "pt-BR", "pt-PT", "es", "pl", "tr", "ro"]
        assert keys["SUFeedURL"] == "https://rocco-labs.github.io/WinZapp_Python/appcast-x86_64.xml"
        assert keys["SUPublicEDKey"] == KEY
        # A signed feed, verified before extraction, and a signing failure
        # that never expires into trusting an unsigned one.
        assert keys["SURequireSignedFeed"] is True and keys["SUVerifyUpdateBeforeExtraction"] is True
        assert keys["SUSignedFeedFailureExpirationInterval"] == 0
        # Downloaded in the background and installed on quit, by default:
        # sparkle_mac applies WinZapp's own setting to both at run time.
        assert keys["SUAllowsAutomaticUpdates"] is True and keys["SUAutomaticallyUpdate"] is True
        assert keys["SUScheduledCheckInterval"] == 3 * 60 * 60

    @pytest.mark.parametrize("key", ["", "not base64!", "Zm9v", KEY + "AAAA", None, "é" * 44])
    def test_a_bad_public_key_is_refused(self, key):
        with pytest.raises(ValueError):
            S.plist_keys(key, "https://x.example", "arm64")

    @pytest.mark.parametrize("base", ["", "http://x.example", "https://x.example/", "https://",
                                      "https://x .example", None, "ftp://x.example"])
    def test_a_feed_that_is_not_plain_https_is_refused(self, base):
        with pytest.raises(ValueError):
            S.plist_keys(KEY, base, "arm64")

    def test_sparkle_is_on_only_with_a_tag_a_key_a_feed_and_the_tags_bundle_version(self):
        info = dict(S.plist_keys(KEY, "https://x.example", "arm64"),
                    WinZappReleaseTag=RUNNING, CFBundleVersion=P.bundle_version(RUNNING))
        assert S.configured(info)
        for broken in ({"WinZappReleaseTag": ""}, {"SUPublicEDKey": ""},
                       {"SUFeedURL": "http://x.example/appcast-arm64.xml"},
                       {"CFBundleVersion": "2.1.0.4250"}):
            assert not S.configured(dict(info, **broken))
        assert not S.configured({})
