"""Account-local pin order, independent of message activity and display names."""

import logging
import math
import threading

METADATA_KEY = "pinned_chat_order"
_state_lock = threading.Lock()


def keep_pinned_order(window):
    return bool(getattr(window, "settings", {}).get("user_interface", {}).get(
        "keep_pinned_chat_order", False))


def canonical_pin_jid(window, jid):
    """Bridge only known identities; never derive a phone number from a LID."""
    if not isinstance(jid, str) or "@" not in jid:
        return ""
    normalize = window._normalize_jid
    jid = normalize(jid)
    if jid.endswith("@lid"):
        # _phone_to_lid is always written in pairs with _lid_to_phone, so a
        # reverse scan could only revive a mapping identity cleanup dropped.
        phone = getattr(window, "_lid_to_phone", {}).get(jid)
        if phone:
            jid = normalize(phone)
    return jid


def pin_timestamp(value):
    """A numeric server pin time is useful; a boolean is not a timestamp."""
    if isinstance(value, bool):
        return 0
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(value) or value <= 1_000_000:
        return 0
    return value / 1000 if value > 1e12 else value


def reconcile_pin_order(previous, pinned, timestamps=None, seed=()):
    """Keep existing ranks; newly pinned chats precede the retained group.

    On the first load, server pin times seed the order. For boolean-only pins,
    use the existing visible order, then a deterministic identity tie-break.
    Neither a later message nor a contact rename changes a retained rank.
    """
    pinned = set(pinned)
    retained = list(dict.fromkeys(jid for jid in previous if jid in pinned))
    positions = {jid: index for index, jid in reversed(list(enumerate(seed)))}
    times = timestamps or {}
    added = sorted(pinned.difference(retained), key=lambda jid: (
        -times.get(jid, 0), positions.get(jid, len(positions)), jid))
    return added + retained


class _PinOrderState:
    def __init__(self):
        self.lock = threading.RLock()
        self.order = None
        self.persisted = None
        self.retired = False


def reset_pinned_order(window):
    """Finish an in-flight order write before the account's metadata is wiped."""
    with _state_lock:
        state = getattr(window, "_pinned_order_state", None)
        if isinstance(state, _PinOrderState):
            with state.lock:
                state.retired = True
        window._pinned_order_state = None


def sync_pinned_order(window, *, pinned=None, restore=None, chats=None):
    """Reconcile once per list pass or pin transition, with a cached DB read.

    The state and metadata belong to this account. clear_local_data resets
    the state when it wipes metadata; an F5 resync preserves both.
    """
    with _state_lock:
        if pinned is not None and pinned is not getattr(window, "_pinned_chats", pinned):
            # A list build that captured the pinned set before an account
            # wipe replaced it: its ranks are moot, and saving them would
            # carry the previous account's pins into the new account. Checked
            # under the lock reset_pinned_order() takes, so a build that sees
            # the old set gets a state the reset retires before the DB wipe.
            return ()
        state = getattr(window, "_pinned_order_state", None)
        if state is None:
            state = window._pinned_order_state = _PinOrderState()
    with state.lock:
        if state.retired:
            return ()
        db = getattr(window, "db", None)
        if state.order is None:
            if db is None:
                # A reused pairing socket can deliver a pin event before the
                # account database opens; caching [] now would hide the saved
                # order for the rest of the session.
                return ()
            stored = []
            try:
                stored = db.get_metadata_json(METADATA_KEY, [])
            except Exception:
                logging.exception("[pin-order] Could not read saved order")
            state.order = stored if isinstance(stored, list) else []
            state.persisted = list(state.order)
        canon = lambda jid: canonical_pin_jid(window, jid)
        members = {canon(jid) for jid in set(
            getattr(window, "_pinned_chats", set()) if pinned is None else pinned)} - {""}
        previous = state.order if restore is None else restore
        previous = [canon(jid) for jid in previous]
        # Server times and the visible order only place newly pinned chats,
        # so the usual pass (no new pin) skips scanning every chat and row.
        added = members.difference(previous)
        times, seed = {}, []
        if added:
            snapshot = list(dict(getattr(window, "chats", {})).values()) if chats is None else chats
            for chat in snapshot:
                if isinstance(chat, dict):
                    jid = canon(chat.get("remoteJid"))
                    if jid in added:
                        times[jid] = max(times.get(jid, 0), pin_timestamp(chat.get("pin")))
            panel = getattr(window, "conversations_panel", None)
            seed = [canon(jid) for jid in getattr(panel, "_displayed_jids", ())]
        order = reconcile_pin_order(previous, members, times, seed)
        state.order = order
        if db is not None and order != state.persisted:
            try:
                db.set_metadata_json(METADATA_KEY, order)
                state.persisted = list(order)
            except Exception:
                logging.exception("[pin-order] Could not save order")
        return tuple(order)


def pinned_chat_ranks(window, pinned=None):
    return {jid: rank for rank, jid in enumerate(sync_pinned_order(window, pinned=pinned))}


def refresh_after_order_setting_change(window, previous):
    """Apply/OK must recompute, not reuse sorted arrays."""
    if keep_pinned_order(window) != previous:
        # The Settings dialog also runs against a bare frame (its own tests);
        # only a MainWindow has a chat list to recompute.
        schedule = getattr(window, "_schedule_set_chats", None)
        if callable(schedule):
            schedule()
