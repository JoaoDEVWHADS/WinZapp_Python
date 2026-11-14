"""The Neonize engine presents the bridge's own secret as the API key, in memory only."""
import logging
from types import SimpleNamespace

from core import neonize_bridge_process as bridge_process
from main_window.neonize_bridge import NeonizeBridgeMixin


def _stub():
    return SimpleNamespace(
        wpp_api_key="wz-local-api-key",
        neonize_bridge=SimpleNamespace(bridge="somewhere"))


def test_the_bridge_secret_becomes_the_api_key(monkeypatch):
    monkeypatch.setattr(bridge_process, "read_secret", lambda bridge: "the-secret")
    stub = _stub()
    NeonizeBridgeMixin._use_neonize_bridge_secret(stub)
    assert stub.wpp_api_key == "the-secret"


def test_without_a_secret_file_the_api_key_stays_and_the_reason_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(bridge_process, "read_secret", lambda bridge: "")
    stub = _stub()
    with caplog.at_level(logging.ERROR):
        NeonizeBridgeMixin._use_neonize_bridge_secret(stub)
    assert stub.wpp_api_key == "wz-local-api-key"
    assert "--folder" in caplog.text
