"""Tests that a WPPConnect update is not announced as an outage.

`_update_wpp_server()` stops the server on purpose. The socket drops, every
probe fails, and nothing answers until the reinstall finishes — two or three
minutes on a real update. Announcing "desconectado do WhatsApp" through that
window is wrong, and it frightens people: two field reports describe the update
as leaving the app "flipping between offline and normal". That is the message,
not the mechanism.

There was already a `_wpp_updating` flag for exactly this, but it was consulted
in one place only — the health checker. `WebSocketClient`'s confirmed-socket-drop
path went straight to `_set_wa_connected(False, "socket disconnected")`, and that
is the one that fired: observed at 17:48:26 during a real 2.10.6 -> 2.10.10
update, seconds after the server was stopped deliberately.

The guard now sits at the single place that decides the message, so it cannot be
half-applied across callers again.
"""

import pytest

from main import MainWindow


class _I18n:
    def t(self, key):
        return {"tray_connecting": "conectando...",
                "tray_wa_disconnected": "desconectado do WhatsApp"}.get(key, key)


class _Stub:
    _set_wa_connected = MainWindow._set_wa_connected

    def __init__(self, updating=False):
        self._wpp_updating = updating
        self._wa_connected = True
        self._wa_offline_strikes = 0
        self._wa_connect_announced = True
        self._auto_offline = False
        self._user_offline = False
        self.i18n = _I18n()
        self.statuses = []
        self.offline_applied = False
        # Only the non-updating path reaches the announcement block; keep it
        # silent so these tests are about the status text, not about sound.
        self.background_mode = True

    # --- collaborators the method reaches for ---
    def _set_status(self, text):
        self.statuses.append(text)

    def _apply_offline_state(self):
        self.offline_applied = True

    def _startup_offline_confirmed(self):
        return False

    def trigger_sync_if_needed(self):
        pass


@pytest.fixture(autouse=True)
def _sync_callafter(monkeypatch):
    """wx.CallAfter would otherwise need a running app; run inline."""
    import main as main_module

    monkeypatch.setattr(main_module.wx, "CallAfter",
                        lambda fn, *a, **k: fn(*a, **k))


class TestDuringAnUpdate:
    def test_it_shows_connecting_not_disconnected(self):
        stub = _Stub(updating=True)
        stub._set_wa_connected(False, "socket disconnected", False)

        assert stub.statuses == ["conectando..."]
        assert "desconectado do WhatsApp" not in stub.statuses

    def test_it_does_not_enter_the_offline_state(self):
        """_apply_offline_state() is what flips the tray/title and gates the
        rest of the app — the update is not an outage and must not trip it."""
        stub = _Stub(updating=True)
        stub._set_wa_connected(False, "socket disconnected", False)

        assert stub.offline_applied is False

    def test_the_health_check_path_is_covered_too(self):
        """The health checker already consulted the flag itself; the point of
        guarding centrally is that both callers now behave the same."""
        stub = _Stub(updating=True)
        stub._set_wa_connected(False, "status-session CLOSED", True)

        assert stub.statuses == ["conectando..."]
        assert stub.offline_applied is False


class TestOutsideAnUpdate:
    def test_a_real_outage_is_still_announced(self):
        """The guard must not swallow genuine disconnections — that would be a
        worse bug than the one it fixes."""
        stub = _Stub(updating=False)
        stub._set_wa_connected(False, "socket disconnected", True)

        assert stub.statuses == ["desconectado do WhatsApp"]
        assert stub.offline_applied is True

    def test_a_missing_flag_is_treated_as_not_updating(self):
        """_wpp_updating is set in __init__; anything reaching this before then
        must fall through to the normal path, not be silently suppressed."""
        stub = _Stub(updating=False)
        del stub._wpp_updating
        stub._set_wa_connected(False, "socket disconnected", True)

        assert stub.statuses == ["desconectado do WhatsApp"]


class TestTheFlagIsActuallyCleared:
    """The suppression is only safe because the flag is guaranteed to clear —
    otherwise a failed update would hide every outage from then on."""

    def test_update_clears_it_in_a_finally(self):
        import inspect

        source = inspect.getsource(MainWindow._update_wpp_server)
        finally_at = source.index("finally:")
        assert "self._wpp_updating = False" in source[finally_at:]
