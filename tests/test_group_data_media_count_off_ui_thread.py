"""Issue #52 (group data loading freeze): _populate_group_unsafe() used to
count local media files for a group by calling os.path.isfile() once per
media message in a synchronous loop — and that method runs via
wx.CallAfter(), i.e. on the main/UI thread. A busy group can have hundreds
of media messages, so that loop blocked the UI thread right as the dialog
finished loading its data — reported live as a freeze specifically while
switching between the dialog's tabs, which is just when a user's input
happens to land during that window.

The count now runs in _count_group_media(), called from _fetch_data() (the
background thread) before scheduling wx.CallAfter — _populate_group_unsafe()
just reads the precomputed value back off `data`.

ConversationDataDialog is a wx.Dialog and can't be instantiated without a
running wx.App, and _populate_group_unsafe() builds real wx widgets, so the
threading placement is checked structurally via source inspection (same
approach as tests/test_group_data_dialog_admin_ui.py) — _count_group_media()
itself, a plain function of self._chat and the filesystem, is exercised
directly against a small stub.
"""

import inspect
import os

from ui.dialogs import conversation_data_dialog as cdd
from ui.dialogs.conversation_data_dialog import ConversationDataDialog


class TestMediaCountRunsOffTheUiThread:
    def test_fetch_data_computes_the_count_before_scheduling_callafter(self):
        src = inspect.getsource(ConversationDataDialog._fetch_data)
        assert 'data["_media_count"] = self._count_group_media()' in src
        # Must happen strictly before the CallAfter that hands off to the
        # main-thread populate method.
        count_idx = src.index('data["_media_count"]')
        callafter_idx = src.index("wx.CallAfter(self._populate_group, data)")
        assert count_idx < callafter_idx

    def test_populate_group_unsafe_no_longer_stats_the_filesystem(self):
        """The regression itself: the blocking os.path.isfile() loop must be
        gone from the main-thread method entirely."""
        src = inspect.getsource(ConversationDataDialog._populate_group_unsafe)
        assert "os.path.isfile" not in src
        assert 'data.get("_media_count"' in src

    def test_count_group_media_still_does_the_real_stat_check(self):
        src = inspect.getsource(ConversationDataDialog._count_group_media)
        assert "os.path.isfile" in src


class _Stub:
    _count_group_media = ConversationDataDialog._count_group_media

    def __init__(self, records):
        self._chat = {"messages": {"messages": {"records": records}}}


def _media_msg(msg_id, msg_type="imageMessage"):
    return {"key": {"id": msg_id}, "messageType": msg_type}


class TestCountGroupMediaBehaviour:
    def test_counts_only_media_types_with_a_locally_cached_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cdd, "data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        (media_dir / "m1.wzmedia").write_bytes(b"x")
        # m2 has no cached file on disk.

        stub = _Stub([
            _media_msg("m1", "imageMessage"),
            _media_msg("m2", "videoMessage"),
            _media_msg("m3", "conversation"),  # not a media type at all
        ])

        assert stub._count_group_media() == 1

    def test_composite_message_ids_are_reduced_to_the_real_media_id(self, tmp_path, monkeypatch):
        """Forwarded/queued message ids look like 'true_<chatId>_<realId>' —
        only the real id segment names the cached .wzmedia file."""
        monkeypatch.setattr(cdd, "data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        (media_dir / "realid.wzmedia").write_bytes(b"x")

        stub = _Stub([_media_msg("true_120363000000000001@g.us_realid", "documentMessage")])

        assert stub._count_group_media() == 1
