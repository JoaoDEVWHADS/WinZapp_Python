"""One request at a time for a fresh copy of an app-state collection.

When a collection's LTHash stops matching, the bridge asks the phone for a
fresh copy and waits up to 90 s for it (an iPhone only answers with WhatsApp
open on the screen). Reported: on one account `regular_low` stayed broken, and
every chat the user opened (send-seen -> markChatAsRead) started its own
request and its own 90 s wait, each on a thread of the executor the sends use
too. A message then waited past the client's 25 s, was reported as not
confirmed, and went out a moment later.

`RecoveryGate` lets one request run per collection: another caller meanwhile
gives up at once instead of waiting, and after a request the phone did not
answer, nobody asks again for COOLDOWN seconds. Giving up only skips the state
notice (the chat's "read" on the phone); the read receipts to the contact are
sent as before. Tested in test_app_state_recovery.py.
"""
import threading
import time

#: seconds after an unanswered request before the phone is asked again
COOLDOWN = 120.0


class RecoveryGate:
    def __init__(self, clock=time.monotonic, cooldown=COOLDOWN):
        self._clock = clock
        self._cooldown = cooldown
        self._guard = threading.Lock()
        self._running = set()
        self._failed_at = {}

    def run(self, name, recover):
        """`recover()` for collection `name` unless one is running or one just
        went unanswered; False without calling it then."""
        with self._guard:
            failed = self._failed_at.get(name)
            if name in self._running or (
                    failed is not None and self._clock() - failed < self._cooldown):
                return False
            self._running.add(name)
        recovered = False
        try:
            recovered = bool(recover())
            return recovered
        finally:
            with self._guard:
                self._running.discard(name)
                if recovered:
                    self._failed_at.pop(name, None)
                else:
                    self._failed_at[name] = self._clock()


# ── One app-state operation at a time ────────────────────────────────────────
#
# Why the collection kept breaking right after each recovery: whatsmeow's
# fetchAppState holds appStateSyncLock, but sendAppState does not. Two state
# notices sent together (several chats marked read at once, an archive while
# a notice from the phone is being fetched) read the same version; the second
# gets 409, applies the conflicting patches on top of a version the first one
# already moved past, and the local LTHash no longer matches the server's.
# WhatsApp Web keeps one queue per collection. The bridge's own calls now go
# through one lock (whatsmeow's internal fetches are covered by
# neonize_patches/whatsmeow/0008).

def serialize(client, lock):
    """Make the client's send_app_state and fetch_app_state take `lock`, so
    the bridge never runs two app-state operations at once, wherever they come
    from (state notices, labels, contacts, the mirror). A client without them
    (a test's stand-in) is left alone."""
    for name in ("send_app_state", "fetch_app_state"):
        original = getattr(client, name, None)
        if original is None:
            continue

        def locked(*args, _original=original, **kwargs):
            with lock:
                return _original(*args, **kwargs)

        setattr(client, name, locked)


class PendingReads:
    """The chats whose read/unread notice the phone has not taken yet, the
    newest wish for each. WhatsApp Web keeps an unsent mutation and sends it
    once the collection works again; dropping it left the chat unread on the
    phone after it was read in WinZapp."""

    def __init__(self):
        self._guard = threading.Lock()
        self._wanted = {}

    def put(self, chat, read):
        with self._guard:
            self._wanted[chat] = bool(read)

    def restore(self, chat, read):
        """Put back a notice that failed again, unless a newer wish for the
        same chat arrived meanwhile (that one wins)."""
        with self._guard:
            self._wanted.setdefault(chat, bool(read))

    def discard(self, chat):
        with self._guard:
            self._wanted.pop(chat, None)

    def take(self):
        """Every pending (chat, read), emptied: whoever takes them sends them
        (and puts back the ones that fail again)."""
        with self._guard:
            items, self._wanted = list(self._wanted.items()), {}
        return items

    def __len__(self):
        with self._guard:
            return len(self._wanted)
