from concurrent.futures import ThreadPoolExecutor
from tests.mocks import MockMainWindow


class TestBug7MediaThreadPool:
    """Bug 7: Media downloads must use bounded thread pool, not unbounded threads."""

    def test_media_pool_exists(self):
        mw = MockMainWindow()
        assert hasattr(mw, "_media_pool")

    def test_media_pool_max_workers(self):
        mw = MockMainWindow()
        assert mw._media_pool._max_workers == 6
