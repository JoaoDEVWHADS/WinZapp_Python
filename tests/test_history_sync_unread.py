"""Regression tests for unread recovery after an offline history sync."""

from main import unread_after_history_sync


def _message(mid, timestamp, *, from_me=False, message_type="conversation"):
    return {
        "key": {"id": mid, "fromMe": from_me},
        "messageTimestamp": timestamp,
        "messageType": message_type,
    }


def test_new_incoming_after_last_local_message_becomes_unread():
    local = [_message("old", 100)]
    fetched = local + [_message("new-1", 101), _message("new-2", 102)]
    assert unread_after_history_sync(0, 0, fetched, local) == 2


def test_own_messages_and_technical_notifications_do_not_become_unread():
    local = [_message("old", 100)]
    fetched = local + [
        _message("mine", 101, from_me=True),
        _message("technical", 102, message_type="e2e_notification"),
    ]
    assert unread_after_history_sync(0, 0, fetched, local) == 0


def test_old_backfill_does_not_become_unread():
    local = [_message("known", 100)]
    fetched = [_message("older", 50)] + local
    assert unread_after_history_sync(0, 0, fetched, local) == 0


def test_existing_local_unread_is_preserved_and_new_arrivals_are_added():
    local = [_message("old", 100)]
    fetched = local + [_message("new", 101)]
    assert unread_after_history_sync(0, 3, fetched, local) == 4
