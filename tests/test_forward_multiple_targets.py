"""Tests for ConversationsPanel._forward_message_to_targets() — forwarding
one message to several picked conversations at once.

Reported live: the forward dialog's conversation picker only ever allowed
selecting one contact at a time (wx.LB_SINGLE), so forwarding to multiple
people meant reopening the dialog and repeating the whole flow once per
recipient. The picker list now allows multi-select (wx.LB_EXTENDED); this
covers the per-target forwarding loop that runs after the dialog closes —
each target is forwarded independently so one bad JID doesn't abort
delivery to the rest, and the caller gets back exactly which targets (by
display name) failed, if any.

The method later grew a `keep_caption` path (forwarding a media message by
re-uploading it through resend_media_message_with_caption instead of
WPPConnect's native forward, which drops the caption) — those cases are
covered separately below.

ConversationsPanel is a wx.Panel and can't be instantiated without a
running wx.App, so the method under test is bound onto a plain stub —
same approach as tests/test_conversation_video_playback.py.
"""

from ui.conversations import ConversationsPanel


class _FakeMainWindow:
    def __init__(self, failing_jids=None):
        self._failing_jids = set(failing_jids or ())
        self.calls = []
        self.resend_calls = []

    def forward_message(self, source_jid, msg_key, target_jid):
        self.calls.append((source_jid, msg_key, target_jid))
        return target_jid not in self._failing_jids

    def resend_media_message_with_caption(self, msg, target_jid):
        self.resend_calls.append((msg, target_jid))
        return target_jid not in self._failing_jids


class _Stub:
    _forward_message_to_targets = ConversationsPanel._forward_message_to_targets

    def __init__(self, failing_jids=None):
        self.main_window = _FakeMainWindow(failing_jids=failing_jids)


MSG_KEY = {"id": "ABC123", "remoteJid": "source@g.us"}
MSG = {"key": MSG_KEY, "message": {}}


class TestForwardToMultipleTargets:
    def test_all_targets_forwarded_independently(self):
        stub = _Stub()
        targets = [("a@s.whatsapp.net", "Alice"), ("b@s.whatsapp.net", "Bob")]

        failed = stub._forward_message_to_targets(MSG, targets)

        assert failed == []
        assert stub.main_window.calls == [
            ("source@g.us", MSG_KEY, "a@s.whatsapp.net"),
            ("source@g.us", MSG_KEY, "b@s.whatsapp.net"),
        ]

    def test_one_failing_target_does_not_abort_the_rest(self):
        stub = _Stub(failing_jids={"b@s.whatsapp.net"})
        targets = [
            ("a@s.whatsapp.net", "Alice"),
            ("b@s.whatsapp.net", "Bob"),
            ("c@s.whatsapp.net", "Carol"),
        ]

        failed = stub._forward_message_to_targets(MSG, targets)

        assert failed == ["Bob"]
        # Carol must still have been attempted despite Bob's failure.
        assert stub.main_window.calls[-1] == ("source@g.us", MSG_KEY, "c@s.whatsapp.net")

    def test_multiple_failures_are_all_reported(self):
        stub = _Stub(failing_jids={"a@s.whatsapp.net", "c@s.whatsapp.net"})
        targets = [
            ("a@s.whatsapp.net", "Alice"),
            ("b@s.whatsapp.net", "Bob"),
            ("c@s.whatsapp.net", "Carol"),
        ]

        failed = stub._forward_message_to_targets(MSG, targets)

        assert failed == ["Alice", "Carol"]

    def test_no_targets_is_a_no_op(self):
        stub = _Stub()

        failed = stub._forward_message_to_targets(MSG, [])

        assert failed == []
        assert stub.main_window.calls == []
        assert stub.main_window.resend_calls == []

    def test_keep_caption_uses_resend_instead_of_native_forward(self):
        stub = _Stub()
        targets = [("a@s.whatsapp.net", "Alice"), ("b@s.whatsapp.net", "Bob")]

        failed = stub._forward_message_to_targets(MSG, targets, keep_caption=True)

        assert failed == []
        assert stub.main_window.calls == []
        assert stub.main_window.resend_calls == [
            (MSG, "a@s.whatsapp.net"),
            (MSG, "b@s.whatsapp.net"),
        ]

    def test_keep_caption_one_failure_does_not_abort_the_rest(self):
        stub = _Stub(failing_jids={"b@s.whatsapp.net"})
        targets = [
            ("a@s.whatsapp.net", "Alice"),
            ("b@s.whatsapp.net", "Bob"),
            ("c@s.whatsapp.net", "Carol"),
        ]

        failed = stub._forward_message_to_targets(MSG, targets, keep_caption=True)

        assert failed == ["Bob"]
        assert stub.main_window.resend_calls[-1] == (MSG, "c@s.whatsapp.net")
