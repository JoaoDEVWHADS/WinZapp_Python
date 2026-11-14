"""Backing up and restoring the accounts' data."""
import io
import os
import sqlite3
import zipfile

import pytest

import session_backup as sb


def account(folder, name, rows=3):
    os.makedirs(folder / name)
    db = sqlite3.connect(folder / name / "session.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE keys(v)")
    db.executemany("INSERT INTO keys VALUES (?)", [(i,) for i in range(rows)])
    db.commit()
    (folder / name / "labels.json").write_text("{}", encoding="utf-8")
    (folder / name / "notes.txt").write_text("not kept", encoding="utf-8")
    return db         # left open, as the bridge keeps it


def test_a_backup_holds_each_accounts_files(tmp_path):
    open_db = account(tmp_path, "acc1")
    data = sb.make_backup(str(tmp_path), ["acc1"])
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(archive.namelist()) == ["acc1/labels.json", "acc1/session.db"]
    copy = tmp_path / "copy.db"
    copy.write_bytes(archive.read("acc1/session.db"))
    # the WAL was not checkpointed: the copy still has every row
    assert sqlite3.connect(copy).execute("SELECT COUNT(*) FROM keys").fetchone() == (3,)
    open_db.close()


@pytest.mark.parametrize("names", [
    ["../x/session.db"], ["acc1/other.db"], ["acc1/sub/session.db"], ["session.db"],
    ["acc1\\session.db"], [], ["bad name/session.db"]])
def test_a_restore_takes_only_known_files(names):
    with pytest.raises(ValueError):
        sb.restore_plan(names)


def test_restore_plan():
    assert sb.restore_plan(["acc1/", "acc1/session.db", "acc1/carts.json", "acc2/bridge.db"]) == {
        "acc1": ["session.db", "carts.json"], "acc2": ["bridge.db"]}


def test_restore_never_writes_over_a_running_account(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("acc1/session.db", b"one")
        archive.writestr("acc2/session.db", b"two")
    os.makedirs(tmp_path / "acc1")
    (tmp_path / "acc1" / "session.db-wal").write_bytes(b"old journal")
    archive = zipfile.ZipFile(data)
    restored, skipped = sb.apply_restore(str(tmp_path), archive,
                                         sb.restore_plan(archive.namelist()),
                                         lambda name: name == "acc2")
    assert (restored, skipped) == (["acc1"], ["acc2"])
    assert (tmp_path / "acc1" / "session.db").read_bytes() == b"one"
    assert not (tmp_path / "acc1" / "session.db-wal").exists()
    assert not (tmp_path / "acc2").exists()


def test_running_means_a_live_client():
    from types import SimpleNamespace as N
    state = {"sessions": {"a": N(client=object()), "b": N(client=None)}}
    assert sb.running(state, "a") and not sb.running(state, "b") and not sb.running(state, "c")
