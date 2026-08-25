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
