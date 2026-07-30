"""Tests for mirroring phone-side changes (clears, message deletions) back
into WinZapp, and the shared message-removal/focus-restore helper.

Context: WPPConnect's list-chats has no per-message data (msgs:null), so the
only way to notice a conversation was cleared or a message deleted on the
phone is to diff a get-messages fetch against what's stored locally — which
is only ever done for the conversation the user has open right now (see the
cost-vs-benefit comment on MainWindow._reconcile_active_conversation_with_remote).

MainWindow is a wx.Frame and ConversationsPanel a wx.Panel; neither can be
instantiated without a running wx.App, so both are exercised as plain
functions bound onto small stubs — same approach as
tests/test_sender_names.py and tests/test_message_bookmarks.py.
"""

import pytest

import wx
from main import MainWindow
from ui.conversations import ConversationsPanel


# ── ConversationsPanel.remove_messages_by_id ────────────────────────────────


class _FakeMessagesList:
    def __init__(self):
        self.deleted_indices = []
        self.focus_calls = []
        self.selected_calls = []
        self.ensure_visible_calls = []
        self._count = 0

    def DeleteItem(self, idx):
        self.deleted_indices.append(idx)
        self._count -= 1

    def GetItemCount(self):
        return self._count

    def Focus(self, idx):
        self.focus_calls.append(idx)

    def Select(self, idx, on=True):
        self.selected_calls.append((idx, on))

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)


class _FakeDB:
    def __init__(self):
        self.deleted = []

    def delete_message(self, jid, msg_id):
        self.deleted.append((jid, msg_id))


class _FakeMainWindowForRemoval:
    def __init__(self, db):
        self.db = db
        self.recompute_calls = []

    def _recompute_chat_last_message(self, jid):
        self.recompute_calls.append(jid)

    def _schedule_set_chats(self):
        pass


def _msg(msg_id):
    return {"key": {"id": msg_id, "fromMe": False}, "message": {"conversation": "x"},
            "messageType": "conversation"}


class _RemovalStub:
    """Minimal stand-in for ConversationsPanel, just for remove_messages_by_id."""

    remove_messages_by_id = ConversationsPanel.remove_messages_by_id

    def __init__(self, sorted_messages, conversation=None):
        self._sorted_messages = list(sorted_messages)
        self._all_sorted_messages = list(sorted_messages)
        self._messages_offset = 0
        self._unread_sep_idx = -1
        self.messages_list = _FakeMessagesList()
        self.messages_list._count = len(sorted_messages)
        self.db = _FakeDB()
        self.main_window = _FakeMainWindowForRemoval(self.db)
        self.conversation = conversation


class TestRemoveMessagesById:
    def test_removes_single_message_and_focuses_previous(self):
        panel = _RemovalStub(
            [_msg("A"), _msg("B"), _msg("C")],
            conversation={"remoteJid": "j@g.us", "messages": {"messages": {
                "records": [_msg("A"), _msg("B"), _msg("C")]}}},
        )

        panel.remove_messages_by_id({"B"}, focus_previous=True)

        assert [m["key"]["id"] for m in panel._sorted_messages] == ["A", "C"]
        assert panel.messages_list.deleted_indices == [1]
        assert panel.messages_list.focus_calls == [0]  # index before the removed row
        assert panel.messages_list.selected_calls == [(0, True)]
        assert panel.messages_list.ensure_visible_calls == [0]
        assert panel.db.deleted == [("j@g.us", "B")]
        remaining_ids = [m["key"]["id"] for m in panel.conversation["messages"]["messages"]["records"]]
        assert remaining_ids == ["A", "C"]

    def test_removing_first_row_focuses_row_zero(self):
        panel = _RemovalStub([_msg("A"), _msg("B")])

        panel.remove_messages_by_id({"A"}, focus_previous=True)

        assert panel.messages_list.focus_calls == [0]

    def test_removing_last_remaining_row_does_not_call_focus(self):
        panel = _RemovalStub([_msg("A")])

        panel.remove_messages_by_id({"A"}, focus_previous=True)

        assert panel.messages_list.focus_calls == []  # nothing left to focus

    def test_batch_removal_of_several_messages(self):
        records = [_msg("A"), _msg("B"), _msg("C"), _msg("D")]
        panel = _RemovalStub(
            records,
            conversation={"remoteJid": "j@g.us", "messages": {"messages": {"records": list(records)}}},
        )

        panel.remove_messages_by_id({"B", "D"}, focus_previous=True)

        assert [m["key"]["id"] for m in panel._sorted_messages] == ["A", "C"]
        # Deleted in descending index order so earlier indices stay valid.
        assert panel.messages_list.deleted_indices == [3, 1]
        assert set(panel.db.deleted) == {("j@g.us", "B"), ("j@g.us", "D")}

    def test_focus_previous_false_does_not_touch_list_focus(self):
        panel = _RemovalStub([_msg("A"), _msg("B")])

        panel.remove_messages_by_id({"A"}, focus_previous=False)

        assert panel.messages_list.focus_calls == []
        assert panel.messages_list.selected_calls == []

    def test_unread_separator_index_shifts_with_removal_above_it(self):
        panel = _RemovalStub([_msg("A"), _msg("B"), _msg("C")])
        panel._unread_sep_idx = 2

        panel.remove_messages_by_id({"A"}, focus_previous=False)

        assert panel._unread_sep_idx == 1

    def test_empty_id_set_is_a_no_op(self):
        panel = _RemovalStub([_msg("A")])

        panel.remove_messages_by_id(set(), focus_previous=True)

        assert panel.messages_list.deleted_indices == []

    def test_unknown_id_is_a_no_op(self):
        panel = _RemovalStub([_msg("A")])

        panel.remove_messages_by_id({"does-not-exist"}, focus_previous=True)

        assert panel.messages_list.deleted_indices == []


# ── MainWindow._reconcile_active_conversation_with_remote ──────────────────


class _FakeConversationsPanel:
    def __init__(self, remote_jid=None):
        self.conversation = {"remoteJid": remote_jid} if remote_jid else None
        self.removed = None
        self.populate_called = False

    def remove_messages_by_id(self, ids, focus_previous=False):
        self.removed = (set(ids), focus_previous)

    def populate_messages(self):
        self.populate_called = True


def _chat_with_records(*ids):
    return {
        "remoteJid": "j@s.whatsapp.net",
        "messages": {"messages": {"records": [_msg(i) for i in ids]}},
    }


class _ReconcileStub:
    """Minimal stand-in for MainWindow, exercising the reconcile/mirror
    methods as plain functions (no HTTP, no wx event loop)."""

    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _reconcile_active_conversation_with_remote = MainWindow._reconcile_active_conversation_with_remote
    _mirror_remote_clear = MainWindow._mirror_remote_clear
    _mirror_remote_deletions = MainWindow._mirror_remote_deletions

    def __init__(self, chats, conversations_panel, remote_ids, messages_set_completed=True):
        self.chats = chats
        self.conversations_panel = conversations_panel
        self.messages_set_completed = messages_set_completed
        self._remote_ids = remote_ids
        self.clear_calls = []
        self._schedule_set_chats_calls = 0

    # Stubbed instead of hitting the network.
    def _fetch_remote_message_ids(self, remote_jid):
        return self._remote_ids

    def clear_chat_messages_local(self, jid, record_cutoff=True):
        self.clear_calls.append((jid, record_cutoff))
        self.chats[jid]["messages"]["messages"]["records"] = []

    def _schedule_set_chats(self):
        self._schedule_set_chats_calls += 1


@pytest.fixture(autouse=True)
def _synchronous_call_after(monkeypatch):
    """Run wx.CallAfter(fn, *args) immediately instead of queuing it onto a
    (nonexistent, in these tests) wx event loop."""
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


class TestReconcileActiveConversation:
    def test_no_open_conversation_does_nothing(self):
        stub = _ReconcileStub(
            chats={}, conversations_panel=_FakeConversationsPanel(), remote_ids=set()
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == []

    def test_short_conversation_is_never_diffed(self):
        """Fewer than 2 local messages: too little history to trust a diff."""
        jid = "j@s.whatsapp.net"
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A")},
            conversations_panel=_FakeConversationsPanel(jid),
            remote_ids=set(),  # would look like "everything deleted" if trusted
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == []
        assert stub.conversations_panel.removed is None

    def test_fetch_failure_never_triggers_a_mirror(self):
        jid = "j@s.whatsapp.net"
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A", "B", "C")},
            conversations_panel=_FakeConversationsPanel(jid),
            remote_ids=None,  # simulates a failed/ambiguous fetch
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == []
        assert stub.conversations_panel.removed is None

    def test_all_messages_gone_mirrors_a_clear(self):
        jid = "j@s.whatsapp.net"
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A", "B", "C")},
            conversations_panel=_FakeConversationsPanel(jid),
            remote_ids=set(),
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == [(jid, False)]  # record_cutoff=False: mirroring, not a new cutoff
        assert stub.conversations_panel.populate_called is True
        assert stub._schedule_set_chats_calls == 1

    def test_some_messages_gone_mirrors_individual_deletions(self):
        jid = "j@s.whatsapp.net"
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A", "B", "C")},
            conversations_panel=_FakeConversationsPanel(jid),
            remote_ids={"A", "C"},  # "B" was deleted on the phone
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == []
        assert stub.conversations_panel.removed == ({"B"}, True)

    def test_nothing_missing_is_a_no_op(self):
        jid = "j@s.whatsapp.net"
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A", "B", "C")},
            conversations_panel=_FakeConversationsPanel(jid),
            remote_ids={"A", "B", "C", "D"},  # server even has a newer message
        )
        stub._reconcile_active_conversation_with_remote()
        assert stub.clear_calls == []
        assert stub.conversations_panel.removed is None

    def test_conversation_switched_away_before_callback_runs_is_ignored(self):
        """The CallAfter for the mirror can land after the user has already
        navigated to a different conversation — must not mutate the wrong one."""
        jid = "j@s.whatsapp.net"
        panel = _FakeConversationsPanel(jid)
        stub = _ReconcileStub(
            chats={jid: _chat_with_records("A", "B", "C")},
            conversations_panel=panel,
            remote_ids=set(),
        )
        # Simulate the user switching conversations between the background
        # fetch and the CallAfter actually running.
        panel.conversation = {"remoteJid": "someone-else@s.whatsapp.net"}

        stub._mirror_remote_clear(jid)

        assert stub.clear_calls == []
