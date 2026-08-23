"""Test for ConversationsPanel._get_participant_name() triggering background
@lid resolution when a group-notification participant (join/leave/promote/
...) has no known name AND no phone mapping yet.

Reported live: group join/leave notifications never converted an unresolved
@lid to a formatted phone number, even once a name genuinely became
resolvable. Root cause: unlike a group opened via ConversationDataDialog
(which proactively calls resolve_lid_jids_via_api() for every unmapped
participant before showing the list), a participant who only ever appears
in a group notification — e.g. someone who left right after being added,
with no other message ever attributed to them — never went through any
resolution path at all, so _lid_to_phone stayed empty for them forever and
every render kept showing the raw LID digits.

resolve_lid_jids_via_api() makes a synchronous HTTP request, so it must
never be called directly from _get_participant_name() (which runs on the UI
thread during message-list rendering) — this test verifies it's dispatched
on a background thread instead, and that it's the same JID being asked
about.
"""

import threading

from main import MainWindow
from ui.conversations import ConversationsPanel


class _FakeMainWindow:
    # The real lookup, not chats.get(): it falls back to the mapped
    # @lid/phone variant, which is the whole reason the panel calls it.
    # This stub already carries chats/_lid_to_phone/_phone_to_lid.
    get_chat = MainWindow.get_chat

    def __init__(self):
        self.contacts = {}
        self.chats = {}
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self._presence_pushname_map = {}
        self._initial_sync_running = False
        self.resolve_calls = []
        self._resolved_event = threading.Event()

    def _is_self_jid(self, jid):
        return False

    def self_reference_label(self):
        return "Eu"

    @staticmethod
    def _normalize_jid(jid):
        return jid

    def resolve_lid_jids_via_api(self, jids):
        self.resolve_calls.append(jids)
        self._resolved_event.set()


class _PanelStub:
    _get_participant_name = ConversationsPanel._get_participant_name

    def __init__(self, main_window):
        self.main_window = main_window
        self._sorted_messages = []
        self._group_participants_cache = []


LID = "123456789012345@lid"


def test_unresolved_lid_triggers_a_background_resolution_call():
    mw = _FakeMainWindow()
    panel = _PanelStub(mw)

    result = panel._get_participant_name(LID)

    # The call must not block the caller (it's on the UI thread) — this
    # returns a fallback value immediately, the resolution happens async.
    assert result == "123456789012345"
    assert mw._resolved_event.wait(timeout=2), "resolve_lid_jids_via_api was never called"
    assert mw.resolve_calls == [[LID]]


def test_already_resolved_lid_does_not_trigger_a_call():
    mw = _FakeMainWindow()
    mw._lid_to_phone[LID] = "5511999999999@s.whatsapp.net"
    panel = _PanelStub(mw)

    result = panel._get_participant_name(LID)

    assert "+55" in result or result.replace(" ", "").isdigit() is False  # formatted, not raw digits
    assert not mw._resolved_event.wait(timeout=0.3)
    assert mw.resolve_calls == []


def test_a_plain_phone_jid_never_triggers_lid_resolution():
    mw = _FakeMainWindow()
    panel = _PanelStub(mw)

    panel._get_participant_name("5511999999999@s.whatsapp.net")

    assert not mw._resolved_event.wait(timeout=0.3)
    assert mw.resolve_calls == []


def test_initial_sync_does_not_spawn_participant_resolution_threads():
    """Foreground get-messages owns the browser page; participant lookup waits."""
    mw = _FakeMainWindow()
    mw._initial_sync_running = True
    panel = _PanelStub(mw)

    result = panel._get_participant_name(LID)

    assert result == "123456789012345"
    assert not mw._resolved_event.wait(timeout=0.3)
    assert mw.resolve_calls == []


def test_batch_lookup_can_suppress_per_participant_thread():
    mw = _FakeMainWindow()
    panel = _PanelStub(mw)

    result = panel._get_participant_name(LID, resolve_missing=False)

    assert result == "123456789012345"
    assert not mw._resolved_event.wait(timeout=0.3)
    assert mw.resolve_calls == []
