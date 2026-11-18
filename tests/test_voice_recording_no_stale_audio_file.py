"""Regression guard for the stale `as_audio_file` branch (2026-11-17).

The merge of upstream/main (56591c143, PR #815) kept upstream's refactored
`if as_audio_file:` call while the local fix e50294df6 had removed both the
variable and `_enqueue_system_audio_file` itself. Every voice message then
died with `NameError: name 'as_audio_file' is not defined` inside
`_process()` — the exception was logged and swallowed, the dispatcher ticket
completed with no action, and nothing was ever enqueued.

The voice path imports wx, so the behavioral coverage lives in the Qt-free
voice tests and on the Windows runners; this guard pins the exact regression
everywhere, including wx-less environments.
"""

from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] /
          "client" / "ui" / "conversation_panel" / "voice_recording.py")


def test_voice_recording_has_no_stale_as_audio_file_reference():
    assert "as_audio_file" not in SOURCE.read_text(encoding="utf-8")


def test_voice_recording_does_not_call_removed_enqueue_system_audio_file():
    assert "_enqueue_system_audio_file" not in SOURCE.read_text(encoding="utf-8")
