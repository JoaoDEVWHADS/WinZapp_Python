"""The lifecycle of a session: which one is current, what state it is in and what
each neonize event changes. Pure logic, no neonize and no asyncio, tested in
test_session_lifecycle.py.

Why there is a "generation". neonize's `connect()` blocks the thread until Go's
context is canceled by `stop()` (neonize/client.py: Go's `Neonize()` "only
returns when the context is canceled via Stop"; `disconnect()` only closes the
socket). Closing the session without `stop()` left the thread alive and the
next `start-session` returned early, with the state stuck in CLOSED. Now each
`open()` opens a new generation and `end()` invalidates it: an old thread that
wakes up later (end of `connect()`, late event) sees that it is no longer the
current one and does not touch the new one's state.
"""
import threading

CLOSED = "CLOSED"
INITIALIZING = "INITIALIZING"
QRCODE = "QRCODE"
CONNECTED = "CONNECTED"
# Unlinked account (the phone removed the device). It is WPPConnect's `notLogged`,
# which the client (connection_state.UNLINKED_STATES) reads as "unlinked" through
# the state query; CLOSED would make it restart the session and ask for a QR unannounced.
NOT_LOGGED = "notLogged"
# Terminal failure (ban, outdated version, another device took the connection).
# With CLOSED the client's health check (every 30 s) would call start-session
# nonstop, and reconnecting a banned account only makes it worse. Any other text
# that is not CLOSED/DESTROYED/empty nor an unlink state is read by the client as
# "session in an active state": it stays offline and does not restart on its own
# (main_window/connection.py::check_wa_connection_http). Only a start-session
# asked from outside (or the end of the failure) takes the session out of here.
TERMINAL = "terminalFailure"

# States in which the session was ended: a thread still alive there is just
# finishing, and a new start-session can replace it.
ENDED = (CLOSED, NOT_LOGGED, TERMINAL)

# The ones a client's close-session does not erase: the notice stays valid.
PERMANENT = (NOT_LOGGED, TERMINAL)

# How long start-session waits for the old thread to finish after stop().
OLD_THREAD_DEADLINE = 10.0

# Decisions of `decide_start`.
START = "start"
RESTART = "restart"
IGNORE = "ignore"


def decide_start(thread_alive, status, phone_number) -> str:
    """What a start-session does: START (there is no thread), RESTART (there is a
    thread that has to stop first: it is finishing after a close or logout, or is
    a stalled pairing attempt that the phone restarts) or IGNORE (it is already up)."""
    if not thread_alive:
        return START
    if status in ENDED or (phone_number and status == QRCODE):
        return RESTART
    return IGNORE


# Events of the thread/neonize that change the state.
CONNECTED_EVENT = "connected"
QR = "qr"
DROPPED = "dropped"                 # DisconnectedEv, KeepAliveTimeoutEv, transient failure
RESTORED = "restored"               # KeepAliveRestoredEv
LEFT = "left"                       # LoggedOutEv: the phone removed the device
TERMINAL_FAILURE = "terminal_failure"   # banned, outdated version, another device took the connection
THREAD_ENDED = "thread_ended"       # connect() returned


def next_state(status, degraded, event):
    """(new status, degraded) after `event`. `degraded` remembers that it was us
    who took the session out of CONNECTED (drop or keep-alive), so the "restored"
    notice only restores what the drop took away."""
    if event == CONNECTED_EVENT:
        return CONNECTED, False
    if event == QR:
        return QRCODE, False
    if event == DROPPED:
        if status == CONNECTED:
            return INITIALIZING, True
        return status, degraded
    if event == RESTORED:
        if status == INITIALIZING and degraded:
            return CONNECTED, False
        return status, degraded
    if event == LEFT:
        return NOT_LOGGED, False
    if event == TERMINAL_FAILURE:
        return (status, degraded) if status in PERMANENT else (TERMINAL, False)
    if event == THREAD_ENDED:
        return (status, degraded) if status in ENDED else (CLOSED, False)
    return status, degraded


class Lifecycle:
    """State and generation of a session, under a lock: the state only changes by
    whoever is still the current generation."""

    def __init__(self):
        self._lock = threading.Lock()
        self.status = CLOSED
        self.generation = 0
        self.degraded = False

    def open(self) -> int:
        """New generation, in INITIALIZING; returns its number."""
        with self._lock:
            self.generation += 1
            self.status = INITIALIZING
            self.degraded = False
            return self.generation

    def end(self, status=None):
        """Invalidates the current generation: whatever it still says is ignored.
        Without `status`, it becomes CLOSED, except an unlinked account or one
        with a terminal failure, which stay as they are (the close-session the
        client sends afterwards does not erase the notice)."""
        with self._lock:
            self.generation += 1
            if status is None:
                status = self.status if self.status in PERMANENT else CLOSED
            self.status = status
            self.degraded = False

    def current(self, generation) -> bool:
        return generation == self.generation

    def apply(self, generation, event):
        """Applies `event` if `generation` is the current one. Returns (before, after)
        or None when the event is from an old generation."""
        with self._lock:
            if generation != self.generation:
                return None
            before = self.status
            self.status, self.degraded = next_state(before, self.degraded, event)
            return before, self.status


# neonize's ConnectFailureReason (Neonize.proto): GENERIC 1, LOGGED_OUT 2,
# TEMP_BANNED 3, MAIN_DEVICE_GONE 4, UNKNOWN_LOGOUT 5, CLIENT_OUTDATED 6,
# BAD_USER_AGENT 7, INTERNAL_SERVER_ERROR 8, EXPERIMENTAL 9, SERVICE_UNAVAILABLE 10.
LOGOUT_REASONS = (2, 4, 5)
TERMINAL_REASONS = (3, 6, 7)


def classify_failure(reason) -> str:
    """What a ConnectFailureEv means: LEFT (the device was removed),
    TERMINAL_FAILURE (repeating does not help and may make it worse: ban,
    outdated version) or DROPPED (server failure, transient)."""
    if reason in LOGOUT_REASONS:
        return LEFT
    if reason in TERMINAL_REASONS:
        return TERMINAL_FAILURE
    return DROPPED


# The client (websocket_client.on_wpp_status_find) only handles the unlink if it
# still sees itself as connected, and python-socketio runs each event on a thread
# of its own: sent together, session-logged(false) could clear "connected" first
# and the status-find be ignored. That is why the status-find goes first and the
# other after.
SESSION_LOGGED_DELAY = 1.5


def logout_notices(name):
    """[(delay in seconds, event, data)] that the client receives when the phone
    removes the device, in the order they must go out."""
    return [(0.0, "status-find", {"session": name, "status": NOT_LOGGED}),
            (SESSION_LOGGED_DELAY, "session-logged", {"session": name, "status": False})]


# How long a phone pairing code lives. GUESS: there is no way to measure it
# without an account; 195 s is the interval at which wa-js renews the code in
# WPPConnect (docs/traps/pairing-flow.md), so the code does not die before that.
# Warning a bit late is better than warning that a still-valid code died.
CODE_LIFETIME = 195.0


def code_expired_notice(name) -> dict:
    """phoneCodeError that the client says out loud (`LinkCodeExpired`). Without
    phone and without a new code: generating another with nobody asking spends
    the per-number quota (docs/traps/pairing-flow.md)."""
    return {"session": name, "name": "LinkCodeExpired",
            "message": "the pairing code expired", "rateLimited": False}


def host_device_response(status, me, lid):
    """(http, body) of GET host-device. Only CONNECTED with an identity gives the
    number. QRCODE and unlinked say, like WPPConnect, that there is no linked
    number (body without `phoneNumber`): it is the only response the client reads
    as "unlinked" and the one it checks before erasing local data. Any other state
    (freshly started bridge, reconnecting, closed) does not know yet: 503, which
    the client reads as "I do not know" and never as an unlink."""
    if status == CONNECTED and me:
        return 200, {"status": "success", "response": {
            "phoneNumber": {"_serialized": me}, "wid": {"_serialized": me},
            "lid": {"_serialized": lid}}}
    if status in (QRCODE, NOT_LOGGED):
        return 200, {"status": "success", "response": {}}
    return 503, {"status": "error", "message": "The WhatsApp session is not connected."}


def deletable_status(message) -> bool:
    """True if the stored message is a status of mine (only those does status/{id}/delete delete)."""
    return (isinstance(message, dict) and bool(message.get("fromMe"))
            and message.get("to") == "status@broadcast")
