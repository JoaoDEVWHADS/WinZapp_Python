"""Tests for the single chat-list refresh at the end of the mentions scan.

The scan walks every message of every chat, so the per-mapping refresh
register_jid_mapping() normally schedules is a rebuild storm — the same one
resolve_lid_jids_via_api() had. It therefore passes defer_ui=True and owes the
list exactly one refresh when it finishes.

That refresh is gated on `updated_contacts or mapped`, and `mapped` is there
for one case in particular: a scan that learned @lid <-> phone mappings but
changed no contact record. The gate was written *inside* `if phones_to_resolve:`,
which made it unreachable in precisely that case — the two are fed by unrelated
passes. `mapped` counts pairs found on `key.remoteJidAlt` while walking the
messages; `phones_to_resolve` holds *mentioned* phone JIDs that still need a
name. A scan that learns mappings, needs no @lid lookup (so
resolve_lid_jids_via_api()'s own unconditional refresh never fires) and finds no
unnamed mention refreshed nothing at all, and the list kept showing raw @lid
until something unrelated happened to rebuild it.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method is bound to a plain stub, as elsewhere in this suite.
"""

import threading
import types

import pytest

import main
from main import MainWindow


LID = "111222333444555@lid"
PHONE = "5511999999999@s.whatsapp.net"


def _chat_with_alt(lid=LID, alt=PHONE):
    """A stored message carrying the @lid <-> phone bridge in its own key —
    the shape that needs no API lookup at all."""
    return {
        "remoteJid": lid,
        "messages": {"messages": {"records": [
            {"key": {"id": "m1", "remoteJid": lid, "remoteJidAlt": alt}},
        ]}},
    }


class _Stub:
    def __init__(self, chats):
        self.chats = chats
        self.contacts = {}
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self._contact_resolution_lock = threading.Lock()
        self.refreshes = 0
        self.message_refreshes = 0
        self.mapped_calls = []
        self.resolved_lid_batches = []
        self.profile_lookups = []

    # ── what the scan calls out to ───────────────────────────────────
    def register_jid_mapping(self, lid_jid, phone_jid, save=True, defer_ui=False):
        self.mapped_calls.append((lid_jid, phone_jid, defer_ui))
        self._lid_to_phone[lid_jid] = phone_jid

    def resolve_lid_jids_via_api(self, jids):
        # The real one ends with an unconditional refresh of its own; that is
        # exactly why it must not be what this test relies on.
        self.resolved_lid_batches.append(list(jids))

    def get_contact_profile(self, jid):
        self.profile_lookups.append(jid)
        return {"response": {"name": "Alguém"}}

    def _learn_sender_names_bulk(self, records):
        pass

    def _needs_sender_resolution(self, jid):
        return False

    def _normalize_jid(self, jid):
        return jid

    def _schedule_set_chats(self):
        self.refreshes += 1

    def _schedule_refresh_active_messages(self):
        self.message_refreshes += 1


def _make(chats):
    stub = _Stub(chats)
    stub.scan_all_cached_messages_for_mentions = types.MethodType(
        MainWindow.__dict__["scan_all_cached_messages_for_mentions"], stub)
    return stub


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    """The scan runs on its own thread and sleeps 3 s before starting."""
    monkeypatch.setattr(main.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(
        main.threading, "Thread",
        lambda target=None, **kw: types.SimpleNamespace(start=lambda: target and target()))


class TestAScanThatOnlyLearnsMappings:
    """No @lid needs the API, no mention needs a name — the case `mapped`
    exists for, and the one the misplaced gate could not reach."""

    def test_it_refreshes_the_chat_list(self):
        stub = _make({LID: _chat_with_alt()})
        stub.scan_all_cached_messages_for_mentions()
        assert stub._lid_to_phone[LID] == PHONE, "the mapping itself must be learned"
        assert stub.refreshes == 1, (
            "the per-mapping refreshes were deferred, so this one is the only "
            "thing standing between a learned name and a list still showing @lid")

    def test_it_refreshes_the_open_conversation_too(self):
        stub = _make({LID: _chat_with_alt()})
        stub.scan_all_cached_messages_for_mentions()
        assert stub.message_refreshes == 1

    def test_nothing_was_resolved_through_the_api(self):
        """Pins the premise: this scan never reaches
        resolve_lid_jids_via_api(), whose own unconditional refresh would
        otherwise mask the bug."""
        stub = _make({LID: _chat_with_alt()})
        stub.scan_all_cached_messages_for_mentions()
        assert stub.resolved_lid_batches == []
        assert stub.profile_lookups == []

    def test_the_mappings_are_learned_with_the_ui_deferred(self):
        stub = _make({LID: _chat_with_alt()})
        stub.scan_all_cached_messages_for_mentions()
        assert stub.mapped_calls == [(LID, PHONE, True)]


class TestAScanWithNothingToLearn:
    def test_it_does_not_refresh(self):
        """The gate still gates: an idle scan must not schedule a rebuild of a
        935-chat list for nothing."""
        stub = _make({PHONE: {"remoteJid": PHONE,
                              "messages": {"messages": {"records": []}}}})
        stub.scan_all_cached_messages_for_mentions()
        assert stub.refreshes == 0
        assert stub.message_refreshes == 0

    def test_a_mapping_already_known_is_not_relearned(self):
        stub = _make({LID: _chat_with_alt()})
        stub._lid_to_phone[LID] = PHONE
        stub.scan_all_cached_messages_for_mentions()
        assert stub.mapped_calls == []
        assert stub.refreshes == 0


class TestTheEmptyAccount:
    def test_no_chats_at_all_is_not_an_error(self):
        stub = _make({})
        stub.scan_all_cached_messages_for_mentions()
        assert stub.refreshes == 0
