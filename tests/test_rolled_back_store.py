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
import types

import pytest
import wx

import main as main_module
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
    _deletions_before_remote_window = MainWindow._deletions_before_remote_window
    _mirror_remote_clear = MainWindow._mirror_remote_clear
    _mirror_remote_deletions = MainWindow._mirror_remote_deletions
    _REMOTE_CLEAR_CONFIRM_STRIKES = MainWindow._REMOTE_CLEAR_CONFIRM_STRIKES
    _REMOTE_BEFORE_PAGES = MainWindow._REMOTE_BEFORE_PAGES

    def __init__(self, records, remote, before=None):
        """*remote* is (ids, oldest ts) for the newest window, anchored at
        "anchor". *before* maps an anchor to the page before it, as returned
        by _page(); an anchor it does not know is a failed fetch."""
        self.chats = {GROUP: {"remoteJid": GROUP, "messages": {"messages": {"records": records}}}}
        self.conversations_panel = _Panel(GROUP)
        self.messages_set_completed = True
        self.settings = {}
        self._remote = remote
        self._before = before or {}
        self.before_calls = []
        self.clear_calls = []

    def _fetch_remote_message_window(self, remote_jid):
        ids, oldest = self._remote
        return set(ids), oldest, ("anchor" if ids else "")

    def _fetch_remote_messages_before(self, remote_jid, anchor_id):
        self.before_calls.append(anchor_id)
        return self._before.get(anchor_id)

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


STRIKES = MainWindow._REMOTE_CLEAR_CONFIRM_STRIKES


def _ids(records):
    return {r["key"]["id"] for r in records}


def _page(records):
    """What _fetch_remote_messages_before() answers for these records."""
    if not records:
        return set(), 0, ""
    oldest = min(records, key=lambda r: r["messageTimestamp"])
    return _ids(records), oldest["messageTimestamp"], "ser_" + oldest["key"]["id"]


def _poll(stub, times=1):
    for _ in range(times):
        stub._reconcile_active_conversation_with_remote()


class TestAShrunkenWindowIsNotADeletion:
    def test_older_messages_the_database_still_holds_are_kept(self):
        """The window held only a message newer than all local history (its
        own paging behind it stopped early); the older ones are still in
        WhatsApp Web's database, one anchored page away."""
        history = _old_history()
        stub = _ReconcileStub(history, ({"brand-new"}, int(time.time()) - 600),
                              before={"anchor": _page(history)})

        _poll(stub, STRIKES + 1)

        assert stub.conversations_panel.removed is None
        assert stub.clear_calls == []
        assert stub.before_calls[0] == "anchor"

    def test_it_is_not_counted_as_a_clear_either(self):
        """A non-empty answer sharing no id with local history used to count
        as a clear strike; three polls of it wiped the conversation."""
        history = _old_history()
        stub = _ReconcileStub(history, ({"brand-new"}, int(time.time()) - 600),
                              before={"anchor": _page(history)})

        _poll(stub, STRIKES + 1)

        assert stub.clear_calls == []

    def test_a_mass_apparent_deletion_waits_for_confirmation(self):
        """A stray old message in the answer pulls its oldest timestamp back
        and everything after it looks deleted. Past the cap it is not mirrored
        from one read — but it is mirrored once confirmed, since a bulk
        deletion on the phone has exactly this shape."""
        history = _old_history(40)
        kept = _ids(history[:2]) | _ids(history[-2:])
        stub = _ReconcileStub(history, (kept, history[0]["messageTimestamp"]))

        _poll(stub, STRIKES - 1)
        assert stub.conversations_panel.removed is None

        _poll(stub)
        assert stub.conversations_panel.removed == _ids(history[2:-2])

    def test_leaving_the_chat_does_not_lose_the_confirmation(self):
        history = _old_history(40)
        kept = _ids(history[:2]) | _ids(history[-2:])
        stub = _ReconcileStub(history, (kept, history[0]["messageTimestamp"]))

        _poll(stub, STRIKES - 1)
        stub.conversations_panel.conversation = {"remoteJid": "someone-else@g.us"}
        _poll(stub)
        stub.conversations_panel.conversation = {"remoteJid": GROUP}
        _poll(stub)

        assert stub.conversations_panel.removed == _ids(history[2:-2])

    def test_a_message_seen_again_is_never_mirrored(self):
        """A read that missed the messages, then one that found them: the run
        starts over, so a wobbling answer cannot confirm anything."""
        history = _old_history(40)
        kept = _ids(history[:2]) | _ids(history[-2:])
        stub = _ReconcileStub(history, (kept, history[0]["messageTimestamp"]))

        _poll(stub, STRIKES - 1)
        stub._remote = (_ids(history), history[0]["messageTimestamp"])
        _poll(stub)
        stub._remote = (kept, history[0]["messageTimestamp"])
        _poll(stub, STRIKES - 1)

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
        covered = history[6:]                      # window holds m6..m9 only
        remote_ids = _ids(covered) - {"m8"}
        stub = _ReconcileStub(history, (remote_ids, covered[0]["messageTimestamp"]),
                              before={"anchor": _page(history[:6])})

        _poll(stub, STRIKES + 1)

        assert stub.conversations_panel.removed == {"m8"}

    def test_an_empty_answer_still_mirrors_a_clear_after_the_strikes(self):
        stub = _ReconcileStub(_old_history(5), (set(), 0))

        _poll(stub, STRIKES)

        assert stub.clear_calls == [GROUP]


class TestOlderDeletionsStillArrive:
    """Everything v1.1.1.0 mirrored must still be mirrored."""

    def test_the_oldest_messages_of_a_short_chat(self):
        """Delete-for-me of the two first messages: WhatsApp Web now holds
        m2..m9 and nothing before them."""
        history = _old_history(10)
        stub = _ReconcileStub(history, (_ids(history[2:]), history[2]["messageTimestamp"]),
                              before={"anchor": _page([])})

        _poll(stub, STRIKES - 1)
        assert stub.conversations_panel.removed is None

        _poll(stub)
        assert stub.conversations_panel.removed == {"m0", "m1"}

    def test_a_clear_on_the_phone_with_new_messages_since(self):
        """Cleared while WinZapp was closed, then a message arrived: the window
        holds only that one, and nothing exists before it. More than the cap."""
        history = _old_history(30)
        stub = _ReconcileStub(history, ({"new"}, int(time.time()) - 600),
                              before={"anchor": _page([])})

        _poll(stub, STRIKES)

        assert stub.conversations_panel.removed == _ids(history)
        assert stub.clear_calls == []

    def test_a_deletion_found_further_back_across_pages(self):
        history = _old_history(30)
        stub = _ReconcileStub(
            history, (_ids(history[20:]), history[20]["messageTimestamp"]),
            before={
                "anchor": _page([r for r in history[10:20] if r["key"]["id"] != "m15"]),
                "ser_m10": _page(history[:10]),
            })

        _poll(stub, STRIKES)

        assert stub.conversations_panel.removed == {"m15"}
        assert stub.before_calls[:2] == ["anchor", "ser_m10"]

    def test_a_look_further_back_that_keeps_failing_still_mirrors(self):
        """As in v1.1.1.0, what cannot be found counts as missing — only
        confirmed, never from one read."""
        history = _old_history(10)
        stub = _ReconcileStub(history, (_ids(history[2:]), history[2]["messageTimestamp"]))

        _poll(stub, STRIKES - 1)
        assert stub.conversations_panel.removed is None

        _poll(stub)
        assert stub.conversations_panel.removed == {"m0", "m1"}

    def test_a_batch_pushed_out_of_the_slice_while_confirming_is_still_mirrored(self):
        """A busy chat: 11 messages deleted on the phone, and new ones keep
        arriving during the confirmation polls, pushing the deleted ones out of
        the last messages_page_size records."""
        history = _old_history(20)
        base = history[0]["messageTimestamp"]
        remote = {"m0"} | _ids(history[12:])
        stub = _ReconcileStub(history, (remote, base))
        stub.settings = {"user_interface": {"messages_page_size": 20}}

        for poll in range(STRIKES):
            _poll(stub)
            new = [_msg(f"n{poll}_{k}", base + 100 + poll * 10 + k) for k in range(5)]
            history.extend(new)
            remote |= _ids(new)
            stub._remote = (remote, base)

        assert stub.conversations_panel.removed == {f"m{i}" for i in range(1, 12)}

    def test_running_out_of_pages_still_mirrors_after_confirmation(self):
        history = _old_history(30)
        before = {"anchor": _page([history[28]])}
        before.update({f"ser_m{k}": _page([history[k - 1]]) for k in range(28, 1, -1)})
        stub = _ReconcileStub(history, ({"m29"}, history[29]["messageTimestamp"]), before=before)

        _poll(stub, STRIKES)

        assert len(stub.before_calls) == STRIKES * MainWindow._REMOTE_BEFORE_PAGES
        assert stub.conversations_panel.removed == {f"m{i}" for i in range(24)}

    def test_a_page_that_does_not_move_back_still_mirrors_after_confirmation(self):
        history = _old_history(10)
        stub = _ReconcileStub(
            history, (_ids(history[2:]), history[2]["messageTimestamp"]),
            before={"anchor": ({"m2"}, history[2]["messageTimestamp"], "anchor")})

        _poll(stub, STRIKES)

        assert stub.conversations_panel.removed == {"m0", "m1"}

    def test_a_direct_deletion_is_not_delayed_by_an_older_one(self):
        history = _old_history(10)
        window = [r for r in history[2:] if r["key"]["id"] != "m7"]
        stub = _ReconcileStub(history, (_ids(window), history[2]["messageTimestamp"]),
                              before={"anchor": _page([])})

        _poll(stub)

        assert stub.conversations_panel.removed == {"m7"}


class _FetchStub:
    _fetch_remote_message_window = MainWindow._fetch_remote_message_window
    _fetch_remote_messages_before = MainWindow._fetch_remote_messages_before

    def __init__(self, answer):
        self.answer = answer
        self.queries = []

    def _get_remote_messages(self, remote_jid, extra_query=""):
        self.queries.append(extra_query)
        return self.answer


def _raw_pair(mid, ts):
    return _msg(mid, ts), {"id": {"_serialized": f"false_{GROUP}_{mid}"}}


class TestTheFetches:
    def test_the_window_names_its_oldest_message_as_the_anchor(self):
        stub = _FetchStub(([_raw_pair("b", 200), _raw_pair("a", 100)], 2))
        assert stub._fetch_remote_message_window(GROUP) == ({"a", "b"}, 100, f"false_{GROUP}_a")

    def test_the_page_before_is_asked_with_the_encoded_anchor(self):
        stub = _FetchStub(([_raw_pair("a", 100)], 1))
        assert stub._fetch_remote_messages_before(GROUP, "false_x@g.us_A B") == (
            {"a"}, 100, f"false_{GROUP}_a")
        assert stub.queries == ["&direction=before&id=false_x%40g.us_A%20B"]

    def test_an_empty_page_is_the_end_of_history(self):
        assert _FetchStub(([], 0))._fetch_remote_messages_before(GROUP, "x") == (set(), 0, "")

    def test_unreadable_items_are_a_failure_not_an_empty_page(self):
        assert _FetchStub(([], 3))._fetch_remote_messages_before(GROUP, "x") is None

    def test_a_failed_request_is_a_failure(self):
        assert _FetchStub(None)._fetch_remote_messages_before(GROUP, "x") is None
        assert _FetchStub(None)._fetch_remote_message_window(GROUP) is None


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class _GetStub:
    _get_remote_messages = MainWindow._get_remote_messages

    def __init__(self):
        self.ws = types.SimpleNamespace(_normalize_wpp_message=self._normalize)
        self.settings = {"user_interface": {"messages_page_size": 50}}
        self._phone_to_lid = {}
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "tok"

    @staticmethod
    def _normalize(wm):
        if wm.get("bad"):
            raise ValueError("unreadable")
        return {"key": {"id": wm["id"]["_serialized"].split("_")[-1]},
                "messageTimestamp": wm["t"]}


class TestGetRemoteMessages:
    def test_builds_the_url_and_counts_raw_items(self, monkeypatch):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            return _Response(200, {"response": [
                {"id": {"_serialized": "false_5511@c.us_A"}, "t": 100}, {"bad": True}]})

        monkeypatch.setattr(main_module, "api_get", fake_get)
        pairs, raw_count = _GetStub()._get_remote_messages(
            "5511@s.whatsapp.net", "&direction=before&id=x")

        assert calls == ["http://127.0.0.1:6300/api/tok/get-messages/5511@c.us"
                         "?count=50&direction=before&id=x"]
        assert [n["key"]["id"] for n, _raw in pairs] == ["A"]
        assert raw_count == 2

    def test_an_error_status_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(main_module, "api_get", lambda url, **kw: _Response(500, {}))
        assert _GetStub()._get_remote_messages("5511@s.whatsapp.net") is None


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
