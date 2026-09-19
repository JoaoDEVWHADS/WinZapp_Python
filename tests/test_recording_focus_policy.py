import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _method_source(relative: str, class_name: str, method_name: str) -> str:
    source = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == method_name:
                    return ast.get_source_segment(source, member) or ""
    raise AssertionError(f"{class_name}.{method_name} not found in {relative}")


def test_conversation_silent_recording_does_not_manufacture_send_focus_event():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel",
        "_focus_recording_button_silently"
    )

    assert "if self._voice_recording_focus_suppression_enabled():" in method
    assert "return False" in method
    assert method.count("button.SetFocus()") == 1
    assert method.index("return False") < method.index("button.SetFocus()")


def test_status_silent_recording_uses_cloaked_real_focus_instead_of_panel_fallback():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_focus_recording_button_silently"
    )

    assert "cloak_focus_announcement(button" in method
    assert method.count("button.SetFocus()") == 2
    assert "_silence_send_voice_focus_if_enabled()" in method


def test_panel_focus_fallback_uses_nvda_silent_pane_role():
    source = (ROOT / "client/core/focus_cloak.py").read_text(encoding="utf-8")

    assert "class PanelFocusCloakAccessible" in source
    assert "return (wx.ACC_OK, wx.ROLE_SYSTEM_PANE)" in source
    assert 'return (wx.ACC_OK, "")' in source
    assert "def cloak_panel_focus_fallback" in source


def test_conversation_recording_cloaks_panel_before_hiding_focused_controls():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel", "_start_voice_recording"
    )

    assert method.count("cloak_panel_focus_fallback(") >= 2
    first_cloak = method.index("cloak_panel_focus_fallback(")
    first_record_hide = method.index("self.record_voice_message_btn.Hide()")
    assert first_cloak < first_record_hide
    assert "self.message_field" in method
    assert "recording_controls_to_hide" in method


def test_status_recording_cloaks_panel_before_hiding_start_button():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_start_voice_recording"
    )

    cloak = method.index("cloak_panel_focus_fallback(")
    hide = method.index("self._voice_start_btn.Hide()")
    assert cloak < hide
    assert "self._voice_post_panel" in method


def test_silent_conversation_recording_preserves_message_field_focus():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel", "_start_voice_recording"
    )

    assert "keep_message_field_focused" in method
    assert "if keep_message_field_focused:" in method
    assert "else:\n                self.message_field.Hide()" in method

    silent_block = method.split("if keep_message_field_focused:", 1)[1].split(
        "else:\n                self.message_field.Hide()", 1
    )[0]
    assert "self.message_field" not in silent_block.split(
        "recording_controls_to_hide = [", 1
    )[1].split("]", 1)[0]


def test_voice_recording_start_arms_full_speech_silence_transition():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel", "_start_voice_recording"
    )

    assert method.count("_arm_voice_recording_silence_transition()") >= 2
    assert method.count("_silence_send_voice_focus_if_enabled()") >= 2


def test_voice_send_keeps_speech_suppressed_through_focus_restore():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel", "_send_voice_message"
    )

    assert "_arm_voice_recording_silence_transition()" in method
    assert method.index("_arm_voice_recording_silence_transition()") < method.index(
        "self._is_recording     = False"
    )
    assert method.count("_focus_message_field_after_voice_recording()") == 2
    assert "self.message_field.SetFocus()" not in method


def test_voice_discard_keeps_speech_suppressed_through_focus_restore():
    method = _method_source(
        "client/ui/conversations.py", "ConversationsPanel", "_discard_voice_message"
    )

    assert "_arm_voice_recording_silence_transition()" in method
    assert method.index("_arm_voice_recording_silence_transition()") < method.index(
        "self._is_recording     = False"
    )
    assert "_focus_message_field_after_voice_recording()" in method
    assert "self.message_field.SetFocus()" not in method


def test_voice_focus_restore_cloaks_native_field_announcement_and_cancels_speech():
    method = _method_source(
        "client/ui/conversations.py",
        "ConversationsPanel",
        "_focus_message_field_after_voice_recording",
    )

    assert "cloak_focus_announcement(self.message_field" in method
    assert "self.message_field.SetFocus()" in method
    assert "_silence_send_voice_focus_if_enabled()" in method
    assert "_arm_voice_recording_silence_transition()" in method


def test_focus_cloak_hides_name_and_role_during_silent_focus():
    source = (ROOT / "client/core/focus_cloak.py").read_text(encoding="utf-8")

    assert "def GetRole(self, childId):" in source
    assert "wx.ROLE_SYSTEM_PANE" in source
    assert "def GetName(self, childId):" in source
    assert "def GetDescription(self, childId):" in source


def test_status_silent_recording_focuses_send_before_hiding_start():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_start_voice_recording"
    )

    focus = method.index("_focus_recording_button_silently(self._voice_send_btn)")
    hide = method.index("self._voice_start_btn.Hide()")
    assert focus < hide


def test_status_leave_moves_focus_before_disabling_voice_composer():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_leave_status_composer"
    )

    focus = method.index("self._status_list.SetFocus()")
    hide = method.index("self._hide_post_panels()")
    assert focus < hide
    assert "if voice_composer:" in method
    assert "self._status_list.SetFocus()" in method.split("if voice_composer:", 1)[1].split(
        "self._hide_post_panels()", 1
    )[0]
    assert "cloak_focus_announcement(self._status_list" in method


def test_status_unavailable_fix_does_not_depend_on_silence_setting():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_leave_status_composer"
    )

    voice_block = method.split("if voice_composer:", 1)[1].split(
        "self._hide_post_panels()", 1
    )[0]
    set_focus = voice_block.index("self._status_list.SetFocus()")
    suppress_if = voice_block.index("if suppress_voice_focus:")
    assert set_focus > suppress_if
    # SetFocus is outside the suppression-only block: every voice-composer
    # exit moves focus before the focused controls are disabled.
    before_focus = voice_block[:set_focus]
    assert before_focus.rstrip().endswith(
        "self._silence_send_voice_focus_if_enabled()"
    ) or "if suppress_voice_focus:" in before_focus


def test_status_voice_exit_focus_is_unconditional_within_voice_composer():
    method = _method_source(
        "client/status_panel.py", "StatusPanel", "_leave_status_composer"
    )
    lines = method.splitlines()
    focus_lines = [line for line in lines if "self._status_list.SetFocus()" in line]
    assert any(line.startswith(" " * 12) for line in focus_lines)
