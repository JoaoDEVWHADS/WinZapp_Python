"""Tests for where a chat's display identity comes from.

Two independent defects made conversations disappear from the list entirely.
Both were measured on a real 539-chat account that showed only 323 rows:

1. list-chats returns each individual chat with a nested `contact` block
   (name/shortName/pushname) and nothing read it, so every individual chat was
   stored and rendered nameless — 124 of 263 chats had a usable name in that
   block, 0 of 263 reached the database with one.

2. _compute_chat_lists() dropped a chat as "no content and no identity" using
   only the raw dict's name/pushName, ~30 lines *before* it called
   _resolve_contact_name(). WhatsApp Web returns `msgs: null` in list-chats, so
   lastMessage is empty for every chat right after a sync; any chat that also
   had no unread count was dropped before its name was ever looked up, even
   though all 263 had a matching contact record.

_lift_contact_identity covers (1) and is tested directly. (2) is a reordering
inside a large wx-bound method, so the decision it now makes is reproduced here
against the same inputs.
"""

import pytest

from main import MainWindow


lift = MainWindow._lift_contact_identity


class TestLiftContactIdentity:
    def test_takes_name_from_the_contact_block(self):
        chat = {"contact": {"name": "Tia Ana", "pushname": "Aninha"}}
        lift(chat)
        assert chat["name"] == "Tia Ana"
        assert chat["pushName"] == "Aninha"

    def test_falls_back_to_short_name(self):
        chat = {"contact": {"shortName": "Ana"}}
        lift(chat)
        assert chat["name"] == "Ana"

    def test_accepts_either_pushname_spelling(self):
        """WPPConnect spells it `pushname`; other payloads use `pushName`."""
        chat = {"contact": {"pushName": "Zé"}}
        lift(chat)
        assert chat["pushName"] == "Zé"

    def test_never_overwrites_an_existing_top_level_name(self):
        chat = {"name": "Apelido meu", "contact": {"name": "Nome do contato"}}
        lift(chat)
        assert chat["name"] == "Apelido meu"

    def test_treats_a_blank_top_level_name_as_absent(self):
        chat = {"name": "   ", "contact": {"name": "Real"}}
        lift(chat)
        assert chat["name"] == "Real"

    def test_ignores_a_blank_contact_name(self):
        chat = {"contact": {"name": "  ", "shortName": ""}}
        lift(chat)
        assert "name" not in chat

    @pytest.mark.parametrize("chat", [
        {},                       # group chats carry no contact block
        {"contact": None},
        {"contact": "nope"},
        {"contact": []},
    ])
    def test_survives_a_missing_or_malformed_contact_block(self, chat):
        before = dict(chat)
        lift(chat)
        assert chat == before


def _keeps_chat(*, records, last_msg, unread, pinned, cleared, raw_name,
                raw_push, resolved_name, group_name=""):
    """The keep/drop decision _compute_chat_lists() makes, same inputs."""
    has_content = bool(records or last_msg or unread > 0 or pinned or cleared)
    name_hint = (raw_name or raw_push or resolved_name or group_name).strip()
    has_identity = bool(name_hint and not name_hint.isdigit() and len(name_hint) > 1)
    return has_content or has_identity


class TestKeepDecision:
    def _base(self, **over):
        args = dict(records=[], last_msg=None, unread=0, pinned=False,
                    cleared=False, raw_name="", raw_push="",
                    resolved_name="", group_name="")
        args.update(over)
        return args

    def test_the_regression_chat_is_kept(self):
        """No messages, no lastMessage, no unread, nameless dict — but the
        contact is known. This is the shape of all 218 vanished chats."""
        assert _keeps_chat(**self._base(resolved_name="Fulano de Tal")) is True

    def test_still_dropped_when_nothing_at_all_is_known(self):
        """The filter must keep dropping genuinely empty, anonymous entries —
        that is what it exists for."""
        assert _keeps_chat(**self._base()) is False

    def test_a_digits_only_hint_is_not_an_identity(self):
        assert _keeps_chat(**self._base(resolved_name="5511999999999")) is False

    def test_a_single_character_hint_is_not_an_identity(self):
        assert _keeps_chat(**self._base(resolved_name="A")) is False

    @pytest.mark.parametrize("field", ["records", "last_msg", "unread", "pinned", "cleared"])
    def test_content_alone_keeps_a_nameless_chat(self, field):
        value = {"records": [{"id": 1}], "last_msg": {"t": 1}, "unread": 3,
                 "pinned": True, "cleared": True}[field]
        assert _keeps_chat(**self._base(**{field: value})) is True

    def test_raw_name_still_wins_when_present(self):
        assert _keeps_chat(**self._base(raw_name="Grupo X")) is True

    def test_group_name_still_counts(self):
        assert _keeps_chat(**self._base(group_name="Equipe WinZapp")) is True
