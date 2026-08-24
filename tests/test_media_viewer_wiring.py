"""Source-level regression tests for MediaViewer integration.

These tests intentionally avoid importing wxPython so they also run in the
Linux packaging/review environment where wx is not installed.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _method_calls(rel, class_name, method_name):
    tree = ast.parse(_source(rel))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return {
                        n.func.attr
                        for n in ast.walk(child)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    }
    raise AssertionError(f"{class_name}.{method_name} not found")


def test_conversation_activation_routes_images_and_videos_to_media_viewer():
    src = _source("client/ui/conversations.py")
    assert "from ui.media_viewer import MediaViewerDialog" in src
    calls = _method_calls("client/ui/conversations.py", "ConversationsPanel", "_do_activate_message")
    assert "_open_conversation_media_viewer" in calls


def test_status_plain_selection_does_not_open_or_mark_viewed():
    calls = _method_calls("client/status_panel.py", "StatusPanel", "_on_status_contact_selected")
    assert "_open_status_media_viewer" not in calls
    assert "_show_current_status" not in calls
    assert "_mark_status_viewed" not in calls


def test_status_activation_opens_media_viewer():
    calls = _method_calls("client/status_panel.py", "StatusPanel", "_on_status_contact_activated")
    assert "_open_status_media_viewer" in calls


def test_only_viewer_open_callback_marks_status_viewed():
    calls = _method_calls("client/status_panel.py", "StatusPanel", "_on_viewer_status_opened")
    assert "_mark_status_viewed" in calls
    legacy = _method_calls("client/status_panel.py", "StatusPanel", "_show_current_status")
    assert "_mark_status_viewed" not in legacy


def test_video_player_has_real_seek_volume_and_speeded_frame_clock():
    src = _source("client/core/video_player.py")
    assert "def set_volume(" in src
    assert "def bytes_to_seconds(" in src
    assert "self._restart_video_pipe(seconds)" in src
    assert '"-ss", f"{start_seconds:.3f}"' in src
    assert '"-re"' not in src
    assert "_FRAME_FPS * max(0.25, self._speed)" in src



def test_viewer_is_maximized_and_text_mode_is_read_only():
    src = _source("client/ui/media_viewer.py")
    assert "self.Maximize(True)" in src
    assert "wx.TE_MULTILINE | wx.TE_READONLY" in src
    assert "self._close_btn" in src
    assert "self._volume_slider" in src
    assert "self._position_slider" in src


def test_i18n_audit_covers_save_filters():
    conversations = _source("client/ui/conversations.py")
    for key in (
        "file_filter_audio",
        "file_filter_images",
        "file_filter_videos",
        "file_filter_documents",
    ):
        assert key in conversations
def test_media_viewer_translations_exist_in_every_locale():
    required = {
        "media_viewer_title",
        "media_viewer_loading",
        "media_viewer_play",
        "media_viewer_pause",
        "media_viewer_position",
        "media_viewer_volume",
        "media_viewer_speed",
        "media_viewer_caption",
        "media_viewer_error",
        "media_viewer_text_status",
        "language_select_title",
        "language_select_prompt",
        "file_filter_audio",
        "file_filter_images",
        "file_filter_videos",
        "file_filter_documents",
        "media_audio_convert_failed",
        "media_video_convert_failed",
        "startup_critical_title",
        "startup_critical_message",
    }
    for locale in ("en-US", "pt-BR", "es-ES", "pt-PT", "pl"):
        data = json.loads(_source(f"client/languages/{locale}.json"))
        missing = required.difference(data)
        assert not missing, f"{locale}: missing {sorted(missing)}"
        assert all(str(data[key]).strip() for key in required)
