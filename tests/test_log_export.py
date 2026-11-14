"""Settings > Advanced > Export this account's logs (core/log_export.py).

Asked for: one action that saves, where the user chooses, a zip with every
log of the current account's logs folder and the Neonize bridge's logs."""
import datetime
import zipfile
from types import SimpleNamespace

import wx

from core import log_export
from ui.dialogs import advanced_tab
from ui.dialogs.advanced_tab import AdvancedTabMixin


def _make(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"content of {name}", encoding="utf-8")
    return str(folder)


def test_every_account_log_and_only_the_bridge_logs_go_in(tmp_path):
    account = _make(tmp_path / "accounts" / "abc" / "logs",
                    ["log.log", "shutdown_audit.log", "wppconnect.log.1"])
    run = _make(tmp_path / "neonize_bridge" / "run", ["bridge.log", "bridge.log.1", "bridge.pid"])
    (tmp_path / "neonize_bridge" / "run" / "clients").mkdir()

    names = [name for _path, name in log_export.log_sources(account, run)]

    assert names == ["account/log.log", "account/shutdown_audit.log",
                     "account/wppconnect.log.1",
                     "neonize_bridge/bridge.log", "neonize_bridge/bridge.log.1"]


def test_an_install_without_the_bridge_exports_the_account_logs(tmp_path):
    account = _make(tmp_path / "logs", ["log.log"])
    assert [n for _p, n in log_export.log_sources(account, None)] == ["account/log.log"]
    assert [n for _p, n in log_export.log_sources(account, str(tmp_path / "missing"))] == [
        "account/log.log"]
    assert log_export.log_sources(str(tmp_path / "nothing"), None) == []


def test_the_zip_holds_the_files_as_they_are(tmp_path):
    account = _make(tmp_path / "logs", ["log.log", "stderr.log"])
    target = str(tmp_path / "out.zip")
    written, skipped = log_export.write_zip(target, log_export.log_sources(account))
    assert (written, skipped) == (2, [])
    with zipfile.ZipFile(target) as archive:
        assert archive.read("account/log.log") == b"content of log.log"


def test_an_unreadable_log_is_left_out_and_named(tmp_path):
    account = _make(tmp_path / "logs", ["log.log"])
    sources = log_export.log_sources(account) + [(str(tmp_path / "gone.log"), "account/gone.log")]
    written, skipped = log_export.write_zip(str(tmp_path / "out.zip"), sources)
    assert (written, skipped) == (1, ["account/gone.log"])


def test_a_zip_that_cannot_be_written_raises_and_leaves_nothing(tmp_path):
    account = _make(tmp_path / "logs", ["log.log"])
    target = tmp_path / "no-such-folder" / "out.zip"
    try:
        log_export.write_zip(str(target), log_export.log_sources(account))
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    assert not target.exists()


def test_the_proposed_name_carries_the_date():
    assert log_export.default_name(datetime.datetime(2026, 10, 29, 14, 5)) == \
        "winzapp-logs-20261029-1405.zip"


# ── The button ──────────────────────────────────────────────────────────────

class _Dialog:
    result, path, made = wx.ID_OK, "", []

    def __init__(self, parent, title, **kwargs):
        _Dialog.made.append(kwargs)

    def ShowModal(self):
        return _Dialog.result

    def GetPath(self):
        return _Dialog.path

    def Destroy(self):
        pass


def _tab(spoken, remembered):
    return SimpleNamespace(main_window=SimpleNamespace(
        i18n=SimpleNamespace(t=lambda key: key + " {count}" if key.endswith("done") else key),
        settings={}, speak_output=SimpleNamespace(output=spoken.append),
        remember_save_folder=remembered.append))


def _inline(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args: fn(*args))

    class _Now:
        def __init__(self, target, daemon=None, name=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(advanced_tab.threading, "Thread", _Now)


def test_the_button_asks_where_to_save_and_says_how_many_went(monkeypatch, tmp_path):
    account = _make(tmp_path / "logs", ["log.log", "shutdown_audit.log"])
    run = _make(tmp_path / "run", ["bridge.log"])
    monkeypatch.setattr("app_paths.log_path", lambda *parts: account)
    monkeypatch.setattr(advanced_tab, "_bridge_run_folder", lambda: run)
    monkeypatch.setattr(wx, "FileDialog", _Dialog)
    monkeypatch.setattr("ui.dialogs.settings_pages.dialog_owner", lambda fallback: fallback)
    _inline(monkeypatch)
    _Dialog.result, _Dialog.path, _Dialog.made = wx.ID_OK, str(tmp_path / "chosen"), []
    spoken, remembered = [], []

    AdvancedTabMixin._on_export_logs(_tab(spoken, remembered))

    assert _Dialog.made[0]["style"] & wx.FD_SAVE and _Dialog.made[0]["style"] & wx.FD_OVERWRITE_PROMPT
    assert _Dialog.made[0]["defaultFile"].startswith("winzapp-logs-")
    target = str(tmp_path / "chosen.zip")        # ".zip" added when left out
    assert remembered == [target]
    assert spoken == ["advanced_export_logs_working", "advanced_export_logs_done 3"]
    with zipfile.ZipFile(target) as archive:
        assert len(archive.namelist()) == 3


def test_cancelling_the_dialog_writes_nothing(monkeypatch, tmp_path):
    account = _make(tmp_path / "logs", ["log.log"])
    monkeypatch.setattr("app_paths.log_path", lambda *parts: account)
    monkeypatch.setattr(advanced_tab, "_bridge_run_folder", lambda: None)
    monkeypatch.setattr(wx, "FileDialog", _Dialog)
    monkeypatch.setattr("ui.dialogs.settings_pages.dialog_owner", lambda fallback: fallback)
    _inline(monkeypatch)
    _Dialog.result, _Dialog.made = wx.ID_CANCEL, []
    spoken, remembered = [], []
    AdvancedTabMixin._on_export_logs(_tab(spoken, remembered))
    assert spoken == [] and remembered == []
