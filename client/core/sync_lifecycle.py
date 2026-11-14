"""Ownership of delayed sync work, independent of wx and account data."""

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class SyncContext:
    run: int
    token: object
    server: object
    port: object


def capture_sync_context(window):
    values = vars(window)
    def value(name, default=None):
        return values.get(name, getattr(type(window), name, default))
    return SyncContext(value("_sync_run_id", 0), value("token"),
                       value("wpp_server"), value("wpp_port"))


def sync_context_is_current(window, context, *, require_online=False):
    if context != capture_sync_context(window):
        return False
    values = vars(window)
    if any(values.get(flag, False) for flag in
           ("_shutting_down", "_wpp_updating", "_user_offline")):
        return False
    return not require_online or (
        values.get("_wa_connected", False) and not values.get("offline_mode", False))


def message_response(body):
    """Missing/invalid envelope is unknown; only an explicit list is a page."""
    if isinstance(body, dict) and isinstance(body.get("response"), list):
        return body["response"]
    return None


def chat_content_identity(chat):
    """Detached immutable snapshot of the JSON message tree, including edits/stars."""
    def freeze(value):
        if isinstance(value, dict):
            return frozenset((key, freeze(item)) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return tuple(freeze(item) for item in value)
        if isinstance(value, (set, frozenset)):
            return frozenset(freeze(item) for item in value)
        if isinstance(value, bytearray):
            return bytes(value)
        return value
    records = ((chat or {}).get("messages") or {}).get("messages") or {}
    return freeze(records)


def record_phone_request_attempt(window, jid, result, outcome, now):
    """Only a send or ambiguous send spends the phone notification budget."""
    if result is not True and not outcome.get("ambiguous"):
        return
    attempts = window._older_request_attempts
    attempts[jid] = attempts.get(jid, 0) + 1
    if outcome.get("ambiguous"):
        window._older_requested_chats[jid] = now
        window._persist_older_requested()


def schedule_backfill(window):
    """One worker, with a remembered request when a newer round takes over."""
    context = capture_sync_context(window)
    if not sync_context_is_current(window, context):
        return
    lock = vars(window).setdefault("_history_worker_lock", threading.RLock())
    with lock:
        window._history_requested_context = context
        worker = vars(window).get("_history_worker")
        if worker is not None:
            return
        existing = vars(window).get("_backfill_thread")
        if existing is not None and existing.is_alive():
            return

        def run():
            try:
                if sync_context_is_current(window, context):
                    window._backfill_empty_chats(expected_context=context)
            finally:
                with lock:
                    if window._history_worker is not worker:
                        return
                    window._history_worker = None
                    window._backfill_thread = None
                    wanted = window._history_requested_context
                if wanted != context and sync_context_is_current(window, wanted):
                    schedule_backfill(window)

        worker = threading.Thread(target=run, daemon=True, name="chat-backfill")
        window._history_worker = window._backfill_thread = worker
        try:
            worker.start()
        except Exception:
            window._history_worker = window._backfill_thread = None
            raise
