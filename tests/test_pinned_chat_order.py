"""Optional pin order survives activity, polls, reloads and rejected changes.

Real methods run on plain stubs: no wx.App, desktop, audio, or WhatsApp.
"""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.pinned_chat_order import (
    METADATA_KEY, canonical_pin_jid, keep_pinned_order, pin_timestamp,
    pinned_chat_ranks, reconcile_pin_order, refresh_after_order_setting_change,
    reset_pinned_order, sync_pinned_order,
)
from core.utils import DEFAULT_SETTINGS, backfill_missing_defaults
from main import MainWindow
from main_window import chat_actions
from tests.test_chat_row_move_to_top import _Win, _win

A, B, C = "1111@s.whatsapp.net", "2222@s.whatsapp.net", "3333@s.whatsapp.net"
OTHER, LID = "4444@s.whatsapp.net", "5555@lid"


class _DB:
    def __init__(self, saved=None):
        self.data = {} if saved is None else {METADATA_KEY: saved}
        self.reads = 0
        self.writes = []

    def get_metadata_json(self, key, default):
        self.reads += 1
        return copy.deepcopy(self.data.get(key, default))

    def set_metadata_json(self, key, value):
        self.data[key] = copy.deepcopy(value)
        self.writes.append((key, copy.deepcopy(value)))


class _Window(_Win):
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _compute_chat_lists = MainWindow._compute_chat_lists
    _apply_pin_state = MainWindow._apply_pin_state
    pin_chat = MainWindow.pin_chat
    unpin_chat = MainWindow.unpin_chat
    on_chat_pin_update = MainWindow.on_chat_pin_update
    _on_pin_sync_rejected = MainWindow._on_pin_sync_rejected

    def _schedule_set_chats(self):
        self.scheduled += 1

    def _sync_pin_to_server(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def _resolve_contact_name(self, chat):
        return chat["pushName"]

    def _group_name_from_chat_dict(self, chat):
        return ""

    def _is_bad_contact_name(self, name):
        return not name

    def is_chat_locked(self, jid):
        return jid in self.locked

    def _chat_archive_flag(self, chat):
        return chat.get("archive", False)


def window(*, enabled=True, db=None, order=(A, B, C, OTHER)):
    panel = _win(list(zip(order, [300, 200, 100, 50])), pinned=(A, B, C)).conversations_panel
    win = _Window(panel, pinned=(A, B, C))
    win.settings = {"user_interface": {"keep_pinned_chat_order": enabled}}
    win.db = _DB() if db is None else db
    win._lid_to_phone, win._phone_to_lid = {}, {}
    win._deleted_chats, win._archived_chats, win.locked = set(), set(), set()
    win.i18n = SimpleNamespace(t=lambda key: key)
    win.scheduled, win.requests, win.background_mode = 0, [], True
    for jid, chat in win.chats.items():
        chat["pushName"] = f"Contact {jid.split('@')[0]}"
    return win


@pytest.fixture(autouse=True)
def no_desktop(monkeypatch):
    monkeypatch.setattr("wx.Window.FindFocus", staticmethod(lambda: None))


@pytest.mark.parametrize("value,expected", [
    (True, 0), (False, 0), ("true", 0), (None, 0), (1, 0),
    (float("nan"), 0), (float("inf"), 0), ("broken", 0),
    (1_700_000_000, 1_700_000_000), ("1700000000", 1_700_000_000),
    (1_700_000_000_000, 1_700_000_000),
])
def test_only_real_server_pin_times_seed_the_order(value, expected):
    assert pin_timestamp(value) == expected


def test_initial_server_times_win_over_message_times():
    win = window()
    for jid, pinned_at in zip((A, B, C), (1_700_000_001, 1_700_000_003, 1_700_000_002)):
        win.chats[jid]["pin"] = pinned_at
    assert sync_pinned_order(win) == (B, C, A)
    win.chats[A]["t"] = 99999
    assert sync_pinned_order(win) == (B, C, A)


@pytest.mark.parametrize("changed", [A, B, C])
def test_three_pins_do_not_move_and_only_the_changed_row_is_repainted(changed):
    win = window()
    sync_pinned_order(win)
    panel = win.conversations_panel
    panel.conversations_list.focused = 1
    win.chats[changed]["t"] = 999
    assert win.move_chat_row_to_top(changed)
    assert panel._displayed_jids == [A, B, C, OTHER]
    assert panel.conversations_list.focused == 1
    assert win.build_calls == [changed]
    assert "ts=999" in panel.conversations_list.rows[[A, B, C, OTHER].index(changed)]
    assert not any(call[0] in ("InsertItem", "DeleteItem", "DeleteAllItems")
                   for call in panel.conversations_list.calls)
    assert win.scheduled == 0


@pytest.mark.parametrize("partition,index", [("main", 0), ("archived", 2), ("locked", 4)])
def test_full_list_recompute_keeps_the_same_pin_order_in_every_panel(partition, index):
    win = window()
    sync_pinned_order(win)
    if partition == "archived":
        for jid in (A, B, C):
            win.chats[jid]["archive"] = True
    elif partition == "locked":
        win.locked = {A, B, C}
    win.chats[C]["t"] = 999
    win.chats[A]["pushName"] = "ZZZ renamed contact"
    result = win._compute_chat_lists()
    assert [chat["remoteJid"] for chat in result[index]][:3] == [A, B, C]
    assert result[index + 1][0] == "ZZZ renamed contact"


def test_default_and_disabled_option_keep_the_old_recent_activity_order():
    win = window(enabled=False)
    assert not keep_pinned_order(win)
    win.chats[C]["t"] = 999
    assert win.move_chat_row_to_top(C)
    assert win.conversations_panel._displayed_jids == [C, A, B, OTHER]
    del win.settings["user_interface"]["keep_pinned_chat_order"]
    assert not keep_pinned_order(win)


def test_unpinned_chats_still_rise_below_all_three_pins():
    win = window(order=(A, B, C, OTHER))
    win.chats[OTHER]["t"] = 999
    assert win.move_chat_row_to_top(OTHER)
    assert win.conversations_panel._displayed_jids == [A, B, C, OTHER]
    assert [chat["remoteJid"] for chat in win._compute_chat_lists()[0]] == [A, B, C, OTHER]


def test_reload_uses_saved_order_and_never_reads_or_writes_per_row():
    win = window()
    assert sync_pinned_order(win) == (A, B, C)
    reloaded = window(db=win.db, order=(C, B, A, OTHER))
    for _ in range(3):
        reloaded.chats[C]["t"] += 10000
        assert pinned_chat_ranks(reloaded) == {A: 0, B: 1, C: 2}
    assert win.db.reads == 2  # once in each process/window
    assert win.db.writes == [(METADATA_KEY, [A, B, C])]


@pytest.mark.parametrize("saved", [None, "bad", {A: 1}, [True, {}, 5, A, A, B]])
def test_corrupt_or_old_metadata_does_not_break_the_list(saved):
    win = window(db=_DB(saved))
    order = sync_pinned_order(win)
    assert len(order) == 3 and set(order) == {A, B, C}
    assert all(isinstance(jid, str) for jid in win.db.data[METADATA_KEY])


def test_known_phone_and_lid_are_one_rank_even_when_the_mapping_is_learned_later():
    win = window(db=_DB([B, LID, C]))
    win._pinned_chats = {B, LID, C}
    assert sync_pinned_order(win) == (B, LID, C)
    win._lid_to_phone = {LID: A}
    win._pinned_chats.add(A)
    assert sync_pinned_order(win) == (B, A, C)
    assert canonical_pin_jid(win, LID) == A
    assert canonical_pin_jid(win, "1111:2@c.us") == A
    assert win.db.data[METADATA_KEY] == [B, A, C]


def test_a_stale_reverse_entry_is_ignored_and_unmapped_lid_is_never_guessed():
    win = window()
    assert canonical_pin_jid(win, LID) == LID
    # Identity cleanup can leave only the reverse half; it must not revive it.
    win._phone_to_lid = {A: LID}
    assert canonical_pin_jid(win, LID) == LID


def test_a_pin_event_before_the_database_opens_keeps_the_saved_order():
    db = _DB([C, A, B])
    win = window(db=db)
    win.db = None
    assert sync_pinned_order(win) == ()
    win.db = db
    assert sync_pinned_order(win) == (C, A, B)
    assert db.data[METADATA_KEY] == [C, A, B]


def test_a_pass_without_a_new_pin_scans_no_chat_or_row():
    class _NoScan(list):
        def __iter__(self):
            raise AssertionError("scanned although no chat was newly pinned")

    win = window(db=_DB([A, B, C]))
    win.conversations_panel._displayed_jids = _NoScan()
    assert sync_pinned_order(win, chats=_NoScan()) == (A, B, C)


def test_local_unpin_and_repin_promote_only_that_chat():
    win = window()
    win.unpin_chat(B)
    assert sync_pinned_order(win) == (A, C)
    win.pin_chat(B)
    assert sync_pinned_order(win) == (B, A, C)
    win.pin_chat(B)  # duplicate events/requests do not change its rank
    assert sync_pinned_order(win) == (B, A, C)


def test_phone_side_events_and_repeated_poll_preserve_retained_ranks():
    win = window()
    win.on_chat_pin_update(B, True)
    assert sync_pinned_order(win) == (A, B, C)
    win.on_chat_pin_update(B, False)
    assert sync_pinned_order(win) == (A, C)
    win.on_chat_pin_update(B, True)
    assert sync_pinned_order(win) == (B, A, C)
    win.chats[C]["pin"] = True  # a bool must not replace its saved rank
    win.chats[C]["t"] = 999
    assert sync_pinned_order(win, chats=list(win.chats.values())) == (B, A, C)


def test_a_rejected_unpin_restores_its_exact_old_place_without_network(monkeypatch):
    class _Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(chat_actions, "threading", SimpleNamespace(Thread=_Thread))
    monkeypatch.setattr(chat_actions, "api_post", lambda *a, **k:
                        SimpleNamespace(ok=False, status_code=400, text="rejected"))
    monkeypatch.setattr(chat_actions.wx, "CallAfter", lambda fn, *a: fn(*a))
    win = window()
    win._sync_pin_to_server = MainWindow._sync_pin_to_server.__get__(win)
    win.wpp_server, win.wpp_port, win.token = "http://fake.invalid", 1, "fake"
    win.unpin_chat(B)
    assert sync_pinned_order(win) == (A, B, C)
    assert win._pinned_chats == {A, B, C}


def test_failed_pin_does_not_drop_a_separate_concurrent_pin():
    win = window()
    previous = sync_pinned_order(win)
    win._apply_pin_state(OTHER, True)
    win._apply_pin_state("6666@s.whatsapp.net", True)
    win._on_pin_sync_rejected(OTHER, True, previous)
    assert sync_pinned_order(win) == ("6666@s.whatsapp.net", A, B, C)


def test_setting_change_recomputes_once_and_old_installs_stay_opt_out():
    win = window(enabled=False)
    backfill_missing_defaults(win.settings, DEFAULT_SETTINGS)
    assert not keep_pinned_order(win)
    win.settings["user_interface"]["keep_pinned_chat_order"] = True
    refresh_after_order_setting_change(win, False)
    refresh_after_order_setting_change(win, True)
    assert win.scheduled == 1
    win.settings["user_interface"]["keep_pinned_chat_order"] = False
    refresh_after_order_setting_change(win, True)
    assert win.scheduled == 2
    defaults = json.loads((Path(__file__).parents[1] / "client/data/settings_default.json").read_text())
    assert defaults["user_interface"]["keep_pinned_chat_order"] is False


def test_setting_change_tolerates_a_window_without_a_chat_list():
    bare = SimpleNamespace(settings={"user_interface": {"keep_pinned_chat_order": True}})
    refresh_after_order_setting_change(bare, False)  # Settings dialog on a bare frame


def test_reconciliation_never_uses_set_iteration_as_a_saved_order():
    assert reconcile_pin_order([], {C, B, A}, seed=[A, B, C]) == [A, B, C]
    assert reconcile_pin_order([], {C, B, A}) == sorted((A, B, C))


def test_a_retired_worker_cannot_write_the_previous_accounts_order():
    win = window()
    sync_pinned_order(win)
    old_state = win._pinned_order_state
    reset_pinned_order(win)
    win.db.data.clear()  # synthetic account wipe
    win._pinned_order_state = old_state  # simulate a worker holding the old state
    assert sync_pinned_order(win) == ()
    assert win.db.data == {}


def test_a_list_build_from_before_an_account_wipe_saves_nothing():
    win = window()
    sync_pinned_order(win)
    captured = win._pinned_chats  # what an in-flight _compute_chat_lists holds
    win._pinned_chats = set()  # clear_local_data(wipe_metadata=True)
    reset_pinned_order(win)
    win.db.data.clear()
    assert pinned_chat_ranks(win, captured) == {}
    assert win.db.data == {}
    assert sync_pinned_order(win) == ()
    assert win.db.data == {}


def test_a_failed_metadata_write_is_retried_without_reordering(monkeypatch):
    win = window()
    original_write = win.db.set_metadata_json
    monkeypatch.setattr(win.db, "set_metadata_json", lambda *a:
                        (_ for _ in ()).throw(OSError("synthetic write failure")))
    assert sync_pinned_order(win) == (A, B, C)
    assert METADATA_KEY not in win.db.data
    monkeypatch.setattr(win.db, "set_metadata_json", original_write)
    win.chats[C]["t"] = 999
    assert sync_pinned_order(win) == (A, B, C)
    assert win.db.data[METADATA_KEY] == [A, B, C]
