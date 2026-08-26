"""Structural guards for runtime-only WPPConnect integration contracts."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _patch(relative_path):
    return (ROOT / "client" / "api_patches" / relative_path).read_text(
        encoding="utf-8"
    )


def test_message_edit_accepts_current_and_legacy_callback_shapes():
    source = _patch("src/util/createSessionUtil.ts")

    assert "legacyMessage ?? eventOrChat?.msg" in source
    assert "onMessageEdit emitted without a serialized message" in source
    assert "session: client.session" in source


def test_force_kill_filter_is_separator_agnostic_and_skips_itself():
    """forceKillByUserDataDir()'s PowerShell filter has to match the *real*
    Chrome CommandLine, and both halves of that used to be wrong.

    Both call sites pass `userDataDir/<session>` with a forward slash, but
    that string never reaches Chrome verbatim: puppeteer path.resolve()s the
    relative './userDataDir/<session>' before building --user-data-dir, so the
    live process reads `...\\userDataDir\\<session>` (backslashes, and 8.3 short
    names for the parent directories). PowerShell's `-like` treats `\\` and `/`
    as ordinary, non-interchangeable characters, so a filter that keeps the
    literal separator matched the browser zero times — while still matching
    the powershell.exe running the query, whose own -Command argument does
    contain the forward-slash text, which is what made the script Stop-Process
    itself on every invocation.
    """
    source = _patch("src/util/createSessionUtil.ts")

    # Every run of separators collapses to a `*`, so only the tail of the path
    # is matched — immune to the separator flavour and to 8.3 shortening.
    assert r".replace(/[\\/]+/g, '*')" in source
    # The old backslash-doubling escape must not come back: `-like` reads `\\`
    # as two literal backslashes, which no command line ever contains.
    assert r"replace(/\\/g, '\\\\')" not in source
    # Wildcard metacharacters are neutralised before the separator wildcards
    # are introduced, so a session id can never act as a pattern.
    assert r".replace(/[`*?[\]]/g, '`$&')" in source
    assert "$_.ProcessId -ne $mypid" in source


def test_status_probe_distinguishes_not_ready_from_disconnected():
    source = _patch("src/middleware/statusConnection.ts")

    assert "connected !== true" in source
    assert "new SessionNotReadyError(detail)" in source
    assert "WAPI is not defined" in source
    assert "next(error)" in source


def test_set_limit_route_authenticates_and_checks_connection():
    source = _patch("src/routes/index.ts")
    route = re.search(
        r"routes\.post\(\s*'/api/:session/set-limit',(?P<body>.*?)\);",
        source,
        re.DOTALL,
    )

    assert route is not None
    assert re.search(
        r"verifyToken,\s*statusConnection,\s*MiscController\.setLimit",
        route.group("body"),
    )
