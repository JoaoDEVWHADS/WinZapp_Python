"""Tests for client/accounts.py — process-safe account registry."""

import json
import os
import re

import pytest

from accounts import AccountRegistry, RegistryCorruptError


def _reg(tmp_path):
    return AccountRegistry(str(tmp_path / "global"))


# ── basics ───────────────────────────────────────────────────────────────
def test_empty_registry(tmp_path):
    reg = _reg(tmp_path)
    assert reg.list() == []
    assert reg.last_foreground() is None


def test_add_account_full_uuid_and_persist(tmp_path):
    reg = _reg(tmp_path)
    acc = reg.add("Praca")
    assert acc["name"] == "Praca"
    assert acc["state"] == "pending"
    # Full 32-hex uuid, not truncated
    assert re.fullmatch(r"[0-9a-f]{32}", acc["id"])
    assert acc["order"] == 1
    # persists across re-open
    reg2 = _reg(tmp_path)
    assert any(a["id"] == acc["id"] for a in reg2.list())


def test_order_is_stable_after_rename(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    b = reg.add("B")
    assert a["order"] == 1 and b["order"] == 2
    reg.rename(a["id"], "AAA")
    assert reg.get(a["id"])["order"] == 1
    assert reg.get(a["id"])["name"] == "AAA"


def test_states(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    for st in ("paired", "deleting", "archived", "pending"):
        reg.set_state(a["id"], st)
        assert reg.get(a["id"])["state"] == st
    with pytest.raises(ValueError):
        reg.set_state(a["id"], "bogus")


def test_autostart(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    assert reg.get(a["id"])["autostart"] is False
    reg.set_autostart(a["id"], True)
    assert reg.get(a["id"])["autostart"] is True


def test_last_foreground(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    reg.set_last_foreground(a["id"])
    assert _reg(tmp_path).last_foreground() == a["id"]


def test_remove(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    reg.remove(a["id"])
    assert reg.get(a["id"]) is None


def test_data_dir_sibling_of_global(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    dd = reg.data_dir_for(a["id"])
    # accounts/<id> is a sibling of global/, not inside it
    assert dd.endswith(a["id"])
    assert "accounts" in dd
    assert "global" not in dd.replace("global", "", 0) or "accounts" in dd


# ── helpers for listing ──────────────────────────────────────────────────
def test_list_paired_and_autostart_sorted_by_order(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A"); b = reg.add("B"); c = reg.add("C")
    for x in (a, b, c):
        reg.set_state(x["id"], "paired")
    reg.set_autostart(a["id"], True)
    reg.set_autostart(c["id"], True)
    paired_ids = [x["id"] for x in reg.list_paired()]
    assert paired_ids == [a["id"], b["id"], c["id"]]  # by order
    auto_ids = [x["id"] for x in reg.list_autostart_paired()]
    assert auto_ids == [a["id"], c["id"]]


def test_pending_excluded_from_paired(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")  # pending
    b = reg.add("B"); reg.set_state(b["id"], "paired")
    assert [x["id"] for x in reg.list_paired()] == [b["id"]]


# ── security / robustness ────────────────────────────────────────────────
def test_invalid_id_rejected_on_read(tmp_path):
    """An id that isn't 32-hex (path traversal attempt) fails model validation
    and drops the registry into recovery (safer than trusting a tampered file)."""
    reg = _reg(tmp_path)
    reg.add("Good")
    path = reg._path
    data = json.loads(open(path).read())
    data["accounts"].append(
        {"id": "../../etc", "name": "Evil", "state": "paired",
         "autostart": False, "order": 99, "created_at": 0, "last_used_at": 0}
    )
    open(path, "w").write(json.dumps(data))
    reg2 = _reg(tmp_path)
    assert reg2.is_recovery_mode() is True
    assert reg2.list() == []


def test_data_dir_for_rejects_bad_id(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(ValueError):
        reg.data_dir_for("../../etc")
    with pytest.raises(ValueError):
        reg.data_dir_for("a" * 32 + "\n")  # trailing newline must fail fullmatch


def test_set_last_foreground_unknown_rejected(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(ValueError):
        reg.set_last_foreground("f" * 32)
    reg.set_last_foreground(None)  # None always allowed
    assert reg.last_foreground() is None


def test_remove_clears_dangling_last_foreground(tmp_path):
    reg = _reg(tmp_path)
    a = reg.add("A")
    reg.set_last_foreground(a["id"])
    reg.remove(a["id"])
    assert reg.last_foreground() is None


def test_recovery_marker_persists_across_instances(tmp_path):
    reg = _reg(tmp_path)
    reg.add("A")
    open(reg._path, "w").write("{ broken ")
    _reg(tmp_path)  # first instance detects corruption + drops marker
    # A fresh instance (another process) must ALSO be in recovery and refuse
    # first-run/add, even though the corrupt file was copied aside.
    reg3 = _reg(tmp_path)
    assert reg3.is_recovery_mode() is True
    with pytest.raises(RegistryCorruptError):
        reg3.add("B")


def test_is_recovery_mode_refreshes_under_lock(tmp_path):
    """An instance built BEFORE corruption must still report recovery once
    another 'process' has entered it (GPT r3 #6)."""
    reg_early = _reg(tmp_path)   # constructed while healthy
    reg_early.add("A")
    assert reg_early.is_recovery_mode() is False
    # Another process corrupts + enters recovery (drops the marker):
    open(reg_early._path, "w").write("{ broken")
    _reg(tmp_path)
    # The early instance must now see recovery on re-check (not a stale flag).
    assert reg_early.is_recovery_mode() is True


def test_update_fields_unknown_account_raises_and_keeps_lf(tmp_path):
    """Archiving an already-removed account must NOT clear the current
    last_foreground (GPT r3 #5)."""
    reg = _reg(tmp_path)
    a = reg.add("A")
    reg.set_last_foreground(a["id"])
    ghost = "e" * 32
    with pytest.raises(KeyError):
        reg.update_fields(ghost, state="archived", autostart=False, last_foreground=None)
    assert reg.last_foreground() == a["id"]  # unchanged


def test_schema_bool_is_corrupt(tmp_path):
    """schema:true must not pass validation (bool is an int subclass) — GPT r4 #4."""
    reg = _reg(tmp_path)
    reg.add("A")
    data = json.loads(open(reg._path).read())
    data["schema"] = True
    open(reg._path, "w").write(json.dumps(data))
    reg2 = _reg(tmp_path)
    assert reg2.is_recovery_mode() is True


def test_accounts_json_as_dir_is_recovery(tmp_path):
    """A directory where accounts.json should be is corrupt, not empty (GPT r5 #4)."""
    import os
    gd = str(tmp_path / "global")
    os.makedirs(os.path.join(gd, "accounts.json"))  # a dir, not a file
    reg = AccountRegistry(gd)
    assert reg.is_recovery_mode() is True


def test_corrupt_json_read_only_recovery(tmp_path):
    reg = _reg(tmp_path)
    reg.add("A")
    # Corrupt the file
    open(reg._path, "w").write("{ this is not json ")
    reg2 = _reg(tmp_path)
    # read-only recovery mode: reads yield empty, mutations blocked, backup made
    assert reg2.is_recovery_mode() is True
    assert reg2.list() == []
    with pytest.raises(RegistryCorruptError):
        reg2.add("B")
    # a .corrupt-* backup exists
    import glob
    assert glob.glob(str(tmp_path / "global" / "accounts.json.corrupt-*"))


def test_locked_writes_no_lost_update(tmp_path):
    """Two registry instances (same lock) interleaving writes don't lose data."""
    import threading
    reg = _reg(tmp_path)
    ids = []
    lock = threading.Lock()

    def worker(name):
        r = _reg(tmp_path)
        acc = r.add(name)
        with lock:
            ids.append(acc["id"])

    threads = [threading.Thread(target=worker, args=(f"acc{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = _reg(tmp_path)
    stored_ids = {a["id"] for a in final.list()}
    assert len(stored_ids) == 6, "a concurrent add was lost"
    assert set(ids) == stored_ids
    # orders are unique 1..6
    orders = sorted(a["order"] for a in final.list())
    assert orders == [1, 2, 3, 4, 5, 6]


if os.name != "nt":
    def test_broken_symlink_marker_counts_as_recovery(tmp_path):
        """A dangling symlink at the recovery-marker path must be treated as
        recovery present, not silently absent (GPT r6 #1: lexists, not exists)."""
        gd = str(tmp_path / "global")
        os.makedirs(gd, exist_ok=True)
        marker = os.path.join(gd, "accounts.recovery")
        os.symlink(os.path.join(gd, "nonexistent-target"), marker)
        assert not os.path.exists(marker)   # dangling -> exists() is False
        assert os.path.lexists(marker)      # ...but lexists() is True
        reg = AccountRegistry(gd)
        assert reg.is_recovery_mode() is True
else:
    def test_broken_symlink_marker_counts_as_recovery(tmp_path, monkeypatch):
        """Exercise dangling-link semantics without Windows symlink privilege.

        Creating a symlink requires Developer Mode or elevation on many Windows
        hosts. AccountRegistry only depends on the observable contract here:
        lexists(marker) is true while exists(marker) would be false.
        """
        gd = str(tmp_path / "global")
        marker = os.path.normcase(os.path.join(gd, "accounts.recovery"))
        real_lexists = os.path.lexists

        def marker_lexists(path):
            if os.path.normcase(os.fspath(path)) == marker:
                return True
            return real_lexists(path)

        monkeypatch.setattr(os.path, "lexists", marker_lexists)
        reg = AccountRegistry(gd)
        assert reg.is_recovery_mode() is True

