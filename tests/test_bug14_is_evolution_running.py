import re


class TestBug14IsEvolutionRunning:
    """Bug 14: _is_evolution_running should use configured server, not hardcoded 127.0.0.1."""

    def test_uses_evolution_server_not_hardcoded(self):
        src = open("client/main.py", encoding="utf-8").read()
        m = re.search(r'def _is_evolution_running.*?urlparse.*?hostname', src, re.DOTALL)
        assert m, "_is_evolution_running should parse host from evolution_server"

    def test_host_comes_from_evolution_server(self):
        src = open("client/main.py", encoding="utf-8").read()
        m = re.search(r'def _is_evolution_running.*?urlparse.*?hostname', src, re.DOTALL)
        assert m, "_is_evolution_running should parse host from evolution_server"
        assert "self.evolution_server" in m.group(), "Should read host from evolution_server"
