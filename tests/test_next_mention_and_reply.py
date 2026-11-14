"""Alt+Shift+J and Alt+Shift+O: the next mention and the next reply to me.

Alt+Shift+M and Alt+Shift+P only walk backwards. These two walk forwards, with
the same wrap-around the other way: after the newest comes the oldest, so
repeated presses tour every one and never dead-end. The keys were picked from
what the shortcut catalogue leaves free for the messages list, and the check
that they stay free in every language is here too — a mnemonic-derived binding
elsewhere can differ per locale.

ConversationsPanel needs a wx.App, so the handlers run on a small stub, as in
tests/test_mentions_and_reactions.py.
"""

import pathlib
import re

import pytest

import core.keyboard_shortcuts as keyboard_shortcuts
from core.shortcut_catalog import SHORTCUTS
from tests.locales import load_strings, registered_locale_codes
from tests.test_mentions_and_reactions import ME, _FakeList, _FakeMainWindow, _mention, _plain
from ui.conversation_panel.message_accels import pick_newer_index
from ui.conversations import ConversationsPanel

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
LOCALES = list(registered_locale_codes())
NEXT_KEYS = (
    ("messages.ID_ALT_SHIFT_J", 74, "shortcut_alt_shift_j_label"),
    ("messages.ID_ALT_SHIFT_O", 79, "shortcut_alt_shift_o_label"),
)


class TestPickingTheNewerOne:
    def test_the_closest_one_below_the_focused_row(self):
        assert pick_newer_index([2, 5, 9], 3) == 5

    def test_from_a_row_that_is_itself_one_the_next_is_chosen(self):
        assert pick_newer_index([2, 5, 9], 5) == 9

    def test_after_the_newest_it_wraps_to_the_oldest(self):
        assert pick_newer_index([2, 5, 9], 9) == 2
        assert pick_newer_index([2, 5, 9], 12) == 2

    def test_with_nothing_focused_it_starts_from_the_oldest(self):
        assert pick_newer_index([2, 5, 9], -1) == 2

    def test_a_single_one_is_always_that_one(self):
        assert pick_newer_index([4], 4) == 4
        assert pick_newer_index([4], 0) == 4

    def test_none_is_minus_one(self):
        assert pick_newer_index([], 3) == -1


class _Panel:
    _is_separator = ConversationsPanel._is_separator
    _on_accel_mentions = ConversationsPanel._on_accel_mentions
    _on_accel_mentions_next = ConversationsPanel._on_accel_mentions_next

    def __init__(self, messages=(), focused=-1, open_chat=True):
        self.main_window = _FakeMainWindow()
        self.main_window._is_self_jid = lambda jid: jid == ME
        self._sorted_messages = list(messages)
        self.messages_list = _FakeList(focused=focused)
        self.conversation = {"remoteJid": "grupo@g.us"} if open_chat else None


class TestNextMention:
    MESSAGES = [_plain(), _mention(ME), _plain(), _mention(ME), _plain()]

    def test_it_goes_to_the_next_mention_and_says_so(self):
        panel = _Panel(self.MESSAGES, focused=1)
        panel._on_accel_mentions_next(None)
        assert panel.messages_list.focus_calls == [3]
        assert panel.main_window.announced == ["jumped_to_mention"]

    def test_after_the_last_one_it_wraps_to_the_first(self):
        panel = _Panel(self.MESSAGES, focused=3)
        panel._on_accel_mentions_next(None)
        assert panel.messages_list.focus_calls == [1]

    def test_it_mirrors_the_backward_key(self):
        """Forward then back lands where it started."""
        panel = _Panel(self.MESSAGES, focused=1)
        panel._on_accel_mentions_next(None)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [3, 1]

    def test_without_mentions_it_says_so_like_the_backward_key(self):
        panel = _Panel([_plain(), _plain()], focused=0)
        panel._on_accel_mentions_next(None)
        assert panel.main_window.announced == ["no_mentions_found"]
        assert panel.messages_list.focus_calls == []

    def test_with_no_conversation_open_it_does_nothing(self):
        panel = _Panel(self.MESSAGES, open_chat=False)
        panel._on_accel_mentions_next(None)
        assert panel.main_window.announced == []


class _RepliesPanel:
    _is_separator = ConversationsPanel._is_separator
    _get_context_info = ConversationsPanel._get_context_info
    _is_reply_to_me = ConversationsPanel._is_reply_to_me
    _on_accel_replies = ConversationsPanel._on_accel_replies
    _on_accel_replies_next = ConversationsPanel._on_accel_replies_next

    def __init__(self, messages=(), focused=-1):
        self.main_window = _FakeMainWindow()
        self.main_window._is_self_jid = lambda jid: jid == ME
        self._sorted_messages = list(messages)
        self.messages_list = _FakeList(focused=focused)
        self.conversation = {"remoteJid": "grupo@g.us"}


def _reply(mid):
    ctx = {"stanzaId": "m", "participant": ME, "quotedMessage": {"conversation": "oi"}}
    return {"key": {"id": mid, "fromMe": False},
            "message": {"extendedTextMessage": {"text": "sim", "contextInfo": ctx}}}


class TestNextReply:
    MESSAGES = [_plain(), _reply("a"), _plain(), _reply("b")]

    def test_it_goes_to_the_next_reply(self):
        panel = _RepliesPanel(self.MESSAGES, focused=1)
        panel._on_accel_replies_next(None)
        assert panel.messages_list.focus_calls == [3]
        assert panel.main_window.announced == ["jumped_to_reply"]

    def test_after_the_last_one_it_wraps_to_the_first(self):
        panel = _RepliesPanel(self.MESSAGES, focused=3)
        panel._on_accel_replies_next(None)
        assert panel.messages_list.focus_calls == [1]

    def test_without_replies_it_says_so(self):
        panel = _RepliesPanel([_plain()], focused=0)
        panel._on_accel_replies_next(None)
        assert panel.main_window.announced == ["no_replies_found"]


class TestTheKeys:
    @pytest.mark.parametrize("shortcut_id, keycode, label", NEXT_KEYS)
    def test_they_are_in_the_catalogue_so_the_shortcuts_tab_can_change_them(
        self, shortcut_id, keycode, label
    ):
        [row] = [s for s in SHORTCUTS if s.id == shortcut_id]
        assert (row.scope, row.mod, row.key, row.label) == ("messages", 5, keycode, label)

    @pytest.mark.parametrize("locale", LOCALES)
    @pytest.mark.parametrize("shortcut_id, keycode, label", NEXT_KEYS)
    def test_no_other_command_shares_the_default_in_any_language(
        self, locale, shortcut_id, keycode, label
    ):
        """The same check the Shortcuts tab runs when someone types a key, plus
        the stricter one it skips for keys that shipped as duplicates: nothing
        in a context that can be active together has this default."""
        table = load_strings(locale)
        translate = table.__getitem__
        [row] = [s for s in SHORTCUTS if s.id == shortcut_id]
        binding = keyboard_shortcuts.default_binding(row, translate)
        assert keyboard_shortcuts.conflicts(row, binding, {}, SHORTCUTS, translate) == []
        same = [
            other.id for other in SHORTCUTS
            if other.id != row.id
            and keyboard_shortcuts.default_binding(other, translate) == binding
            and keyboard_shortcuts.scopes_overlap(row.scope, other.scope)
        ]
        assert same == []

    def test_they_are_bound_to_the_forward_handlers(self):
        # Their table entries are evaluated in
        # tests/test_shortcut_table_catalog_coverage.py; this is the Bind.
        source = (CLIENT / "ui/conversation_panel/accelerators.py").read_text(encoding="utf-8")
        assert re.search(r"self\._on_accel_mentions_next,\s*id=self\.ID_ALT_SHIFT_J\)", source)
        assert re.search(r"self\._on_accel_replies_next,\s*id=self\.ID_ALT_SHIFT_O\)", source)

    @pytest.mark.parametrize("shortcut_id, keycode, label", NEXT_KEYS)
    def test_the_f1_list_describes_them(self, shortcut_id, keycode, label):
        source = (CLIENT / "ui/dialogs/shortcuts_dialog.py").read_text(encoding="utf-8")
        assert f'i18n.t("{label}")' in source

    @pytest.mark.parametrize("locale", LOCALES)
    @pytest.mark.parametrize("shortcut_id, keycode, label", NEXT_KEYS)
    def test_the_label_names_its_key_and_the_tab_shows_the_rest(
        self, locale, shortcut_id, keycode, label
    ):
        table = load_strings(locale)
        [row] = [s for s in SHORTCUTS if s.id == shortcut_id]
        assert table[label].startswith(f"Alt+Shift+{chr(keycode)}:")
        assert keyboard_shortcuts.action_text(row, table.__getitem__) == (
            table[label].split(":", 1)[1].strip()
        )
