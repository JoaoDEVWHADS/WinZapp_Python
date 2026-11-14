"""Which entries of the server's chat list WinZapp keeps and shows.

Statuses never are conversations. Channels (@newsletter) are left out unless the
user ticks Settings > Interface > Chats > "Show channels in the chat list"
(off by default: a tab of their own is planned, and WhatsApp itself is trying
channels in the chat list).
"""
import json
import os
from types import SimpleNamespace

import pytest

from core.listed_chats import channels_listed, is_listed_chat
from main import MainWindow
from tests.test_chat_row_move_to_top import _Win, _win

PERSON, GROUP, CHANNEL = "5511999990000@s.whatsapp.net", "1203-44@g.us", "120363@newsletter"


def test_people_and_groups_are_listed():
    for jid in (PERSON, "77@lid", GROUP):
        assert is_listed_chat(jid)
        assert is_listed_chat(jid, show_channels=True)


def test_channels_are_left_out_unless_asked_for():
    assert not is_listed_chat(CHANNEL)
    assert is_listed_chat(CHANNEL, show_channels=True)


def test_statuses_and_junk_are_never_listed():
    for jid in ("status@broadcast", "123@broadcast", "", None, 42):
        assert not is_listed_chat(jid)
        assert not is_listed_chat(jid, show_channels=True)


@pytest.mark.parametrize("settings,expected", [
    ({}, False), (None, False), ({"user_interface": {}}, False),
    ({"user_interface": {"show_channels_in_chat_list": False}}, False),
    ({"user_interface": {"show_channels_in_chat_list": True}}, True),
    ({"user_interface": {"show_channels_in_chat_list": "yes"}}, False),
    ({"user_interface": "broken"}, False),
])
def test_the_setting_is_off_unless_it_is_exactly_true(settings, expected):
    assert channels_listed(settings) is expected


def test_the_shipped_defaults_leave_channels_out_of_the_list():
    from core.utils import DEFAULT_SETTINGS
    root = os.path.join(os.path.dirname(__file__), "..", "client", "data", "settings_default.json")
    shipped = json.load(open(root, encoding="utf-8"))

    assert DEFAULT_SETTINGS["user_interface"]["show_channels_in_chat_list"] is False
    assert shipped["user_interface"]["show_channels_in_chat_list"] is False


class _Window(_Win):
    _compute_chat_lists = MainWindow._compute_chat_lists
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def _resolve_contact_name(self, chat):
        return chat["pushName"]

    def _group_name_from_chat_dict(self, chat):
        return "Grupo"

    def _is_bad_contact_name(self, name):
        return not name

    def is_chat_locked(self, jid):
        return False

    def _chat_archive_flag(self, chat):
        return False


def listed(show_channels):
    panel = _win([(PERSON, 300), (CHANNEL, 200), (GROUP, 100)]).conversations_panel
    win = _Window(panel)
    win.settings = {"user_interface": {"show_channels_in_chat_list": show_channels}}
    win._lid_to_phone, win._phone_to_lid = {}, {}
    win._deleted_chats, win._archived_chats, win.locked = set(), set(), set()
    win.i18n = SimpleNamespace(t=lambda key: key)
    win.background_mode = True
    for jid, chat in win.chats.items():
        chat["pushName"] = f"Name {jid.split('@')[0]}"
        chat["remoteJid"] = jid
    main, _names, *_rest = win._compute_chat_lists()
    return [chat["remoteJid"] for chat in main]


def test_a_channel_already_stored_is_hidden_from_the_conversation_list_by_default():
    assert CHANNEL not in listed(False) and PERSON in listed(False)


def test_ticking_the_option_shows_the_channels_again():
    assert CHANNEL in listed(True)
