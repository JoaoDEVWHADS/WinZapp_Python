"""With a custom API the Chrome profile is the server's, not this machine's
(issue #414).

"Use custom API (remote server)" (`connection.wpp_custom_api`) points WinZapp
at a WPPConnect it did not start — on the reporter's setup, a Linux VPS. The
browser, its `userDataDir` and every lock on it live there, while WinZapp kept
inspecting `<global_dir>/api/userDataDir/<session>` on the Windows client: an
empty folder, so every shutdown audited `login_store=absent`, the profile
recovery read `verdict=missing` and told the user "the profile is damaged and
there is no saved copy" about an intact 25 MB profile on the server.

What is pinned here is that none of the local-profile machinery runs against
a custom API — it can neither judge nor restore a profile it cannot see — and
that a bundled-server install behaves exactly as before.
"""

import types

import pytest

from core import profile_recovery
from core.profile_recovery import profile_is_local
from main_window.connection import ConnectionMixin
from main_window.session_lifecycle import SessionLifecycleMixin
from main_window.wpp_server import WppServerMixin


def _forbidden(*args, **kwargs):
    raise AssertionError("the local profile must not be touched with a custom API")


class _Stub:
    def __init__(self, custom_api=True, global_dir="/g"):
        self.wpp_custom_api = custom_api
        self.global_dir = global_dir
        self.token = "sess123:tok"
        self.settings = {"privateinfo": {"paired": True}}
        self.audits = []

    def _shutdown_audit(self, line):
        self.audits.append(line)

    def _stop_neonize_bridge(self):
        self.bridge_stopped = True

    neonize = False

    def _uses_neonize(self):
        return self.neonize


@pytest.mark.parametrize("owner,expected", [
    (types.SimpleNamespace(), True),
    (types.SimpleNamespace(wpp_custom_api=False), True),
    (types.SimpleNamespace(wpp_custom_api=True), False),
])
def test_only_the_bundled_server_keeps_its_profile_here(owner, expected):
    assert profile_is_local(owner) is expected


class TestRecovery:
    def test_a_custom_api_never_hears_its_profile_is_damaged(self, monkeypatch):
        import main_window.session_lifecycle as module
        monkeypatch.setattr(module.wx, "CallAfter", _forbidden)
        stub = _Stub()
        stub.browser_payload_blocks_startup = _forbidden
        assert SessionLifecycleMixin._recover_suspect_profile(stub) is False
        # The once-per-launch budget is left alone: nothing was spent.
        assert not getattr(stub, "_profile_recovery_attempted", False)
        assert len(stub.audits) == 1 and "custom API server" in stub.audits[0]

    @pytest.mark.parametrize("custom_api", [True, False])
    def test_an_early_repair_is_worth_trying_only_on_a_local_profile(
            self, monkeypatch, custom_api):
        import main_window.session_lifecycle as module
        # A newest snapshot that would restore: only the setting decides.
        monkeypatch.setattr(module, "pick_restore_generation",
                            lambda *args: (False, "ok", False))
        stub = _Stub(custom_api=custom_api)
        stub._profile_recovery_generation = lambda: 0
        assert SessionLifecycleMixin._profile_restore_worth_trying(stub) is (not custom_api)

    @pytest.mark.parametrize("custom_api", [True, False])
    def test_a_snapshot_is_taken_at_close_only_of_a_local_profile(
            self, monkeypatch, custom_api):
        copied = []
        monkeypatch.setattr(profile_recovery, "capture_snapshot",
                            lambda *args, **kwargs: copied.append(args) or True)
        monkeypatch.setattr(profile_recovery, "discard_pending_snapshot",
                            lambda *args: None)
        SessionLifecycleMixin._capture_profile_snapshot(
            _Stub(custom_api=custom_api), "sess123", True, None)
        assert bool(copied) is (not custom_api)


class TestLiveBackup:
    def test_never_closes_the_server_session_for_a_backup(self):
        stub = _Stub()
        stub._live_snapshot_last_attempt = 0
        stub.settings["profile_backup"] = {"live_snapshot_enabled": True,
                                           "live_snapshot_interval_hours": 1,
                                           "live_snapshot_confirm": False}
        stub._start_live_snapshot_worker = _forbidden
        stub._ask_live_profile_snapshot = _forbidden
        SessionLifecycleMixin._maybe_refresh_profile_snapshot_live(stub, now=10 * 3600)
        assert not getattr(stub, "_live_snapshot_pending", False)

    def test_the_worker_is_refused_too(self):
        assert SessionLifecycleMixin._live_snapshot_blocked_reason(_Stub()) == (
            "the profile is on the custom API server")


class TestProfileRelease:
    def test_release_is_the_servers_to_wait_for(self, monkeypatch):
        import main_window.connection as module
        monkeypatch.setattr(module.sys, "platform", "win32")
        stub = _Stub()
        stub._chrome_pids_owning_session = _forbidden
        stub._kill_orphaned_chrome_for_session = _forbidden
        assert ConnectionMixin.wait_for_profile_release(stub, "sess123") is True
        assert stub.audits == []  # no "profile released" that never happened

    def test_no_local_chrome_is_killed_and_no_lock_removed(self, monkeypatch):
        import main_window.connection as module
        monkeypatch.setattr(module.sys, "platform", "win32")
        monkeypatch.setattr(module.subprocess, "check_output", _forbidden)
        monkeypatch.setattr(module.os, "remove", _forbidden)
        assert ConnectionMixin._kill_orphaned_chrome_for_session(_Stub(), "sess123") is None


class TestAuditFingerprint:
    def test_a_custom_api_profile_reads_remote_not_absent(self):
        assert ConnectionMixin._login_store_fingerprint(_Stub()) == "remote"

    def test_a_bundled_server_still_reads_the_local_store(self, tmp_path):
        stub = _Stub(custom_api=False, global_dir=str(tmp_path))
        assert ConnectionMixin._login_store_fingerprint(stub) == "absent"


class TestShutdown:
    def test_a_custom_api_server_is_never_killed_on_the_way_out(self):
        stub = _Stub()
        stub.token = ""          # no session to close: straight to the Node step
        stub.global_dir = None   # no lease to release
        stub.wpp_process = None
        stub._close_orphaned_server_sessions = lambda: None
        stub._find_pid_listening_on_port = _forbidden
        stub.wait_for_profile_release = _forbidden
        WppServerMixin._stop_wpp_server(stub, budget=5.0)
        assert stub.audits[-1] == "custom API — the server is not ours to stop"

    def test_the_orphan_sweep_does_not_run_on_the_neonize_bridge(self):
        """The bridge answers 401 to check-connection-session / close-session
        by bare name, which the sweep counted as "closed"; and the sessions it
        holds are the other accounts' of this install."""
        stub = _Stub()
        stub.neonize = True
        stub.token = ""
        stub.global_dir = None
        stub.wpp_process = None
        swept = []
        stub._close_orphaned_server_sessions = lambda: swept.append(True)
        WppServerMixin._stop_wpp_server(stub, budget=5.0)
        assert swept == [] and stub.bridge_stopped is True

    def test_the_orphan_sweep_still_runs_on_a_custom_server(self):
        stub = _Stub()
        stub.token = ""
        stub.global_dir = None
        stub.wpp_process = None
        swept = []
        stub._close_orphaned_server_sessions = lambda: swept.append(True)
        WppServerMixin._stop_wpp_server(stub, budget=5.0)
        assert swept == [True]

    def test_a_bundled_server_left_from_a_crash_is_still_found_by_port(self):
        stub = _Stub(custom_api=False)
        stub.token = ""
        stub.global_dir = None
        stub.wpp_process = None
        stub.wpp_port = 6300
        looked_up = []
        stub._find_pid_listening_on_port = lambda port: looked_up.append(port)
        WppServerMixin._stop_wpp_server(stub, budget=5.0)
        assert looked_up == [6300]
        assert stub.audits[-1] == "no node pid to kill (proc gone / port free)"


class TestStaleLocks:
    def test_a_dangling_singleton_symlink_is_removed(self, tmp_path, monkeypatch):
        """Chrome's SingletonLock is a symlink to `<host>-<pid>`; once that
        process is gone it dangles, and os.path.exists() follows it to
        nothing (issue #414)."""
        import main_window.connection as module
        profile = tmp_path / "api" / "userDataDir" / "sess123"
        profile.mkdir(parents=True)
        lock = profile / "SingletonLock"
        try:
            lock.symlink_to(tmp_path / "host-12345")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available here")
        (profile / "lockfile").write_text("", encoding="utf-8")
        monkeypatch.setattr(module.sys, "platform", "win32")
        monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "")
        stub = _Stub(custom_api=False, global_dir=str(tmp_path))

        ConnectionMixin._kill_orphaned_chrome_for_session(stub, "sess123")

        assert not lock.is_symlink() and not (profile / "lockfile").exists()
