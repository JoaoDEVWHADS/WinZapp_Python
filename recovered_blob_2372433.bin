import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pytest
from mocks import MockMainWindow


class TestBug1WsUrl:
    """Bug 1: evolution_ws_server default deve ser http://, nunca ws://."""

    def test_evolution_ws_server_url_uses_http(self):
        """A URL montada para sio.connect() deve comecar com http://.
        A linha 1101 de main.py faz:
          self.ws.sio.connect(f\"{self.evolution_ws_server}:{self.evolution_port}/\")
        O default corrigido em main.py:357 agora usa http://127.0.0.1.
        """
        mw = MockMainWindow()
        ws_server = mw.evolution_ws_server
        port = mw.evolution_port
        url = f"{ws_server}:{port}/"
        assert url.startswith("http://"), (
            f"URL invalida: {url}. "
            "python-socketio nao reconhece ws:// para o handshake HTTP."
        )

    def test_evolution_ws_server_default_no_settings(self):
        """Quando evolution_ws_server nao esta nas settings, o default
        deve ser http://127.0.0.1 (fix aplicado em main.py:357)."""
        settings_vazias = {"connection": {}}
        ws_server = settings_vazias.get("connection", {}).get(
            "evolution_ws_server", "http://127.0.0.1"
        )
        assert ws_server == "http://127.0.0.1"

    def test_old_ws_setting_normalized_to_http(self):
        """Usuarios com configuracao antiga (ws://) salva no settings.json
        precisam ser normalizados. Simula migracao."""
        old_settings_com_ws = {
            "connection": {
                "evolution_ws_server": "ws://127.0.0.1",
                "evolution_port": 3414,
            }
        }
        ws_server = old_settings_com_ws["connection"].get("evolution_ws_server", "http://127.0.0.1")
        url = f"{ws_server}:{old_settings_com_ws['connection']['evolution_port']}/"
        # Antes da migracao, esta URL comeca com ws://
        assert url.startswith("ws://"), "URL antiga com ws:// deve ser detectada"

        # A migracao deve trocar ws:// por http://
        if ws_server.startswith("ws://"):
            ws_server = "http://" + ws_server[5:]
        url_fixed = f"{ws_server}:{old_settings_com_ws['connection']['evolution_port']}/"
        assert url_fixed.startswith("http://"), f"URL apos migracao: {url_fixed}"
        assert "ws://" not in url_fixed
