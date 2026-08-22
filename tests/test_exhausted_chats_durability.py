"""Regression tests for durable older-history exhaustion.

An empty page in WhatsApp Web only proves that the linked device's local Store
has no older row.  It does *not* prove the primary phone has no older history.
Current WhatsApp exposes an explicit endOfHistoryTransferType and only value 1
means no messages remain on the primary; values 0 and 2 explicitly mean more
remain.  Elapsed time must therefore never become an exhaustion signal.
"""

import types

import pytest

import main
from main import MainWindow


RETRY = MainWindow._OLDER_REQUEST_RETRY
JID = "5511999999999@s.whatsapp.net"
ANCHOR = {"key": {"id": "m1", "remoteJid": JID}, "messageTimestamp": 1_700_000_000}


class _DB:
    def __init__(self):
        self.metadata = {}

    def set_metadata_json(self, key, value):
        self.metadata[key] = value


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {"response": []}


class _Stub:
    def __init__(self, ask_succeeds=True, confirm_end=False):
        self.db = _DB()
        self._exhausted_chats = set()
        self._older_requested_chats = {}
        self._older_request_confirmed_end = set()
        self._phone_to_lid = {}
        self._lid_to_phone = {}
        self.settings = {"user_interface": {"messages_page_size": 200}}
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "tok"
        self.ws = None
        self._ask_succeeds = ask_succeeds
        self._confirm_end = confirm_end
        self.asks = []

    def request_older_messages(self, jid, timeout=60):
        self.asks.append(jid)
        if self._confirm_end:
            self._older_request_confirmed_end.add(jid)
            return False
        return self._ask_succeeds

    def _resolve_jid_for_msg_key(self, jid):
        return jid

    def _serialize_msg_id(self, jid, key):
        return f"false_{jid}_{key.get('id', '')}"


def _make(ask_succeeds=True, confirm_end=False):
    stub = _Stub(ask_succeeds, confirm_end)
    for name in ("fetch_older_messages", "_persist_exhausted_chats",
                 "_persist_older_requested", "_forget_history_exhaustion",
                 "_normalize_jid"):
        raw = MainWindow.__dict__[name]
        if isinstance(raw, (staticmethod, classmethod)):
            setattr(stub, name, getattr(MainWindow, name))
        else:
            setattr(stub, name, types.MethodType(raw, stub))
    stub._OLDER_REQUEST_RETRY = MainWindow._OLDER_REQUEST_RETRY
    stub._OLDER_REQUEST_GRACE = MainWindow._OLDER_REQUEST_GRACE
    return stub


@pytest.fixture(autouse=True)
def _empty_page(monkeypatch):
    monkeypatch.setattr(main, "api_get", lambda *a, **kw: _Response())


class TestEmptyBrowserStorePage:
    def test_it_asks_phone_and_stays_requeryable(self):
        stub = _make()
        assert stub.fetch_older_messages(JID, ANCHOR) is None
        assert stub.asks == [JID]
        assert JID not in stub._exhausted_chats

    def test_successful_ask_is_persisted_only_as_retry_throttle(self):
        stub = _make()
        stub.fetch_older_messages(JID, ANCHOR)
        assert JID in stub._older_requested_chats
        assert JID in stub.db.metadata["older_history_requested"]

    def test_second_empty_page_inside_retry_window_does_not_ask_again(self):
        stub = _make()
        stub.fetch_older_messages(JID, ANCHOR)
        stub.fetch_older_messages(JID, ANCHOR)
        assert stub.asks == [JID]
        assert JID not in stub._exhausted_chats

    def test_old_timestamp_retries_instead_of_declaring_end(self):
        stub = _make()
        stub._older_requested_chats[JID] = main.time.time() - RETRY - 1
        assert stub.fetch_older_messages(JID, ANCHOR) is None
        assert stub.asks == [JID]
        assert JID not in stub._exhausted_chats
        assert "exhausted_chats" not in stub.db.metadata

    def test_even_a_very_old_timestamp_is_not_end_evidence(self):
        stub = _make()
        stub._older_requested_chats[JID] = 0.0
        assert stub.fetch_older_messages(JID, ANCHOR) is None
        assert stub.asks == [JID]
        assert JID not in stub._exhausted_chats


class TestExplicitPrimaryEndSignal:
    def test_only_confirmed_end_becomes_durable(self):
        stub = _make(confirm_end=True)
        assert stub.fetch_older_messages(JID, ANCHOR) == []
        assert JID in stub._exhausted_chats
        assert stub.db.metadata["exhausted_chats"] == [JID]

    def test_preexisting_explicit_signal_is_honoured_without_new_request(self):
        stub = _make()
        stub._older_request_confirmed_end.add(JID)
        assert stub.fetch_older_messages(JID, ANCHOR) == []
        assert stub.asks == []
        assert stub.db.metadata["exhausted_chats"] == [JID]

    def test_background_backfill_respects_a_durable_explicit_end(self):
        stub = _make()
        stub._exhausted_chats.add(JID)
        assert stub.fetch_older_messages(JID, ANCHOR, store_only=True) == []
        assert stub.asks == []

    def test_user_scroll_can_challenge_an_old_durable_cache(self):
        # Important for databases written by pre-v3 builds.
        stub = _make()
        stub._exhausted_chats.add(JID)
        assert stub.fetch_older_messages(JID, ANCHOR) is None
        assert stub.asks == [JID]
        assert JID not in stub._exhausted_chats


class TestFailedAsk:
    def test_failure_or_refusal_is_never_end_evidence(self):
        stub = _make(ask_succeeds=False)
        assert stub.fetch_older_messages(JID, ANCHOR) is None
        assert JID not in stub._exhausted_chats
        assert JID not in stub._older_requested_chats
        assert "exhausted_chats" not in stub.db.metadata


class TestResyncClearsHistoryConclusions:
    def test_resync_forgets_all_history_request_state(self):
        stub = _make()
        stub._exhausted_chats.add(JID)
        stub._older_requested_chats[JID] = 1.0
        stub._older_request_confirmed_end.add(JID)
        stub._forget_history_exhaustion()
        assert stub._exhausted_chats == set()
        assert stub._older_requested_chats == {}
        assert stub._older_request_confirmed_end == set()
        assert stub.db.metadata["exhausted_chats"] == []
        assert stub.db.metadata["older_history_requested"] == {}

    def test_resync_worker_is_wired_to_forget_history_conclusions(self):
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(
            inspect.getsource(MainWindow._resync_all_worker)))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "_forget_history_exhaustion" in called
        assert "clear_local_data" in called
