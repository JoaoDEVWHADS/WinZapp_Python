"""Regression guards: WhatsApp calls must not operate in offline mode."""

from pathlib import Path

MAIN_SOURCE = (
    Path(__file__).resolve().parents[1] / "client" / "main.py"
).read_text(encoding="utf-8")


def _method_source(name: str) -> str:
    marker = f"    def {name}("
    start = MAIN_SOURCE.index(marker)
    end = MAIN_SOURCE.find("\n    def ", start + len(marker))
    return MAIN_SOURCE[start:] if end == -1 else MAIN_SOURCE[start:end]


def test_outgoing_voice_and_video_calls_are_blocked_offline():
    source = _method_source("_start_individual_call")
    assert 'getattr(self, "offline_mode", False)' in source
    assert 'self.i18n.t("offline_mode_enabled")' in source
    assert source.index('getattr(self, "offline_mode", False)') < source.index("_normalize_jid")


def test_call_control_cannot_bypass_offline_mode():
    source = _method_source("_post_call_control")
    assert 'getattr(self, "offline_mode", False) and endpoint != "end"' in source


def test_incoming_calls_cannot_be_answered_or_rejected_offline():
    for name in ("accept_incoming_call", "reject_incoming_call"):
        source = _method_source(name)
        assert 'getattr(self, "offline_mode", False)' in source
        assert "stop_incoming_call_alert(identity)" in source


def test_incoming_ringing_is_ignored_offline():
    source = _method_source("on_incoming_call_event")
    assert 'if is_ringing and getattr(self, "offline_mode", False):' in source


def test_browser_call_media_cannot_attach_offline():
    state_source = _method_source("on_voice_call_state_event")
    attach_source = _method_source("_attach_audio_to_browser_call")
    assert 'getattr(self, "offline_mode", False)' in state_source
    assert "_stop_voice_call_audio()" in state_source
    assert 'getattr(self, "offline_mode", False)' in attach_source


def test_entering_manual_offline_tears_down_existing_call_activity():
    source = _method_source("toggle_offline_mode")
    assert "entering_offline" in source
    assert "end_active_call()" in source
    assert "_stop_voice_call_audio()" in source
    assert "stop_all_incoming_call_alerts()" in source
