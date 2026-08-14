"""Tests for the optional Unicode normalization in searches.

Settings > Geral > "Usar normalização Unicode nas pesquisas", off by default.
Off, searching behaves byte for byte as it always did (plain lowercase); on,
diacritics are folded so "reuniao" finds "reunião".

Both searches the user can type into read the same switch: the conversation
list (Ctrl+F, MainWindow.add_chats_to_ui) and messages inside a conversation
(Ctrl+Shift+F, ConversationsPanel._on_search_text_changed). The panel is a
wx.Panel and cannot be instantiated without a running wx.App, so the search
runs against a stub — same approach as
tests/test_conversation_search_ignores_decorations.py.
"""

import pytest

from core.utils import normalize_for_search
from ui.conversations import ConversationsPanel


class TestNormalizeForSearch:
    def test_off_is_plain_lowercase(self):
        assert normalize_for_search("Reunião", False) == "reunião"

    def test_off_does_not_fold_accents(self):
        # The default must not silently change what searching matches.
        assert normalize_for_search("reuniao", False) not in normalize_for_search("Reunião", False)

    def test_on_folds_accents(self):
        assert normalize_for_search("reuniao", True) in normalize_for_search("Reunião", True)

    @pytest.mark.parametrize("typed,real", [
        ("reuniao", "reunião"),
        ("acao", "ação"),
        ("nao", "não"),
        ("reunion", "reunión"),
        ("wiadomosc", "wiadomość"),
        ("uber", "über"),
    ])
    def test_common_cases(self, typed, real):
        assert normalize_for_search(typed, True) in normalize_for_search(real, True)

    def test_stroked_letters_are_not_folded(self):
        """Documents a real limit rather than pretending it works: "ł", "ø"
        and "đ" are single codepoints with no NFD decomposition, so they
        survive folding. Anything promising otherwise needs a
        transliteration table."""
        assert normalize_for_search("lodka", True) not in normalize_for_search("łódka", True)

    def test_compatibility_characters_are_left_alone(self):
        """NFD, not NFKD: "½" must not become "1⁄2" and "ﬁ" must not become
        "fi" — that is a different transformation from ignoring accents."""
        assert normalize_for_search("½", True) == "½"

    def test_empty_and_none_are_safe(self):
        assert normalize_for_search("", True) == ""
        assert normalize_for_search(None, True) == ""


class _FakeSearchField:
    def __init__(self, value=""):
        self._value = value

    def GetValue(self):
        return self._value


class _FakeMainWindow:
    def __init__(self, fold):
        self._fold = fold

    def _search_folds_accents(self):
        return self._fold


class _Stub:
    _is_separator = ConversationsPanel._is_separator
    _message_search_text = ConversationsPanel._message_search_text
    _on_search_text_changed = ConversationsPanel._on_search_text_changed

    def __init__(self, messages, fold):
        self._sorted_messages = messages
        self._search_field = _FakeSearchField("")
        self._search_results = []
        self._search_result_idx = -1
        self.main_window = _FakeMainWindow(fold)

    def _is_system_event(self, msg):
        return False

    def _sender_label(self, msg):
        return msg.get("_sender", "")

    def _get_message_content(self, msg):
        return msg.get("_body", "")

    def _get_context_info(self, msg):
        return None

    def search(self, query):
        self._search_field = _FakeSearchField(query)
        self._on_search_text_changed(None)
        return self._search_results


def _msg(msg_id, body, sender="Fulano"):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "messageType": "conversation",
        "_sender": sender,
        "_body": body,
    }


class TestConversationSearchHonoursTheSetting:
    def test_accentless_query_misses_when_off(self):
        panel = _Stub([_msg("T1", "a reunião é amanhã")], fold=False)

        assert panel.search("reuniao") == []

    def test_accentless_query_matches_when_on(self):
        panel = _Stub([_msg("T1", "a reunião é amanhã")], fold=True)

        assert panel.search("reuniao") == ["T1"]

    def test_accented_query_matches_either_way(self):
        for fold in (False, True):
            panel = _Stub([_msg("T1", "a reunião é amanhã")], fold=fold)
            assert panel.search("reunião") == ["T1"], f"fold={fold}"

    def test_folding_also_applies_to_the_sender_name(self):
        panel = _Stub([_msg("T1", "oi", sender="Inês")], fold=True)

        assert panel.search("ines") == ["T1"]

    def test_unrelated_messages_still_do_not_match(self):
        """Folding must widen what counts as equal, not what counts as a
        match — a query that shares no letters stays a miss."""
        panel = _Stub([_msg("T1", "a reunião é amanhã")], fold=True)

        assert panel.search("orçamento") == []
