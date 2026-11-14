"""A stored session belongs to the connection engine that made it.

Reported live on the first switch from WPPConnect to Neonize: the new engine was
handed the WPPConnect token, the bridge answered with a pairing code, and the
client took that for a lost profile, then for a logout, and only "Disconnect
all" and a restart got the account to pair. The session of the other engine is
now set aside at startup and the account starts unpaired on the new one; going
back brings the old session back.
"""

from core import connection_engine as engines
from core import session_engine
from main import MainWindow
from session_store import SessionStore, sessions_to_close


WPP_TOKEN = "wpp-session:$2b$10$abcdef"
BRIDGE_TOKEN = "neo-session:" + "a1" * 32


def _paired(engine=None, token=WPP_TOKEN):
    info = {"WA_token_protected": token, "paired": True, "WA_phone_number": "5511",
            "WA_phone_number_linked": "5511"}
    if engine:
        info["session_engine"] = engine
    return info


class TestReconcile:
    def test_an_untagged_session_is_the_wppconnect_one(self):
        info = _paired()
        assert session_engine.reconcile(info, engines.NEONIZE, WPP_TOKEN) == session_engine.PARKED
        assert "paired" not in info and "WA_token_protected" not in info
        assert info["session_engine"] == engines.NEONIZE
        assert info["engine_sessions"][engines.WPPCONNECT]["WA_token_protected"] == WPP_TOKEN
        assert info["engine_sessions"][engines.WPPCONNECT]["paired"] is True

    def test_the_local_data_record_stays_with_the_account(self):
        info = _paired()
        session_engine.reconcile(info, engines.NEONIZE, WPP_TOKEN)
        assert info["WA_phone_number_linked"] == "5511"

    def test_the_same_engine_changes_nothing(self):
        info = _paired(engines.WPPCONNECT)
        before = dict(info)
        assert session_engine.reconcile(info, engines.WPPCONNECT) == session_engine.UNCHANGED
        assert info == before

    def test_an_untagged_session_on_the_default_engine_is_just_tagged(self):
        info = _paired()
        assert session_engine.reconcile(info, engines.WPPCONNECT, WPP_TOKEN) == session_engine.UNCHANGED
        assert info["session_engine"] == engines.WPPCONNECT
        assert info["paired"] is True

    def test_going_back_restores_the_parked_session(self):
        info = _paired()
        session_engine.reconcile(info, engines.NEONIZE, WPP_TOKEN)
        info.update({"WA_token_protected": BRIDGE_TOKEN, "paired": True})
        assert session_engine.reconcile(info, engines.WPPCONNECT, WPP_TOKEN) == session_engine.RESTORED
        assert info["WA_token_protected"] == WPP_TOKEN
        assert info["WA_phone_number"] == "5511"
        assert info["session_engine"] == engines.WPPCONNECT
        assert list(info["engine_sessions"]) == [engines.NEONIZE]
        assert session_engine.reconcile(info, engines.NEONIZE, BRIDGE_TOKEN) == session_engine.RESTORED
        assert info["WA_token_protected"] == BRIDGE_TOKEN
        assert "engine_sessions" in info and list(info["engine_sessions"]) == [engines.WPPCONNECT]


    def test_a_legacy_session_of_a_custom_server_stays_with_it(self):
        info = _paired()
        assert session_engine.reconcile(info, engines.CUSTOM, WPP_TOKEN) == session_engine.UNCHANGED
        assert info["paired"] is True
        assert info["session_engine"] == engines.CUSTOM

    def test_a_legacy_bridge_session_is_neonizes_and_parked_elsewhere(self):
        info = _paired(token=BRIDGE_TOKEN)
        assert session_engine.reconcile(info, engines.NEONIZE, BRIDGE_TOKEN) == session_engine.UNCHANGED
        info = _paired(token=BRIDGE_TOKEN)
        assert session_engine.reconcile(info, engines.WPPCONNECT, BRIDGE_TOKEN) == session_engine.PARKED
        assert info["engine_sessions"][engines.NEONIZE]["WA_token_protected"] == BRIDGE_TOKEN

    def test_an_untagged_session_store_entry_is_told_apart_by_its_token(self):
        entry_w = {"name": "w", "token": WPP_TOKEN}
        entry_n = {"name": "n", "token": BRIDGE_TOKEN}
        assert session_engine.entry_engine(entry_w, engines.NEONIZE) == engines.WPPCONNECT
        assert session_engine.entry_engine(entry_n, engines.WPPCONNECT) == engines.NEONIZE
        assert session_engine.entry_engine(entry_w, engines.CUSTOM) == engines.CUSTOM
        assert session_engine.entry_engine({"name": "x"}, engines.NEONIZE) == engines.NEONIZE

    def test_an_account_that_never_paired_just_takes_the_engine(self):
        info = {"WA_token": ""}
        assert session_engine.reconcile(info, engines.NEONIZE) == session_engine.UNCHANGED
        assert info["session_engine"] == engines.NEONIZE
        assert "engine_sessions" not in info

    def test_a_tag_that_names_no_engine_is_ignored(self):
        info = _paired("unknown")
        assert session_engine.reconcile(info, engines.NEONIZE, WPP_TOKEN) == session_engine.PARKED


class _Crypto:
    def encrypt(self, text):
        return text

    def decrypt(self, text):
        return text


class TestSessionStoreEngines:
    def test_the_engine_is_recorded_and_defaults_to_wppconnect(self, tmp_path):
        store = SessionStore(str(tmp_path), _Crypto())
        store.register("old", "old:hash")
        store.register("new", "new:hash", engine=engines.NEONIZE)
        assert session_engine.entry_engine(store.get("old")) == engines.WPPCONNECT
        assert session_engine.entry_engine(store.get("new")) == engines.NEONIZE

    def test_cleanup_only_takes_the_sessions_of_the_running_engine(self):
        sessions = [
            {"name": "w", "status": "abandoned", "token": WPP_TOKEN},
            {"name": "n", "status": "abandoned", "engine": engines.NEONIZE},
            {"name": "live", "status": "active", "engine": engines.NEONIZE},
        ]
        assert [s["name"] for s in sessions_to_close(sessions, "x")] == ["w", "n"]
        assert [s["name"] for s in sessions_to_close(sessions, "x", engines.NEONIZE)] == ["n"]
        assert [s["name"] for s in sessions_to_close(sessions, "x", engines.WPPCONNECT)] == ["w"]


class _Stub:
    _reconcile_session_engine = MainWindow._reconcile_session_engine
    _session_engine_name = MainWindow._session_engine_name

    def __init__(self, engine, private_info):
        self.wpp_engine = engine
        self.settings = {"privateinfo": private_info}
        self.token = "stale:token"
        self.saved = 0
        self.audit = []
        self.announced = 0

    def _get_wa_token(self):
        return WPP_TOKEN

    def _announce_engine_switch(self):
        self.announced += 1

    def save_settings(self):
        self.saved += 1

    def _shutdown_audit(self, line):
        self.audit.append(line)


class TestStartupReconcile:
    def test_a_switch_parks_the_session_clears_the_token_and_saves(self):
        stub = _Stub(engines.NEONIZE, _paired())
        stub._reconcile_session_engine()
        assert stub.token == ""
        assert stub.saved == 1
        assert "paired" not in stub.settings["privateinfo"]
        assert stub.audit == ["engine switch (unrecorded) -> neonize: parked"]

    def test_the_user_is_told_once_why_pairing_is_asked_again(self):
        stub = _Stub(engines.NEONIZE, _paired())
        stub._reconcile_session_engine()
        stub._reconcile_session_engine()
        assert stub.announced == 1

    def test_a_background_start_does_not_open_a_box(self):
        stub = _Stub(engines.NEONIZE, _paired())
        stub.background_mode = True
        stub._reconcile_session_engine()
        assert stub.announced == 0

    def test_going_back_to_a_parked_session_needs_no_explanation(self):
        info = _paired()
        session_engine.reconcile(info, engines.NEONIZE, WPP_TOKEN)
        stub = _Stub(engines.WPPCONNECT, info)
        stub._reconcile_session_engine()
        assert stub.announced == 0
        assert stub.settings["privateinfo"]["paired"] is True

    def test_a_second_start_on_the_same_engine_does_not_save_again(self):
        stub = _Stub(engines.NEONIZE, _paired())
        stub._reconcile_session_engine()
        stub.saved = 0
        stub.token = "kept"
        stub._reconcile_session_engine()
        assert stub.saved == 0
        assert stub.token == "kept"


class _RecordingStore:
    def __init__(self, entries):
        self.entries = entries
        self.abandoned = []
        self.registered = []

    def list(self):
        return list(self.entries)

    def set_status(self, name, status):
        self.abandoned.append((name, status))

    def register(self, name, token=None, status="active", engine=None):
        self.registered.append((name, status, engine))


class _TokenStub:
    _set_wa_token = MainWindow._set_wa_token
    _session_engine_name = MainWindow._session_engine_name
    global_dir = None

    def __init__(self, engine, store):
        from cryptography.fernet import Fernet
        self.wpp_engine = engine
        self.settings = {"privateinfo": {}}
        self._key = Fernet.generate_key()
        self._store = store

    def _token_key(self):
        return self._key

    def save_settings(self):
        pass

    def _get_session_store(self):
        return self._store


class TestPairingOnTheNewEngine:
    def test_the_session_of_the_other_engine_is_not_abandoned(self):
        store = _RecordingStore([
            {"name": "wpp", "status": "active", "token": WPP_TOKEN},
            {"name": "neo-old", "status": "active", "engine": engines.NEONIZE},
        ])
        _TokenStub(engines.NEONIZE, store)._set_wa_token("neo-new:hash")
        assert store.abandoned == [("neo-old", "abandoned")]
        assert store.registered == [("neo-new", "active", engines.NEONIZE)]
