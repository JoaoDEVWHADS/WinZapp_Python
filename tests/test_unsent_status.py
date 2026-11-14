"""A status post that failed or went unconfirmed stays in the Status list,
right after "My status", with a context menu and Ctrl+Shift+Y (configurable
as status.ID_CTRL_SHIFT_Y) to try posting it again. Never posted again by
itself."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from core.shortcut_catalog import SHORTCUTS
from status_tab import status_composer, unsent_status
from status_tab.status_composer import StatusComposerMixin
from status_tab.status_list import StatusListMixin
from status_tab.unsent_status import (FAILED, MEDIA, TEXT, UNCONFIRMED, UnsentStatusMixin,
                                      can_retry, unsent_post, unsent_row_label)

I18N = SimpleNamespace(t=lambda key: {"status_unsent_row": "{what} | {state}"}.get(key, key))


class TestTheRow:
    def test_the_row_says_what_and_how_it_ended(self, tmp_path):
        video = unsent_post(MEDIA, FAILED, path=str(tmp_path / "clip.mp4"))
        assert unsent_row_label(video, I18N) == "clip.mp4 | status_unsent_failed"
        text = unsent_post(TEXT, UNCONFIRMED, text="a long private text")
        assert unsent_row_label(text, I18N) == "status_unsent_text | status_unsent_unconfirmed"

    def test_a_media_post_can_be_retried_while_its_file_is_there(self, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x")
        post = unsent_post(MEDIA, FAILED, path=str(clip))
        assert can_retry(post)
        clip.unlink()
        assert not can_retry(post)
        assert can_retry(unsent_post(TEXT, FAILED, text="t"))


class _List:
    def __init__(self):
        self.rows, self.focused = [], 0

    def DeleteAllItems(self):
        self.rows = []

    def Append(self, row):
        self.rows.append(row[0])

    def GetItemCount(self):
        return len(self.rows)

    def GetFocusedItem(self):
        return self.focused

    def Focus(self, row):
        self.focused = row

    def Select(self, row):
        pass

    def Freeze(self):
        self.frozen = getattr(self, "frozen", 0) + 1

    def Thaw(self):
        self.frozen -= 1


class _Panel(UnsentStatusMixin):
    _populate_list = StatusListMixin._populate_list
    _latest_ts = staticmethod(StatusListMixin._latest_ts)
    _begin_status_post = StatusComposerMixin._begin_status_post
    _end_status_post = StatusComposerMixin._end_status_post

    def __init__(self):
        self.main_window = SimpleNamespace(i18n=I18N, output=Mock())
        self._status_list = _List()
        self._viewer_panel = SimpleNamespace(Hide=lambda: None, IsShown=lambda: False)
        self._my_statuses, self._status_contacts = [], []
        self._send_text_status_bg = Mock()
        self._send_all_media_statuses_bg = Mock()

    def _my_status_label(self, i18n):
        return "My status"

    def Layout(self):
        pass


@pytest.fixture
def inline(monkeypatch):
    class _Thread:
        def __init__(self, target, args=(), daemon=True):
            self._run = lambda: target(*args)

        def start(self):
            self._run()

    monkeypatch.setattr(unsent_status.threading, "Thread", _Thread)


class TestTheList:
    def test_unsent_posts_follow_my_status(self):
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(TEXT, FAILED, text="t"))
        assert panel._status_list.rows == ["My status", "status_unsent_text | status_unsent_failed"]
        assert panel._unsent_post_at(1)["text"] == "t" and panel._unsent_post_at(0) is None

    def test_retry_sends_once_and_takes_the_row_out(self, inline):
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(TEXT, UNCONFIRMED, text="t"))
        panel._status_list.focused = 1
        panel._on_accel_retry_status_post()
        panel._send_text_status_bg.assert_called_once_with("t")
        assert panel._status_list.rows == ["My status"]
        panel._on_accel_retry_status_post()   # nothing left on that row
        panel._send_text_status_bg.assert_called_once()

    def test_a_media_retry_goes_through_the_batch_path(self, inline, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x")
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(MEDIA, FAILED, path=str(clip), caption="c"))
        panel._retry_unsent_status(panel._unsent_status_posts[0]["id"])
        panel._send_all_media_statuses_bg.assert_called_once_with([str(clip)], "c")

    def test_a_retry_while_posting_waits(self, inline):
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(TEXT, FAILED, text="t"))
        panel._status_post_in_flight = True
        panel._retry_unsent_status(panel._unsent_status_posts[0]["id"])
        panel._send_text_status_bg.assert_not_called()
        assert len(panel._unsent_status_posts) == 1

    def test_a_missing_file_is_said_and_kept(self, inline, tmp_path):
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(MEDIA, FAILED, path=str(tmp_path / "gone.mp4")))
        panel._retry_unsent_status(panel._unsent_status_posts[0]["id"])
        panel._send_all_media_statuses_bg.assert_not_called()
        panel.main_window.output.assert_called_with("status_retry_file_missing", interrupt=True)

    def test_discard_drops_the_row(self):
        panel = _Panel()
        panel._populate_list([], [])
        panel._remember_unsent_status(unsent_post(TEXT, FAILED, text="t"))
        panel._discard_unsent_status(panel._unsent_status_posts[0]["id"])
        assert panel._status_list.rows == ["My status"] and panel._unsent_status_posts == []

    def test_the_key_on_another_row_says_so(self):
        panel = _Panel()
        panel._populate_list([], [])
        panel._on_accel_retry_status_post()
        panel.main_window.output.assert_called_once_with("status_retry_not_available", interrupt=True)

    def test_the_menu_is_only_for_unsent_rows(self):
        panel = _Panel()
        panel._populate_list([], [])
        event = SimpleNamespace(Skip=Mock())
        panel._on_status_list_context_menu(event)
        event.Skip.assert_called_once()

    def test_it_is_catalogued_and_configurable(self):
        [shortcut] = [s for s in SHORTCUTS if s.id == "status.ID_CTRL_SHIFT_Y"]
        assert (shortcut.scope, shortcut.mod, shortcut.key) == ("status", 6, ord("Y"))


class _Composer:
    _send_text_status_bg = StatusComposerMixin._send_text_status_bg
    _send_all_media_statuses_bg = StatusComposerMixin._send_all_media_statuses_bg
    _end_status_post = StatusComposerMixin._end_status_post

    def __init__(self):
        self.main_window = SimpleNamespace(
            i18n=SimpleNamespace(t=lambda key: key), app_name="WinZapp",
            wpp_server="http://localhost", wpp_port=6300, token="token")
        self.remembered = []
        self._remember_unsent_status = self.remembered.append
        self._on_status_sent = Mock()


class TestThePostPathsRecordIt:
    @pytest.fixture(autouse=True)
    def _inline(self, monkeypatch):
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
        monkeypatch.setattr(wx, "MessageBox", Mock())

    def test_a_failed_text_post_is_kept(self, monkeypatch):
        monkeypatch.setattr(status_composer, "api_post", Mock(side_effect=ConnectionError("down")))
        composer = _Composer()
        composer._send_text_status_bg("hello")
        [post] = composer.remembered
        assert (post["kind"], post["state"], post["text"]) == (TEXT, FAILED, "hello")

    def test_a_posted_text_is_not(self, monkeypatch):
        # The answer of a status WhatsApp accepted (status_rules._post_was_rejected).
        accepted = {"response": [{"sendMsgResult": {"messageSendResult": "OK"}}]}
        monkeypatch.setattr(status_composer, "api_post", Mock(return_value=SimpleNamespace(
            status_code=201, text="", json=lambda: accepted)))
        composer = _Composer()
        composer._send_text_status_bg("hello")
        assert composer.remembered == []
        composer._on_status_sent.assert_called_once()

    def test_an_unconfirmed_media_post_is_kept_as_unconfirmed(self, tmp_path):
        composer = _Composer()
        composer._send_media_status_bg = lambda path, caption, **kw: status_composer.STATUS_POST_UNCONFIRMED
        clip = str(tmp_path / "clip.mp4")
        composer._send_all_media_statuses_bg([clip], "c")
        [post] = composer.remembered
        assert (post["kind"], post["state"], post["path"], post["caption"]) == (MEDIA, UNCONFIRMED, clip, "c")


class TestTheUserKeepsTheirPlace:
    """Reviewer: a failed upload rebuilt the list, closed the inline viewer
    and, the new row sitting above, put the focus on another contact."""

    def _with_contacts(self):
        panel = _Panel()
        panel._status_row_text = lambda entry, i18n: entry["name"]
        ana = {"name": "Ana", "statuses": [{"messageTimestamp": 2}]}
        bia = {"name": "Bia", "statuses": [{"messageTimestamp": 1}]}
        panel._populate_list([], [ana, bia])
        return panel, ana, bia

    def test_the_focus_stays_on_the_same_contact_when_a_row_is_added_above(self):
        panel, _ana, bia = self._with_contacts()
        panel._status_list.focused = panel._status_contact_row[1]   # Bia
        panel._unsent_status_posts = [unsent_post(TEXT, FAILED, text="oi")]
        panel._redraw_unsent_rows()
        row = panel._status_list.focused
        assert panel._status_contacts[panel._status_row_contact[row]] is bia
        assert panel._status_list.frozen == 0

    def test_with_a_status_open_the_rows_wait_for_the_viewer_to_close(self):
        """Rebuilding closes the inline viewer, and showing it again restarts
        a video being watched: the unsent row waits instead."""
        panel, _ana, _bia = self._with_contacts()
        before = list(panel._status_list.rows)
        shown = {"value": True}
        panel._viewer_panel = SimpleNamespace(Hide=lambda: None, IsShown=lambda: shown["value"])
        panel._unsent_status_posts = [unsent_post(TEXT, FAILED, text="oi")]
        panel._redraw_unsent_rows()
        assert panel._status_list.rows == before and panel._unsent_redraw_pending
        shown["value"] = False
        panel._flush_unsent_redraw()
        assert len(panel._status_list.rows) == len(before) + 1
        assert not panel._unsent_redraw_pending


def test_restored_row_finds_the_row_by_what_it_is():
    from status_tab.unsent_status import restored_row
    entry = object()
    assert restored_row(5, "p1", None, {2: "p1"}, {}, [], 9) == 2
    assert restored_row(5, None, entry, {}, {0: 7}, [entry], 9) == 7
    assert restored_row(12, None, None, {}, {}, [], 9) == 8
    assert restored_row(3, None, None, {}, {}, [], 0) == -1


class TestTheRestoredRowDoesNotReopenTheViewer:
    """Reviewer, third round: in classic mode a selected contact opens the
    inline viewer, and the redraw selects the row it puts the focus back on;
    after Esc the viewer came straight back, and over the composer too."""

    def _classic(self):
        from status_tab.status_list import StatusListMixin as _List
        panel = _Panel()
        panel._status_row_text = lambda entry, i18n: entry["name"]
        panel._use_status_media_viewer_dialog = lambda: False
        panel.shown = []
        panel._show_current_status = lambda announce=True: panel.shown.append(announce)
        panel._on_status_contact_selected = _List._on_status_contact_selected.__get__(panel)
        panel._status_list.Select = lambda row: panel._on_status_contact_selected(
            SimpleNamespace(GetIndex=lambda: row))
        ana = {"name": "Ana", "statuses": [{"messageTimestamp": 2}]}
        panel._populate_list([], [ana])
        return panel

    def test_a_flush_after_esc_leaves_the_viewer_closed(self):
        panel = self._classic()
        panel._status_list.focused = panel._status_contact_row[0]
        panel._unsent_status_posts = [unsent_post(TEXT, FAILED, text="oi")]
        panel._unsent_redraw_pending = True
        panel._flush_unsent_redraw()
        assert panel.shown == [] and not panel._unsent_redraw_pending

    def test_while_composing_the_rows_wait_for_the_composer_to_close(self):
        panel = self._classic()
        composing = {"value": True}
        panel._is_status_composer_open = lambda: composing["value"]
        panel._unsent_status_posts = [unsent_post(TEXT, FAILED, text="oi")]
        before = list(panel._status_list.rows)
        panel._redraw_unsent_rows()
        assert panel._status_list.rows == before and panel._unsent_redraw_pending
        composing["value"] = False
        panel._flush_unsent_redraw()
        assert len(panel._status_list.rows) == len(before) + 1
