"""Choosing WPPConnect while the neonize bridge still listens on the shared port.

Both engines use port 6300 for the first account. The bridge left running by the
other engine looked like "a WPPConnect already listening", the Node was never
started, and every call came back 401 ("no pairing code was received").

The real MainWindow methods run on a stub: no window, no socket, no process.
"""
import logging
from types import SimpleNamespace

from core import neonize_bridge_process as nb
from main import MainWindow

BRIDGE = {"installation_id": "", "instance_id": "", "protocol_version": 1, "pid": 9, "ppid": 1}
NODE = {"installation_id": "abc", "instance_id": "def", "protocol_version": 1, "pid": 9, "ppid": 1}


class _Window:
    _port_held_by_neonize_bridge = MainWindow._port_held_by_neonize_bridge
    _make_room_for_wppconnect = MainWindow._make_room_for_wppconnect

    def __init__(self, free_after=0, custom=False):
        self.wpp_port, self.wpp_custom_api = 6300, custom
        self.free_after, self.checks, self.moved = free_after, 0, 0

    def _is_port_free(self, port):
        self.checks += 1
        return self.free_after >= 0 and self.checks > self.free_after

    def _ensure_wpp_port_still_free(self):
        self.moved += 1


def _identity(monkeypatch, answer):
    monkeypatch.setattr(nb, "fetch_identity", lambda port=6300, **k: answer)


def _stop(monkeypatch):
    stopped = []
    monkeypatch.setattr(nb.NeonizeBridge, "stop", lambda self: stopped.append(self.port) or True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return stopped


def test_a_bridge_on_the_port_is_recognised_and_a_node_is_not(monkeypatch):
    win = _Window()
    _identity(monkeypatch, BRIDGE)
    assert win._port_held_by_neonize_bridge() is True
    _identity(monkeypatch, NODE)
    assert win._port_held_by_neonize_bridge() is False
    _identity(monkeypatch, None)                     # an old Node answers no identity
    assert win._port_held_by_neonize_bridge() is False


def test_the_bridge_is_stopped_and_the_port_freed_for_the_node(monkeypatch):
    stopped = _stop(monkeypatch)
    _identity(monkeypatch, BRIDGE)
    win = _Window(free_after=2)

    win._make_room_for_wppconnect()

    assert stopped == [6300] and win.moved == 0


def test_a_bridge_that_cannot_be_stopped_moves_this_run_to_another_port(monkeypatch):
    stopped = _stop(monkeypatch)
    _identity(monkeypatch, BRIDGE)
    win = _Window(free_after=-1)                     # the port never frees up
    times = iter(range(0, 1000, 5))
    monkeypatch.setattr("time.time", lambda: next(times))

    win._make_room_for_wppconnect()

    assert stopped == [6300] and win.moved == 1


def test_a_real_node_or_a_custom_server_is_left_alone(monkeypatch):
    stopped = _stop(monkeypatch)
    _identity(monkeypatch, NODE)
    win = _Window()
    win._make_room_for_wppconnect()
    _identity(monkeypatch, BRIDGE)
    custom = _Window(custom=True)
    custom._make_room_for_wppconnect()

    assert stopped == [] and win.moved == custom.moved == 0
