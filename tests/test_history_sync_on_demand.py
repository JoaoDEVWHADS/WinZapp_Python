"""Tests for the on-demand history-sync path and its health reporting.

WhatsApp's multi-device design only pushes a bounded window of history to a
linked device and keeps the rest on the primary phone. WhatsApp Web surfaces
that as the "get older messages from your phone" banner; underneath it sends a
peer data operation request of type HISTORY_SYNC_ON_DEMAND, which WPPConnect
does not wrap — WinZapp reaches it through the /request-older-messages route
added to the patched deviceController.

Two behaviours matter enough to pin down here:

  * Running out of *local* history is not the same as running out of history.
    fetch_older_messages() used to add the chat to _exhausted_chats the moment
    the API answered with an empty list, and the guard at the top of that
    method then refused to ever query it again. Since the phone replies to an
    on-demand request asynchronously (a history-sync chunk, minutes later),
    that permanent marker would throw away the very messages the request went
    out to fetch. So: request sent => chat stays re-queryable; request not
    sent => mark exhausted exactly like before.

  * A dead history-sync pipeline is completely silent from WinZapp's side —
    get-messages keeps answering 200 with a short list, which looks identical
    to a genuinely short conversation. log_history_sync_status() exists to put
    that distinction in log.log instead of requiring a CDP session against the
    live page to find it.
"""

import logging

import pytest

from main import MainWindow


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Stub:
    """Carries only what the methods under test actually touch."""

    wpp_server = "http://127.0.0.1"
    wpp_port = 6300
    token = "tok"

    fetch_history_sync_status = MainWindow.fetch_history_sync_status
    log_history_sync_status = MainWindow.log_history_sync_status
    request_older_messages = MainWindow.request_older_messages
    unblock_history_sync = MainWindow.unblock_history_sync
    refresh_history_still_landing = MainWindow.refresh_history_still_landing
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self, connected=True):
        self._wa_connected = connected
        self._phone_to_lid = {}
        self._lid_to_phone = {}


class TestFetchHistorySyncStatus:
    def test_returns_response_payload(self, monkeypatch):
        stub = _Stub()
        payload = {"backendWorkerBridgeReady": True, "storeCounts": {"message": 9000}}
        monkeypatch.setattr(
            "main.requests.get",
            lambda *a, **k: _Response(200, {"status": "success", "response": payload}),
        )
        assert stub.fetch_history_sync_status() == payload

    def test_disconnected_session_never_calls_the_api(self, monkeypatch):
        stub = _Stub(connected=False)

        def _boom(*a, **k):
            raise AssertionError("must not hit the API while disconnected")

        monkeypatch.setattr("main.requests.get", _boom)
        assert stub.fetch_history_sync_status() is None

    def test_missing_route_is_not_fatal(self, monkeypatch):
        """An older client/api/ build simply has no such endpoint."""
        stub = _Stub()
        monkeypatch.setattr("main.requests.get", lambda *a, **k: _Response(404, text="nope"))
        assert stub.fetch_history_sync_status() is None

    def test_transport_error_is_swallowed(self, monkeypatch):
        stub = _Stub()

        def _raise(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr("main.requests.get", _raise)
        assert stub.fetch_history_sync_status() is None


class TestLogHistorySyncStatus:
    def test_dead_bridge_is_logged_at_error(self, monkeypatch, caplog):
        stub = _Stub()
        monkeypatch.setattr(
            _Stub,
            "fetch_history_sync_status",
            lambda self, timeout=30: {
                "backendWorkerBridgeReady": False,
                "unprocessedChunks": 20,
                "storeCounts": {"message": 1083, "chat": 604},
                "chunkStatus": {"1": "notification_stored", "2": "notification_stored"},
            },
        )
        with caplog.at_level(logging.INFO):
            stub.log_history_sync_status(context="after initial sync")
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "a dead bridge must be loud — it invalidates every sync"
        assert "backend worker bridge is DOWN" in errors[0].getMessage()

    def test_chunk_states_are_tallied(self, monkeypatch, caplog):
        stub = _Stub()
        monkeypatch.setattr(
            _Stub,
            "fetch_history_sync_status",
            lambda self, timeout=30: {
                "backendWorkerBridgeReady": True,
                "unprocessedChunks": 0,
                "storeCounts": {"message": 50000, "chat": 604},
                "chunkStatus": {
                    "1": "notification_stored",
                    "2": "decoded",
                    "3": "decoded",
                },
            },
        )
        with caplog.at_level(logging.INFO):
            stub.log_history_sync_status()
        tallies = [r.getMessage() for r in caplog.records if "chunk states" in r.getMessage()]
        assert tallies
        assert "'decoded': 2" in tallies[0]
        assert "'notification_stored': 1" in tallies[0]

    def test_healthy_bridge_logs_no_error(self, monkeypatch, caplog):
        stub = _Stub()
        monkeypatch.setattr(
            _Stub,
            "fetch_history_sync_status",
            lambda self, timeout=30: {
                "backendWorkerBridgeReady": True,
                "unprocessedChunks": 0,
                "storeCounts": {"message": 50000, "chat": 604},
            },
        )
        with caplog.at_level(logging.INFO):
            assert stub.log_history_sync_status() is not None
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_no_status_available_returns_none(self, monkeypatch):
        stub = _Stub()
        monkeypatch.setattr(_Stub, "fetch_history_sync_status", lambda self, timeout=30: None)
        assert stub.log_history_sync_status(context="x") is None


class TestRequestOlderMessages:
    def test_posts_to_the_cus_form_for_a_phone_jid(self, monkeypatch):
        stub = _Stub()
        seen = {}

        def _post(url, **kwargs):
            seen["url"] = url
            return _Response(200, {"status": "success", "response": {"requested": True}})

        monkeypatch.setattr("main.requests.post", _post)
        assert stub.request_older_messages("5535999999999@s.whatsapp.net") is True
        assert seen["url"].endswith("/request-older-messages/5535999999999@c.us")

    def test_prefers_the_lid_form_when_one_is_mapped(self, monkeypatch):
        """Same addressing rule sync_chat_messages() uses."""
        stub = _Stub()
        stub._phone_to_lid["5535999999999@s.whatsapp.net"] = "12345@lid"
        seen = {}
        monkeypatch.setattr(
            "main.requests.post",
            lambda url, **k: (
                seen.__setitem__("url", url),
                _Response(200, {"status": "success", "response": {"requested": True}}),
            )[1],
        )
        stub.request_older_messages("5535999999999@s.whatsapp.net")
        assert seen["url"].endswith("/request-older-messages/12345@lid")

    def test_group_jid_is_passed_through_unchanged(self, monkeypatch):
        stub = _Stub()
        seen = {}
        monkeypatch.setattr(
            "main.requests.post",
            lambda url, **k: (
                seen.__setitem__("url", url),
                _Response(200, {"status": "success", "response": {"requested": True}}),
            )[1],
        )
        stub.request_older_messages("120363000000000000@g.us")
        assert seen["url"].endswith("/request-older-messages/120363000000000000@g.us")

    def test_server_refusal_reports_false(self, monkeypatch):
        """WhatsApp Web disables on-demand sending after repeated failures."""
        stub = _Stub()
        monkeypatch.setattr(
            "main.requests.post",
            lambda *a, **k: _Response(
                500,
                {"status": "error", "response": {"error": "on-demand requests disabled"}},
            ),
        )
        assert stub.request_older_messages("120363000000000000@g.us") is False

    def test_200_without_requested_flag_is_not_a_success(self, monkeypatch):
        stub = _Stub()
        monkeypatch.setattr(
            "main.requests.post",
            lambda *a, **k: _Response(200, {"status": "success", "response": {"requested": False}}),
        )
        assert stub.request_older_messages("120363000000000000@g.us") is False

    def test_disconnected_session_never_calls_the_api(self, monkeypatch):
        stub = _Stub(connected=False)

        def _boom(*a, **k):
            raise AssertionError("must not hit the API while disconnected")

        monkeypatch.setattr("main.requests.post", _boom)
        assert stub.request_older_messages("120363000000000000@g.us") is False

    def test_transport_error_is_swallowed(self, monkeypatch):
        stub = _Stub()

        def _raise(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr("main.requests.post", _raise)
        assert stub.request_older_messages("120363000000000000@g.us") is False


class TestRefreshHistoryStillLanding:
    """The flag that tells the backfill whether a short chat is short or early.

    _note_backfill_state() runs on the sync's worker threads and must not make
    its own status call per chat, so this is read once per pass and left on the
    instance.
    """

    def _stub(self, status, monkeypatch):
        stub = _Stub()
        monkeypatch.setattr(
            _Stub, "fetch_history_sync_status", lambda self, timeout=30: status)
        return stub

    def test_queued_chunks_mean_history_is_still_landing(self, monkeypatch):
        stub = self._stub({"unprocessedChunks": 12, "initialSyncComplete": True}, monkeypatch)
        assert stub.refresh_history_still_landing() is True
        assert stub._history_still_landing is True

    def test_a_fresh_pairing_counts_even_with_an_empty_queue(self, monkeypatch):
        """The new-pairing case, and the reason the chunk count alone is not
        enough: at the moment the first sync runs the phone has usually not
        delivered anything yet, so an empty queue there means "nothing has
        arrived", not "nothing is coming"."""
        stub = self._stub({"unprocessedChunks": 0, "initialSyncComplete": False}, monkeypatch)
        assert stub.refresh_history_still_landing() is True

    def test_a_settled_session_is_settled(self, monkeypatch):
        stub = self._stub({"unprocessedChunks": 0, "initialSyncComplete": True}, monkeypatch)
        stub._history_still_landing = True
        assert stub.refresh_history_still_landing() is False
        assert stub._history_still_landing is False

    def test_an_interrupted_recent_sync_does_not_pin_the_flag(self, monkeypatch):
        """recentCompleted stays false forever on such a session — keying off it
        would re-query every short chat on every launch for good."""
        stub = self._stub(
            {"unprocessedChunks": 0, "initialSyncComplete": True, "recentCompleted": False},
            monkeypatch)
        assert stub.refresh_history_still_landing() is False

    def test_an_unreadable_status_is_treated_as_settled(self, monkeypatch):
        """Better to take a short chat at face value than to re-query 600 of
        them for the whole budget because the status endpoint is missing."""
        stub = self._stub(None, monkeypatch)
        assert stub.refresh_history_still_landing() is False
        assert stub._history_still_landing is False


def _history_sync_warnings(caplog):
    """WARNING+ messages from this feature only.

    caplog sees the whole root logger, and other modules' teardown noise
    (asyncio's "Task was destroyed but it is pending!") lands in it when the
    full suite runs — filtering on the tag keeps these assertions about the
    code under test.
    """
    return [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING and "[history-sync]" in r.getMessage()
    ]


class TestUnblockHistorySync:
    """The queue deadlock this endpoint exists to clear.

    WhatsApp Web takes the next chunk to process by sorting unprocessed
    notifications on *descending* syncType, so ON_DEMAND (6) always outranks
    RECENT (3) — while an ON_DEMAND chunk is only let through once
    `recentCompleted` is true, which stays false until the RECENT chunks queued
    behind it have been processed. Nothing breaks that tie on its own: the same
    row is picked and refused on every pass, forever. Measured live: four such
    chunks held 22 recent ones (~30MB of history) frozen; dropping them took
    WhatsApp Web's message store from 1,526 to 6,014 rows in 40 seconds.
    """

    def test_removed_chunks_are_reported_loudly(self, monkeypatch, caplog):
        stub = _Stub()
        monkeypatch.setattr(
            "main.requests.post",
            lambda *a, **k: _Response(200, {"status": "success", "response": {
                "recentCompleted": False, "unprocessed": 26, "recentWaiting": 22,
                "onDemandPending": 4, "removed": ["a", "b", "c", "d"],
                "restarted": True,
            }}),
        )
        with caplog.at_level(logging.INFO):
            payload = stub.unblock_history_sync()
        assert payload["removed"] == ["a", "b", "c", "d"]
        warnings = _history_sync_warnings(caplog)
        assert warnings, "dropping chunks is not a routine event — say so"
        assert "blocking 22" in warnings[0]

    def test_healthy_queue_is_a_quiet_no_op(self, monkeypatch, caplog):
        stub = _Stub()
        monkeypatch.setattr(
            "main.requests.post",
            lambda *a, **k: _Response(200, {"status": "success", "response": {
                "recentCompleted": True, "unprocessed": 0, "recentWaiting": 0,
                "onDemandPending": 0, "removed": [],
                "skipped": "recent sync complete — on-demand chunks can be processed",
            }}),
        )
        with caplog.at_level(logging.INFO):
            payload = stub.unblock_history_sync()
        assert payload["removed"] == []
        assert not _history_sync_warnings(caplog)

    def test_missing_route_is_not_fatal(self, monkeypatch):
        """An older client/api/ build simply has no such endpoint."""
        stub = _Stub()
        monkeypatch.setattr("main.requests.post", lambda *a, **k: _Response(404, text="nope"))
        assert stub.unblock_history_sync() is None

    def test_disconnected_session_never_calls_the_api(self, monkeypatch):
        stub = _Stub(connected=False)

        def _boom(*a, **k):
            raise AssertionError("must not hit the API while disconnected")

        monkeypatch.setattr("main.requests.post", _boom)
        assert stub.unblock_history_sync() is None

    def test_transport_error_is_swallowed(self, monkeypatch):
        stub = _Stub()

        def _raise(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr("main.requests.post", _raise)
        assert stub.unblock_history_sync() is None

    def test_restart_rehydrates_bootstrap_after_page_reload(self):
        """A fresh bootstrap instance otherwise rejects every manual restart."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        controller = (
            root / "client" / "api_patches" / "src" / "controller"
            / "deviceController.ts"
        ).read_text(encoding="utf-8")
        rehydrate_at = controller.index("setInitialChatHistorySynced")
        restart_at = controller.index(
            "continueSync.call(boot, source.ManualRestart)"
        )
        assert rehydrate_at < restart_at
        assert "initialComplete === true" in controller


class _FetchStub:
    """Just the exhaustion bookkeeping of fetch_older_messages()."""

    def __init__(self, request_succeeds):
        self._exhausted_chats = set()
        self._older_requested_chats = set()
        self._request_succeeds = request_succeeds
        self.requested_for = []

    def request_older_messages(self, jid, timeout=60):
        self.requested_for.append(jid)
        return self._request_succeeds


def _run_empty_result_branch(stub, remote_jid):
    """Mirror of the no-messages branch in fetch_older_messages()."""
    already_asked = remote_jid in stub._older_requested_chats
    requested = False
    if not already_asked:
        stub._older_requested_chats.add(remote_jid)
        requested = stub.request_older_messages(remote_jid)
    if not requested:
        stub._exhausted_chats.add(remote_jid)


class TestExhaustionBookkeeping:
    """A chat we just asked the phone about must stay re-queryable.

    fetch_older_messages() returns early for anything in _exhausted_chats, so
    marking a chat there right after firing an on-demand request would discard
    the reply the request exists to collect.
    """

    def test_successful_request_leaves_the_chat_requeryable(self):
        stub = _FetchStub(request_succeeds=True)
        _run_empty_result_branch(stub, "120363000000000000@g.us")
        assert stub.requested_for == ["120363000000000000@g.us"]
        assert "120363000000000000@g.us" not in stub._exhausted_chats

    def test_failed_request_marks_exhausted(self):
        stub = _FetchStub(request_succeeds=False)
        _run_empty_result_branch(stub, "120363000000000000@g.us")
        assert "120363000000000000@g.us" in stub._exhausted_chats

    def test_the_phone_is_asked_only_once_per_chat(self):
        """Second empty result gives up instead of re-asking the phone."""
        stub = _FetchStub(request_succeeds=True)
        jid = "120363000000000000@g.us"
        _run_empty_result_branch(stub, jid)
        _run_empty_result_branch(stub, jid)
        assert stub.requested_for == [jid]
        assert jid in stub._exhausted_chats


class TestBrowserFlagsStayRemoved:
    """The flags that break history sync must be gone from EVERY list.

    index.ts builds the effective config with `merge-deep`, which unions
    arrays instead of replacing them, so config.ts's browserArgs and the list
    start.js passes to initServer() are concatenated. start.js can therefore
    only ever *add* a flag — deleting one there while config.ts still lists it
    changes nothing, which is exactly how '--disable-notifications' survived
    its first removal and kept the Notification API undefined, and with it
    WhatsApp Web's persistent storage bucket.

    (Neither flag was the cause of the short-history bug — that was the blanket
    request interception, see TestDocumentOnlyInterception. They stay removed
    on their own merits: this page runs its backend in workers, and the
    Notification API is what Chrome's persistent-storage auto-grant keys off.)
    """

    FLAG_LISTS = (
        ("client/api_patches/start.js", r"^\s*'(--[^']+)',"),
        ("client/api_patches/src/config.ts", r"^\s*'(--[^']+)',"),
        ("client/api_patches/src/util/sessionUtil.ts", r"^\s*'(--[^']+)',"),
    )
    FORBIDDEN = ("--disable-notifications", "--disable-shared-workers")

    def _flags(self, relpath, pattern):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / relpath).read_text(encoding="utf-8")
        # Only real array entries — the comments explaining the removal
        # legitimately name the flags.
        return re.findall(pattern, text, re.M)

    @pytest.mark.parametrize("relpath,pattern", FLAG_LISTS)
    def test_forbidden_flags_absent(self, relpath, pattern):
        flags = self._flags(relpath, pattern)
        assert flags, f"no flags parsed out of {relpath} — pattern went stale"
        for bad in self.FORBIDDEN:
            assert bad not in flags, f"{bad} is back in {relpath}"

    def test_lists_are_otherwise_intact(self):
        """Guards the parser above: a typo'd regex must not pass vacuously."""
        start = self._flags(*self.FLAG_LISTS[0])
        assert "--no-sandbox" in start
        assert "--disable-web-security" in start


class TestRoutesArePatched:
    """The endpoints these methods call must exist in the patched API."""

    def test_routes_declared(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        routes = (root / "client" / "api_patches" / "src" / "routes" / "index.ts").read_text(
            encoding="utf-8"
        )
        assert "/api/:session/request-older-messages/:phone" in routes
        assert "/api/:session/history-sync-status" in routes
        assert "/api/:session/unblock-history-sync" in routes

    def test_on_demand_requests_are_gated_on_recent_sync(self):
        """Sending one early deadlocks the queue — see TestUnblockHistorySync."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        controller = (
            root / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
        ).read_text(encoding="utf-8")
        send_at = controller.index("sendPeerDataOperationRequest(kind")
        guard_at = controller.index("out.recentCompleted !== true")
        assert guard_at < send_at, "the guard must run before the request goes out"

    def test_stale_recent_flag_is_repaired_only_for_an_empty_queue(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        controller = (
            root / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
        ).read_text(encoding="utf-8")

        empty_queue = controller.index("if (rows.length === 0)")
        repair = controller.index("recentCompleted: true", empty_queue)
        send = controller.index("sendPeerDataOperationRequest(kind")
        assert empty_queue < repair < send
        assert "out.unprocessed = rows.length" in controller


class TestDocumentOnlyInterception:
    """Puppeteer's blanket request interception must not come back.

    page.setRequestInterception(true) — which is all WPPConnect's
    setWhatsappVersion() does to serve the pinned HTML — makes every CORS-mode
    request issued from a dedicated Worker hang forever, with no error on
    either side. Measured with plain puppeteer and no WhatsApp involved:
    interception off, a worker's cross-origin fetch answers 200 in ~560ms; on,
    it never returns (page-issued and no-cors requests are unaffected either
    way).

    WhatsApp Web boots its whole storage/decode backend in such a worker, whose
    init script imports its bundles from static.whatsapp.net. Those imports
    hung, the worker never signalled ready, and every history-sync chunk — each
    one awaiting that bridge — stayed undecoded. So start.js keeps the version
    pin but serves it through a raw-CDP Fetch.enable scoped to the document URL
    alone, and hands `version=undefined` on so WPPConnect installs nothing.
    """

    def _start_js(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "client" / "api_patches" / "start.js").read_text(encoding="utf-8")

    def test_narrow_fetch_pattern_is_installed(self):
        start = self._start_js()
        assert "Fetch.enable" in start
        assert "urlPattern: WA_WEB_URL" in start
        assert "Fetch.fulfillRequest" in start

    def test_version_is_consumed_so_wppconnect_installs_nothing(self):
        """Passing the version through would re-enable the blanket interception."""
        start = self._start_js()
        assert "version = undefined;" in start
        assert "browserController.initWhatsapp = async function" in start

    def test_every_paused_request_is_answered(self):
        """A paused request nobody answers is the bug itself, not a fix for it."""
        start = self._start_js()
        for answer in ("Fetch.fulfillRequest", "Fetch.failRequest", "Fetch.continueRequest"):
            assert answer in start, f"{answer} branch missing from the handler"

    def test_dead_wapi_loader_is_gone(self):
        """WAPI.loadEarlierMessages calls chat.loadEarlierMsgs(), which current
        WhatsApp Web builds no longer have — every call threw immediately and
        the surrounding `catch { break; }` made it look like a working fix."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        controller = (
            root / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
        ).read_text(encoding="utf-8")
        # Match call sites only — the comment above the replacement explains
        # why the old call was wrong and legitimately names it.
        assert "await (window as any).WAPI.loadEarlierMessages(" not in controller
        assert "await (window as any).WPP.chat.loadEarlierMessages(" not in controller
