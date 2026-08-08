"""Regression test: renaming a WhatsApp group was never picked up locally.

WPPConnect/Baileys already delivers a "gp2" system message for a group
subject change (messageType "groupNotification", subtype "subject", the new
name in "body" — see WebSocketClient's gp2 handling and its rendering in
ui/conversations.py's group-notification text). That message already showed
up correctly *inside* the conversation ("Fulano mudou o nome do grupo para
X"), but nothing ever updated chat["name"] itself, so the chat list, window
title and tray tooltip kept showing the old name until the next full sync —
which could re-fetch stale group-info and never happen for a quiet group.

MainWindow._apply_group_subject_change() applies the new name from the same
event immediately. Tested as a plain function bound to a stub, per the
project's convention for MainWindow (a wx.Frame) — see
tests/test_reported_bugfixes.py.
"""

from main import MainWindow


class _MainWindowStub:
    _apply_group_subject_change = MainWindow._apply_group_subject_change


def _subject_change_msg(new_name: str, subtype: str = "subject"):
    return {
        "messageType": "groupNotification",
        "message": {
            "groupNotification": {
                "subtype": subtype,
                "body": new_name,
            }
        },
    }


def test_group_subject_change_renames_existing_chat():
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}

    mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg("Grupo Novo"))

    assert chat["name"] == "Grupo Novo"
    assert mw._group_name_cache["123@g.us"] == "Grupo Novo"


def test_non_group_jid_is_ignored():
    mw = _MainWindowStub()
    chat = {"remoteJid": "5511999@s.whatsapp.net", "name": "Contato"}

    mw._apply_group_subject_change(
        "5511999@s.whatsapp.net", chat, _subject_change_msg("Não deveria aplicar")
    )

    assert chat["name"] == "Contato"


def test_other_group_notification_subtypes_are_ignored():
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo"}

    mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg("Nova Foto", subtype="picture"))

    assert chat["name"] == "Grupo"


def test_regular_message_is_ignored():
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo"}
    msg = {"messageType": "conversation", "message": {"conversation": "oi"}}

    mw._apply_group_subject_change("123@g.us", chat, msg)

    assert chat["name"] == "Grupo"


def test_empty_body_does_not_blank_out_existing_name():
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo"}

    mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg(""))

    assert chat["name"] == "Grupo"
