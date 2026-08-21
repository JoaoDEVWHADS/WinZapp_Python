"""Tests for walking a chat's history back to its beginning.

The ordinary backfill retires a chat the moment it holds one page
(_note_backfill_state: `count >= history_page_target()`), so a conversation
with 20,000 messages kept exactly 200 and the rest only ever arrived if the
user happened to scroll up to it by hand. deep_backfill_chat() pages
backwards until WhatsApp Web has nothing older.

Three properties matter and each has a way of going quietly wrong:

* It must stop. The stop signal is fetch_older_messages() answering with an
  empty page, which is also where the chat gets marked exhausted.
* It must not hold the account in RAM. Paging a 935-chat account back to the
  beginning is millions of message dicts; store_only writes them to SQLite
  and keeps none.
* It must resume, not restart. The anchor is read from the database and
  exhausted chats are persisted, so a relaunch continues the walk instead of
  re-requesting from the newest page for ever.

MainWindow is a wx.Frame, so the methods are bound to a stub carrying only
what they touch — the pattern the rest of this suite uses.
"""

import types

import pytest

import main
from main import MainWindow


def _msg(i):
    return {"key": {"id": f"m{i}", "remoteJid": "chat@g.us"},
            "messageTimestamp": 1_700_000_000 + i}


class _DB:
    def __init__(self, oldest_by_jid=None):
        self.oldest = oldest_by_jid or {}
        self.batches = []
        self.metadata = {}
        self.message_ids = {
            jid: {msg.get("key", {}).get("id")} for jid, msg in self.oldest.items()
            if msg
        }

    def get_messages_asc(self, jid, limit=200, offset=0):
        got = self.oldest.get(jid)
        return [got] if got else []

    def insert_messages_batch(self, jid, msgs):
        self.batches.append((jid, len(msgs)))
        ids = self.message_ids.setdefault(jid, set())
        ids.update(m.get("key", {}).get("id") for m in msgs)

    def get_message_count(self, jid):
        return len(self.message_ids.get(jid, set()))

    def set_metadata_json(self, key, value):
        self.metadata[key] = value


class _Stub:
    def __init__(self, pages, oldest=None):
        # pages: list of responses fetch_older_messages() will return, in order
        self._pages = list(pages)
        self._wa_connected = True
        self.offline_mode = False
        self.db = _DB({"chat@g.us": oldest} if oldest else {})
        self._exhausted_chats = set()
        self._deleted_chats = set()
        self.chats = {}
        self.settings = {"user_interface": {"messages_page_size": 200}}
        self.calls = []
        self.requested = []

    def fetch_older_messages(self, jid, anchor, store_only=False):
        self.calls.append({"jid": jid, "anchor": anchor, "store_only": store_only})
        if not self._pages:
            return []
        page = self._pages.pop(0)
        if page:
            self.db.insert_messages_batch(jid, page)
            # the real one advances the anchor as it stores
            self.db.oldest[jid] = page[0]
        else:
            self._exhausted_chats.add(jid)
        return page

    def request_older_messages(self, jid):
        self.requested.append(jid)
        return True


def _make(pages, oldest=None):
    stub = _Stub(pages, oldest)
    for name in ("deep_backfill_chat", "_oldest_stored_message",
                 "_chats_needing_deep_history", "history_page_target",
                 "_persist_exhausted_chats"):
        stub_attr = MainWindow.__dict__[name]
        setattr(stub, name, types.MethodType(stub_attr, stub))
    stub._history_anchor_position = MainWindow._history_anchor_position
    for const in ("_DEEP_PAGES_PER_VISIT", "_DEEP_PAGE_DELAY",
                  "_DEEP_CHATS_PER_PASS"):
        setattr(stub, const, getattr(MainWindow, const))
    return stub


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda *_a: None)


class TestWalkingOneChatBack:
    def test_it_pages_until_the_history_runs_out(self):
        """Two full pages then an empty one: it stops on the empty answer
        rather than on the visit budget."""
        stub = _make([[_msg(3), _msg(4)], [_msg(1), _msg(2)], []], oldest=_msg(5))
        stored = stub.deep_backfill_chat("chat@g.us")
        assert stored == 4
        assert len(stub.calls) == 3
        assert "chat@g.us" in stub._exhausted_chats

    def test_the_visit_budget_caps_one_chat(self):
        """One enormous conversation must not hold the queue while the rest
        of the account waits. It comes back next pass."""
        # Every response must genuinely move backwards from the prior anchor.
        stub = _make([[_msg(i)] for i in range(98, 48, -1)], oldest=_msg(99))
        stub.deep_backfill_chat("chat@g.us")
        assert len(stub.calls) == MainWindow._DEEP_PAGES_PER_VISIT
        assert "chat@g.us" not in stub._exhausted_chats

    def test_every_page_is_stored_without_being_kept_in_memory(self):
        stub = _make([[_msg(3), _msg(4)], []], oldest=_msg(5))
        stub.deep_backfill_chat("chat@g.us")
        assert all(c["store_only"] for c in stub.calls), \
            "a deep page kept in RAM defeats the whole point"
        assert stub.db.batches == [("chat@g.us", 2)]

    def test_an_already_exhausted_chat_is_not_asked_again(self):
        """This is what makes a relaunch cheap instead of a full re-walk."""
        stub = _make([[_msg(1)]], oldest=_msg(5))
        stub._exhausted_chats.add("chat@g.us")
        assert stub.deep_backfill_chat("chat@g.us") == 0
        assert stub.calls == []

    def test_a_chat_with_nothing_stored_is_left_to_the_ordinary_backfill(self):
        """No anchor to page before — that queue handles it, not this one."""
        stub = _make([[_msg(1)]], oldest=None)
        assert stub.deep_backfill_chat("chat@g.us") == 0
        assert stub.calls == []

    def test_it_stops_when_the_connection_drops(self):
        stub = _make([[_msg(1)], [_msg(2)]], oldest=_msg(5))
        stub._wa_connected = False
        assert stub.deep_backfill_chat("chat@g.us") == 0
        assert stub.calls == []

    def test_it_stops_in_offline_mode(self):
        stub = _make([[_msg(1)]], oldest=_msg(5))
        stub.offline_mode = True
        assert stub.deep_backfill_chat("chat@g.us") == 0

    def test_the_anchor_comes_from_the_database_not_from_memory(self):
        """Anchoring on the in-memory list would re-request the newest window
        every visit and never advance, because that list is the newest page."""
        stub = _make([[_msg(3)], []], oldest=_msg(5))
        stub.chats = {"chat@g.us": {"messages": {"messages": {"records": [_msg(9)]}}}}
        stub.deep_backfill_chat("chat@g.us")
        assert stub.calls[0]["anchor"] == _msg(5)

    def test_a_repeated_page_is_not_counted_as_progress(self):
        """When the API falls back to the page containing the requested
        anchor, SQLite replaces the same ID and the walk must pause instead
        of renewing its deadline forever."""
        stub = _make([[_msg(5)], [_msg(5)]], oldest=_msg(5))
        assert stub.deep_backfill_chat("chat@g.us") == 0
        assert len(stub.calls) == 1
        assert stub.requested == ["chat@g.us"]
        assert stub._deep_stalled_anchors["chat@g.us"] == (1_700_000_005, "m5")

        # A second visit at the same anchor performs no duplicate request.
        assert stub.deep_backfill_chat("chat@g.us") == 0
        assert len(stub.calls) == 1

    def test_progress_counts_only_new_database_rows(self):
        stub = _make([[_msg(3), _msg(4), _msg(4)], []], oldest=_msg(5))
        assert stub.deep_backfill_chat("chat@g.us") == 2


class TestChoosingWhichChatsNeedIt:
    def _chat(self, n):
        return {"messages": {"messages": {"records": [_msg(i) for i in range(n)]}}}

    def test_a_chat_holding_a_full_page_is_queued(self):
        stub = _make([])
        stub.chats = {"full@g.us": self._chat(200)}
        assert stub._chats_needing_deep_history() == ["full@g.us"]

    def test_a_chat_short_of_a_page_belongs_to_the_other_queue(self):
        stub = _make([])
        stub.chats = {"short@g.us": self._chat(15)}
        assert stub._chats_needing_deep_history() == []

    def test_an_exhausted_chat_is_not_queued(self):
        stub = _make([])
        stub.chats = {"done@g.us": self._chat(200)}
        stub._exhausted_chats.add("done@g.us")
        assert stub._chats_needing_deep_history() == []

    def test_a_deleted_chat_is_not_queued(self):
        stub = _make([])
        stub.chats = {"gone@g.us": self._chat(200)}
        stub._deleted_chats.add("gone@g.us")
        assert stub._chats_needing_deep_history() == []


class TestExhaustionSurvivesARestart:
    def test_marking_a_chat_exhausted_persists_it(self):
        stub = _make([])
        stub._exhausted_chats.update({"b@g.us", "a@g.us"})
        stub._persist_exhausted_chats()
        assert stub.db.metadata["exhausted_chats"] == ["a@g.us", "b@g.us"]

    def test_persisting_without_a_database_is_not_fatal(self):
        stub = _make([])
        stub.db = None
        stub._persist_exhausted_chats()   # must not raise


class _LoopStub:
    """Drives the real _backfill_empty_chats() for one pass.

    The wiring — whether the loop still runs when only deep work is left, and
    whether it calls the walk at all — lives in that method and nowhere else,
    so testing deep_backfill_chat() in isolation cannot reach it. That gap is
    exactly how two defences shipped untested earlier in this branch.
    """

    def __init__(self, deep_pending, pending=(), names=()):
        import threading
        self._ui_ready_event = threading.Event()
        self._ui_ready_event.set()
        self._sync_run_id = 1
        self._wa_connected = True
        self._history_still_landing = False
        self._chats_awaiting_messages = set(pending)
        self._names = list(names)
        self._deep_pending = list(deep_pending)
        self.walked = []
        self.returned_early = False
        self._passes = 0

    # collaborators the loop calls
    def refresh_history_still_landing(self, context=""):
        return False

    def _pending_name_resolution(self):
        return list(self._names)

    def _backfill_names(self):
        return 0

    def _chats_needing_deep_history(self):
        return list(self._deep_pending)

    def deep_backfill_chat(self, jid):
        self.walked.append(jid)
        # One pass is enough; stop the loop the way a shutdown would.
        self._ui_ready_event.clear()
        return 1

    def _local_record_count(self, jid):
        return 0

    def _resolve_backfill_target(self, jid):
        return None, None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: None


def _loop(deep_pending, pending=(), names=()):
    stub = _LoopStub(deep_pending, pending, names)
    stub._backfill_empty_chats = types.MethodType(
        MainWindow.__dict__["_backfill_empty_chats"], stub)
    for const in ("_BACKFILL_BUDGET", "_BACKFILL_LANDING_BUDGET",
                  "_BACKFILL_FIRST_DELAY", "_BACKFILL_MAX_DELAY",
                  "_BACKFILL_CHUNK", "_BACKFILL_WORKERS",
                  "_DEEP_CHATS_PER_PASS"):
        setattr(stub, const, getattr(MainWindow, const))
    stub._backfill_empty_chats()
    return stub


class TestTheLoopActuallyRunsTheWalk:
    def test_deep_work_alone_keeps_the_loop_alive(self):
        """Every chat has a full page and a name, so the old exit condition
        called that "nothing pending" and returned — which is precisely the
        state a 20,000-message account is in after the first sync."""
        stub = _loop(deep_pending=["a@g.us", "b@g.us"])
        assert stub.walked, "the loop returned without walking anything"

    def test_the_walk_is_chunked_per_pass(self):
        stub = _loop(deep_pending=[f"{i}@g.us" for i in range(50)])
        assert len(stub.walked) <= MainWindow._DEEP_CHATS_PER_PASS

    def test_nothing_at_all_still_ends_the_loop(self):
        stub = _loop(deep_pending=[])
        assert stub.walked == []


class _FetchStub:
    """Drives the real fetch_older_messages() far enough to reach the branch
    that decides whether a page is kept in memory."""

    def __init__(self, returned):
        self._returned = returned
        self._wa_connected = True
        self._exhausted_chats = set()
        self._older_requested_chats = set()
        self.chats = {"chat@g.us": {"messages": {"messages": {"records": [_msg(9)]}}}}
        self.settings = {"user_interface": {"messages_page_size": 200}}
        self.wpp_server, self.wpp_port, self.token = "http://x", 1, "t"
        self.batched = []
        self.upserted = []
        self.full_saves = 0
        self.ws = self

    # message normalisation, reduced to identity
    def _normalize_wpp_message(self, m):
        return m

    def _extract_lid_mapping(self, m):
        pass

    def _normalize_jid(self, jid):
        return jid

    def _resolve_jid_for_msg_key(self, jid):
        return jid

    def _serialize_msg_id(self, jid, key):
        return f"false_{jid}_{key.get('id', '')}"

    class _DB2:
        def __init__(self, outer):
            self.outer = outer

        def insert_messages_batch(self, jid, msgs):
            self.outer.batched.append((jid, len(msgs)))

        def upsert_chat(self, jid, chat):
            self.outer.upserted.append(jid)

    def save_data(self, *a, **kw):
        self.full_saves += 1

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: None


def _fetch_stub(monkeypatch, returned):
    stub = _FetchStub(returned)
    stub.db = _FetchStub._DB2(stub)
    stub.fetch_older_messages = types.MethodType(
        MainWindow.__dict__["fetch_older_messages"], stub)

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"response": returned}

    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: _Resp())
    return stub


class TestStoreOnlyKeepsNothingResident:
    """The branch that makes the deep walk affordable. Without it, paging a
    935-chat account back to its beginning appends every message to
    self.chats — millions of dicts held for nothing, since the open
    conversation reloads its page from SQLite anyway."""

    def test_store_only_writes_to_disk_without_growing_the_record_list(self, monkeypatch):
        stub = _fetch_stub(monkeypatch, [_msg(1), _msg(2)])
        before = list(stub.chats["chat@g.us"]["messages"]["messages"]["records"])
        got = stub.fetch_older_messages("chat@g.us", _msg(5), store_only=True)
        assert len(got) == 2
        assert stub.batched == [("chat@g.us", 2)], "the page must still reach the database"
        assert stub.chats["chat@g.us"]["messages"]["messages"]["records"] == before, \
            "store_only kept the page in memory"
        assert stub.upserted == [], "no chat rewrite is needed for a store-only page"

    def test_the_scroll_up_path_still_grows_the_list(self, monkeypatch):
        """The user is looking at those records — that path must not change."""
        stub = _fetch_stub(monkeypatch, [_msg(1), _msg(2)])
        stub.fetch_older_messages("chat@g.us", _msg(5))
        records = stub.chats["chat@g.us"]["messages"]["messages"]["records"]
        assert len(records) == 3
        assert stub.batched == [("chat@g.us", 2)]
