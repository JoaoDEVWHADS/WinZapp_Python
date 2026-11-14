"""Issue #462: ten shortcuts to review the last ten messages by position.

Alt+1..Alt+0 belong to the main window, so the ten commands ship with NO key:
they are rows of the shortcut catalogue (one per position) that the Shortcuts
tab can bind to whatever the user frees up. The key reads the Nth newest message
aloud, and the same key again, quickly, copies it.
"""

import pathlib
import re

import pytest

import core.keyboard_shortcuts as keyboard_shortcuts
from core.message_review import (
    REVIEW_REPEAT_SECONDS, is_repeated_review, recent_message_index,
)
from core.shortcut_catalog import SHORTCUTS
from tests.locales import load_strings, registered_locale_codes

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
LOCALES = list(registered_locale_codes())
REVIEW = [s for s in SHORTCUTS if s.command.startswith("ID_REVIEW[")]


def _msg(mid):
    return {"key": {"id": mid}}


SEPARATOR = {"_type": "unread_separator"}


def _is_separator(msg):
    return msg.get("_type") in ("unread_separator", "empty_placeholder")


class TestWhichMessage:
    MESSAGES = [_msg(f"m{n}") for n in range(1, 13)]  # m12 is the newest

    def test_one_is_the_newest(self):
        assert recent_message_index(self.MESSAGES, 1, _is_separator) == 11

    def test_two_is_the_one_before(self):
        assert recent_message_index(self.MESSAGES, 2, _is_separator) == 10

    def test_ten_is_the_tenth_newest(self):
        assert recent_message_index(self.MESSAGES, 10, _is_separator) == 2

    def test_a_conversation_shorter_than_the_position_has_none(self):
        assert recent_message_index(self.MESSAGES[:3], 4, _is_separator) == -1
        assert recent_message_index([], 1, _is_separator) == -1

    def test_the_unread_separator_is_not_a_message(self):
        rows = [_msg("a"), SEPARATOR, _msg("b"), _msg("c")]
        assert recent_message_index(rows, 3, _is_separator) == 0
        assert recent_message_index(rows, 4, _is_separator) == -1

    def test_the_placeholder_row_is_not_a_message_either(self):
        assert recent_message_index([{"_type": "empty_placeholder"}], 1, _is_separator) == -1


class TestPressingTwice:
    def test_the_same_key_on_the_same_message_in_time_repeats(self):
        assert is_repeated_review((3, 100.0, "x"), 3, "x", 100.5)

    def test_exactly_at_the_limit_still_counts(self):
        assert is_repeated_review((3, 100.0, "x"), 3, "x", 100.0 + REVIEW_REPEAT_SECONDS)

    def test_too_late_it_is_a_new_press(self):
        assert not is_repeated_review((3, 100.0, "x"), 3, "x", 100.0 + REVIEW_REPEAT_SECONDS + 0.1)

    def test_another_key_is_a_new_press(self):
        assert not is_repeated_review((3, 100.0, "x"), 4, "x", 100.2)

    def test_a_message_that_arrived_meanwhile_is_a_new_press(self):
        """Position 1 means a different message once a new one comes in; copying
        it for a second press that read another would be a surprise."""
        assert not is_repeated_review((1, 100.0, "old"), 1, "new", 100.2)

    def test_nothing_before_is_a_new_press(self):
        assert not is_repeated_review(None, 1, "x", 100.0)


class TestTheCatalogue:
    def test_there_is_one_row_per_position(self):
        assert sorted(s.command for s in REVIEW) == sorted(f"ID_REVIEW[{d}]" for d in range(10))

    def test_every_row_is_in_the_messages_context_with_one_label(self):
        assert {(s.scope, s.label) for s in REVIEW} == {
            ("messages", "shortcut_review_message_label")
        }

    @pytest.mark.parametrize("locale", LOCALES)
    def test_none_has_a_default_key_in_any_language(self, locale):
        """Shipping Alt+1..0 would take the main window's keys; the whole point
        of the issue's resolution is that the user chooses."""
        translate = load_strings(locale).__getitem__
        assert [keyboard_shortcuts.default_binding(s, translate) for s in REVIEW] == [None] * 10

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_label_has_no_colon_so_the_tab_shows_all_of_it(self, locale):
        """The Shortcuts tab keeps what follows the first colon of a label as the
        action's name; this one has no key to name before it."""
        table = load_strings(locale)
        label = table["shortcut_review_message_label"]
        assert ":" not in label
        [row] = [s for s in REVIEW if s.command == "ID_REVIEW[3]"]
        assert keyboard_shortcuts.action_text(row, table.__getitem__) == label + " (3)"

    def test_a_key_the_main_window_uses_is_refused_until_freed(self):
        """Assigning Alt+3 to a review is the user's to do, after freeing it:
        the tab's own rule says no while the main window still has it, and
        yes once that one is moved or removed."""
        table = load_strings("en-US").__getitem__
        [row] = [s for s in REVIEW if s.command == "ID_REVIEW[3]"]
        taken = keyboard_shortcuts.conflicts(row, (1, ord("3")), {}, SHORTCUTS, table)
        assert {s.id for s in taken} == {"main.ID_ALT_3"}
        freed = {"main.ID_ALT_3": None}
        assert keyboard_shortcuts.conflicts(row, (1, ord("3")), freed, SHORTCUTS, table) == []

    def test_an_unused_key_is_accepted_at_once(self):
        table = load_strings("en-US").__getitem__
        [row] = [s for s in REVIEW if s.command == "ID_REVIEW[1]"]
        assert keyboard_shortcuts.conflicts(row, (5, ord("W")), {}, SHORTCUTS, table) == []

    def test_a_chosen_key_becomes_the_binding_and_resetting_removes_it(self):
        table = load_strings("en-US").__getitem__
        [row] = [s for s in REVIEW if s.command == "ID_REVIEW[1]"]
        chosen = {row.id: [5, ord("W")]}
        assert keyboard_shortcuts.binding_for(row, chosen, table) == (5, ord("W"))
        assert keyboard_shortcuts.binding_for(row, {}, table) is None


class TestTheWiring:
    def test_each_command_is_bound_to_its_handler(self):
        # The table itself (no key until one is chosen) is evaluated in
        # tests/test_shortcut_table_catalog_coverage.py; this is the Bind.
        source = (CLIENT / "ui/conversation_panel/accelerators.py").read_text(encoding="utf-8")
        assert re.search(r"self\._on_accel_review_message\(d\),\s*id=self\.ID_REVIEW\[_d\]", source)

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_sentence_for_no_message_exists(self, locale):
        assert load_strings(locale)["review_no_message"]
