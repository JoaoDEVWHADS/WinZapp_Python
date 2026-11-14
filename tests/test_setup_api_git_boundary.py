"""Tests for the current filesystem/Git boundary in setup_api.py.

Older versions exposed plan_api_checkout() and directory classification helpers.
The installer now decides mode directly from client/api/.git and node_modules;
these tests cover the surviving helpers without depending on deleted APIs.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _setup_api_module():
    spec = importlib.util.spec_from_file_location(
        "winzapp_setup_api", ROOT / "setup_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_env_returns_empty_when_file_is_missing(tmp_path, monkeypatch):
    module = _setup_api_module()
    monkeypatch.setattr(module, "ROOT_DIR", str(tmp_path))
    assert module._load_env() == {}


def test_load_env_reads_nonempty_assignments(tmp_path, monkeypatch):
    module = _setup_api_module()
    (tmp_path / ".env").write_text(
        "# comment\nWPPCONNECT_TAG_VERSION=v2.10.0\nEMPTY=\nNAME=value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT_DIR", str(tmp_path))

    assert module._load_env() == {
        "WPPCONNECT_TAG_VERSION": "v2.10.0",
        "NAME": "value",
    }


def test_recover_package_json_is_a_noop_without_git(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    api.mkdir()
    package = api / "package.json"
    package.write_text('{"local": true}', encoding="utf-8")
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))

    module._recover_upstream_package_json()

    assert package.read_text(encoding="utf-8") == '{"local": true}'


def test_recover_package_json_restores_head_atomically(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    (api / ".git").mkdir(parents=True)
    package = api / "package.json"
    package.write_text('{"local": true}', encoding="utf-8")
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout=b'{"name":"upstream"}\n'
        ),
    )

    module._recover_upstream_package_json()

class TestAFreshCheckoutStillGetsThePin:
    def test_an_absent_client_api_clones_and_checks_the_tag_out(self):
        assert _plan(False, False, False) == {"clone": True, "action": "checkout"}

    def test_an_empty_directory_is_treated_as_absent(self):
        """A cancelled extraction leaves the folder behind, not an install."""
        assert _plan(True, False, False) == {"clone": True, "action": "checkout"}

    def test_a_fresh_checkout_with_nothing_pinned_never_tracks_the_latest_release(self):
        assert _plan(False, False, False, tag="") == {"clone": True, "action": "none"}


def test_recover_package_json_rejects_failed_git_show(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    (api / ".git").mkdir(parents=True)
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b""),
    )

    import pytest
    with pytest.raises(RuntimeError, match="Could not read package.json"):
        module._recover_upstream_package_json()


def test_main_still_distinguishes_incremental_from_clean_install_by_git_and_modules():
    source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    assert 'already_cloned = os.path.isdir(git_dir)' in source
    assert 'has_node_modules = os.path.isdir(os.path.join(CLIENT_API_DIR, "node_modules"))' in source
    assert 'is_incremental_update = already_cloned and has_node_modules and not args.clean' in source


class TestMainActuallyRunsThePlannedCheckout:
    """The plan is only worth anything if main() runs it, and main()'s wiring
    is what was wrong. Everything past the checkout (npm install, Chromium,
    the build) is cut off by making the restore raise: it is the first call
    after the branch, and it sits outside main()'s own try/except.
    """

    class _StopBeforeNpm(Exception):
        pass

    def _run_main(self, monkeypatch, api_dir):
        setup_api = _setup_api_module()
        commands = []

        def fake_run(cmd, cwd=None):
            commands.append([str(c) for c in cmd])
            if cmd[:2] == ["git", "clone"]:
                # Mirror what a real clone leaves behind: the .git the pinned
                # checkout below is decided against.
                git = Path(cmd[-1]) / ".git"
                git.mkdir(parents=True, exist_ok=True)
                (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
                (git / "config").write_text("[core]\n", encoding="utf-8")
                (Path(cmd[-1]) / "package.json").write_text(
                    '{"version": "2.10.17", "dependencies": {}}', encoding="utf-8"
                )

        def stop(*_args, **_kwargs):
            raise self._StopBeforeNpm

        monkeypatch.setattr(setup_api, "CLIENT_API_DIR", str(api_dir))
        monkeypatch.setattr(setup_api, "_load_env", lambda: {})
        monkeypatch.setattr(setup_api, "tag_to_install", lambda pin: pin)
        monkeypatch.setattr(setup_api, "_run", fake_run)
        monkeypatch.setattr(setup_api, "_current_tag", lambda cwd: "")
        monkeypatch.setattr(setup_api, "_recover_upstream_package_json", stop)
        try:
            setup_api.main()
        except self._StopBeforeNpm:
            pass
        return commands

    def test_an_absent_client_api_is_cloned_and_pinned(self, tmp_path, monkeypatch):
        commands = self._run_main(monkeypatch, tmp_path / "api")

        assert ["git", "checkout", "-f", PIN] in commands, (
            f"the homologated tag was never checked out: {commands}"
        )

    def test_a_partial_git_directory_never_invokes_git(self, tmp_path, monkeypatch):
        api = tmp_path / "api"
        (api / ".git").mkdir(parents=True)
        (api / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (api / "package.json").write_text(
            '{"version": "%s"}' % PIN.lstrip("v"), encoding="utf-8"
        )

        commands = self._run_main(monkeypatch, api)

        assert not [c for c in commands if c[:1] == ["git"]], (
            f"git was run inside an unmanaged client/api/: {commands}"
        )


class TestTheTagFollowsTheApprovedList:
    """setup_api.py lands where Help > Force reinstall lands users."""

    PIN = "v2.10.71"
    LIST = {"schema": 1, "approved": [{"version": "2.10.74", "min_pin": "2.10.71"}]}

    def _tag(self, monkeypatch, fetched, environ=None):
        from core import wpp_approved

        def fetch(*_args, **_kwargs):
            if isinstance(fetched, Exception):
                raise fetched
            return fetched

        monkeypatch.setattr(wpp_approved, "fetch_manifest", fetch)
        return _setup_api_module().tag_to_install(self.PIN, environ or {})

    def test_the_approved_release_wins_over_the_pin(self, monkeypatch):
        assert self._tag(monkeypatch, self.LIST) == "v2.10.74"

    def test_nothing_approved_for_this_pin_stays_on_it(self, monkeypatch):
        older = {"schema": 1, "approved": [{"version": "2.10.63", "min_pin": "2.10.62"}]}
        assert self._tag(monkeypatch, older) == self.PIN

    def test_an_unreadable_list_stays_on_the_pin(self, monkeypatch):
        assert self._tag(monkeypatch, OSError("offline")) == self.PIN

    def test_ci_builds_the_pin_without_reading_the_list(self, monkeypatch):
        assert self._tag(monkeypatch, OSError("must not be read"), {"CI": "true"}) == self.PIN
        assert self._tag(monkeypatch, self.LIST, {"CI": "true"}) == self.PIN

    def test_a_release_that_needs_a_later_winzapp_is_left_out(self, monkeypatch):
        entry = {"version": "2.10.74", "min_pin": "2.10.71", "min_winzapp": "9.0.0.0"}
        assert self._tag(monkeypatch, {"schema": 1, "approved": [entry]}) == self.PIN


class TestARestoredNodeModulesCacheIsNotAnInstall:
    """The failure that stopped every alpha build after 2026-09-07.

    build-windows.yml restores `client/api/node_modules` from actions/cache
    BEFORE running setup_api.py. That creates client/api/ holding nothing but
    the cached folder, which read as "an install is already here": the plan
    dropped to verify-snapshot, verify-snapshot read a package.json that had
    not been cloned yet, and the run died with

      RuntimeError: Unmanaged client/api contains WPPConnect unknown, ...

    The first run to populate that cache therefore poisoned every run after
    it, which is why this appeared as "CI was fine, then suddenly every merge
    to main published no alpha".
    """

    def test_a_directory_holding_only_the_cached_node_modules_is_not_an_install(
        self, tmp_path
    ):
        (tmp_path / "node_modules").mkdir()
        assert _setup_api_module().api_dir_holds_an_install(tmp_path) is False

    def test_such_a_directory_is_cloned_into_and_pinned(self, tmp_path):
        """The whole point: it takes the clone branch, which moves node_modules
        aside and restores it afterwards — so the cache still does its job."""
        module = _setup_api_module()
        (tmp_path / "node_modules").mkdir()
        plan = module.plan_api_checkout(
            api_dir_exists=True,
            api_dir_nonempty=module.api_dir_holds_an_install(tmp_path),
            git_has_head_and_config=False,
            tag=PIN,
        )
        assert plan == {"clone": True, "action": "checkout"}

    def test_a_real_install_beside_node_modules_is_still_an_install(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert _setup_api_module().api_dir_holds_an_install(tmp_path) is True

    def test_a_missing_directory_is_not_an_install(self, tmp_path):
        assert _setup_api_module().api_dir_holds_an_install(tmp_path / "nope") is False

    def test_an_unreadable_directory_is_still_verified_never_cloned_over(
        self, tmp_path, monkeypatch
    ):
        module = _setup_api_module()

        def _denied(_path):
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(module.os, "listdir", _denied)
        assert module.api_dir_holds_an_install(tmp_path) is True
