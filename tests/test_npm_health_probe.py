"""Tests for the npm invocation used by the current setup_api.py.

The old preflight health probe was removed.  The real npm install is now the
source of truth: portable npm-cli.js is launched through its Node executable,
while a normal npm command is invoked directly, and neither path adds an
artificial timeout.
"""

import inspect

import setup_api


def _main_source():
    return inspect.getsource(setup_api.main)


def test_clean_install_has_no_obsolete_help_probe():
    source = _main_source()
    assert '"install", "--help"' not in source


def _probe_source():
    """The health probe in the installer body, inside main's catalogue gate."""
    source = inspect.getsource(_setup_api()._main_with_catalogue)
    start = source.index('"install", "--help"')
    return source[max(0, start - 2000):start + 2000]


def test_system_npm_is_invoked_directly():
    source = _main_source()
    assert '_run([npm_bin, "install", "--no-audit", "--no-fund", "--legacy-peer-deps"]' in source


def test_real_npm_install_has_no_timeout():
    source = _main_source()
    install_lines = [
        line for line in source.splitlines()
        if '"install", "--no-audit"' in line
    ]
    assert install_lines
    assert all("timeout" not in line for line in install_lines)


class TestTheRealInstallStillDecides:
    def test_npm_install_itself_is_not_given_a_timeout(self):
        """It is the operation the probe stands in for. Capping it would move
        the same flake onto the step that actually matters."""
        source = inspect.getsource(_setup_api()._main_with_catalogue)
        install = source.index('"install", "--no-audit"')
        line_start = source.rindex("\n", 0, install)
        line_end = source.index("\n", install)
        assert "timeout" not in source[line_start:line_end]


def test_run_helper_propagates_nonzero_exit_when_checking(monkeypatch):
    class Result:
        returncode = 7

    monkeypatch.setattr(setup_api.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(setup_api.subprocess, "run", lambda *a, **kw: Result())

    import pytest
    with pytest.raises(SystemExit) as exc:
        setup_api._run(["npm", "--version"])

    assert exc.value.code == 7
