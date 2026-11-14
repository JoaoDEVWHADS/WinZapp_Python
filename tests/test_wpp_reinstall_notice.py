"""One-time WPPConnect reinstall recommendation for pre-2.0 accounts.

No version number was ever persisted to settings.json before this feature,
so migrate_wpp_reinstall_notice() cannot compare version strings — it only
knows "this settings.json existed before the flag did", which is exactly
"this account predates 2.0" since the flag ships pre-set True in
settings_default.json. Covers the migration itself, plus the gating/display
method that shows the dialog and always clears the flag afterwards,
regardless of the user's answer.
"""

import types

import pytest

import wx

from core.utils import migrate_wpp_reinstall_notice
from main import MainWindow


class TestMigration:
    def test_a_settings_dict_without_the_flag_is_armed(self):
        settings = {"general": {}}
        assert migrate_wpp_reinstall_notice(settings) is True
        assert settings["general"]["wpp_reinstall_notice_migrated"] is True
        assert settings["general"]["wpp_reinstall_notice_pending"] is True

    def test_already_migrated_is_left_alone_even_if_pending_was_since_cleared(self):
        """A user who already answered "No" must not be re-armed on the next
        launch just because pending is now False."""
        settings = {
            "general": {
                "wpp_reinstall_notice_migrated": True,
                "wpp_reinstall_notice_pending": False,
            }
        }
        assert migrate_wpp_reinstall_notice(settings) is False
        assert settings["general"]["wpp_reinstall_notice_pending"] is False

    def test_already_migrated_and_still_pending_is_also_left_alone(self):
        """Between "flagged as pending" and "the dialog actually ran", the
        migration itself must be idempotent."""
        settings = {
            "general": {
                "wpp_reinstall_notice_migrated": True,
                "wpp_reinstall_notice_pending": True,
            }
        }
        assert migrate_wpp_reinstall_notice(settings) is False
        assert settings["general"]["wpp_reinstall_notice_pending"] is True

    def test_malformed_settings_does_not_crash(self):
        assert migrate_wpp_reinstall_notice(None) is False
        assert migrate_wpp_reinstall_notice([]) is False

    def test_malformed_general_section_is_replaced_not_crashed_on(self):
        settings = {"general": "not a dict"}
        assert migrate_wpp_reinstall_notice(settings) is True
        assert settings["general"]["wpp_reinstall_notice_pending"] is True


class TestOrdering:
    def test_migrate_settings_calls_it_before_the_backfill(self):
        import inspect

        migrate_src = inspect.getsource(MainWindow._migrate_settings)
        assert "migrate_wpp_reinstall_notice" in migrate_src

        loader_src = inspect.getsource(MainWindow.load_settings)
        assert loader_src.index("self._migrate_settings()") < loader_src.index(
            "backfill_missing_defaults("
        )


def _stub(pending: bool):
    calls = []
    spoken = []
    stub = types.SimpleNamespace(
        settings={"general": {"wpp_reinstall_notice_pending": pending}},
        i18n=types.SimpleNamespace(t=lambda k: f"<{k}>"),
        output=lambda text, interrupt=False: spoken.append(text),
        save_settings=lambda: calls.append("saved"),
        _on_force_reinstall_wpp=lambda event: calls.append("reinstall"),
        spoken=spoken,
        calls=calls,
    )
    stub._show_wpp_reinstall_notice_if_pending = (
        MainWindow._show_wpp_reinstall_notice_if_pending.__get__(stub)
    )
    return stub


STALE = {"versions": [{"version": "2.3000.1046948731-alpha"}]}
FRESH = {"versions": [{"version": "2.3000.1046948731-alpha"},
                      {"version": "2.3000.1047835881-alpha"}]}


@pytest.fixture
def catalogue(monkeypatch):
    """What versions.json the notice finds. Stale by default, so these tests
    never depend on whichever client/api happens to exist on the machine."""
    import core.wa_version_catalogue as cat
    state = {"value": STALE, "paths": []}

    def _read(path):
        state["paths"].append(path)
        return state["value"]
    monkeypatch.setattr(cat, "read_catalogue", _read)
    return state


@pytest.mark.usefixtures("catalogue")
class TestShowIfPending:
    def test_not_pending_shows_nothing_and_costs_nothing(self, monkeypatch):
        shown = []
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: shown.append(a))
        stub = _stub(pending=False)
        stub._show_wpp_reinstall_notice_if_pending()
        assert shown == []
        assert stub.calls == []
        assert stub.spoken == []

    def test_yes_triggers_the_same_reinstall_path_and_clears_the_flag(self, monkeypatch):
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
        stub = _stub(pending=True)
        stub._show_wpp_reinstall_notice_if_pending()
        assert "reinstall" in stub.calls
        assert "saved" in stub.calls
        assert stub.settings["general"]["wpp_reinstall_notice_pending"] is False
        assert stub.spoken == ["<wpp_reinstall_notice_message>"]

    def test_no_does_not_reinstall_but_still_clears_and_saves_the_flag(self, monkeypatch):
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)
        stub = _stub(pending=True)
        stub._show_wpp_reinstall_notice_if_pending()
        assert "reinstall" not in stub.calls
        assert "saved" in stub.calls
        assert stub.settings["general"]["wpp_reinstall_notice_pending"] is False


class TestAnInstallAlreadyReinstalled:
    """Reported 2026-09-27 by an alpha tester who had reinstalled WPPConnect by
    hand long before: pinned 2.3000.1047835881-alpha of 430, calls working,
    and still told on launch that the install may lack calls."""

    def test_a_catalogue_that_reaches_the_calls_build_is_not_asked_about(self, monkeypatch, catalogue):
        shown = []
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: shown.append(a))
        catalogue["value"] = FRESH
        stub = _stub(pending=True)

        stub._show_wpp_reinstall_notice_if_pending()

        assert shown == []
        assert stub.spoken == []
        assert "reinstall" not in stub.calls
        # ...and it stays that way on the next launch.
        assert stub.settings["general"]["wpp_reinstall_notice_pending"] is False
        assert "saved" in stub.calls

    def test_it_reads_the_installed_wa_version_catalogue(self, monkeypatch, catalogue):
        import os
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)
        _stub(pending=True)._show_wpp_reinstall_notice_if_pending()
        assert catalogue["paths"][0].replace(os.sep, "/").endswith(
            "api/node_modules/@wppconnect/wa-version/versions.json")

    def test_an_unreadable_catalogue_still_asks(self, monkeypatch, catalogue):
        """Cannot tell is not proof the install is fine."""
        asked = []
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: asked.append(a) or wx.NO)
        catalogue["value"] = None

        _stub(pending=True)._show_wpp_reinstall_notice_if_pending()

        assert len(asked) == 1
