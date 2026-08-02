"""Tests for client/session_store.py — per-account WPPConnect session isolation."""

import os

import pytest

import session_store as ss


def _acc_dir(tmp_path):
    d = str(tmp_path / "accounts" / ("a" * 32))
    os.makedirs(d, exist_ok=True)
    return d


class FakeCrypto:
    """Reversible stand-in for the Fernet token vault. base64 so the plaintext
    isn't literally present on disk (mirrors real encryption for the test)."""
    def encrypt(self, s: str) -> str:
        import base64
        return "enc:" + base64.b64encode(s.encode()).decode()

    def decrypt(self, s: str) -> str:
        import base64
        assert s.startswith("enc:")
        return base64.b64decode(s[len("enc:"):]).decode()


def _store(tmp_path):
    return ss.SessionStore(_acc_dir(tmp_path), crypto=FakeCrypto())


def test_register_and_get_session(tmp_path):
    st = _store(tmp_path)
    st.register("winzapp_aaa", token="winzapp_aaa:HASH", status="active")
    s = st.get("winzapp_aaa")
    assert s["status"] == "active"
    assert s["token"] == "winzapp_aaa:HASH"  # transparently decrypted


def test_token_stored_encrypted_on_disk(tmp_path):
    st = _store(tmp_path)
    st.register("s1", token="s1:SECRET", status="active")
    raw = open(os.path.join(_acc_dir(tmp_path), "sessions.json")).read()
    assert "SECRET" not in raw  # never plaintext
    assert "enc:" in raw


def test_sessions_to_close_excludes_current_and_pairing(tmp_path):
    st = _store(tmp_path)
    st.register("cur", token="cur:H", status="active")
    st.register("old", token="old:H", status="abandoned")
    st.register("pair", token="pair:H", status="pairing")
    to_close = ss.sessions_to_close(st.list(), current_session="cur")
    names = {s["name"] for s in to_close}
    # only 'abandoned' (not current 'active', not 'pairing') should be closed
    assert names == {"old"}


def test_set_status(tmp_path):
    st = _store(tmp_path)
    st.register("s1", token="s1:H", status="pairing")
    st.set_status("s1", "active")
    assert st.get("s1")["status"] == "active"


def test_pairing_crash_owner_recorded(tmp_path):
    st = _store(tmp_path)
    st.register("s1", token="s1:H", status="pairing",
                owner_pid=123, owner_create_time=1.0, attempt_id="att1")
    s = st.get("s1")
    assert s["owner_pid"] == 123 and s["attempt_id"] == "att1"


def test_corrupt_token_treated_as_absent(tmp_path):
    """A token that fails to decrypt must not crash — treated as no token."""
    class BadCrypto:
        def encrypt(self, s): return "enc:" + s
        def decrypt(self, s): raise ValueError("bad key")
    d = _acc_dir(tmp_path)
    st = ss.SessionStore(d, crypto=FakeCrypto())
    st.register("s1", token="s1:H", status="active")
    st2 = ss.SessionStore(d, crypto=BadCrypto())
    assert st2.get("s1")["token"] is None  # decrypt failure -> None, no crash


def test_migrate_legacy_token(tmp_path):
    """A migrated account with a legacy token but no sessions.json gets one
    seeded (status active)."""
    st = _store(tmp_path)
    sess = st.ensure_from_legacy_token("winzapp_default", "winzapp_default:LEGACY")
    assert sess["status"] == "active"
    assert st.get("winzapp_default")["token"] == "winzapp_default:LEGACY"


def test_second_account_cleanup_never_touches_first_accounts_session(tmp_path):
    """REGRESSION (real multi-account bug): pairing/cleaning account B must
    NEVER close account A's live session. Ownership is proven per-account from
    each account's OWN sessions.json — B's store has no knowledge of A's
    session 'sessA', so it can never appear in B's sessions_to_close()."""
    a_dir = str(tmp_path / "accounts" / ("a" * 32))
    b_dir = str(tmp_path / "accounts" / ("b" * 32))
    os.makedirs(a_dir, exist_ok=True)
    os.makedirs(b_dir, exist_ok=True)
    store_a = ss.SessionStore(a_dir, crypto=FakeCrypto())
    store_b = ss.SessionStore(b_dir, crypto=FakeCrypto())
    store_a.register("sessA", token="sessA:H", status="active")
    # B pairs a new session, superseding its own old one.
    store_b.register("sessB_old", token="sessB_old:H", status="abandoned")
    store_b.register("sessB_new", token="sessB_new:H", status="active")
    closable = ss.sessions_to_close(store_b.list(), current_session="sessB_new")
    names = {s["name"] for s in closable}
    assert names == {"sessB_old"}          # only B's own abandoned one
    assert "sessA" not in names            # A's live session is untouchable
