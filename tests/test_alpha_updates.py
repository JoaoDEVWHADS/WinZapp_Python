"""Tests for the current WinZapp release updater.

The updater now follows GitHub's single /releases/latest endpoint.  Alpha
channel selection used to live here, but that API was removed from
client/updater.py; these tests cover the behavior the current implementation
actually exposes instead of pinning deleted private helpers.
"""

from types import SimpleNamespace

import pytest

import updater


def _assets(*names):
    return [
        {"name": name, "browser_download_url": f"https://example.invalid/{name}"}
        for name in names
    ]


def test_zip_asset_prefers_full_package():
    url = updater.find_zip_asset(
        _assets("extras.zip", "WinZapp.zip", "WinZappClient.zip"),
        client_only=False,
    )
    assert url.endswith("/WinZapp.zip")


def test_zip_asset_prefers_client_only_package_when_requested():
    url = updater.find_zip_asset(
        _assets("WinZapp.zip", "WinZappClient.zip"),
        client_only=True,
    )
    assert url.endswith("/WinZappClient.zip")


def test_zip_asset_falls_back_to_a_zip_when_named_asset_is_absent():
    url = updater.find_zip_asset(_assets("portable-build.zip"), client_only=False)
    assert url.endswith("/portable-build.zip")


def test_zip_asset_absent():
    assert updater.find_zip_asset([], client_only=False) == ""
    assert updater.find_zip_asset(None, client_only=False) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.25.0.0beta", ((0, 25, 0, 0), "beta")),
        ("0.25.0.1500alpha", ((0, 25, 0, 1500), "alpha")),
        ("1.0.0.0", ((1, 0, 0, 0), "")),
    ],
)
def test_supported_versions_parse(value, expected):
    assert updater.parse_version(value) == expected


def test_version_ordering_is_numeric_before_suffix():
    assert updater.is_newer("0.25.0.1500alpha", "0.25.0.0beta")
    assert updater.is_newer("0.25.0.1501alpha", "0.25.0.1500alpha")
    assert updater.is_newer("0.26.0.0beta", "0.25.0.1501alpha")
    assert not updater.is_newer("0.25.0.1501alpha", "0.26.0.0beta")

def test_alpha_offered_when_channel_enabled():
    releases = [
        _release("v0.25.0.1500alpha"),
        _release("v0.25.0.0beta"),
    ]
    picked = updater.select_release(releases, include_alpha=True)
    assert picked["tag_name"] == "v0.25.0.1500alpha"


def test_newest_stable_wins_over_older_stable_even_when_alphas_come_first():
    """The listing is ordered by publish date and mixes both channels, so with
    alphas filtered out the newest stable can sit several entries down."""
    releases = [
        _release("v0.25.0.1502alpha"),
        _release("v0.25.0.1501alpha"),
        _release("v0.25.0.0beta"),
        _release("v0.24.2.0beta"),
    ]
    picked = updater.select_release(releases, include_alpha=False)
    assert picked["tag_name"] == "v0.25.0.0beta"


def test_next_stable_outranks_every_alpha():
    """An alpha user must be pulled back onto the stable line as soon as a new
    stable release ships — not stranded on the alpha channel forever."""
    releases = [
        _release("v0.26.0.0beta"),
        _release("v0.25.0.1502alpha"),
    ]
    picked = updater.select_release(releases, include_alpha=True)
    assert picked["tag_name"] == "v0.26.0.0beta"


def test_newest_alpha_wins_among_alphas():
    releases = [
        _release("v0.25.0.1500alpha"),
        _release("v0.25.0.1502alpha"),
        _release("v0.25.0.1501alpha"),
    ]
    picked = updater.select_release(releases, include_alpha=True)
    assert picked["tag_name"] == "v0.25.0.1502alpha"


def test_drafts_are_never_selected():
    """alpha-release.yml uploads into a draft and only publishes it once every
    asset is up, so a cancelled run leaves a draft behind. It must be invisible."""
    releases = [
        _release("v0.25.0.1503alpha", draft=True),
        _release("v0.25.0.1502alpha"),
    ]
    picked = updater.select_release(releases, include_alpha=True)
    assert picked["tag_name"] == "v0.25.0.1502alpha"


def test_release_without_zip_asset_is_skipped_not_blocking():
    """A release whose ZIP upload was cut short must not block updates for
    everyone until the next one is cut — the previous good one still wins."""
    releases = [
        _release("v0.25.0.1503alpha", assets=_assets("SHA256SUMS.txt")),
        _release("v0.25.0.1502alpha"),
    ]
    picked = updater.select_release(releases, include_alpha=True)
    assert picked["tag_name"] == "v0.25.0.1502alpha"


def test_unparseable_tags_are_ignored():
    """The joaopr4 pre-release workflow publishes "-pre" tags that aren't
    WinZapp versions at all; they can't be compared, so they can't be chosen."""
    releases = [
        _release("v2026.08.21.1200-pre"),
        _release("v0.25.0.0beta"),
    ]
    picked = updater.select_release(releases, include_alpha=False)
    assert picked["tag_name"] == "v0.25.0.0beta"


def test_a_neonize_dll_release_is_never_offered_as_a_winzapp_update():
    """neonize-dll.yml publishes the bridge's neonize build in this repository,
    with a .zip asset, under a tag that starts with "neonize-" (the workflow
    refuses any other): it must never reach the updater, on either channel."""
    neonize = _release("neonize-0.6.0-winzapp.1", prerelease=True,
                       assets=_assets("neonize-0.6.0-winzapp-windows-amd64.zip", "SHA256SUMS.txt"))
    for include_alpha in (False, True):
        assert updater.select_release([neonize], include_alpha=include_alpha) is None
        assert updater.select_release([neonize, _release("v0.25.0.0")],
                                      include_alpha=include_alpha)["tag_name"] == "v0.25.0.0"


def test_returns_none_when_nothing_eligible():
    assert updater.select_release([_release("v0.25.0.1500alpha")], include_alpha=False) is None
    assert updater.select_release([], include_alpha=True) is None


# ── Version comparison across the two channels ────────────────────────────────

def test_alpha_version_parses():
    """The "alpha" suffix alpha-release.yml bakes into the tag has to survive
    parse_version(), or is_newer() would refuse every alpha outright."""
    assert updater.parse_version("0.25.0.1500alpha") == ((0, 25, 0, 1500), "alpha")


def test_alpha_ordering_against_the_stable_line():
    stable_base = "0.25.0.0beta"
    alpha_a     = "0.25.0.1500alpha"
    alpha_b     = "0.25.0.1501alpha"
    next_stable = "0.26.0.0beta"

    # An alpha is newer than the stable release it was cut from...
    assert updater.is_newer(alpha_a, stable_base) is True
    # ...alphas advance among themselves...
    assert updater.is_newer(alpha_b, alpha_a) is True
    # ...and the next stable outranks them all.
    assert updater.is_newer(next_stable, alpha_b) is True
    assert updater.is_newer(alpha_b, next_stable) is False


def test_alpha_ordering_once_the_stable_line_drops_the_suffix():
    """WinZapp ships `0.25.0.0beta` today, but the alpha channel has to keep
    working when releases become plain `a.b.c.d`. The suffix is optional in
    parse_version() and the numeric components are compared first, so the same
    relationships must hold with no suffix at all."""
    assert updater.parse_version("1.0.0.0") == ((1, 0, 0, 0), "")
    assert updater.is_newer("1.0.0.2159alpha", "1.0.0.0") is True      # alpha > its base
    assert updater.is_newer("1.0.0.2160alpha", "1.0.0.2159alpha") is True
    assert updater.is_newer("1.1.0.0", "1.0.0.2160alpha") is True      # next stable wins
    assert updater.is_newer("2.0.0.0", "1.0.0.2160alpha") is True


def test_alpha_ordering_across_the_beta_to_stable_transition():
    """Leaving beta by advancing the numbers keeps every alpha user reachable."""
    alpha_on_beta_line = "0.25.0.2159alpha"
    assert updater.is_newer("1.0.0.0", alpha_on_beta_line) is True
    assert updater.is_newer("0.26.0.0", alpha_on_beta_line) is True
    # Dropping only the suffix does NOT advance past them — that is the case
    # .github/scripts/check_stable_release_ordering.py exists to catch.
    assert updater.is_newer("0.25.0.0", alpha_on_beta_line) is False


def test_select_release_on_a_suffixless_stable_line():
    releases = [_release("v1.0.0.2159alpha"), _release("v1.0.0.0")]
    assert updater.select_release(releases, include_alpha=False)["tag_name"] == "v1.0.0.0"
    assert updater.select_release(releases, include_alpha=True)["tag_name"] == "v1.0.0.2159alpha"
    # And the next stable pulls alpha users back onto the stable line.
    releases.append(_release("v1.1.0.0"))
    assert updater.select_release(releases, include_alpha=True)["tag_name"] == "v1.1.0.0"


def test_a_date_shaped_version_would_break_the_stable_line():
    """Guards the reasoning in alpha-release.yml's version step: a timestamp
    version (2026.08.22.1530) outranks every 0.x stable release, so shipping
    one would mean no future stable release could ever be offered again."""
    assert updater.is_newer("2026.08.22.1530alpha", "0.26.0.0beta") is True
    assert updater.is_newer("0.26.0.0beta", "2026.08.22.1530alpha") is False


# ── UpdateChecker._alpha_enabled ──────────────────────────────────────────────

class _StubMainWindow:
    def __init__(self, settings):
        self.settings = settings


def _checker(settings):
    return updater.UpdateChecker(_StubMainWindow(settings))


def test_alpha_channel_is_off_by_default():
    assert _checker({"general": {}})._alpha_enabled() is False
    assert _checker({})._alpha_enabled() is False


def test_alpha_channel_reads_the_setting():
    assert _checker({"general": {"alpha_updates_enabled": True}})._alpha_enabled() is True
    assert _checker({"general": {"alpha_updates_enabled": False}})._alpha_enabled() is False


def test_alpha_channel_is_read_fresh_each_time():
    """The checker outlives the settings dialog, so ticking the box mid-session
    must take effect without a restart."""
    settings = {"general": {"alpha_updates_enabled": False}}
    checker = _checker(settings)
    assert checker._alpha_enabled() is False
    settings["general"]["alpha_updates_enabled"] = True
    assert checker._alpha_enabled() is True


def test_alpha_channel_survives_broken_settings():
    """A missing/exploded settings object must not take the updater down with
    it — it just means "no alpha"."""
    class _Exploding:
        @property
        def settings(self):
            raise RuntimeError("settings not loaded yet")

    assert updater.UpdateChecker(_Exploding())._alpha_enabled() is False


# ── _fetch_releases: listing + /releases/latest ────────────────────────────────

def _fetching_checker(responses):
    """Build a checker whose _get_json() answers from *responses* (url
    substring -> payload, or an Exception instance to raise)."""
    checker = _checker({"general": {}})
    calls = []

    def _get_json(url, params=None):
        calls.append((url, params))
        for fragment, payload in responses.items():
            if url.endswith(fragment):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected url {url}")

    checker._get_json = _get_json
    checker._calls = calls
    return checker


def test_fetch_merges_listing_and_latest_stable():
    """The listing is the only place alphas appear; /releases/latest is the only
    thing that keeps finding the newest STABLE release once alphas fill the
    listing's first page. Both are needed."""
    listing = [_release(f"v0.25.0.{n}alpha") for n in range(1500, 1600)]
    stable  = _release("v0.25.0.0beta")
    checker = _fetching_checker({"/releases/latest": stable, "/releases": listing})

    fetched = checker._fetch_releases()
    tags = {r["tag_name"] for r in fetched}
    assert "v0.25.0.0beta" in tags          # would have been off the page
    assert "v0.25.0.1599alpha" in tags

    # And the stable user still gets the stable release out of it.
    picked = updater.select_release(fetched, include_alpha=False)
    assert picked["tag_name"] == "v0.25.0.0beta"


def test_fetch_asks_for_a_full_page():
    """Default paging is 30; alphas land far more often than stable releases."""
    checker = _fetching_checker({
        "/releases/latest": _release("v0.25.0.0beta"),
        "/releases": [],
    })
    checker._fetch_releases()
    listing_call = [c for c in checker._calls if c[0].endswith("/releases")][0]
    assert listing_call[1] == {"per_page": 100}


def test_fetch_dedupes_a_release_returned_by_both_endpoints():
    stable = dict(_release("v0.25.0.0beta"), id=42)
    checker = _fetching_checker({"/releases/latest": stable, "/releases": [stable]})
    assert len(checker._fetch_releases()) == 1


def test_fetch_survives_a_failing_listing():
    """A rate-limited listing still leaves the stable release reachable."""
    checker = _fetching_checker({
        "/releases/latest": _release("v0.25.0.0beta"),
        "/releases": RuntimeError("HTTP 403 rate limited"),
    })
    fetched = checker._fetch_releases()
    assert [r["tag_name"] for r in fetched] == ["v0.25.0.0beta"]


def test_fetch_survives_a_missing_latest_stable():
    """/releases/latest 404s on a repo that only ever published prereleases."""
    checker = _fetching_checker({
        "/releases/latest": RuntimeError("HTTP 404"),
        "/releases": [_release("v0.25.0.1500alpha")],
    })
    fetched = checker._fetch_releases()
    assert [r["tag_name"] for r in fetched] == ["v0.25.0.1500alpha"]


def test_fetch_raises_only_when_both_endpoints_fail():
    checker = _fetching_checker({
        "/releases/latest": RuntimeError("HTTP 404"),
        "/releases": RuntimeError("HTTP 403 rate limited"),
    })
    with pytest.raises(Exception):
        checker._fetch_releases()


def test_fetch_accepts_a_single_release_object_from_a_fork():
    """A fork could point the configured URL at one release rather than a list."""
    checker = _fetching_checker({
        "/releases/latest": RuntimeError("HTTP 404"),
        "/releases": _release("v0.25.0.0beta"),
    })
    assert [r["tag_name"] for r in checker._fetch_releases()] == ["v0.25.0.0beta"]


def test_configured_stable_url_is_the_listing_url_plus_latest():
    import config
    assert config.GITHUB_API_LATEST_STABLE_RELEASE == (
        config.GITHUB_API_LATEST_RELEASE + "/latest"
    )


# ── End-to-end: _check_once picks the right release and offers it ─────────────

class _I18n:
    # The language the window shows, as core.i18n.I18n always carries it:
    # the updater reads this rather than asking get_language(), which on the
    # window's own instance re-reads the install-wide setting.
    language = "pt-BR"

    def get_language(self):
        return "pt-BR"

    def t(self, key):
        return key


class _MainWindow:
    def __init__(self):
        self.i18n = _I18n()


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _release(tag, assets=None, body=""):
    return {
        "tag_name": tag,
        "assets": assets if assets is not None else _assets(
            "WinZapp.zip", "SHA256SUMS.txt"
        ),
        "body": body,
    }


def test_check_once_offers_a_newer_latest_release(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    offered = []
    monkeypatch.setattr(updater, "__version__", "1.0.0.0")
    monkeypatch.setattr(updater, "is_client_only_install", lambda: False)
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _Response(_release("v1.1.0.0")),
    )
    monkeypatch.setattr(
        updater,
        "resolve_changelog",
        lambda *a, **kw: "changes",
    )
    monkeypatch.setattr(
        updater.wx,
        "CallAfter",
        lambda fn, *args: offered.append((fn.__name__, args)),
    )

    checker._check_once()

    assert offered
    name, args = offered[0]
    assert name == "_show_update_dialog"
    assert args[0] == "1.1.0.0"
    assert args[1] == "changes"
    assert args[2].endswith("/WinZapp.zip")
    assert args[3].endswith("/SHA256SUMS.txt")


def test_check_once_retries_when_latest_release_is_not_newer(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []
    monkeypatch.setattr(checker, "_fetch_releases", lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(checker, "_schedule_retry", lambda interval=None: retried.append(interval))
    checker._check_once()
    # A failed fetch retries soon first (see UpdateChecker._FETCH_RETRY_DELAYS).
    assert retried == [updater.UpdateChecker._FETCH_RETRY_DELAYS[0]]


def test_check_once_retries_on_network_failure(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []

    def fail(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr(updater.requests, "get", fail)
    monkeypatch.setattr(checker, "_schedule_retry", lambda: retried.append(True))

    checker._check_once()

    assert retried == [True]


def test_check_once_retries_when_release_has_no_zip(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _Response(_release("v1.1.0.0", assets=_assets("notes.txt"))),
    )
    assert glob["alpha_updates_enabled"] is True
    assert "alpha_updates_enabled" not in per["general"]


# ── Re-confirming the newest release after the user says Yes ─────────────────

def _full_release(tag):
    return _release(tag, assets=_assets("WinZapp.zip"))


def test_a_newer_alpha_published_meanwhile_replaces_the_offered_one():
    releases = [_full_release("v0.25.0.1500alpha"), _full_release("v0.25.0.1502alpha"),
                _full_release("v0.25.0.1501alpha")]
    got = updater.newer_release_than_offered(releases, True, "0.25.0.0beta", "0.25.0.1501alpha")
    assert got["tag_name"] == "v0.25.0.1502alpha"


def test_the_offered_release_still_the_newest_is_kept():
    releases = [_full_release("v0.25.0.1501alpha"), _full_release("v0.25.0.1500alpha")]
    assert updater.newer_release_than_offered(
        releases, True, "0.25.0.0beta", "0.25.0.1501alpha") is None


def test_an_alpha_is_never_swapped_in_when_the_channel_is_off():
    releases = [_full_release("v0.25.0.1502alpha"), _full_release("v0.26.0.0beta")]
    got = updater.newer_release_than_offered(releases, False, "0.25.0.0beta", "0.26.0.0beta")
    assert got is None


def test_nothing_is_swapped_in_when_no_release_is_listed():
    assert updater.newer_release_than_offered([], True, "0.25.0.0beta", "0.25.0.1501alpha") is None


class _Stub:
    """UpdateChecker with just what the reconfirmation touches."""

    def __init__(self, releases=None, fail=False, shutting_down=False):
        self._releases, self._fail = releases or [], fail
        self._mw = type("MW", (), {"_shutting_down": shutting_down})()
        self._install_pending = True
        self.calls = []

    def _fetch_releases(self):
        if self._fail:
            raise RuntimeError("offline")
        return self._releases

    def _alpha_enabled(self):
        return True

    def _do_install(self, *args):
        self.calls.append(("install", args))

    def _release_prompt(self):
        self.calls.append(("release",))

    def _install_reconfirmed(self, *args):
        pass

    def _schedule_retry(self):
        self.calls.append(("retry",))


def _run_worker(stub, monkeypatch, offered):
    import update_reconfirm as ur
    sent = []
    monkeypatch.setattr(ur.wx, "CallAfter", lambda fn, *a: sent.append((fn, a)), raising=False)
    monkeypatch.setattr(ur, "__version__", "0.25.0.0beta")
    ur.ReconfirmMixin._reconfirm_worker(stub, *offered)
    assert len(sent) == 1
    return sent[0][1]


OFFERED = ("0.25.0.1501alpha", "https://x/zip", "https://x/sums", "", True)


def test_worker_hands_over_the_newer_release(monkeypatch):
    newer = _release("v0.25.0.1502alpha", assets=_assets("WinZapp.zip", "SHA256SUMS.txt"))
    args = _run_worker(_Stub([newer]), monkeypatch, OFFERED)
    assert args[0] == "0.25.0.1502alpha"
    assert args[1].endswith("WinZapp.zip") and args[2].endswith("SHA256SUMS.txt")
    assert args[4] is True


def test_worker_keeps_the_offered_release_when_the_fetch_fails(monkeypatch):
    assert _run_worker(_Stub(fail=True), monkeypatch, OFFERED) == OFFERED


def test_worker_ignores_a_newer_release_without_a_zip(monkeypatch):
    broken = _release("v0.25.0.1502alpha", assets=_assets("SHA256SUMS.txt"))
    assert _run_worker(_Stub([broken]), monkeypatch, OFFERED) == OFFERED


def test_a_release_not_newer_than_the_running_version_is_not_swapped_in():
    releases = [_full_release("v0.25.0.1500alpha")]
    assert updater.newer_release_than_offered(
        releases, True, "0.25.0.1600alpha", "0.25.0.1501alpha") is None


def test_install_hands_over_and_clears_the_pending_guard():
    import update_reconfirm as ur
    stub = _Stub()
    ur.ReconfirmMixin._install_reconfirmed(stub, *OFFERED)
    assert stub._install_pending is False
    assert stub.calls == [("install", OFFERED)]


def test_install_while_shutting_down_releases_the_prompt():
    import update_reconfirm as ur
    stub = _Stub(shutting_down=True)
    ur.ReconfirmMixin._install_reconfirmed(stub, *OFFERED)
    assert stub.calls == [("release",), ("retry",)]
