"""Regression test: renaming a WhatsApp group was never picked up locally.

WPPConnect/Baileys delivers a "gp2" system message for a group subject change
(messageType "groupNotification", subtype "subject", the new name in "body" —
see WebSocketClient's gp2 handling and its rendering in ui/conversations.py's
group-notification text). That message showed up correctly *inside* the
conversation, but nothing ever updated chat["name"] itself, so the chat list,
window title and tray tooltip kept showing the old name until the next full
sync — which could re-fetch stale group-info and never happen for a quiet
group. MainWindow._apply_group_subject_change() applies it immediately.

The catch found later, in the field: that "body" is not always filled in. The
notification arrives and renders, but with no new name in it — so this bailed
out empty-handed, the chat kept its old name, and the timeline row fell back
to the vaguer "X changed the group name" instead of naming it. /group-info
does know the new name (it is a live lookup, unlike the chat store list-chats
serialises), which is why the group-data dialog showed it correctly the whole
time. _resolve_subject_change_async() closes that gap and writes the resolved
name back into the notification body so the row upgrades itself too.

Tested as plain functions bound to a stub, per the project's convention for
MainWindow (a wx.Frame) — see tests/test_reported_bugfixes.py.
"""

import threading

import pytest

from main import MainWindow
from core.websocket_client import WebSocketClient


class _MainWindowStub:
    _apply_group_subject_change = MainWindow._apply_group_subject_change
    _resolve_subject_change_async = MainWindow._resolve_subject_change_async
    _store_group_subject = MainWindow._store_group_subject
    on_group_subject_updated = MainWindow.on_group_subject_updated
    _reconcile_group_info_name = MainWindow._reconcile_group_info_name

    def __init__(self, group_info_name=""):
        self._group_info_name = group_info_name
        self.group_info_calls = []
        self.saved = []
        self.set_chats_calls = 0
        self.chats = {}

    # Collaborators the methods under test reach for.
    def _fill_group_name(self, jid):
        self.group_info_calls.append(jid)
        return self._group_info_name

    def _schedule_save(self, dirty_jid=None):
        self.saved.append(dirty_jid)

    def _schedule_set_chats(self):
        self.set_chats_calls += 1


@pytest.fixture
def run_threads_inline(monkeypatch):
    """The group-info lookup blocks on HTTP so it runs on its own thread; run
    it inline to observe the result deterministically."""
    class _Inline:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(threading, "Thread", _Inline)


@pytest.fixture(autouse=True)
def no_wx_main_loop(monkeypatch):
    """wx.CallAfter needs a running app; the calls it defers here are all UI
    refreshes, so running them inline (and harmlessly failing on the stub's
    missing panel) is not what these tests are about — just record them."""
    import main as main_module
    monkeypatch.setattr(main_module.wx, "CallAfter", lambda fn, *a, **k: None)


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


class TestNotificationWithoutTheNewName:
    """The field case: the rename notification arrives carrying no name."""

    def test_the_live_funnel_resolves_it_from_group_info(self, run_threads_inline):
        mw = _MainWindowStub(group_info_name="Grupo Novo")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}

        mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg(""), live=True)

        assert mw.group_info_calls == ["123@g.us"]
        assert chat["name"] == "Grupo Novo"
        assert mw._group_name_cache["123@g.us"] == "Grupo Novo"

    def test_the_resolved_name_is_written_back_into_the_notification(self, run_threads_inline):
        """So the timeline row upgrades from "X changed the group name" to
        "... to Y" — the renderer prefers group_notif_subject_changed_to
        whenever a body is present, and the record keeps it across a reopen."""
        mw = _MainWindowStub(group_info_name="Grupo Novo")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}
        msg = _subject_change_msg("")

        mw._apply_group_subject_change("123@g.us", chat, msg, live=True)

        assert msg["message"]["groupNotification"]["body"] == "Grupo Novo"

    def test_history_backfill_does_not_spend_a_request(self, run_threads_inline):
        """One HTTP request per past rename, for names already superseded by
        the current one, buys nothing — the default is live=False."""
        mw = _MainWindowStub(group_info_name="Grupo Novo")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}

        mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg(""))

        assert mw.group_info_calls == []
        assert chat["name"] == "Grupo Antigo"

    def test_a_failed_lookup_changes_nothing(self, run_threads_inline):
        mw = _MainWindowStub(group_info_name="")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}
        msg = _subject_change_msg("")

        mw._apply_group_subject_change("123@g.us", chat, msg, live=True)

        assert chat["name"] == "Grupo Antigo"
        assert msg["message"]["groupNotification"]["body"] == ""
        assert mw.saved == []

    def test_a_lookup_confirming_the_current_name_still_fills_the_row(self, run_threads_inline):
        """Nothing to rename — the notification arrived after the name was
        already applied by another path — but the row still needs the name to
        say what it was changed to."""
        mw = _MainWindowStub(group_info_name="Grupo Novo")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Novo"}
        msg = _subject_change_msg("")

        mw._apply_group_subject_change("123@g.us", chat, msg, live=True)

        assert msg["message"]["groupNotification"]["body"] == "Grupo Novo"
        assert chat["name"] == "Grupo Novo"

    def test_a_body_that_is_present_never_costs_a_request(self, run_threads_inline):
        mw = _MainWindowStub(group_info_name="nao deveria ser consultado")
        chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}

        mw._apply_group_subject_change("123@g.us", chat, _subject_change_msg("Grupo Novo"), live=True)

        assert mw.group_info_calls == []
        assert chat["name"] == "Grupo Novo"


def test_groups_update_renames_and_persists_the_known_group():
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}
    mw.chats["123@g.us"] = chat

    mw.on_group_subject_updated("123@g.us", "Grupo Novo")

    assert chat["name"] == "Grupo Novo"
    assert mw.saved == ["123@g.us"]
    assert mw.set_chats_calls == 1


def test_group_info_name_is_fed_back_into_the_conversation_list(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.wx, "CallAfter", lambda fn, *args: fn(*args))
    mw = _MainWindowStub()
    chat = {"remoteJid": "123@g.us", "name": "Grupo Antigo"}
    mw.chats["123@g.us"] = chat

    mw._reconcile_group_info_name(
        "123@g.us", {"subject": "Grupo Novo", "name": "Grupo Antigo"}
    )

    assert chat["name"] == "Grupo Novo"
    assert mw._group_name_cache["123@g.us"] == "Grupo Novo"
    assert mw.saved == ["123@g.us"]
    assert mw.set_chats_calls == 1


class _GroupUpdateMain:
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self):
        self.updates = []

    def on_group_subject_updated(self, jid, subject):
        self.updates.append((jid, subject))


class _WebSocketStub:
    on_groups_update = WebSocketClient.on_groups_update
    _belongs_to_this_session = WebSocketClient._belongs_to_this_session
    _clean_jid = WebSocketClient._clean_jid

    def __init__(self):
        self.instance_name = "session"
        self.main_window = _GroupUpdateMain()


def test_groups_update_accepts_wid_ids_and_trims_the_subject(monkeypatch):
    import core.websocket_client as websocket_module

    monkeypatch.setattr(websocket_module.wx, "CallAfter", lambda fn, *args: fn(*args))
    ws = _WebSocketStub()

    ws.on_groups_update({
        "session": "session",
        "data": [{
            "id": {"_serialized": "123@g.us"},
            "subject": "  Grupo Novo  ",
        }],
    })

    assert ws.main_window.updates == [("123@g.us", "Grupo Novo")]


def test_node_emits_group_updates_from_subject_notifications():
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "client/api_patches/src/util/createSessionUtil.ts"
    ).read_text(encoding="utf-8")

    assert "message.type === 'gp2' && message.subtype === 'subject'" in source
    assert "req.io.emit('groups.update'" in source
    assert "await client.getChatById(groupId)" in source
