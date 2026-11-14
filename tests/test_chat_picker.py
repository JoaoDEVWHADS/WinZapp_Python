"""Tests for the media-cleanup chat-picker logic.

Kept as plain functions with no wx dependency so they run headless (see
ChatCheckList's own docstring in client/ui/dialogs/chat_picker.py for why):

- filter_options()/visible_all_checked() — the group/individual filter and
  the "select all" row's own checked state.
- core.media_cleanup.chat_options() — building the picker's option list from
  the conversation lists already in memory.
"""

from core.media_cleanup import chat_options
from ui.dialogs.chat_picker import filter_options, visible_all_checked


# ── filter_options / visible_all_checked (no wx.App needed) ────────────────

_OPTIONS = [
    ("g1@g.us", "Grupo da Família", True),
    ("5511999999999@s.whatsapp.net", "+55 11 99999-9999", False),
    ("g2@g.us", "Trabalho", True),
    ("5511988888888@s.whatsapp.net", "Ana", False),
]


def test_filter_options_all_keeps_everything():
    assert filter_options(_OPTIONS, "all") == _OPTIONS


def test_filter_options_groups_only():
    result = filter_options(_OPTIONS, "groups")
    assert [o[0] for o in result] == ["g1@g.us", "g2@g.us"]


def test_filter_options_individual_only():
    result = filter_options(_OPTIONS, "individual")
    assert [o[0] for o in result] == [
        "5511999999999@s.whatsapp.net", "5511988888888@s.whatsapp.net",
    ]


def test_visible_all_checked_true_when_every_visible_jid_is_checked():
    visible = ["a", "b", "c"]
    assert visible_all_checked(visible, {"a", "b", "c", "d"}) is True


def test_visible_all_checked_false_when_one_missing():
    visible = ["a", "b", "c"]
    assert visible_all_checked(visible, {"a", "b"}) is False


def test_visible_all_checked_false_when_empty():
    assert visible_all_checked([], {"a"}) is False


# ── chat_options ───────────────────────────────────────────────────────────

def _chat(jid):
    return {"remoteJid": jid}


def test_chat_options_merges_main_and_archived_sorted_by_name():
    main = ([_chat("b@s.whatsapp.net"), _chat("g@g.us")], ["Bia", "Amigos"])
    archived = ([_chat("a@s.whatsapp.net")], ["Ana"])
    options = chat_options([main, archived])
    assert options == [
        ("g@g.us", "Amigos", True),
        ("a@s.whatsapp.net", "Ana", False),
        ("b@s.whatsapp.net", "Bia", False),
    ]


def test_chat_options_excludes_locked_chats_and_dedupes():
    main = ([_chat("x@s.whatsapp.net"), _chat("y@s.whatsapp.net"), _chat("y@s.whatsapp.net")],
            ["X", "Y", "Y de novo"])
    options = chat_options([main], is_locked=lambda jid: jid.startswith("x@"))
    assert options == [("y@s.whatsapp.net", "Y", False)]


def test_chat_options_survives_missing_pieces():
    assert chat_options([(None, None), ([{}], ["sem jid"]), ([_chat("z@g.us")], [None])]) \
        == [("z@g.us", "z@g.us", True)]
