"""Tests for MainWindow._on_message_failed() refreshing the chat list.

Reported live: sending a message that then failed left the chat-list
preview still showing the failed message as the conversation's "last
message" — _mark_message_failed() only updated the row inside the open
conversation panel, never told the chat-list widget to re-render. The
preview only "fixed itself" when the user happened to reopen the
conversation for an unrelated reason (which rebuilds the list from
scratch anyway). See tests/test_chat_ordering.py for the companion fix
(a failed send is also now excluded from _counts_as_last_message(), so
once the list *does* refresh it picks the right message).

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so _on_message_failed() is exercised as a plain function against
a small stub — same approach as tests/test_sender_names.py.
"""

from main import MainWindow


class _FakeConversationsPanel:
    def __init__(self):
        self.marked_failed = []

    def _mark_message_failed(self, local_id):
        self.marked_failed.append(local_id)

    def _is_cancelled_pending(self, local_id):
        # _on_message_failed() asks this first, to complete a cancellation the
        # send outran (see tests/test_message_cancel_race.py).
        return False


class _FakeSound:
    def __init__(self):
        self.played = False

    def play(self):
        self.played = True


class _Stub:
    _on_message_failed = MainWindow._on_message_failed
    _is_cancelled_send = MainWindow._is_cancelled_send

    def __init__(self):
        self.conversations_panel = _FakeConversationsPanel()
        self.error_sound = _FakeSound()
        self.schedule_set_chats_calls = 0

    def _schedule_set_chats(self):
        self.schedule_set_chats_calls += 1


class TestOnMessageFailedRefreshesTheChatList:
    def test_marks_the_message_failed_in_the_open_conversation(self):
        mw = _Stub()
        mw._on_message_failed("local-123")
        assert mw.conversations_panel.marked_failed == ["local-123"]

    def test_schedules_a_chat_list_refresh(self):
        """The actual bug: without this call the stale preview sat there
        until the user reopened the conversation for an unrelated reason."""
        mw = _Stub()
        mw._on_message_failed("local-123")
        assert mw.schedule_set_chats_calls == 1

    def test_refreshes_the_list_even_without_a_dialog(self):
        mw = _Stub()
        mw._on_message_failed("local-123", show_dialog=False)
        assert mw.schedule_set_chats_calls == 1
        assert mw.error_sound.played is False

    def test_refreshes_the_list_even_when_showing_the_error_dialog(self, monkeypatch):
        import main as main_module

        class _FakeI18n:
            def t(self, key):
                return key

        monkeypatch.setattr(main_module.wx, "MessageBox", lambda *a, **kw: None)
        mw = _Stub()
        mw.i18n = _FakeI18n()
        mw.app_name = "WinZapp"

        mw._on_message_failed("local-123", error="boom", show_dialog=True)

        assert mw.schedule_set_chats_calls == 1
        assert mw.error_sound.played is True
