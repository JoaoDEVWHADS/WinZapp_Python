from tests.mocks import MockMainWindow


class TestBug9SyncThreadLock:
    """Bug 9: TOCTOU race on sync_thread must be locked."""

    def test_sync_thread_lock_exists(self):
        mw = MockMainWindow()
        assert hasattr(mw, "_sync_thread_lock")
        assert hasattr(mw._sync_thread_lock, "acquire")
        assert hasattr(mw._sync_thread_lock, "release")

    def test_sync_thread_lock_prevents_duplicate(self):
        mw = MockMainWindow()
        lock = mw._sync_thread_lock
        with lock:
            acquired = lock.acquire(blocking=False)
            assert not acquired, "Lock should already be held (reentrant not allowed)"
