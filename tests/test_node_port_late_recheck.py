"""Regression test: resolving a Node port and actually spawning Node on it
used to be two steps separated by a real gap of wall-clock time, not one
atomic operation.

_resolve_wpp_port() checks/reserves the port during MainWindow.__init__,
but _start_wpp_background() — the thing that actually spawns Node bound to
that port — runs much later in startup, after settings/UI/sync all have
their turn. Anything can take that exact port in that window: another
program, or even this same account's own previous Node still winding down.
Node then simply fails to bind it, surfaced only as a generic "API failed
to start in time" with an EADDRINUSE buried in wppconnect.log.

MainWindow._ensure_wpp_port_still_free() re-checks right before the real
spawn and re-resolves (through the same cross-process lock + deterministic
per-account allocator client/node_ports.py already provides) if the
originally chosen port is no longer free.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so the method is exercised bound to a plain stub — same approach as
tests/test_lid_merge_keeps_messages.py. node_ports.allocate_port_for_account
itself is the real, already pure-tested implementation (tests/test_node_ports.py)
— only its is_free() predicate and the account's own state are faked here.
"""

from main import MainWindow

_ensure_wpp_port_still_free = MainWindow._ensure_wpp_port_still_free


class _Stub:
    _ensure_wpp_port_still_free = MainWindow._ensure_wpp_port_still_free

    def __init__(self, wpp_port, global_dir, custom_api=False, has_registry=True,
                 account_id="acc1", busy_ports=()):
        self.settings = {"connection": {"wpp_custom_api": custom_api}}
        self.wpp_port = wpp_port
        self.global_dir = global_dir
        self.registry = object() if has_registry else None
        self.account_id = account_id if has_registry else None
        self.save_calls = 0
        self.peer_ports = []
        self._busy_ports = set(busy_ports)

    def _is_port_free(self, port):
        return port not in self._busy_ports

    def _peer_node_ports(self):
        return self.peer_ports

    def save_settings(self):
        self.save_calls += 1


class TestPortStillFree:
    def test_nothing_changes_when_the_port_is_still_bindable(self, tmp_path):
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path))

        stub._ensure_wpp_port_still_free()

        assert stub.wpp_port == 6301
        assert stub.save_calls == 0


class TestPortNowTaken:
    def test_re_resolves_to_a_different_free_port(self, tmp_path):
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path), busy_ports={6301})

        stub._ensure_wpp_port_still_free()

        assert stub.wpp_port != 6301
        assert stub._is_port_free(stub.wpp_port)

    def test_the_new_port_is_persisted(self, tmp_path):
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path), busy_ports={6301})

        stub._ensure_wpp_port_still_free()

        assert stub.save_calls == 1
        assert stub.settings["connection"]["wpp_port"] == stub.wpp_port

    def test_a_peer_ports_clash_is_still_avoided(self, tmp_path):
        """The re-resolve must still respect other accounts' persisted
        ports, not just "any bindable port" — otherwise it could hand this
        account a port a peer already reserved for itself."""
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path), busy_ports={6301})
        stub.peer_ports = [6302, 6303]

        stub._ensure_wpp_port_still_free()

        assert stub.wpp_port not in {6301, 6302, 6303}


class TestSkipsWhenNotApplicable:
    def test_custom_api_is_left_untouched(self, tmp_path):
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path), custom_api=True,
                     busy_ports={6301})

        stub._ensure_wpp_port_still_free()

        assert stub.wpp_port == 6301
        assert stub.save_calls == 0

    def test_single_account_legacy_mode_is_left_untouched(self, tmp_path):
        stub = _Stub(wpp_port=6301, global_dir=str(tmp_path), has_registry=False,
                     busy_ports={6301})

        stub._ensure_wpp_port_still_free()

        assert stub.wpp_port == 6301
        assert stub.save_calls == 0
