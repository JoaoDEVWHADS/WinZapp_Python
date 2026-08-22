"""Tests for the sync/media/auto-offline announcements master mute.

Settings > Geral > "Anunciar sincronização, download de mídias e modo offline
automático" gates the spoken+sound warnings for sync progress/completion, media
downloads and the automatic offline transition. When unchecked, none of them may
fire; when missing, it must default to enabled so existing installs keep their
current behaviour.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so the
method under test is exercised as a plain function against a small stub that
carries just the attribute it touches.
"""

import pytest

from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for the announce-sync-events method."""

    def __init__(self, settings=None):
        self.settings = settings or {}

    _announce_sync_events_enabled = MainWindow._announce_sync_events_enabled


def test_defaults_to_enabled_when_setting_missing():
    # A settings dict without the key at all (existing installs / partial
    # configs) must keep announcing — the master mute is opt-out.
    assert _Stub({})._announce_sync_events_enabled() is True


def test_defaults_to_enabled_when_general_missing():
    assert _Stub({"general": {}})._announce_sync_events_enabled() is True


def test_explicit_true_is_enabled():
    stub = _Stub({"general": {"announce_sync_events": True}})
    assert stub._announce_sync_events_enabled() is True


def test_explicit_false_is_disabled():
    stub = _Stub({"general": {"announce_sync_events": False}})
    assert stub._announce_sync_events_enabled() is False


class _Sound:
    def __init__(self, raises=False):
        self.raises = raises
        self.calls = 0

    def play(self):
        self.calls += 1
        if self.raises:
            raise RuntimeError("device disappeared")


class _I18n:
    def t(self, key):
        return {"sync_complete": "Sincronização concluída"}.get(key, key)


class _CompleteStub:
    _announce_sync_events_enabled = MainWindow._announce_sync_events_enabled
    _announce_sync_complete = MainWindow._announce_sync_complete

    def __init__(self, *, sound_raises=False, background=False, enabled=True):
        self.settings = {"general": {"announce_sync_events": enabled}}
        self._sync_run_id = 7
        self._sync_completion_announced_run_id = None
        self.sync_complete_sound = _Sound(sound_raises)
        self.background_mode = background
        self.i18n = _I18n()
        self.statuses = []
        self.spoken = []

    def _set_status(self, value):
        self.statuses.append(value)

    def output(self, text, interrupt=False):
        self.spoken.append((text, interrupt))


def test_sync_complete_sound_and_tts_are_both_emitted_once():
    stub = _CompleteStub()
    stub._announce_sync_complete(7)
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 1
    assert stub.spoken == [("Sincronização concluída", True)]
    assert stub.statuses == [""]


def test_sound_failure_does_not_suppress_sync_complete_tts():
    stub = _CompleteStub(sound_raises=True)
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 1
    assert stub.spoken == [("Sincronização concluída", True)]


def test_stale_sync_completion_callback_is_ignored():
    stub = _CompleteStub()
    stub._sync_run_id = 8
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 0
    assert stub.spoken == []


def test_background_mode_still_plays_sound_but_skips_tts():
    stub = _CompleteStub(background=True)
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 1
    assert stub.spoken == []


def test_master_mute_suppresses_both_completion_channels():
    stub = _CompleteStub(enabled=False)
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 0
    assert stub.spoken == []


def test_status_clear_failure_does_not_suppress_sound_or_tts():
    stub = _CompleteStub()

    def _boom(_value):
        raise RuntimeError("tray unavailable")

    stub._set_status = _boom
    stub._announce_sync_complete(7)
    assert stub.sync_complete_sound.calls == 1
    assert stub.spoken == [("Sincronização concluída", True)]


def test_run_sync_commits_success_before_queuing_completion_announcement():
    import inspect

    source = inspect.getsource(MainWindow._run_sync)
    committed = source.index("self._sync_completed = True")
    queued = source.index("wx.CallAfter(self._announce_sync_complete")
    assert committed < queued
