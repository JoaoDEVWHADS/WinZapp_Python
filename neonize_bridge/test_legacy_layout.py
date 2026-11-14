"""A data folder written under the old file names keeps working after the rename."""
import json
import sqlite3

import authentication as auth
import legacy_layout
import server
from store import Store


def _legacy_folder(tmp_path):
    (tmp_path / "segredo").write_text("s" * 64, encoding="utf-8")
    (tmp_path / "ativas.json").write_text(json.dumps(["account1"]), encoding="utf-8")
    account = tmp_path / "account1"
    account.mkdir()
    (account / "sessao.db").write_bytes(b"keys")
    (account / "sessao.db-wal").write_bytes(b"wal")
    (account / "ponte.db").write_bytes(b"messages")
    (account / "etiquetas.json").write_text("{}", encoding="utf-8")
    return account


def test_old_files_get_the_current_names(tmp_path):
    account = _legacy_folder(tmp_path)

    assert legacy_layout.migrate(str(tmp_path)) == 5

    assert (tmp_path / "secret").read_text(encoding="utf-8") == "s" * 64
    assert json.loads((tmp_path / "active.json").read_text(encoding="utf-8")) == ["account1"]
    assert (account / "session.db").read_bytes() == b"keys"
    assert (account / "session.db-wal").read_bytes() == b"wal"
    assert (account / "bridge.db").read_bytes() == b"messages"
    assert (account / "labels.json").exists()
    assert not (tmp_path / "segredo").exists() and not (account / "sessao.db").exists()


def test_running_it_again_changes_nothing(tmp_path):
    _legacy_folder(tmp_path)
    legacy_layout.migrate(str(tmp_path))
    assert legacy_layout.migrate(str(tmp_path)) == 0


def test_a_file_whose_new_name_exists_is_never_overwritten(tmp_path):
    account = _legacy_folder(tmp_path)
    (account / "bridge.db").write_bytes(b"newer")

    legacy_layout.migrate(str(tmp_path))

    assert (account / "bridge.db").read_bytes() == b"newer"
    assert (account / "ponte.db").read_bytes() == b"messages"      # left in place


def test_a_database_is_never_left_half_moved(tmp_path):
    account = _legacy_folder(tmp_path)
    calls = []

    def flaky(source, target):
        calls.append(source)
        if source.endswith("sessao.db-wal"):
            raise PermissionError("in use")
        import os
        os.replace(source, target)

    legacy_layout.migrate(str(tmp_path), rename=flaky)

    assert (account / "sessao.db").read_bytes() == b"keys"
    assert (account / "sessao.db-wal").read_bytes() == b"wal"
    assert not (account / "session.db").exists()


def test_a_missing_folder_is_not_an_error(tmp_path):
    assert legacy_layout.migrate(str(tmp_path / "does-not-exist")) == 0


def test_starting_the_server_migrates_the_folder_and_keeps_the_secret(tmp_path):
    _legacy_folder(tmp_path)

    server.create_app(str(tmp_path))

    assert auth.load_secret(str(tmp_path)) == "s" * 64
    assert (tmp_path / "account1" / "session.db").exists()


def test_a_legacy_database_keeps_its_messages_and_the_own_account_marker(tmp_path):
    path = str(tmp_path / "ponte.db")
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE chats(jid TEXT PRIMARY KEY, name TEXT DEFAULT '', ts INTEGER DEFAULT 0,
            unread INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0,
            muted INTEGER DEFAULT 0);
        CREATE TABLE msgs(chat TEXT NOT NULL, id TEXT NOT NULL, ts INTEGER NOT NULL,
            data TEXT NOT NULL, raw BLOB, PRIMARY KEY(chat, id));
        CREATE INDEX msgs_por_data ON msgs(chat, ts);
        CREATE TABLE votos(msg TEXT NOT NULL, quem TEXT NOT NULL, ids TEXT NOT NULL,
            ts INTEGER DEFAULT 0, PRIMARY KEY(msg, quem));
        CREATE TABLE reacoes(msg TEXT NOT NULL, quem TEXT NOT NULL, emoji TEXT NOT NULL,
            ts INTEGER DEFAULT 0, PRIMARY KEY(msg, quem));
        CREATE TABLE recibos(msg TEXT NOT NULL, quem TEXT NOT NULL, etapa TEXT NOT NULL,
            ts INTEGER DEFAULT 0, PRIMARY KEY(msg, quem, etapa));
        CREATE TABLE fixadas(msg TEXT PRIMARY KEY, chat TEXT NOT NULL, ts INTEGER DEFAULT 0,
            duracao INTEGER DEFAULT 0);
        CREATE TABLE comentarios(chat TEXT NOT NULL, id TEXT NOT NULL, parent_id TEXT NOT NULL,
            author TEXT DEFAULT '', ts INTEGER DEFAULT 0, type TEXT NOT NULL,
            body TEXT DEFAULT '', from_me INTEGER DEFAULT 0, serial_pai TEXT DEFAULT '',
            PRIMARY KEY(chat, id));
        INSERT INTO msgs VALUES ('c', 'm1', 5, '{"id": {"id": "m1"}, "t": 5, "body": "oi"}', NULL);
        INSERT INTO votos VALUES ('p1', 'eu', '[0]', 1), ('p1', '5551@c.us', '[1]', 2);
        INSERT INTO reacoes VALUES ('m1', 'eu', 'A', 1);
        INSERT INTO recibos VALUES ('m1', '5@c.us', 'read', 6);
        INSERT INTO fixadas VALUES ('m1', 'c', 10, 50);
        INSERT INTO comentarios VALUES ('c', 'C1', 'P', '1@lid', 3, 'comment', 'hi', 0, 'ser');
    """)
    legacy.commit()
    legacy.close()

    db = Store(path)

    assert [m["body"] for m in db.messages("c", 5)] == ["oi"]
    assert dict(db.votes_of("p1")) == {"me": [0], "5551@c.us": [1]}
    assert db.reactions_of("m1") == [("me", "A")]
    assert db.receipts_of("m1") == [("5@c.us", "read", 6)]
    assert [m["body"] for m in db.pinned_of(["c"], 20)] == ["oi"]
    assert db.comments_of("c", "P")[0]["body"] == "hi"
    assert db.comment_counts() == {"P": 1}
    db.close()
