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
