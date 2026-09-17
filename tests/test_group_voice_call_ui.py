import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_group_voice_call_picker_uses_accessible_native_list_checkboxes():
    source = _source("client/ui/dialogs/group_voice_call.py")

    assert "wx.ListCtrl" in source
    assert "EnableCheckBoxes(True)" in source
    assert "wx.CheckListBox" not in source
    assert "wx.WXK_SPACE" in source
    assert "wx.EVT_LIST_ITEM_ACTIVATED" in source
    assert "self.start_button.Enable(count >= 2)" in source


def test_voice_call_button_routes_group_chats_to_participant_picker():
    source = _source("client/ui/conversations.py")

    assert 'unavailable = jid.endswith(("@newsletter", "@broadcast"))' in source
    assert 'if jid.endswith("@g.us"):' in source
    assert "self._open_group_voice_call_picker(jid, name)" in source
    assert "self.main_window.start_group_voice_call(group_jid, selected, group_name)" in source


def test_group_voice_call_picker_has_translations_in_every_supported_language():
    required = {
        "group_voice_call_title",
        "group_voice_call_participants_label",
        "group_voice_call_toggle_hint",
        "group_voice_call_participants_column",
        "group_voice_call_selected_count",
        "group_voice_call_start_button",
        "group_voice_call_loading",
        "group_voice_call_not_enough_participants",
    }
    for language in ("pt-BR", "pt-PT", "en-US", "es-ES", "pl"):
        data = json.loads(_source(f"client/languages/{language}.json"))
        assert required <= data.keys()
