"""Tests for the Unicode normalization choice in searches.

Settings > Geral > "Normalização Unicode nas pesquisas" — a three-way radio
group, "off" by default:

    off   searching matches exactly what was typed (what the app always did)
    nfd   accents ignored: "reuniao" finds "reunião"
    nfkd  accents AND compatibility forms: "fi" also finds the "ﬁ" ligature

The two folding levels are separate choices rather than one checkbox because
they are different trades, not degrees of the same one: NFKD rewrites
characters that have nothing to do with accents, which is not something a user
asking to ignore accents should get by surprise.

Both searches the user can type into read the same setting: the conversation
list (Ctrl+F, MainWindow.add_chats_to_ui) and messages inside a conversation
(Ctrl+Shift+F, ConversationsPanel._on_search_text_changed). The panel is a
wx.Panel and cannot be instantiated without a running wx.App, so the search
runs against a stub — same approach as
tests/test_conversation_search_ignores_decorations.py.
"""

import pytest

from core.utils import (
    SEARCH_NORMALIZATION_MODES,
    normalize_for_search,
    search_normalization_mode,
)
from ui.conversations import ConversationsPanel


class TestModeCanonicalization:
    def test_the_three_modes_are_ordered_as_the_radio_group_shows_them(self):
        # settings store the string; the dialog stores/reads the index.
        assert SEARCH_NORMALIZATION_MODES == ("off", "nfd", "nfkd")

    @pytest.mark.parametrize("raw,expected", [
        ("off", "off"), ("nfd", "nfd"), ("nfkd", "nfkd"),
        ("NFD", "nfd"), ("  NFKD  ", "nfkd"),
    ])
    def test_accepts_the_stored_strings(self, raw, expected):
        assert search_normalization_mode(raw) == expected

    @pytest.mark.parametrize("raw", ["", "nfc", "yes", "1", 7, [], {}])
    def test_anything_unrecognised_falls_back_to_off(self, raw):
        """A typo or a hand-edited settings.json must not silently turn
        folding on — "off" is the only mode that cannot surprise anyone."""
        assert search_normalization_mode(raw) == "off"

    @pytest.mark.parametrize("raw,expected", [(True, "nfd"), (False, "off"), (None, "off")])
    def test_the_old_checkbox_booleans_still_read(self, raw, expected):
        """This setting shipped briefly as a checkbox; an existing
        settings.json can still carry True/False, where True meant NFD."""
        assert search_normalization_mode(raw) == expected


class TestOff:
    def test_is_plain_lowercase(self):
        assert normalize_for_search("Reunião", "off") == "reunião"

    def test_does_not_fold_accents(self):
        # The default must not silently change what searching matches.
        assert normalize_for_search("reuniao", "off") not in normalize_for_search("Reunião", "off")

    def test_is_the_default(self):
        assert normalize_for_search("Reunião") == normalize_for_search("Reunião", "off")


class TestNfd:
    @pytest.mark.parametrize("typed,real", [
        ("reuniao", "reunião"),
        ("acao", "ação"),
        ("nao", "não"),
        ("reunion", "reunión"),
        ("wiadomosc", "wiadomość"),
        ("uber", "über"),
        ("ines", "Inês"),
    ])
    def test_folds_accents(self, typed, real):
        assert normalize_for_search(typed, "nfd") in normalize_for_search(real, "nfd")

    def test_leaves_compatibility_characters_alone(self):
        """The whole reason NFKD is a separate choice: asking to ignore
        accents must not also rewrite "½" or the "ﬁ" ligature."""
        assert normalize_for_search("½", "nfd") == "½"
        assert normalize_for_search("ﬁ", "nfd") == "ﬁ"


class TestNfkd:
    def test_folds_accents_too(self):
        assert normalize_for_search("reuniao", "nfkd") in normalize_for_search("reunião", "nfkd")

    @pytest.mark.parametrize("typed,real", [
        ("fi", "ﬁ"),            # ligature
        ("1", "①"),             # enclosed digit
        ("2", "²"),             # superscript
        ("abc", "ａｂｃ"),        # full-width
    ])
    def test_folds_compatibility_forms(self, typed, real):
        assert normalize_for_search(typed, "nfkd") in normalize_for_search(real, "nfkd")

    def test_half_becomes_its_spelled_out_form(self):
        # "½" decomposes to "1⁄2" (with U+2044 FRACTION SLASH), not "1/2".
        assert normalize_for_search("½", "nfkd") == "1⁄2"


class TestLimitsOfBothFoldingModes:
    @pytest.mark.parametrize("mode", ["nfd", "nfkd"])
    def test_stroked_letters_are_not_folded(self, mode):
        """Documents a real limit rather than pretending it works: "ł", "ø"
        and "đ" are single codepoints with no decomposition, so they survive
        folding. Anything promising otherwise needs a transliteration table."""
        assert normalize_for_search("lodka", mode) not in normalize_for_search("łódka", mode)

    @pytest.mark.parametrize("mode", SEARCH_NORMALIZATION_MODES)
    def test_empty_and_none_are_safe(self, mode):
        assert normalize_for_search("", mode) == ""
        assert normalize_for_search(None, mode) == ""


class _FakeSearchField:
    def __init__(self, value=""):
        self._value = value

    def GetValue(self):
        return self._value


class _FakeMainWindow:
    def __init__(self, mode):
        self._mode = mode

    def _search_normalization_mode(self):
        return self._mode


class _Stub:
    _is_separator = ConversationsPanel._is_separator
    _message_search_text = ConversationsPanel._message_search_text
    _on_search_text_changed = ConversationsPanel._on_search_text_changed

    def __init__(self, messages, mode):
        self._sorted_messages = messages
        self._search_field = _FakeSearchField("")
        self._search_results = []
        self._search_result_idx = -1
        self.main_window = _FakeMainWindow(mode)

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
        panel = _Stub([_msg("T1", "a reunião é amanhã")], mode="off")

        assert panel.search("reuniao") == []

    @pytest.mark.parametrize("mode", ["nfd", "nfkd"])
    def test_accentless_query_matches_when_folding(self, mode):
        panel = _Stub([_msg("T1", "a reunião é amanhã")], mode=mode)

        assert panel.search("reuniao") == ["T1"]

    @pytest.mark.parametrize("mode", SEARCH_NORMALIZATION_MODES)
    def test_accented_query_matches_in_every_mode(self, mode):
        panel = _Stub([_msg("T1", "a reunião é amanhã")], mode=mode)

        assert panel.search("reunião") == ["T1"]

    def test_only_nfkd_matches_a_ligature(self):
        panel_nfd = _Stub([_msg("T1", "o arquivo ﬁnal")], mode="nfd")
        panel_nfkd = _Stub([_msg("T1", "o arquivo ﬁnal")], mode="nfkd")

        assert panel_nfd.search("final") == []
        assert panel_nfkd.search("final") == ["T1"]

    def test_folding_also_applies_to_the_sender_name(self):
        panel = _Stub([_msg("T1", "oi", sender="Inês")], mode="nfd")

        assert panel.search("ines") == ["T1"]

    def test_unrelated_messages_still_do_not_match(self):
        """Folding must widen what counts as equal, not what counts as a
        match — a query that shares no letters stays a miss."""
        panel = _Stub([_msg("T1", "a reunião é amanhã")], mode="nfkd")

        assert panel.search("orçamento") == []
