import logging
from types import SimpleNamespace

import pytest

from core import api_install_timing as timing
from core import wpp_connection_recovery as recovery


def test_timing_returns_original_result_without_logging_private_arguments(monkeypatch, caplog):
    clock = iter([100.0, 102.5])
    monkeypatch.setattr(timing.time, "monotonic", lambda: next(clock))
    with caplog.at_level(logging.INFO):
        result = timing.timed_call("npm_install", lambda secret: (False, secret), "private-token")
    assert result == (False, "private-token")
    assert "event=start" in caplog.text
    assert "elapsed_s=2.500 outcome=false" in caplog.text
    assert "private-token" not in caplog.text


def test_exception_is_recorded_and_propagated(caplog):
    @timing.timed_step("source_download")
    def fail():
        raise ValueError("private response")
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        fail()
    assert "outcome=exception" in caplog.text
    assert "private response" not in caplog.text


@pytest.mark.parametrize("command,step", [
    (["node", "npm-cli.js", "install", "--timing"], "npm_install"),
    (["npm", "exec", "puppeteer", "browsers", "install", "chrome"], "browser_cli"),
    (["npm", "run", "build"], "npm_build"),
    (["npm", "run", "db:generate"], "db_generate"),
    (["npm", "run", "private-command"], "subprocess"),
])
def test_subprocess_labels_do_not_include_command_arguments(command, step, caplog):
    @timing.timed_subprocess
    def run(window, cmd, **kwargs):
        return True, ""
    with caplog.at_level(logging.INFO):
        assert run(None, command, env={"secret": "value"}) == (True, "")
    assert f"step={step}" in caplog.text
    assert "private-command" not in caplog.text and "value" not in caplog.text


def test_whatsapp_reconnection_is_measured_once(monkeypatch, caplog):
    now = [100.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: now[0])
    window = SimpleNamespace()
    with caplog.at_level(logging.INFO):
        recovery.begin_update_reconnection(window)
        now[0] += 7
        recovery.finish_update_reconnection(window)
        recovery.finish_update_reconnection(window)
    assert "elapsed_s=7.000 outcome=connected" in caplog.text
    assert caplog.text.count("event=end") == 1
