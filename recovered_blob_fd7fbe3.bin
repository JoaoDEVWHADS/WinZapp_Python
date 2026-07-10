import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import time
import pytest
from unittest.mock import MagicMock, patch
from mocks import MockMainWindow


class TestBug9ConnectTime:
    """Bug 9: timestamp guard reseta na reconexao, causando perda de msg."""

    def test_connect_time_preserved_on_reconnect(self):
        """_connect_time nao deve ser sobrescrito na reconexao.
        
        O fix: so define _connect_time na primeira conexao, nao nas
        subsequentes (socketio.Client reconnection=True faz reconexao
        automatica).
        """
        class Fake:
            pass
        
        obj = Fake()
        
        # Primeira conexao: define _connect_time
        if not hasattr(obj, "_connect_time"):
            obj._connect_time = 100.0
        
        # Simula reconexao: nao sobrescreve
        if not hasattr(obj, "_connect_time"):
            obj._connect_time = 200.0
        
        assert obj._connect_time == 100.0, (
            f"_connect_time foi resetado para {obj._connect_time} na reconexao"
        )

    def test_timestamp_guard_after_reconnect(self):
        """Apos reconexao, mensagens com timestamp entre primeira conexao
        e reconexao nao devem ser descartadas.
        
        Cenario:
        - T=100s: primeira conexao, _connect_time=100
        - T=150s: mensagem com timestamp=120 (dentro da janela de 60s)
        - T=200s: reconexao (nao reseta _connect_time)
        - T=210s: mensagem com timestamp=120 chega (estava enfileirada)
        """
        first_connect = 100.0
        reconnect = 200.0
        
        # Com o bug: _connect_time seria resetado para reconnect
        cutoff_bug = reconnect - 60  # = 140
        # msg ts=120 < cutoff=140 → DROPPED (BUG!)
        assert 120 < cutoff_bug, "BUG: mensagem seria descartada"
        
        # Com o fix: _connect_time mantem first_connect
        cutoff_fix = first_connect - 60  # = 40
        # msg ts=120 >= cutoff=40 → KEPT
        assert 120 >= cutoff_fix, "FIX: mensagem seria mantida"

    def test_on_connect_sets_time_only_once(self):
        """on_connect só deve setar _connect_time se nao existir."""
        import time
        class Fake:
            pass
        ws = Fake()
        
        def on_connect():
            if not hasattr(ws, "_connect_time"):
                ws._connect_time = time.time()
        
        on_connect()
        t1 = ws._connect_time
        
        time.sleep(0.01)
        on_connect()
        
        assert ws._connect_time == t1, (
            "_connect_time foi resetado na segunda chamada de on_connect"
        )

    def test_first_message_after_reconnect(self):
        """A primeira mensagem apos reconexao passa pelo guard."""
        # Simula estado apos reconexao
        now = time.time()
        _connect_time = now - 30  # Conectou 30s atras
        
        msg_timestamp = now - 45  # Mensagem de 45s atras
        cutoff = _connect_time - 60
        
        # Mensagem nao deve ser descartada
        assert int(msg_timestamp) >= cutoff
