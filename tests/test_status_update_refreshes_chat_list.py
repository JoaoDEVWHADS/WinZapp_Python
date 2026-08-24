"""A delivery-status change must repaint the conversations list.

The chat list's preview line ends with the last message's delivery status —
_last_msg_preview() appends ConversationsPanel._map_status(last) to it. When an
ack arrives, on_message_status_update() records it on the message and refreshes
the open conversation's own row, but it never told the conversations list to
repaint. So a sent message sat on "Pendente" in the list until some unrelated
event (another message landing anywhere, a sync) happened to trigger
set_chats(). Reported live: a chat still reading "Eu: . 21:07 Pendente" a
couple of seconds after the message had visibly been sent.

MainWindow is a wx.Frame and can't be instantiated without a running wx.App, so
the method is bound onto a stub carrying only what it touches — same approach
as the rest of this suite.
"""

import pytest

from main import MainWindow


class _FakePanel:
    def __init__(self):
        self.refreshed = []

    def refresh_message_status(self, msg_id, status):
        self.refreshed.append((msg_id, status))


class _FakeDB:
    def __init__(self):
        self.written = []

    def insert_message(self, jid, msg):
        self.written.append((jid, msg.get("key", {}).get("id")))


class _Win:
    on_message_status_update = MainWindow.on_message_status_update

    def __init__(self, show_status=True):
        self.chats = {}
        self.db = _FakeDB()
        self.conversations_panel = _FakePanel()
        self.settings = {
            "user_interface": {"show_delivery_status_in_chat_list": show_status}
        }
        self.scheduled = 0

    def _normalize_jid(self, jid):
        return jid

    def _schedule_set_chats(self):
        self.scheduled += 1


JID = "grupo@g.us"


def _win_with_message(msg_id="m1", show_status=True):
    win = _Win(show_status=show_status)
    win.chats[JID] = {
        "messages": {"messages": {"records": [
            {"key": {"id": msg_id, "remoteJid": JID, "fromMe": True},
             "messageType": "conversation",
             "message": {"conversation": "oi"}},
        ]}}
    }
    return win


def _ack(msg_id="m1", status=2):
    return {"key": {"id": msg_id, "remoteJid": JID, "fromMe": True},
            "update": {"status": status}}


def test_an_ack_schedules_a_chat_list_repaint():
    """The exact bug: the preview kept saying "Pendente" because nothing ever
    asked the list to repaint."""
    win = _win_with_message()
    win.on_message_status_update(_ack())
    assert win.scheduled == 1


def test_the_status_still_reaches_the_open_conversation():
    """The pre-existing refresh must not be traded away for the new one."""
    win = _win_with_message()
    win.on_message_status_update(_ack(status=3))
    assert win.conversations_panel.refreshed == [("m1", "3")]


def test_the_status_is_recorded_on_the_message():
    win = _win_with_message()
    win.on_message_status_update(_ack(status=2))
    record = win.chats[JID]["messages"]["messages"]["records"][0]
    assert [u["status"] for u in record["MessageUpdate"]] == ["2"]


def test_every_ack_of_a_burst_schedules_it():
    """pending -> sent -> delivered -> read all change the preview text.
    _schedule_set_chats() is what coalesces the burst; this method's job is
    only to keep asking."""
    win = _win_with_message()
    for status in (1, 2, 3, 4):
        win.on_message_status_update(_ack(status=status))
    assert win.scheduled == 4


def test_no_repaint_when_the_preview_does_not_show_status():
    """Turning the setting off must turn the work off too."""
    win = _win_with_message(show_status=False)
    win.on_message_status_update(_ack())
    assert win.scheduled == 0
    # The open conversation's row still refreshes — that row shows the status
    # regardless of this chat-list-only setting.
    assert win.conversations_panel.refreshed == [("m1", "2")]


def test_an_ack_for_an_unknown_message_schedules_nothing():
    """No message was updated, so no preview can have changed."""
    win = _win_with_message()
    win.on_message_status_update(_ack(msg_id="does-not-exist"))
    assert win.scheduled == 0


def test_an_ack_with_no_status_is_ignored_entirely():
    win = _win_with_message()
    win.on_message_status_update({"key": {"id": "m1", "fromMe": True}, "update": {}})
    assert win.scheduled == 0
    assert win.conversations_panel.refreshed == []


def test_a_missing_setting_defaults_to_repainting():
    """Installs whose settings.json predates the option still get the fix."""
    win = _win_with_message()
    win.settings = {"user_interface": {}}
    win.on_message_status_update(_ack())
    assert win.scheduled == 1
