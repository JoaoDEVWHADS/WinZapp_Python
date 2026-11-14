"""Deleting an account from the bridge: never deletes anything outside the data folder,
requires the session's own credential and takes the databases and the name in active.json
along. Temporary folder and fake sessions, without neonize."""
import json
import os
import sqlite3
from types import SimpleNamespace as N

import pytest
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth
import cleanup
import server
from store import Store


def _account(folder, name):
    """A fake paired account: the two databases and a stray file."""
    target = folder / name
    target.mkdir()
    (target / "session.db").write_bytes(b"keys")
    (target / "bridge.db").write_bytes(b"messages")
    return target


# ------------------------------------------------------------ pure functions

@pytest.mark.parametrize("name", ["..", ".", "a/b", "a\\b", "../outside", "", None, "a b",
                                  "/etc", "C:\\x", "a" * 129])
def test_a_name_that_is_not_a_session_has_no_folder(tmp_path, name):
    assert cleanup.session_folder(str(tmp_path), name) is None


def test_an_ordinary_name_resolves_to_a_direct_child(tmp_path):
    assert cleanup.session_folder(str(tmp_path), "account-1_a") == os.path.join(
        os.path.realpath(tmp_path), "account-1_a")


def test_a_shortcut_to_the_outside_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important.txt").write_text("do not delete")
    data = tmp_path / "data"
    data.mkdir()
    try:
        os.symlink(outside, data / "account1", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symbolic link on this system")

    assert cleanup.session_folder(str(data), "account1") is None
    assert cleanup.delete_folder(str(data), "account1") is False
    assert (outside / "important.txt").read_text() == "do not delete"


def test_deleting_takes_the_accounts_folder_and_only_that(tmp_path):
    _account(tmp_path, "account1")
    other = _account(tmp_path, "account2")
    (tmp_path / "secret").write_text("s")

    assert cleanup.delete_folder(str(tmp_path), "account1") is True

    assert not (tmp_path / "account1").exists()
    assert (other / "session.db").exists() and (tmp_path / "secret").exists()


def test_deleting_again_a_folder_that_no_longer_exists_finishes_the_job(tmp_path):
    assert cleanup.delete_folder(str(tmp_path), "account1") is True


def test_a_folder_that_cannot_be_deleted_is_reported_as_a_failure(tmp_path):
    _account(tmp_path, "account1")

    def refuse(_target):
        raise PermissionError("in use")

    assert cleanup.delete_folder(str(tmp_path), "account1", remove=refuse) is False
    assert (tmp_path / "account1" / "session.db").exists()


def test_the_closed_store_releases_the_file(tmp_path):
    db = Store(str(tmp_path / "bridge.db"))
    db.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db.chats()


def test_shut_down_leaves_the_account_stops_the_session_and_releases_the_databases():
    calls = []
    account = N(client=object(), status="CONNECTED", thread=N(join=lambda t: calls.append("join")),
                leave=lambda: calls.append("leave"),
                db=N(close=lambda: calls.append("close")))
    assert cleanup.shut_down(account) is True
    assert calls == ["leave", "join", "close"]


def test_shutting_down_a_disconnected_account_says_it_did_not_unlink():
    account = N(client=None, status="CLOSED", thread=None, leave=lambda: None,
                db=N(close=lambda: None))
    assert cleanup.shut_down(account) is False


# ------------------------------------------------------- the real server

async def _server(folder):
    client = TestClient(TestServer(server.create_app(str(folder))))
    await client.start_server()
    secret = (folder / auth.SECRET_FILE).read_text(encoding="utf-8")
    return client, secret


def _credential(secret, name):
    return f"{name}:{auth.session_token(secret, name)}"


@pytest.mark.asyncio
async def test_deleting_the_account_takes_the_folder_the_name_in_active_and_the_session(tmp_path):
    client, secret = await _server(tmp_path)
    try:
        credential = _credential(secret, "account1")
        # the bridge opens the account (creates bridge.db) as any app call would
        assert (await client.get(f"/api/{credential}/status-session")).status == 200
        (tmp_path / "account1" / "session.db").write_bytes(b"keys")
        other = _account(tmp_path, "account2")
        (tmp_path / "active.json").write_text(json.dumps(["account1", "account2"]))

        response = await client.post(f"/api/{credential}/delete-session")

        assert response.status == 200
        assert (await response.json())["response"]["removed"] is True
        assert not (tmp_path / "account1").exists()
        assert json.loads((tmp_path / "active.json").read_text()) == ["account2"]
        assert (other / "session.db").exists()
        listed = await (await client.get(f"/api/{secret}/show-all-sessions")).json()
        assert listed["response"] == []
        # asking again (the first answer may have been lost) also finishes
        assert (await client.post(f"/api/{credential}/delete-session")).status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_without_a_credential_or_with_another_accounts_nothing_is_deleted(tmp_path):
    client, secret = await _server(tmp_path)
    try:
        target = _account(tmp_path, "account1")

        assert (await client.post("/api/account1/delete-session")).status == 401
        assert (await client.post("/api/account1:wrong/delete-session")).status == 401
        of_another = _credential(secret, "account2")
        assert (await client.post(f"/api/account1:{of_another.split(':')[1]}/delete-session")
                ).status == 401
        # the bridge's secret, in place of the token, does not work either
        assert (await client.post(f"/api/{secret}/delete-session")).status == 401

        assert (target / "session.db").exists()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["..", "a%2Fb", "a%2F..%2F..%2Foutside", "a%5Cb"])
async def test_a_name_that_escapes_the_folder_is_refused_even_with_a_valid_credential(tmp_path, name):
    """The hash is checked over the text of the name; whoever has the secret (the
    client itself) still cannot point the route outside the data folder."""
    data = tmp_path / "data"
    data.mkdir()
    client, secret = await _server(data)
    try:
        (tmp_path / "important.txt").write_text("do not delete")
        decoded = name.replace("%2F", "/").replace("%5C", "\\")
        credential = _credential(secret, decoded)

        response = await client.post(f"/api/{name}:{credential.split(':')[1]}/delete-session")

        assert response.status in (400, 404)
        assert (tmp_path / "important.txt").read_text() == "do not delete"
        assert data.exists()
    finally:
        await client.close()


def test_shut_down_also_releases_the_app_state_copy():
    calls = []
    account = N(client=None, status="CLOSED", thread=None, leave=lambda: None,
                db=N(close=lambda: calls.append("db")),
                app_state=N(close=lambda: calls.append("app_state")))
    cleanup.shut_down(account)
    assert calls == ["db", "app_state"]


@pytest.mark.asyncio
async def test_clear_session_data_needs_the_secret_and_takes_the_account(tmp_path):
    client, secret = await _server(tmp_path)
    try:
        credential = _credential(secret, "account1")
        assert (await client.get(f"/api/{credential}/status-session")).status == 200
        (tmp_path / "account1" / "session.db").write_bytes(b"keys")
        assert (await client.post(f"/api/account1/{credential}/clear-session-data")).status == 401
        assert (tmp_path / "account1").exists()
        response = await client.post(f"/api/account1/{secret}/clear-session-data")
        assert response.status == 200 and await response.json() == {"success": True}
        assert not (tmp_path / "account1").exists()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_backup_and_restore_need_the_secret(tmp_path):
    import io
    import zipfile
    client, secret = await _server(tmp_path)
    try:
        (tmp_path / "account2").mkdir()
        sqlite3.connect(tmp_path / "account2" / "session.db").execute("CREATE TABLE k(v)").close()
        assert (await client.get("/api/wrong/backup-sessions")).status == 401
        response = await client.get(f"/api/{secret}/backup-sessions")
        assert response.status == 200 and response.content_type == "application/zip"
        names = zipfile.ZipFile(io.BytesIO(await response.read())).namelist()
        assert "account2/session.db" in names
    finally:
        await client.close()
