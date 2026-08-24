"""Regression test: the first message from a contact whose @lid wasn't cached
yet disappeared the moment the conversation was opened.

Reported from a user's log: a message arrived from a long-quiet contact, the
chat list showed its preview, and opening the conversation showed "no
messages" — and the message was gone from the database for good.

What happened. A live message arrives with remoteJid=<something>@lid. When
that @lid isn't in _lid_to_phone yet, on_new_message() keeps the raw @lid as
the chat JID (it resolves the phone number in the background, via
/contact/pn-lid) and files the message under it. Once the answer comes back,
_merge_lid_into_phone() merges the two chats — in memory correctly, but for
the database it called db.delete_chat(lid_jid), which deletes that chat's
message rows outright instead of moving them.

That left the message nowhere the app would ever look again:
navigate_to_conversation() reloads a conversation's messages straight from the
database by JID, and get_messages()'s _jid_variants() knows
@c.us <-> @s.whatsapp.net but nothing about @lid. The chat-list preview still
looked right because it reads the merged in-memory records — and opening the
conversation overwrote exactly those records with the empty DB read.

The fix uses db.merge_or_rename_chat(), the same operation deduplicate_chats()
already uses on the sync path (moves every row it safely can, and only deletes
an old_jid row once an equivalent survives under new_jid), and waits for any
message insert still in flight for that @lid before moving the chat.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is bound to a small stub — same approach as
tests/test_group_admin_restriction.py.
"""

import inspect

import pytest

import main
from main import MainWindow


class _FakeDB:
    def __init__(self):
        self.merge_calls = []
        self.deleted = []
        self.events = []

    def merge_or_rename_chat(self, old_jid, new_jid):
        self.merge_calls.append((old_jid, new_jid))
        self.events.append("merge")

    def delete_chat(self, jid):
        self.deleted.append(jid)
        self.events.append("delete")


class _FakeFuture:
    """Stand-in for the insert Future _msg_bg_executor hands back."""

    def __init__(self, events, raises=None):
        self._events = events
        self._raises = raises
        self.waited_with = None

    def result(self, timeout=None):
        self.waited_with = timeout
        if self._raises is not None:
            raise self._raises
        self._events.append("insert")


class _SyncThread:
    """threading.Thread stand-in that runs the target on .start()."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _Stub:
    _merge_lid_into_phone = MainWindow._merge_lid_into_phone

    def __init__(self, chats=None):
        self.chats = chats if chats is not None else {}
        self.db = _FakeDB()
        self._pending_lid_inserts = {}


def _chat(jid, msg_ids=()):
    return {
        "remoteJid": jid,
        "messages": {"messages": {"records": [
            {"key": {"id": mid, "remoteJid": jid}, "messageTimestamp": i}
            for i, mid in enumerate(msg_ids)
        ]}},
    }


def _records(chat):
    return chat["messages"]["messages"]["records"]


@pytest.fixture(autouse=True)
def _synchronous_threads(monkeypatch):
    monkeypatch.setattr(main.threading, "Thread", _SyncThread)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


LID = "11111111111111@lid"
PHONE = "999999999999@s.whatsapp.net"


class TestDatabaseSideOfTheMerge:
    def test_messages_are_moved_to_the_phone_jid_not_deleted(self):
        stub = _Stub({LID: _chat(LID, ["m1"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.merge_calls == [(LID, PHONE)]
        assert stub.db.deleted == [], (
            "delete_chat() drops the @lid chat's message rows — the message "
            "has to be moved to the phone JID, which is the only one "
            "navigate_to_conversation() will ever query again"
        )

    def test_merge_runs_for_the_both_chats_exist_case_too(self):
        stub = _Stub({LID: _chat(LID, ["m1"]), PHONE: _chat(PHONE, ["m0"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.merge_calls == [(LID, PHONE)]

    def test_nothing_touches_the_database_when_there_is_no_lid_chat(self):
        stub = _Stub({PHONE: _chat(PHONE)})

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.merge_calls == []
        assert stub.db.deleted == []


class TestWaitsForAnInsertStillInFlight:
    def test_the_pending_insert_lands_before_the_chat_is_moved(self):
        """on_new_message() hands the insert to a pool thread. Renaming the
        chat first would file that message under a JID nothing queries."""
        stub = _Stub({LID: _chat(LID, ["m1"])})
        fut = _FakeFuture(stub.db.events)
        stub._pending_lid_inserts[LID] = fut

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.events == ["insert", "merge"]
        assert fut.waited_with, "the wait must be bounded, not indefinite"

    def test_an_insert_that_never_lands_does_not_block_the_merge(self):
        """A failed/timed-out insert is worth a warning, but skipping the
        merge would leave the chat split in the database indefinitely."""
        stub = _Stub({LID: _chat(LID, ["m1"])})
        stub._pending_lid_inserts[LID] = _FakeFuture(
            stub.db.events, raises=TimeoutError("still queued")
        )

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.merge_calls == [(LID, PHONE)]

    def test_the_tracked_future_is_dropped_so_the_dict_does_not_grow(self):
        stub = _Stub({LID: _chat(LID, ["m1"])})
        stub._pending_lid_inserts[LID] = _FakeFuture(stub.db.events)

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub._pending_lid_inserts == {}

    def test_no_pending_insert_merges_straight_away(self):
        stub = _Stub({LID: _chat(LID, ["m1"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.db.events == ["merge"]


class TestInMemoryMergeStillWorks:
    def test_lid_only_chat_is_renamed_keeping_its_records(self):
        stub = _Stub({LID: _chat(LID, ["m1", "m2"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert LID not in stub.chats
        assert stub.chats[PHONE]["remoteJid"] == PHONE
        assert [r["key"]["id"] for r in _records(stub.chats[PHONE])] == ["m1", "m2"]

    def test_records_from_both_chats_are_combined(self):
        stub = _Stub({LID: _chat(LID, ["from_lid"]), PHONE: _chat(PHONE, ["from_phone"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert LID not in stub.chats
        assert [r["key"]["id"] for r in _records(stub.chats[PHONE])] == [
            "from_phone", "from_lid",
        ]

    def test_a_message_present_under_both_jids_is_not_duplicated(self):
        stub = _Stub({LID: _chat(LID, ["shared"]), PHONE: _chat(PHONE, ["shared"])})

        stub._merge_lid_into_phone(LID, PHONE)

        assert [r["key"]["id"] for r in _records(stub.chats[PHONE])] == ["shared"]


class TestOpenConversationFollowsTheMerge:
    class _Panel:
        def __init__(self, jid):
            self.conversation = {"remoteJid": jid}
            self.refreshes = 0

        def refresh_messages_if_changed(self):
            self.refreshes += 1

    def test_the_open_lid_conversation_is_repointed_at_the_phone_chat(self):
        stub = _Stub({LID: _chat(LID, ["m1"])})
        stub.conversations_panel = self._Panel(LID)

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.conversations_panel.conversation is stub.chats[PHONE]
        assert stub.conversations_panel.refreshes == 1

    def test_the_open_phone_conversation_is_refreshed(self):
        stub = _Stub({LID: _chat(LID, ["m1"]), PHONE: _chat(PHONE)})
        stub.conversations_panel = self._Panel(PHONE)

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.conversations_panel.refreshes == 1

    def test_an_unrelated_open_conversation_is_left_alone(self):
        stub = _Stub({LID: _chat(LID, ["m1"])})
        stub.conversations_panel = self._Panel("outro@s.whatsapp.net")

        stub._merge_lid_into_phone(LID, PHONE)

        assert stub.conversations_panel.refreshes == 0


def test_on_new_message_tracks_the_insert_for_lid_chats():
    """The wait above only works if on_new_message actually registers the
    future. That method is ~400 lines of wx/JID handling that can't be driven
    end to end here, so this pins the registration structurally — same
    approach as tests/test_edit_message_refreshes_chat_list.py.
    """
    src = inspect.getsource(MainWindow.on_new_message)
    assert "_pending_lid_inserts[remote_jid]" in src, (
        "on_new_message must record the insert future for @lid chats, or "
        "_merge_lid_into_phone() has nothing to wait on"
    )
    assert 'remote_jid.endswith("@lid")' in src
