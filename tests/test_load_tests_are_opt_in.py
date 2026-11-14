"""The `load` tests run on CI and on request, not on every local `pytest`.

They are ~45 s of synthetic large-account scenarios guarding how cost scales,
which a developer changing one function does not need on every run.
"""

import pytest

from tests.conftest import _load_requested


class _Config:
    def __init__(self, run_load=False):
        self._run_load = run_load

    def getoption(self, name):
        assert name == "--run-load"
        return self._run_load


def test_a_plain_local_run_skips_them(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    assert _load_requested(_Config()) is False


def test_the_flag_opts_in(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    assert _load_requested(_Config(run_load=True)) is True


@pytest.mark.parametrize("value", ["true", "1"])
def test_ci_always_runs_them(monkeypatch, value):
    monkeypatch.setenv("CI", value)
    assert _load_requested(_Config()) is True


@pytest.mark.parametrize("value", ["", "0", "false"])
def test_a_disabled_ci_variable_is_not_ci(monkeypatch, value):
    monkeypatch.setenv("CI", value)
    assert _load_requested(_Config()) is False
