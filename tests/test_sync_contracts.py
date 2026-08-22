"""Tests for core/sync_contracts.py — the Python half of the response contracts.

The module is deliberately toothless: it observes and logs, and returns every
payload exactly as it arrived. Most of what is worth testing here is therefore
what it must NOT do — never raise, never mutate, never reject — plus the one
thing it must: name the field that changed shape.

The last class checks the two halves of the contract (this module and
client/api_patches/src/dto/sync.ts) still describe the same fields. They are
written in different languages against the same payload, so nothing but a test
keeps them from drifting apart.
"""

import logging
import pathlib
import re

import pytest

from core.sync_contracts import (
    CONTRACTS,
    contract_report,
    observe_payload,
    reset_contract_report,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DTO_TS = ROOT / "client" / "api_patches" / "src" / "dto" / "sync.ts"


@pytest.fixture(autouse=True)
def _fresh_report():
    """Suppression is per-run state; each test needs its own."""
    reset_contract_report()
    yield
    reset_contract_report()


class TestItNeverInterferes:
    def test_the_payload_comes_back_identical(self):
        payload = [{"id": "true_5511@c.us_ABC", "fieldWeNeverModelled": 1}]

        result = observe_payload(payload, "get-messages")

        # Identity, not equality: this must not be able to hand the caller a
        # rebuilt copy of what the API sent.
        assert result is payload
        assert result[0]["fieldWeNeverModelled"] == 1

    def test_an_unknown_endpoint_is_passed_straight_through(self):
        payload = [{"whatever": True}]
        assert observe_payload(payload, "send-message") is payload

    def test_a_payload_that_is_not_a_list_of_dicts_does_not_raise(self):
        assert observe_payload(["not a dict", 7, None], "get-messages") is not None
        assert observe_payload(None, "list-chats") is None

    def test_a_broken_record_is_reported_not_raised(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload(["not a dict"], "get-messages")
        assert "expected dict" in caplog.text


class TestWhatItCatches:
    def test_the_id_less_message_that_started_all_this(self, caplog):
        """WhatsApp Web renamed MsgKey._serialized; every message arrived with
        no id and was dropped as id-less by DatabaseManager, with nothing in
        any log to say so."""
        with caplog.at_level(logging.WARNING):
            observe_payload([{"from": "5511@c.us", "body": "oi"}], "get-messages")

        assert "[contract] get-messages: id missing" in caplog.text

    def test_a_field_that_changed_type(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload(
                [{"id": "x", "unreadCount": "3"}], "list-chats")

        assert "unreadCount expected int, got str" in caplog.text

    def test_a_bool_is_not_accepted_where_an_int_is_expected(self, caplog):
        """bool subclasses int in Python, so isinstance(True, int) is True —
        an unreadCount of True would sail through a naive check."""
        with caplog.at_level(logging.WARNING):
            observe_payload([{"id": "x", "unreadCount": True}], "list-chats")

        assert "unreadCount expected int, got bool" in caplog.text

    def test_none_is_never_a_finding(self, caplog):
        """None is how WhatsApp Web says "not set" for nearly every optional
        field — reporting it would drown the real signal."""
        with caplog.at_level(logging.WARNING):
            observe_payload(
                [{"id": "x", "name": None, "msgs": None, "t": None}], "list-chats")

        assert caplog.text == ""

    def test_an_unmodelled_field_is_never_a_finding(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload([{"id": "x", "brandNewThing": {"a": 1}}], "get-messages")

        assert caplog.text == ""

    def test_status_session_without_its_status(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload({"qrcode": None}, "status-session")

        assert "status-session: status missing" in caplog.text


class TestItStaysReadable:
    def test_the_same_problem_is_logged_once_and_then_counted(self, caplog):
        broken = [{"from": "5511@c.us"} for _ in range(50)]

        with caplog.at_level(logging.WARNING):
            observe_payload(broken, "get-messages")

        assert caplog.text.count("[contract]") == 1
        # Only the sample is inspected, so the tally counts what was looked at.
        assert contract_report()[
            ("get-messages", "id", "missing (expected str/dict)")] == 25

    def test_the_sample_bounds_the_work(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload([{"from": "x"} for _ in range(5000)],
                            "get-messages", sample=3)

        assert contract_report()[
            ("get-messages", "id", "missing (expected str/dict)")] == 3

    def test_different_problems_are_reported_separately(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload([{"from": "5511@c.us"}], "get-messages")
            observe_payload([{"id": 7}], "get-messages")

        assert caplog.text.count("[contract]") == 2


class TestTheTwoHalvesAgree:
    """core/sync_contracts.py and src/dto/sync.ts describe the same payloads.

    Written in different languages, edited at different times, with nothing but
    this test to notice when someone adds a field to one and forgets the other
    — which is the same failure mode that let a patched file import a module
    the patch set never carried (see tests/test_api_patches_in_sync.py).
    """

    _SCHEMA_FOR = {
        "get-messages": "SyncMessageSchema",
        "list-chats": "SyncChatSchema",
        "all-contacts": "SyncContactSchema",
        "status-session": "StatusSessionSchema",
    }

    @staticmethod
    def _ts_fields(schema_name: str) -> set[str]:
        source = DTO_TS.read_text(encoding="utf-8")
        block = re.search(
            rf"export const {schema_name} = z\s*\.object\(\{{(.*?)\}}\)",
            source, re.S)
        assert block, f"{schema_name} not found in {DTO_TS.name}"
        # Field names only: the leading identifier of each `name: z...` line.
        return set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*):",
                              block.group(1), re.M))

    @pytest.mark.parametrize("endpoint", sorted(_SCHEMA_FOR))
    def test_the_same_fields_are_described_on_both_sides(self, endpoint):
        if not DTO_TS.exists():
            pytest.skip("api_patches/src/dto/sync.ts not present")
        required, optional = CONTRACTS[endpoint]
        python_fields = set(required) | set(optional)
        ts_fields = self._ts_fields(self._SCHEMA_FOR[endpoint])

        assert python_fields == ts_fields, (
            f"{endpoint}: only in Python {sorted(python_fields - ts_fields)}; "
            f"only in sync.ts {sorted(ts_fields - python_fields)}"
        )


class TestTheLogNamesTheRightSource:
    def test_a_live_event_is_not_blamed_on_get_messages(self, caplog):
        """The same message shape arrives both from the get-messages fetch and
        over Socket.IO. Checking them against one contract is right; telling
        the reader the wrong one arrived would send them to the wrong code."""
        with caplog.at_level(logging.WARNING):
            observe_payload([{"from": "5511@c.us"}], "get-messages",
                            where="wpp message")

        assert "[contract] wpp message: id missing" in caplog.text
        assert "get-messages" not in caplog.text

    def test_the_tally_separates_the_sources(self):
        observe_payload([{"from": "x"}], "get-messages", where="wpp message")
        observe_payload([{"from": "x"}], "get-messages")

        problem = "missing (expected str/dict)"
        report = contract_report()
        assert report[("wpp message", "id", problem)] == 1
        assert report[("get-messages", "id", problem)] == 1


class TestTheChatContractMatchesTheRealPayload:
    """Corrected against a live list-chats after the contract shipped wrong.

    The first version modelled `pinned: bool`. The payload has no `pinned` at
    all — the field is `pin`, and it carries the pin timestamp in milliseconds.
    Nothing reported it, because a field that never arrives is never checked:
    "zero findings" says the payload never contradicted the contract, not that
    the contract describes the payload.
    """

    def test_pin_accepts_the_timestamp_whatsapp_web_actually_sends(self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload([{"id": "5511@c.us", "pin": 1783718891426}],
                            "list-chats")

        assert caplog.text == ""

    def test_pin_also_accepts_the_bool_and_string_forms_both_consumers_parse(
            self, caplog):
        with caplog.at_level(logging.WARNING):
            observe_payload([{"id": "x", "pin": True}], "list-chats")
            observe_payload([{"id": "x", "pin": "false"}], "list-chats")

        assert caplog.text == ""

    def test_the_shape_of_a_real_lid_chat_passes_clean(self, caplog):
        """Trimmed from an actual RAW LID CHAT dump — the unmodelled keys must
        stay silent, exactly as the .passthrough() side does."""
        chat = {
            "id": {"server": "lid", "user": "122999491567856",
                   "_serialized": "122999491567856@lid"},
            "t": 1786978135,
            "unreadCount": 0,
            "archive": False,
            "pin": 1783718891426,
            "msgs": None,
            "isGroup": False,
            "isUser": True,
            "name": "Gu",
            "remoteJid": "122999491567856@lid",
            "contact": {"name": "Gu", "isMyContact": True},
            "hasChatBeenOpened": False,
            "ephemeralDuration": 0,
        }

        with caplog.at_level(logging.WARNING):
            observe_payload([chat], "list-chats")

        assert caplog.text == ""
