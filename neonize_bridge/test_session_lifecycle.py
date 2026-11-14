"""The lifecycle of a session: the pure state machine and the real Session
with a fake client (no neonize, no WhatsApp). Not tested against a real
account: the behaviour of Go's Stop/Disconnect comes from reading neonize."""
import threading
import time

import pytest

import session_lifecycle as sl
import server
from test_one_handler_per_event import registrations


# ------------------------------------------------------------ pure machine
@pytest.mark.parametrize("alive,status,phone_number,expected", [
    (False, "CLOSED", None, sl.START),
    (False, "CONNECTED", None, sl.START),            # dead thread: another comes up
    (True, "CLOSED", None, sl.RESTART),              # close-session still finishing
    (True, "notLogged", None, sl.RESTART),
    (True, "QRCODE", "5511999990000", sl.RESTART),   # stalled pairing, starts over
    (True, "QRCODE", None, sl.IGNORE),
    (True, "CONNECTED", None, sl.IGNORE),
    (True, "CONNECTED", "5511999990000", sl.IGNORE),
    (True, "INITIALIZING", None, sl.IGNORE),
])
def test_decide_start(alive, status, phone_number, expected):
    assert sl.decide_start(alive, status, phone_number) == expected


def test_a_drop_only_takes_it_out_of_connected_and_the_return_only_gives_back_what_the_drop_took():
    assert sl.next_state("CONNECTED", False, sl.DROPPED) == ("INITIALIZING", True)
    assert sl.next_state("QRCODE", False, sl.DROPPED) == ("QRCODE", False)
    assert sl.next_state("INITIALIZING", True, sl.RESTORED) == ("CONNECTED", False)
    # startup INITIALIZING (never was connected): RESTORED does not invent CONNECTED
    assert sl.next_state("INITIALIZING", False, sl.RESTORED) == ("INITIALIZING", False)
    assert sl.next_state("INITIALIZING", True, sl.CONNECTED_EVENT) == ("CONNECTED", False)


def test_thread_end_closes_but_does_not_undo_the_unlink_nor_the_terminal_failure():
    assert sl.next_state("INITIALIZING", False, sl.THREAD_ENDED)[0] == "CLOSED"
    assert sl.next_state("CONNECTED", False, sl.THREAD_ENDED)[0] == "CLOSED"
    assert sl.next_state("notLogged", False, sl.THREAD_ENDED)[0] == "notLogged"
    assert sl.next_state("terminalFailure", False, sl.THREAD_ENDED)[0] == "terminalFailure"
    assert sl.next_state("CONNECTED", False, sl.LEFT)[0] == "notLogged"


def test_terminal_failure_does_not_become_closed_or_the_client_restarts_every_30_s():
    """The client's health check calls start-session when it reads CLOSED/DESTROYED/"";
    any other text (besides the unlink ones) it only shows as offline."""
    for before in ("INITIALIZING", "CONNECTED", "QRCODE", "CLOSED"):
        after = sl.next_state(before, False, sl.TERMINAL_FAILURE)[0]
        assert after == sl.TERMINAL == "terminalFailure"
    assert sl.next_state("notLogged", False, sl.TERMINAL_FAILURE)[0] == "notLogged"
    assert sl.TERMINAL not in ("CLOSED", "DESTROYED", "", "notLogged", "QRCODE",
                               "disconnectedMobile", "UNPAIRED", "UNPAIRED_IDLE")


def test_terminal_failure_is_ended_and_a_start_session_can_replace_the_thread():
    assert sl.decide_start(True, sl.TERMINAL, "") == sl.RESTART
    assert sl.decide_start(False, sl.TERMINAL, "") == sl.START


def test_close_session_after_the_terminal_failure_does_not_erase_it():
    c = sl.Lifecycle()
    g = c.open()
    assert c.apply(g, sl.TERMINAL_FAILURE) == ("INITIALIZING", "terminalFailure")
    c.end()                         # the close-session the client sends afterwards
    assert c.status == "terminalFailure"
    c.end("CLOSED")                 # explicit logout
    assert c.status == "CLOSED"


def test_event_of_an_old_generation_does_not_touch_the_state():
    c = sl.Lifecycle()
    old = c.open()
    assert c.status == "INITIALIZING"
    c.end()
    new = c.open()
    assert c.apply(old, sl.THREAD_ENDED) is None      # the old thread waking up
    assert c.apply(old, sl.CONNECTED_EVENT) is None
    assert c.status == "INITIALIZING"
    assert c.apply(new, sl.CONNECTED_EVENT) == ("INITIALIZING", "CONNECTED")


def test_end_without_a_status_keeps_the_account_unlinked():
    c = sl.Lifecycle()
    g = c.open()
    c.apply(g, sl.LEFT)
    c.end()                         # the close-session the client sends afterwards
    assert c.status == "notLogged"
    c.end("CLOSED")
    assert c.status == "CLOSED"


@pytest.mark.parametrize("reason,expected", [
    (2, sl.LEFT), (4, sl.LEFT), (5, sl.LEFT),
    (3, sl.TERMINAL_FAILURE), (6, sl.TERMINAL_FAILURE), (7, sl.TERMINAL_FAILURE),
    (1, sl.DROPPED), (8, sl.DROPPED), (10, sl.DROPPED), (0, sl.DROPPED)])
def test_classify_failure(reason, expected):
    assert sl.classify_failure(reason) == expected


def test_logout_notices_send_the_status_find_before_the_session_logged():
    notices = sl.logout_notices("account1")
    assert [n[1] for n in notices] == ["status-find", "session-logged"]
    assert notices[0][0] == 0 and notices[1][0] > 0
    assert notices[0][2]["status"] in ("notLogged", "disconnectedMobile")
    assert notices[1][2]["status"] is False


def test_host_device_only_says_the_connected_number_and_never_an_uncertain_empty_one():
    http, body = sl.host_device_response("CONNECTED", "5511@s.whatsapp.net", "9@lid")
    assert http == 200 and body["response"]["phoneNumber"] == {"_serialized": "5511@s.whatsapp.net"}
    # freshly started bridge: a 200 with an empty number was read as "unlinked"
    for status, me in (("INITIALIZING", ""), ("CONNECTED", ""), ("CLOSED", "5511@s.whatsapp.net"),
                       ("INITIALIZING", "5511@s.whatsapp.net")):
        assert sl.host_device_response(status, me, "")[0] == 503
    # really unlinked: 200 without a number, like WPPConnect
    for status in ("notLogged", "QRCODE"):
        assert sl.host_device_response(status, "", "") == (
            200, {"status": "success", "response": {}})


def test_deletable_status_only_my_own_on_the_wall():
    assert sl.deletable_status({"fromMe": True, "to": "status@broadcast"})
    assert not sl.deletable_status({"fromMe": False, "to": "status@broadcast"})
    assert not sl.deletable_status({"fromMe": True, "to": "5511@c.us"})
    assert not sl.deletable_status(None)


def test_expired_code_carries_no_phone_and_is_the_name_the_client_speaks():
    notice = sl.code_expired_notice("account1")
    assert notice["name"] == "LinkCodeExpired" and notice["rateLimited"] is False
    assert sl.CODE_LIFETIME > 0


# ------------------------------------------------- Session with a fake client
class FakeClient:
    """neonize's Go Neonize() only returns on stop(); disconnect() only closes the socket."""

    def __init__(self):
        self.stopped = threading.Event()
        self.calls = []
        self.is_connected = True

    def disconnect(self):
        self.calls.append("disconnect")

    def stop(self):
        self.calls.append("stop")
        self.stopped.set()

    def logout(self):
        self.calls.append("logout")


@pytest.fixture
def session(tmp_path, monkeypatch):
    s = server.Session("account1", str(tmp_path / "account1"), None, None)
    s.events = []
    s.emit = lambda event, data: s.events.append((event, data))
    s.clients = []
    s.generations = []

    def fake_run(self, phone_number, generation):
        cli = self.client = FakeClient()
        self.clients.append(cli)
        self.generations.append(generation)
        try:
            cli.stopped.wait(10)
        finally:
            self._apply(generation, sl.THREAD_ENDED)

    monkeypatch.setattr(server.Session, "_run", fake_run)
    return s


def _wait(condition, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_close_and_start_on_the_same_session_bring_up_a_new_thread(session):
    """Defect 1: stop() only did disconnect(); neonize's connect() did not
    return, the thread stayed alive and the next start-session left early,
    with the state stuck in CLOSED."""
    assert session.begin() is True
    first = session.thread
    assert _wait(lambda: session.clients)
    session.lifecycle.apply(session.generations[0], sl.CONNECTED_EVENT)
    assert session.status == "CONNECTED"

    session.stop()
    assert session.status == "CLOSED"
    assert session.clients[0].calls == ["disconnect", "stop"]

    assert session.begin() is True                 # the client's start-session
    assert session.thread is not first
    assert not first.is_alive()
    assert _wait(lambda: len(session.clients) == 2)
    assert session.status == "INITIALIZING"          # it did not stay CLOSED
    session.stop()
    session.thread.join(3)


def test_start_with_the_session_up_does_not_create_another_thread(session):
    assert session.begin() is True
    thread = session.thread
    assert _wait(lambda: session.clients)
    assert session.begin() is False
    assert session.thread is thread
    session.stop()
    thread.join(3)


def test_late_end_of_the_old_thread_does_not_close_the_new_session(session):
    session.begin()
    assert _wait(lambda: session.clients)
    old = session.generations[0]
    session.stop()
    session.thread.join(3)
    session.begin()
    assert _wait(lambda: len(session.clients) == 2)
    session.lifecycle.apply(session.generations[1], sl.CONNECTED_EVENT)
    assert session._apply(old, sl.THREAD_ENDED) is None
    assert session.status == "CONNECTED"
    session.stop()
    session.thread.join(3)


def test_a_thread_that_does_not_finish_does_not_get_a_sibling(session, monkeypatch):
    monkeypatch.setattr(sl, "OLD_THREAD_DEADLINE", 0.2)
    session.begin()
    assert _wait(lambda: session.clients)
    client = session.clients[0]
    client.stop = lambda: client.calls.append("stop")      # Go does not return
    session.stop()
    assert session.begin() is False
    assert len(session.clients) == 1 and session.status == "CLOSED"
    client.stopped.set()
    session.thread.join(3)


def test_stop_without_a_client_or_thread_does_not_break(session):
    session.stop()
    assert session.status == "CLOSED"


def test_leave_clears_the_identity(session):
    session.begin()
    assert _wait(lambda: session.clients)
    session.me, session.lid = "5511@s.whatsapp.net", "9@lid"
    session.leave()
    assert session.me == "" and session.lid == "" and session.status == "CLOSED"
    assert session.clients[0].calls[0] == "logout"
    session.thread.join(3)


# ------------------------------------------------------- neonize events
def _connected(session):
    session.begin()
    assert _wait(lambda: session.clients)
    g = session.generations[0]
    session.me, session.lid = "5511@s.whatsapp.net", "9@lid"
    session.lifecycle.apply(g, sl.CONNECTED_EVENT)
    return g, session.clients[0]


def test_logout_from_the_phone_notifies_in_order_clears_the_identity_and_stops_the_client(
        session, monkeypatch):
    monkeypatch.setattr(sl, "SESSION_LOGGED_DELAY", 0.05)
    unlinked = []
    session.on_unlink = lambda: unlinked.append(1)
    g, cli = _connected(session)

    session._on_unlinked(g, cli)
    assert session.status == "notLogged"     # the client's state query reads it as an unlink
    assert session.me == "" and session.lid == ""
    assert unlinked == [1]
    assert _wait(lambda: "stop" in cli.calls)
    assert _wait(lambda: len(session.events) == 2)
    assert [e[0] for e in session.events] == ["status-find", "session-logged"]
    assert session.events[1][1]["status"] is False

    session._on_unlinked(g, cli)     # ConnectFailure and LoggedOut of the same logout
    time.sleep(0.15)
    assert len(session.events) == 2 and unlinked == [1]
    session.stop()                          # the close-session the client sends afterwards
    assert session.status == "notLogged"
    session.thread.join(3)


def test_connecting_stores_the_identity_only_for_the_current_generation(session, monkeypatch):
    from types import SimpleNamespace as N
    for name in ("_load_names", "_check_state", "_check_always", "_copy_always"):
        monkeypatch.setattr(server.Session, name, lambda self: None)
    session.begin()
    assert _wait(lambda: session.clients)
    g = session.generations[0]
    c = N(get_me=lambda: N(JID=N(User="5511", Server="s.whatsapp.net"), LID=N(User="9", Server="lid")))

    session._on_connect(g + 1, c, None)             # event of a generation that is not the current one
    assert session.me == "" and session.status == "INITIALIZING" and session.events == []
    session._on_connect(g, c, None)
    assert session.me == "5511@s.whatsapp.net" and session.lid == "9@lid"
    assert session.status == "CONNECTED"
    assert session.events == [("session-logged", {"session": "account1", "status": True})]
    session.stop()
    session.thread.join(3)


def test_drop_becomes_initializing_and_the_return_restores(session):
    g, _ = _connected(session)
    session._on_drop(g, sl.DROPPED, "disconnected")
    assert session.status == "INITIALIZING"
    session._on_drop(g, sl.RESTORED, "keep-alive restored")
    assert session.status == "CONNECTED"
    session.stop()
    session.thread.join(3)
    session._on_drop(g, sl.DROPPED, "disconnected")     # late event of the closed session
    assert session.status == "CLOSED"


def test_terminal_failure_closes_the_session_and_stops_the_client(session):
    g, cli = _connected(session)
    session._on_terminal_failure(g, cli, "temporary ban")
    assert session.status == "terminalFailure"       # not CLOSED: the client would restart
    assert _wait(lambda: "stop" in cli.calls)
    session.thread.join(3)
    assert session.status == "terminalFailure"       # the end of connect() does not erase it


def test_connect_failure_by_reason(session):
    g, cli = _connected(session)
    session._on_fail(g, cli, 8)                    # server failure: transient
    assert session.status == "INITIALIZING"
    session._on_fail(g, cli, 6)                    # old version: terminal
    assert session.status == "terminalFailure"
    session.thread.join(3)


def test_logout_connect_failure_unlinks(session):
    g, cli = _connected(session)
    session._on_fail(g, cli, 4)
    assert session.status == "notLogged"
    session.thread.join(3)


def test_each_lifecycle_event_is_registered_once_in_the_server():
    found = registrations()
    for kind in ("ConnectedEv", "LoggedOutEv", "DisconnectedEv", "ConnectFailureEv",
                 "ClientOutdatedEv", "TemporaryBanEv", "StreamReplacedEv", "StreamErrorEv",
                 "KeepAliveTimeoutEv", "KeepAliveRestoredEv"):
        assert len(found[kind]) == 1, kind
        assert found[kind][0].startswith("server.py"), kind


# ------------------------------------------------- pairing code
def test_a_code_that_expires_without_pairing_warns_once_and_does_not_generate_another(session):
    session.begin()
    assert _wait(lambda: session.clients)
    g = session.generations[0]
    session.lifecycle.apply(g, sl.QR)
    session._watch_code(g, lifetime=0.1, step=0.02)
    assert [e[0] for e in session.events] == ["phoneCodeError"]
    assert session.events[0][1]["name"] == "LinkCodeExpired"
    session.stop()
    session.thread.join(3)


def test_a_paired_code_or_one_from_an_old_session_warns_nothing(session):
    session.begin()
    assert _wait(lambda: session.clients)
    g = session.generations[0]
    session.lifecycle.apply(g, sl.QR)
    session.lifecycle.apply(g, sl.CONNECTED_EVENT)            # paired before expiring
    session._watch_code(g, lifetime=0.1, step=0.02)
    session.lifecycle.apply(g, sl.QR)
    session.stop()                                  # closed: the generation is no longer the current one
    session._watch_code(g, lifetime=0.1, step=0.02)
    assert session.events == []
    session.thread.join(3)
