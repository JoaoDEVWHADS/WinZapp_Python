"""Tests for client/account_ui.py — pure helpers (no wx)."""

from account_ui import (
    accelerator_slots,
    switchable_accounts,
    unpaired_start_options,
    accounts_menu_signature,
    manager_rows,
    can_archive,
    can_hard_delete,
    build_accounts_menu,
)


def _acc(aid, state="paired", order=1, name=None):
    return {"id": aid, "state": state, "order": order, "name": name or aid}


A, B, C = "a" * 32, "b" * 32, "c" * 32


def test_accelerator_slots_by_order():
    accs = [_acc(B, order=2), _acc(A, order=1), _acc(C, order=3)]
    slots = accelerator_slots(accs)
    assert [(n, a["id"]) for n, a in slots] == [(1, A), (2, B), (3, C)]


def test_accelerator_slots_capped_at_9():
    accs = [_acc(f"{i:032x}", order=i) for i in range(15)]
    slots = accelerator_slots(accs)
    assert len(slots) == 9
    assert slots[0][0] == 1 and slots[-1][0] == 9


def test_switchable_only_paired_ordered():
    accs = [_acc(A, "paired", 2), _acc(B, "archived", 1),
            _acc(C, "pending", 3)]
    ids = [a["id"] for a in switchable_accounts(accs)]
    assert ids == [A]  # only paired


def test_unpaired_start_options_excludes_current_and_nonpaired():
    # current account (A) is the unpaired one starting up; only OTHER paired
    # accounts are offered as switch targets. B paired -> offered; C pending
    # and D archived -> not offered; A itself -> excluded.
    accs = [_acc(A, "paired", 1), _acc(B, "paired", 2),
            _acc(C, "pending", 3), _acc("d" * 32, "archived", 4)]
    ids = [a["id"] for a in unpaired_start_options(accs, current_account_id=A)]
    assert ids == [B]


def test_unpaired_start_options_empty_when_no_other_paired():
    # Only the current account is paired -> nothing to switch to, caller must
    # fall through to the normal pairing dialog.
    accs = [_acc(A, "paired", 1), _acc(C, "pending", 2)]
    assert unpaired_start_options(accs, current_account_id=A) == []


def test_accounts_menu_signature_changes_when_account_becomes_paired():
    # The reported "account disappears from the menu" bug: menu built while B
    # was still pending, then B pairs. Signature must differ so a focus-gain
    # rebuild is triggered.
    before = [_acc(A, "paired", 1), _acc(B, "pending", 2)]
    after = [_acc(A, "paired", 1), _acc(B, "paired", 2)]
    assert accounts_menu_signature(before) != accounts_menu_signature(after)
    # B now visible in the menu signature
    assert B in [row[0] for row in accounts_menu_signature(after)]


def test_accounts_menu_signature_stable_when_nothing_menu_visible_changed():
    # A non-menu field changing (last_used_at) must NOT change the signature,
    # so focus-gain does not needlessly rebuild the menu (no flicker).
    a1 = [{"id": A, "state": "paired", "order": 1, "name": "midzi", "last_used_at": 1}]
    a2 = [{"id": A, "state": "paired", "order": 1, "name": "midzi", "last_used_at": 999}]
    assert accounts_menu_signature(a1) == accounts_menu_signature(a2)


def test_accounts_menu_signature_changes_on_rename():
    before = [_acc(A, "paired", 1, name="midzi")]
    after = [_acc(A, "paired", 1, name="tyflopodcast")]
    assert accounts_menu_signature(before) != accounts_menu_signature(after)


def test_manager_rows_hides_deleting():
    accs = [_acc(A, "paired", 1), _acc(B, "deleting", 2), _acc(C, "archived", 3)]
    ids = [a["id"] for a in manager_rows(accs)]
    assert ids == [A, C]


def test_can_archive_rules():
    paired = _acc(A, "paired")
    assert can_archive(paired, current_account_id=B)[0] is True
    # current account can't be archived
    assert can_archive(paired, current_account_id=A)[0] is False
    # non-paired can't be archived
    assert can_archive(_acc(A, "pending"), current_account_id=B)[0] is False


def test_can_hard_delete_rules():
    acc = _acc(A, "paired")
    assert can_hard_delete(acc, current_account_id=B)[0] is True
    assert can_hard_delete(acc, current_account_id=A)[0] is False


def test_can_pair_rules():
    from account_ui import can_pair
    pending = _acc(A, "pending")
    assert can_pair(pending, current_account_id=B)[0] is True
    # current account can't be paired via this path
    assert can_pair(pending, current_account_id=A)[0] is False
    # paired/archived can't be "connected" (already paired / must restore)
    assert can_pair(_acc(A, "paired"), current_account_id=B)[0] is False
    assert can_pair(_acc(A, "archived"), current_account_id=B)[0] is False


def test_can_open_rules():
    from account_ui import can_open
    paired = _acc(A, "paired")
    pending = _acc(A, "pending")
    archived = _acc(A, "archived")
    # another paired or pending account can be opened
    assert can_open(paired, current_account_id=B)[0] is True
    assert can_open(pending, current_account_id=B)[0] is True
    # current account cannot be opened (already active)
    assert can_open(paired, current_account_id=A)[0] is False
    # archived account cannot be opened
    assert can_open(archived, current_account_id=B)[0] is False


def test_build_accounts_menu_uses_factory_ids_verbatim(monkeypatch):
    """REGRESSION: the menu must use the EXACT id object the factory returns
    (e.g. wx.WindowIDRef), never a cast. Casting a reserved WindowIDRef to int()
    drops the reservation and AppendRadioItem then trips 'id should first be
    reserved' (wxAssertionError) — the whole Accounts menu fails to build and
    the user never sees it (real bug hit on Windows)."""
    import account_ui

    class _Item:
        def Check(self, *a):
            pass

    recorded = []

    class _FakeMenu:
        def AppendRadioItem(self, item_id, label):
            recorded.append(item_id)
            return _Item()

        def Append(self, item_id, label):
            recorded.append(item_id)
            return _Item()

        def AppendSeparator(self):
            pass

    monkeypatch.setattr(account_ui, "_wx", lambda: object())

    class _Ref:  # non-int sentinel; a cast would change identity
        pass

    made = []

    def factory():
        r = _Ref()
        made.append(r)
        return r

    class _I18n:
        def t(self, k):
            return k

    accts = [_acc(A, "paired", 1), _acc(B, "paired", 2)]
    id_map = build_accounts_menu(_FakeMenu(), accts, A, _I18n(), factory)
    assert all(any(rid is r for r in made) for rid in recorded)
    assert all(isinstance(k, _Ref) for k in id_map)


def test_hard_delete_removes_dir_and_entry(tmp_path):
    """_hard_delete_account marks deleting, rmtrees the data dir, removes entry."""
    import os
    from accounts import AccountRegistry
    from account_ui import _hard_delete_account

    gd = str(tmp_path / "global")
    os.makedirs(gd, exist_ok=True)
    reg = AccountRegistry(gd)
    acc = reg.add("Victim", state="paired")
    data_dir = reg.data_dir_for(acc["id"])
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "messages.db"), "w") as f:
        f.write("x")
    _hard_delete_account(reg, gd, acc["id"])
    assert reg.get(acc["id"]) is None
    assert not os.path.exists(data_dir)
