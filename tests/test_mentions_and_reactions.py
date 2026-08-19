"""Tests for the two conversation accelerators added alongside mass selection:
jump to the previous mention of me (Alt+Shift+M) and announce the recent
reactions (Alt+Shift+E).

The mention jump walks backwards through the list and wraps around at the
oldest one, so repeated presses tour every mention in the conversation and
never dead-end — that cycle is what these tests pin, along with the
mentionedJid extraction, which has to cope with `message` arriving either as a
dict or as a JSON string depending on which path stored it.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are bound to a small stub carrying only the
attributes they touch — same approach as tests/test_message_bookmarks.py.
"""

import json

import pytest

from ui.conversations import ConversationsPanel


ME = "5511900000000@s.whatsapp.net"
SOMEONE = "5511911111111@s.whatsapp.net"


class _FakeI18n:
    def t(self, key):
        return key


class _FakeList:
    def __init__(self, focused=-1):
        self._focused = focused
        self.focus_calls = []
        self.ensure_visible_calls = []

    def GetFocusedItem(self):
        return self._focused

    def Focus(self, idx):
        self.focus_calls.append(idx)
        self._focused = idx

    def Select(self, idx, on=True):
        pass

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)


class _FakeMainWindow:
    def __init__(self, names=None):
        self.i18n = _FakeI18n()
        self.announced = []
        self._names = names or {}

    def output(self, text, interrupt=False):
        self.announced.append(text)

    def _is_self_jid(self, jid):
        return jid == ME

    def _resolve_jid_name(self, jid):
        return self._names.get(jid, jid)


class _Panel:
    _is_separator = ConversationsPanel._is_separator
    _on_accel_mentions = ConversationsPanel._on_accel_mentions
    _on_accel_recent_reactions = ConversationsPanel._on_accel_recent_reactions

    def __init__(self, messages=(), focused=-1, reactions=None, names=None, open_chat=True):
        self.main_window = _FakeMainWindow(names)
        self._sorted_messages = list(messages)
        self.messages_list = _FakeList(focused=focused)
        self._reaction_map = reactions if reactions is not None else {}
        self.conversation = {"remoteJid": "grupo@g.us"} if open_chat else None


def _mention(*jids, kind="extendedTextMessage"):
    return {"key": {"id": "x"},
            "message": {kind: {"text": "oi", "contextInfo": {"mentionedJid": list(jids)}}}}


def _plain(text="oi"):
    return {"key": {"id": "p"}, "message": {"conversation": text}}


SEPARATOR = {"_type": "unread_separator", "count": 2}


class TestFindingMentions:
    def test_a_conversation_with_no_mentions_says_so(self):
        panel = _Panel(messages=[_plain(), _plain()])
        panel._on_accel_mentions(None)
        assert panel.main_window.announced == ["no_mentions_found"]
        assert panel.messages_list.focus_calls == []

    def test_a_mention_of_someone_else_does_not_count(self):
        panel = _Panel(messages=[_mention(SOMEONE)])
        panel._on_accel_mentions(None)
        assert panel.main_window.announced == ["no_mentions_found"]

    def test_a_mention_of_me_among_others_counts(self):
        panel = _Panel(messages=[_mention(SOMEONE, ME)])
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [0]
        assert panel.main_window.announced == ["jumped_to_mention"]

    @pytest.mark.parametrize("kind", ["extendedTextMessage", "imageMessage", "videoMessage"])
    def test_the_mention_can_hang_off_any_message_type(self, kind):
        panel = _Panel(messages=[_mention(ME, kind=kind)])
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [0]

    def test_a_json_encoded_payload_is_parsed(self):
        msg = {"key": {"id": "x"},
               "message": json.dumps({"extendedTextMessage": {
                   "contextInfo": {"mentionedJid": [ME]}}})}
        panel = _Panel(messages=[msg])
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [0]

    def test_an_unparseable_payload_is_skipped_rather_than_raising(self):
        panel = _Panel(messages=[{"key": {"id": "x"}, "message": "{nao é json"}])
        panel._on_accel_mentions(None)
        assert panel.main_window.announced == ["no_mentions_found"]

    def test_sentinel_rows_are_skipped(self):
        panel = _Panel(messages=[SEPARATOR, _mention(ME)])
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [1]

    def test_nothing_happens_with_no_conversation_open(self):
        panel = _Panel(messages=[_mention(ME)], open_chat=False)
        panel._on_accel_mentions(None)
        assert panel.main_window.announced == []
        assert panel.messages_list.focus_calls == []


class TestTheMentionCycle:
    """Each press moves to the next mention *older* than the focused row, and
    wraps to the newest once past the oldest — so repeated presses tour them
    all instead of sticking on the first."""

    def _panel(self, focused):
        # mentions at rows 1, 3 and 5
        msgs = [_plain(), _mention(ME), _plain(), _mention(ME), _plain(), _mention(ME)]
        return _Panel(messages=msgs, focused=focused)

    def test_from_the_bottom_it_goes_to_the_newest_mention(self):
        panel = self._panel(focused=5)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [3]

    def test_then_to_the_one_before_it(self):
        panel = self._panel(focused=3)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [1]

    def test_past_the_oldest_it_wraps_to_the_newest(self):
        panel = self._panel(focused=1)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [5]

    def test_with_nothing_focused_it_starts_at_the_newest(self):
        panel = self._panel(focused=-1)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [5]

    def test_repeated_presses_tour_every_mention_and_come_back(self):
        panel = self._panel(focused=-1)
        seen = []
        for _ in range(4):
            panel._on_accel_mentions(None)
            seen.append(panel.messages_list._focused)
        assert seen == [5, 3, 1, 5]

    def test_a_single_mention_stays_reachable_from_itself(self):
        """Focused on the only mention there is, the wrap-around must land
        back on it rather than leaving focus where it was with no feedback."""
        panel = _Panel(messages=[_plain(), _mention(ME)], focused=1)
        panel._on_accel_mentions(None)
        assert panel.messages_list.focus_calls == [1]

    def test_the_row_is_scrolled_into_view(self):
        panel = self._panel(focused=5)
        panel._on_accel_mentions(None)
        assert panel.messages_list.ensure_visible_calls == [3]


class TestRecentReactions:
    def test_no_reactions_says_so(self):
        panel = _Panel(reactions={})
        panel._on_accel_recent_reactions(None)
        assert panel.main_window.announced == ["no_reactions_found"]

    def test_a_reaction_is_announced_with_the_reactor_name(self):
        panel = _Panel(reactions={"m1": {SOMEONE: "👍"}}, names={SOMEONE: "Fulano"})
        panel._on_accel_recent_reactions(None)
        assert panel.main_window.announced == ["recent_reactions Fulano: 👍"]

    def test_several_reactions_are_joined(self):
        panel = _Panel(
            reactions={"m1": {SOMEONE: "👍"}, "m2": {ME: "❤️"}},
            names={SOMEONE: "Fulano", ME: "Beltrano"},
        )
        panel._on_accel_recent_reactions(None)
        announced, = panel.main_window.announced
        assert announced.startswith("recent_reactions ")
        assert "Fulano: 👍" in announced and "Beltrano: ❤️" in announced

    def test_at_most_ten_are_announced(self):
        """It is spoken in one breath by the screen reader; an unbounded list
        of a busy group's reactions would be unusable."""
        reactions = {f"m{i}": {f"{i}@s.whatsapp.net": "👍"} for i in range(25)}
        panel = _Panel(reactions=reactions)
        panel._on_accel_recent_reactions(None)
        announced, = panel.main_window.announced
        assert announced.count(": 👍") == 10

    def test_nothing_happens_with_no_conversation_open(self):
        panel = _Panel(reactions={"m1": {SOMEONE: "👍"}}, open_chat=False)
        panel._on_accel_recent_reactions(None)
        assert panel.main_window.announced == []


class TestKnownGaps:
    """Defects found while writing these tests, pinned as xfail so they are
    not lost and so the test turns green by itself once fixed."""

    @pytest.mark.xfail(
        reason="_on_accel_recent_reactions passes the reactor KEY to "
               "_resolve_jid_name, but our own reactions are stored under the "
               "_SELF_REACTOR_KEY sentinel ('_me_'), not a JID. The screen "
               "reader announces that sentinel instead of 'Eu' — the "
               "ui_self_reference_eu string already exists for exactly this.",
        strict=True,
    )
    def test_my_own_reaction_should_be_announced_as_me(self):
        panel = _Panel(reactions={"m1": {ConversationsPanel._SELF_REACTOR_KEY: "👍"}},
                       names={})
        panel._on_accel_recent_reactions(None)
        announced, = panel.main_window.announced
        assert ConversationsPanel._SELF_REACTOR_KEY not in announced
