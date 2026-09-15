"""A WhatsApp Web store that holds LESS than we do must not rewrite local state.

Both halves come from one live incident (2026-09-15):

1. An open group lost 199 messages, then 50 more. WhatsApp Web had unloaded
   the chat down to one or two messages; a new one arrived, get-messages
   returned it, and _reconcile_active_conversation_with_remote() mirrored every
   stored message older than it as a phone-side deletion. Minutes later the
   browser profile was restored from a snapshot a day old, so neither side had
   those messages any more.
2. After the restore, the unread counts went back near zero. get_remote_chats()
   copied every chat's rolled-back `t` over the local one; on the next round
   reconcile_snapshot_unread() saw the snapshot as current and took its counts —
   from a snapshot taken after an accidental mark-all-as-read.
"""

import time

import pytest
import wx

from core.incremental_sync import chat_activity_floor
from core.remote_reconcile import deletions_within_remote_window, remote_window_oldest
from main import MainWindow
from tests.test_get_remote_chats_persistence import _chat, _make, post  # noqa: F401 (fixture)

GROUP = "120363409931936700@g.us"


def _msg(mid, ts, **extra):
    record = {
        "key": {"id": mid, "fromMe": False, "remoteJid": GROUP},
        "message": {"conversation": "oi"},
        "messageType": "conversation",
        "messageTimestamp": ts,
    }
    record.update(extra)
    return record


# ── the pure rules ──────────────────────────────────────────────────────────


class TestRemoteWindow:
    def test_oldest_is_the_earliest_timestamp_returned(self):
        assert remote_window_oldest([_msg("a", 300), _msg("b", 100), _msg("c", 200)]) == 100

    def test_milliseconds_are_read_as_seconds(self):
        assert remote_window_oldest([_msg("a", 1_700_000_000_123)]) == 1_700_000_000

    def test_no_timestamps_means_no_window(self):
        assert remote_window_oldest([{"key": {"id": "a"}}]) == 0
        assert remote_window_oldest([]) == 0


class TestDeletionsWithinRemoteWindow:
    def test_a_message_inside_the_window_and_absent_is_deleted(self):
        local = [_msg("old", 100), _msg("gone", 250), _msg("kept", 300)]
        assert deletions_within_remote_window(local, {"kept"}, 200) == {"gone"}

    def test_a_message_older_than_the_window_is_never_judged(self):
        """The incident: the store held only the newest message, and every
        older stored message looked deleted."""
        local = [_msg(str(i), 1000 + i) for i in range(199)] + [_msg("new", 5000)]
        assert deletions_within_remote_window(local, {"new"}, 5000) == set()

    def test_an_empty_answer_proves_nothing_here(self):
        assert deletions_within_remote_window([_msg("a", 100)], set(), 0) == set()

    def test_an_answer_without_timestamps_proves_nothing(self):
        assert deletions_within_remote_window([_msg("a", 100)], {"b"}, 0) == set()

    def test_siblings_cut_off_in_the_oldest_second_are_not_judged(self):
        """An album: five messages in one second, the count cut keeps two.
        The three left out share the oldest timestamp and are only not loaded."""
        local = [_msg(f"p{i}", 1000) for i in range(5)] + [_msg("n", 1001)]
        assert deletions_within_remote_window(local, {"p3", "p4", "n"}, 1000) == set()

    def test_a_message_in_the_oldest_second_is_not_judged_even_if_really_gone(self):
        """The price of the rule above, accepted: cosmetic, never destructive."""
        local = [_msg("same-second", 1000), _msg("kept", 1000), _msg("n", 1001)]
        assert deletions_within_remote_window(local, {"kept", "n"}, 1000) == set()


class TestActivityFloor:
    def test_the_newest_countable_message_sets_the_floor(self):
        chat = {"messages": {"messages": {"records": [_msg("a", 100), _msg("b", 400)]}}}
        assert chat_activity_floor(chat, lambda m: True) == 400

    def test_a_non_countable_record_cannot_raise_it(self):
        chat = {"messages": {"messages": {"records": [
            _msg("a", 100), _msg("join", 900, messageType="groupNotification")]}}}
        assert chat_activity_floor(chat, lambda m: m.get("messageType") != "groupNotification") == 100

    def test_no_records_means_no_floor(self):
        assert chat_activity_floor({}, lambda m: True) == 0

    def test_a_filter_that_raises_counts_as_not_countable(self):
        def boom(_m):
            raise RuntimeError("boom")
        chat = {"messages": {"messages": {"records": [_msg("a", 100)]}}}
        assert chat_activity_floor(chat, boom) == 0

    def test_a_message_still_pending_locally_is_ignored(self):
        chat = {"messages": {"messages": {"records": [
            _msg("sent", 100), _msg("pending", 900, _local_pending=True)]}}}
        assert chat_activity_floor(chat, lambda m: True) == 100

    def test_a_message_stamped_in_the_future_is_ignored(self):
        """Skipped, not clamped to now: a clamped floor would climb with the
        clock every round and read as new activity each time."""
        chat = {"messages": {"messages": {"records": [
            _msg("past", 3000), _msg("future", 5000)]}}}
        assert chat_activity_floor(chat, lambda m: True, now=4000) == 3000

    def test_the_floor_is_stable_across_rounds_while_the_clock_is_ahead(self):
        chat = {"messages": {"messages": {"records": [
            _msg("past", 3000), _msg("future", 5000)]}}}
        floors = {chat_activity_floor(chat, lambda m: True, now=now) for now in (4000, 4060, 4120)}
        assert floors == {3000}


# ── the reconcile, end to end ───────────────────────────────────────────────


class _Panel:
    def __init__(self, jid):
        self.conversation = {"remoteJid": jid}
        self.removed = None
        self.populate_called = False

    def remove_messages_by_id(self, ids, focus_previous=False):
        self.removed = set(ids)

    def populate_messages(self):
        self.populate_called = True


class _ReconcileStub:
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _reconcile_active_conversation_with_remote = MainWindow._reconcile_active_conversation_with_remote
    _mirror_remote_clear = MainWindow._mirror_remote_clear
    _mirror_remote_deletions = MainWindow._mirror_remote_deletions
    _REMOTE_CLEAR_CONFIRM_STRIKES = MainWindow._REMOTE_CLEAR_CONFIRM_STRIKES

    def __init__(self, records, remote):
        self.chats = {GROUP: {"remoteJid": GROUP, "messages": {"messages": {"records": records}}}}
        self.conversations_panel = _Panel(GROUP)
        self.messages_set_completed = True
        self.settings = {}
        self._remote = remote
        self.clear_calls = []

    def _fetch_remote_message_window(self, remote_jid):
        return self._remote

    def clear_chat_messages_local(self, jid, record_cutoff=True):
        self.clear_calls.append(jid)

    def _schedule_set_chats(self):
        pass


@pytest.fixture(autouse=True)
def _sync_call_after(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


def _old_history(n=200):
    base = int(time.time()) - 86_400
    return [_msg(f"m{i}", base + i) for i in range(n)]


class TestAShrunkenWindowIsNotADeletion:
    def test_the_incident_deletes_nothing(self):
        """Store holds only a message newer than all local history."""
        new_ts = int(time.time()) - 600
        stub = _ReconcileStub(_old_history(), ({"brand-new"}, new_ts))

        stub._reconcile_active_conversation_with_remote()

        assert stub.conversations_panel.removed is None
        assert stub.clear_calls == []

    def test_it_is_not_counted_as_a_clear_either(self):
        """A non-empty answer sharing no id with local history used to count
        as a clear strike; three polls of it wiped the conversation."""
        new_ts = int(time.time()) - 600
        stub = _ReconcileStub(_old_history(), ({"brand-new"}, new_ts))

        for _ in range(MainWindow._REMOTE_CLEAR_CONFIRM_STRIKES + 1):
            stub._reconcile_active_conversation_with_remote()

        assert stub.clear_calls == []
        assert stub.conversations_panel.removed is None

    def test_a_mass_apparent_deletion_is_not_mirrored(self):
        """A stray old message in the answer pulls its oldest timestamp back
        and everything after it looks deleted. Past the cap, nothing goes."""
        history = _old_history(40)
        kept = {r["key"]["id"] for r in history[:2]} | {r["key"]["id"] for r in history[-2:]}
        stub = _ReconcileStub(history, (kept, history[0]["messageTimestamp"]))

        stub._reconcile_active_conversation_with_remote()

        assert stub.conversations_panel.removed is None

    def test_a_deletion_at_the_cap_is_still_mirrored(self):
        from core.remote_reconcile import MAX_MIRRORED_DELETIONS
        history = _old_history(30)
        gone = {r["key"]["id"] for r in history[5:5 + MAX_MIRRORED_DELETIONS]}
        remote_ids = {r["key"]["id"] for r in history} - gone
        stub = _ReconcileStub(history, (remote_ids, history[0]["messageTimestamp"]))

        stub._reconcile_active_conversation_with_remote()

        assert stub.conversations_panel.removed == gone

    def test_a_real_deletion_inside_the_window_is_still_mirrored(self):
        history = _old_history(10)
        remote_ids = {r["key"]["id"] for r in history} - {"m7"}
        oldest = history[0]["messageTimestamp"]
        stub = _ReconcileStub(history, (remote_ids, oldest))

        stub._reconcile_active_conversation_with_remote()

        assert stub.conversations_panel.removed == {"m7"}

    def test_a_partially_loaded_window_only_judges_what_it_covers(self):
        history = _old_history(10)
        covered = history[6:]                      # store holds m6..m9 only
        remote_ids = {r["key"]["id"] for r in covered} - {"m8"}
        stub = _ReconcileStub(history, (remote_ids, covered[0]["messageTimestamp"]))

        stub._reconcile_active_conversation_with_remote()

        assert stub.conversations_panel.removed == {"m8"}

    def test_an_empty_answer_still_mirrors_a_clear_after_the_strikes(self):
        stub = _ReconcileStub(_old_history(5), (set(), 0))

        for _ in range(MainWindow._REMOTE_CLEAR_CONFIRM_STRIKES):
            stub._reconcile_active_conversation_with_remote()

        assert stub.clear_calls == [GROUP]


# ── the chat-list merge ─────────────────────────────────────────────────────


JID = "5511900000001@s.whatsapp.net"


def _cached(t, unread, records):
    return {JID: {"remoteJid": JID, "t": t, "unreadCount": unread,
                  "messages": {"messages": {"records": records}}}}


def _record(ts):
    return {"key": {"id": f"id{ts}", "fromMe": False, "remoteJid": JID},
            "message": {"conversation": "oi"}, "messageType": "conversation",
            "messageTimestamp": ts}


class TestARolledBackSnapshotCannotRewindTheList:
    def test_t_is_not_lowered_below_a_message_we_hold(self, post):
        cached = _cached(1_700_000_500, 4, [_record(1_700_000_500)])
        post["payload"] = [_chat("5511900000001@c.us", t=1_700_000_000, unreadCount=0)]

        result = _make(cached).get_remote_chats(dict(cached), persist_full=False, notify_errors=False)

        assert result[JID]["t"] == 1_700_000_500

    def test_the_unread_count_survives_the_second_round(self, post):
        """The incident chain: round one used to rewind `t`, round two then
        accepted the snapshot's near-zero count."""
        cached = _cached(1_700_000_500, 4, [_record(1_700_000_500)])
        post["payload"] = [_chat("5511900000001@c.us", t=1_700_000_000, unreadCount=0)]
        stub = _make(cached)

        first = stub.get_remote_chats(dict(cached), persist_full=False, notify_errors=False)
        second = stub.get_remote_chats(dict(first), persist_full=False, notify_errors=False)

        assert second[JID]["unreadCount"] == 4
        assert second[JID]["t"] == 1_700_000_500

    def test_a_newer_snapshot_still_moves_t_forward(self, post):
        cached = _cached(1_700_000_500, 0, [_record(1_700_000_500)])
        post["payload"] = [_chat("5511900000001@c.us", t=1_700_000_900, unreadCount=1)]

        result = _make(cached).get_remote_chats(dict(cached), persist_full=False, notify_errors=False)

        assert result[JID]["t"] == 1_700_000_900
        assert result[JID]["unreadCount"] == 1

    def test_a_chat_with_no_stored_messages_behaves_as_before(self, post):
        cached = _cached(1_700_000_500, 0, [])
        post["payload"] = [_chat("5511900000001@c.us", t=1_700_000_000, unreadCount=0)]

        result = _make(cached).get_remote_chats(dict(cached), persist_full=False, notify_errors=False)

        assert result[JID]["t"] == 1_700_000_000
