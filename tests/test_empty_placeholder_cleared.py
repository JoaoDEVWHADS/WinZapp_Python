"""Tests for the "no messages" placeholder being removed when a message lands.

An empty conversation shows a placeholder row ("Nenhuma mensagem nesta
conversa") that is a sentinel, not a message. Every send/receive path appends
straight to _sorted_messages and the list control, so the first message in an
empty conversation used to arrive *below* a placeholder still claiming the
conversation was empty — a row a screen reader then reads out on the way past.

_clear_empty_placeholder() drops it, and every append path calls it first.
Because it is a sentinel, removing it also shifts the unread separator's row
index, which is why the recompute is part of the same operation.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test run against a stub — same approach as
tests/test_unread_separator_reuse.py, whose fake list control this mirrors.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeMessagesList:
    def __init__(self, items=None):
        self.items = list(items or [])

    def DeleteItem(self, pos):
        del self.items[pos]

    def Append(self, row):
        self.items.append(row[0])


class _Stub:
    _clear_empty_placeholder = ConversationsPanel._clear_empty_placeholder
    _recompute_unread_sep_idx = ConversationsPanel._recompute_unread_sep_idx
    _is_separator = ConversationsPanel._is_separator

    def __init__(self, sorted_messages, items=None, sep_idx=-1):
        self._sorted_messages = sorted_messages
        self.messages_list = _FakeMessagesList(
            items if items is not None else [str(m) for m in sorted_messages]
        )
        self._unread_sep_idx = sep_idx


def _placeholder():
    return {"_type": "empty_placeholder"}


def _sep(count=2):
    return {"_type": "unread_separator", "count": count}


def _msg(msg_id):
    return {"key": {"id": msg_id, "fromMe": False}, "messageType": "conversation"}


class TestPlaceholderRemoval:
    def test_placeholder_is_dropped_from_both_the_model_and_the_list(self):
        panel = _Stub([_placeholder()], items=["sem mensagens"])

        panel._clear_empty_placeholder()

        assert panel._sorted_messages == []
        assert panel.messages_list.items == []

    def test_a_conversation_with_messages_is_untouched(self):
        panel = _Stub([_msg("A"), _msg("B")], items=["A", "B"])

        panel._clear_empty_placeholder()

        assert len(panel._sorted_messages) == 2
        assert panel.messages_list.items == ["A", "B"]

    def test_an_empty_list_does_not_crash(self):
        panel = _Stub([], items=[])

        panel._clear_empty_placeholder()   # must not raise

        assert panel._sorted_messages == []

    def test_only_the_first_row_counts_as_the_placeholder(self):
        """The placeholder is only ever row 0. A sentinel further down is not
        it, and must not be silently deleted."""
        panel = _Stub([_msg("A"), _placeholder()], items=["A", "sem mensagens"])

        panel._clear_empty_placeholder()

        assert len(panel._sorted_messages) == 2
        assert panel.messages_list.items == ["A", "sem mensagens"]

    def test_a_non_dict_row_does_not_crash(self):
        panel = _Stub(["nao é um dict"], items=["x"])

        panel._clear_empty_placeholder()   # must not raise

        assert len(panel._sorted_messages) == 1


class TestSeparatorIndexFollows:
    def test_the_unread_separator_index_is_recomputed(self):
        """Deleting row 0 shifts every row above the separator down by one —
        a stale index would leave Alt+3 pointing at the wrong row."""
        panel = _Stub(
            [_placeholder(), _sep(), _msg("A")],
            items=["sem mensagens", "__sep__", "A"],
            sep_idx=1,
        )

        panel._clear_empty_placeholder()

        assert panel._unread_sep_idx == 0
        assert panel.messages_list.items == ["__sep__", "A"]

    def test_no_separator_leaves_the_index_at_minus_one(self):
        panel = _Stub([_placeholder(), _msg("A")], items=["sem mensagens", "A"], sep_idx=-1)

        panel._clear_empty_placeholder()

        assert panel._unread_sep_idx == -1


class TestAppendPathsCallIt:
    @pytest.mark.parametrize("method_name", [
        "on_incoming_message",
        # on_send_message()'s own append path, split out of it alongside
        # _apply_message_edit().
        "_send_new_text_message",
        "_send_voice_message",
        "_on_send_attachment",
        "_on_attach_contact",
    ])
    def test_every_append_path_clears_the_placeholder_first(self, method_name):
        """Each of these appends a row; appending onto a placeholder is the
        bug. Checked at source level because driving these methods whole needs
        a live wx.App and a WhatsApp session."""
        import inspect

        src = inspect.getsource(getattr(ConversationsPanel, method_name))
        assert "_clear_empty_placeholder()" in src, (
            f"{method_name} appends to the messages list without clearing the "
            f"'no messages' placeholder first"
        )
