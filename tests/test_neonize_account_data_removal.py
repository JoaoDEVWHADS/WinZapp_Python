"""Removing an account (or cleaning an abandoned pairing) on the Neonize engine
removes its data from the bridge.

Audit F4, H2: the WhatsApp keys and every message of an account live in
neonize_bridge/data/<session>/, which account_removal.py (browser profile
and restore points) never touched, and the device stayed linked on the phone.
The bridge deletes it (neonize_bridge/cleanup.py); the client asks for each
session name and keeps the account 'deleting' while the bridge has not
confirmed.
"""
import json
import os
import types

import pytest

import account_removal
from accounts import AccountRegistry
from core import neonize_session_data as data
from main_window.neonize_bridge import NeonizeBridgeMixin

SESSION_A = "a" * 32
SESSION_B = "c" * 32
SECRET = "s3cr3t-of-the-bridge"
BASE = "http://127.0.0.1:6300"


class _Response:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def _bridge(delete_status=200, mint_status=200, raises=None):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if raises is not None:
            raise raises
        if url.endswith("/generate-token"):
            return _Response(mint_status, {"token": "hash123"})
        return _Response(delete_status, {"status": "success"})

    return post, calls


class TestAskingTheBridge:
    def test_it_mints_the_sessions_token_then_deletes(self):
        post, calls = _bridge()
        assert data.delete_session(BASE, SECRET, SESSION_A, post=post) is True
        assert calls == [f"{BASE}/api/{SESSION_A}/{SECRET}/generate-token",
                         f"{BASE}/api/{SESSION_A}:hash123/delete-session"]

    @pytest.mark.parametrize("kwargs", [
        {"delete_status": 500}, {"delete_status": 401}, {"mint_status": 401},
        {"raises": ConnectionError("refused")},
    ])
    def test_anything_but_a_confirmation_keeps_the_work_to_retry(self, kwargs):
        post, _calls = _bridge(**kwargs)
        assert data.delete_session(BASE, SECRET, SESSION_A, post=post) is False

    def test_the_secret_is_never_logged(self, caplog):
        post, _calls = _bridge(raises=ConnectionError(f"{BASE}/api/x/{SECRET}/generate-token"))
        with caplog.at_level("DEBUG"):
            data.delete_session(BASE, SECRET, SESSION_A, post=post)
        assert SECRET not in caplog.text


@pytest.fixture
def install(tmp_path):
    global_dir = tmp_path / "global"
    registry = AccountRegistry(str(global_dir))
    return registry, str(global_dir)


def _account(registry, sessions):
    account = registry.add("one", state="paired")
    folder = registry.data_dir_for(account["id"])
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "sessions.json"), "w", encoding="utf-8") as handle:
        json.dump({"sessions": sessions}, handle)
    return account


class TestRemovingTheAccount:
    def test_every_session_name_goes_to_the_bridge_and_the_account_is_dropped(self, install):
        registry, global_dir = install
        account = _account(registry, [{"name": SESSION_A, "status": "active"},
                                      {"name": SESSION_B, "status": "abandoned"}])
        asked = []

        done = account_removal.purge_account(
            registry, global_dir, account["id"],
            lambda name: asked.append(name) or True)

        assert done is True and sorted(asked) == sorted([SESSION_A, SESSION_B])
        assert registry.get(account["id"]) is None

    def test_a_bridge_that_does_not_confirm_keeps_the_account_deleting(self, install):
        registry, global_dir = install
        account = _account(registry, [{"name": SESSION_A, "status": "active"}])

        done = account_removal.purge_account(
            registry, global_dir, account["id"], lambda name: False)

        assert done is False
        assert registry.get(account["id"])["state"] == "deleting"
        # the names survive for the retry once the bridge is up
        assert account_removal.session_names(registry.data_dir_for(account["id"])) == [SESSION_A]

    def test_the_retry_finishes_it(self, install):
        registry, global_dir = install
        account = _account(registry, [{"name": SESSION_A, "status": "active"}])
        account_removal.purge_account(registry, global_dir, account["id"], lambda name: False)

        assert account_removal.finish_pending_deletions(
            registry, global_dir, lambda name: True) == 1
        assert registry.get(account["id"]) is None

    def test_a_session_another_account_still_uses_is_not_asked_about(self, install):
        registry, global_dir = install
        mine = _account(registry, [{"name": SESSION_A, "status": "active"},
                                   {"name": SESSION_B, "status": "active"}])
        _account(registry, [{"name": SESSION_B, "status": "active"}])
        asked = []

        account_removal.purge_account(registry, global_dir, mine["id"],
                                      lambda name: asked.append(name) or True)

        assert asked == [SESSION_A]

    def test_without_a_bridge_nothing_changes(self, install):
        registry, global_dir = install
        account = _account(registry, [{"name": SESSION_A, "status": "active"}])
        assert account_removal.purge_account(registry, global_dir, account["id"]) is True


class TestWhoGetsADeleter:
    def test_only_a_process_on_the_neonize_engine(self):
        wppconnect = types.SimpleNamespace(wpp_engine="wppconnect", wpp_custom_api=False)
        wppconnect._uses_neonize = lambda: NeonizeBridgeMixin._uses_neonize(wppconnect)
        assert NeonizeBridgeMixin._neonize_session_deleter(wppconnect) is None

    def test_the_deleter_talks_to_this_processs_bridge_with_its_secret(self, monkeypatch):
        seen = []
        monkeypatch.setattr(data, "delete_session",
                            lambda base, secret, name: seen.append((base, secret, name)) or True)
        window = types.SimpleNamespace(
            wpp_engine="neonize", wpp_custom_api=True, wpp_server="http://127.0.0.1",
            wpp_port=6300, wpp_api_key=SECRET)
        window._uses_neonize = lambda: NeonizeBridgeMixin._uses_neonize(window)

        deleter = NeonizeBridgeMixin._neonize_session_deleter(window)

        assert deleter(SESSION_A) is True
        assert seen == [(BASE, SECRET, SESSION_A)]

    def test_before_a_window_exists_a_missing_bridge_defers_the_removal(self, tmp_path, monkeypatch):
        from app_settings import AppSettings
        from core import neonize_bridge_process as bridge
        AppSettings(str(tmp_path)).set("wpp_engine", "neonize")
        AppSettings(str(tmp_path)).set("wpp_custom_api", True)
        monkeypatch.setattr(bridge, "port_open", lambda *a, **k: False)
        monkeypatch.setattr(bridge, "read_secret", lambda *a, **k: SECRET)

        deleter = data.startup_deleter(str(tmp_path))

        assert deleter is not None and deleter(SESSION_A) is False

    def test_before_a_window_exists_other_engines_have_no_deleter(self, tmp_path):
        assert data.startup_deleter(str(tmp_path)) is None


class _Store:
    def __init__(self, sessions):
        self.sessions, self.removed = sessions, []

    def list(self):
        return list(self.sessions)

    def remove(self, name):
        self.removed.append(name)


class TestAbandonedPairingAttempts:
    @pytest.fixture(autouse=True)
    def _inert_lock(self, monkeypatch):
        import coord_locks

        class _Null:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(coord_locks, "sessions_lock", lambda *a, **k: _Null())

    def _window(self, store, deleter, protected=()):
        window = types.SimpleNamespace(
            token=f"{SESSION_A}:hash", global_dir="unused", _get_session_store=lambda: store,
            _protected_session_names=lambda: set(protected),
            _session_engine_name=lambda: "neonize",
            _neonize_session_deleter=lambda: deleter)
        return window

    def test_a_superseded_attempt_is_deleted_on_the_bridge_and_forgotten(self):
        store = _Store([{"name": SESSION_B, "status": "abandoned", "engine": "neonize"},
                        {"name": SESSION_A, "status": "active", "engine": "neonize"}])
        asked = []
        window = self._window(store, lambda name: asked.append(name) or True)

        NeonizeBridgeMixin._cleanup_abandoned_bridge_sessions(window)

        assert asked == [SESSION_B] and store.removed == [SESSION_B]

    def test_a_refusal_keeps_the_row_for_the_next_start(self):
        store = _Store([{"name": SESSION_B, "status": "abandoned", "engine": "neonize"}])
        window = self._window(store, lambda name: False)

        NeonizeBridgeMixin._cleanup_abandoned_bridge_sessions(window)

        assert store.removed == []

    def test_a_name_another_account_uses_is_never_deleted(self):
        store = _Store([{"name": SESSION_B, "status": "abandoned", "engine": "neonize"}])
        asked = []
        window = self._window(store, lambda name: asked.append(name) or True,
                              protected={SESSION_B})

        NeonizeBridgeMixin._cleanup_abandoned_bridge_sessions(window)

        assert asked == [] and store.removed == []

    def test_a_session_of_the_other_engine_is_left_alone(self):
        store = _Store([{"name": SESSION_B, "status": "abandoned",
                         "token": f"{SESSION_B}:$2b$10$abcdef"}])
        asked = []
        window = self._window(store, lambda name: asked.append(name) or True)

        NeonizeBridgeMixin._cleanup_abandoned_bridge_sessions(window)

        assert asked == [] and store.removed == []

    def test_the_worker_uses_it_instead_of_skipping_a_custom_api(self):
        from main import MainWindow
        ran = []
        window = types.SimpleNamespace(
            wpp_custom_api=True, _uses_neonize=lambda: True,
            _cleanup_abandoned_bridge_sessions=lambda: ran.append(True))
        MainWindow._cleanup_abandoned_sessions_worker(window)
        assert ran == [True]


class TestTheBridgeOutlivesTheRemovalOfTheAccountInUse:
    def test_stopping_is_held_back_until_the_data_was_deleted(self):
        stopped = []
        window = types.SimpleNamespace(
            neonize_bridge=types.SimpleNamespace(stop=lambda: stopped.append(True)),
            _purge_account_on_exit="x" * 32)

        NeonizeBridgeMixin._stop_neonize_bridge(window)
        assert stopped == []

        NeonizeBridgeMixin._stop_neonize_bridge(window, force=True)
        assert stopped == [True]

    def test_a_normal_exit_still_stops_it(self):
        stopped = []
        window = types.SimpleNamespace(
            neonize_bridge=types.SimpleNamespace(stop=lambda: stopped.append(True)))
        NeonizeBridgeMixin._stop_neonize_bridge(window)
        assert stopped == [True]
