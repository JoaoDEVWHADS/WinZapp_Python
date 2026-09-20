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


def test_portable_npm_is_launched_through_node():
    source = _main_source()
    assert 'if npm_bin.endswith("npm-cli.js"):' in source
    assert '_run([node_bin, npm_bin, "install", "--no-audit", "--no-fund", "--legacy-peer-deps"]' in source


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


def test_incremental_update_falls_back_to_install_when_update_fails():
    source = _main_source()
    assert 'npm update failed' in source
    assert 'falling back to npm install' in source


def test_run_helper_propagates_nonzero_exit_when_checking(monkeypatch):
    class Result:
        returncode = 7

    monkeypatch.setattr(setup_api.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(setup_api.subprocess, "run", lambda *a, **kw: Result())

    import pytest
    with pytest.raises(SystemExit) as exc:
        setup_api._run(["npm", "--version"])

    assert exc.value.code == 7
