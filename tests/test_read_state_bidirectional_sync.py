"""Regression tests for read-state synchronization across linked devices."""

from main import MainWindow, reconcile_snapshot_unread


JID = "5511999999999@s.whatsapp.net"


def test_current_remote_zero_clears_unread_from_phone_even_when_archived():
    assert reconcile_snapshot_unread(0, 4, 2000, 2000) == 0


def test_snapshot_older_than_a_live_arrival_cannot_clear_it():
    assert reconcile_snapshot_unread(0, 1, 1000, 1001) == 1


def test_unsynced_live_chat_keeps_its_local_count():
    assert reconcile_snapshot_unread(0, 2, 2000, 2000, unsynced=True) == 2


def test_higher_remote_count_is_always_accepted():
    assert reconcile_snapshot_unread(5, 2, 2000, 1000) == 5


class _RollbackStub:
    _restore_unread_after_send_seen_failure = (
        MainWindow._restore_unread_after_send_seen_failure
    )
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self, *, archived=False):
        self.chats = {
            JID: {
                "unreadCount": 0,
                "t": 2000,
                "archived": archived,
            }
        }
        self._locally_read_at = {JID: 2000}
        self._new_since_read = {JID: 0}
        self.persisted = 0
        self.saved = []
        self.refreshed = []
        self.list_refreshes = 0

    def _persist_locally_read_at(self):
        self.persisted += 1

    def _schedule_save(self, dirty_jid=None):
        self.saved.append(dirty_jid)

    def _refresh_chat_row_in_list(self, jid):
        self.refreshed.append(jid)

    def _schedule_set_chats(self):
        self.list_refreshes += 1


def test_failed_send_seen_restores_normal_chat_unread_state():
    stub = _RollbackStub()

    stub._restore_unread_after_send_seen_failure(JID, 3, 2000)

    assert stub.chats[JID]["unreadCount"] == 3
    assert JID not in stub._locally_read_at
    assert stub.saved == [JID]


def test_failed_send_seen_restores_archived_chat_unread_state():
    stub = _RollbackStub(archived=True)

    stub._restore_unread_after_send_seen_failure(JID, 3, 2000)

    assert stub.chats[JID]["unreadCount"] == 3
    assert stub.chats[JID]["archived"] is True


def test_failed_send_seen_does_not_overwrite_a_new_message():
    stub = _RollbackStub()
    stub.chats[JID]["unreadCount"] = 1
    stub.chats[JID]["t"] = 2001
    stub._new_since_read[JID] = 1

    stub._restore_unread_after_send_seen_failure(JID, 3, 2000)

    assert stub.chats[JID]["unreadCount"] == 1
    assert stub._locally_read_at[JID] == 2000
