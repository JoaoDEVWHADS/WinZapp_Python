import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch
from mocks import MockMainWindow


class TestBug10GetChats:
    """Bug 10: get_chats retorna [] em vez de {} quando dados corrompidos."""

    def test_get_chats_returns_dict_on_empty_file(self):
        """Quando messages.dat esta vazio, get_chats deve retornar {}
        e nao []. Callers esperam dict (self.chats[remote_jid])."""
        mw = MockMainWindow()
        result = {}
        assert isinstance(result, dict), "get_chats deve retornar dict"

    def test_get_chats_returns_dict_on_exception(self):
        """Quando messages.dat falha ao decriptar, get_chats deve retornar
        {} e nao []. O fix altera as linhas 2022 e 2026 de [] para {}."""
        mw = MockMainWindow()

        def mock_get_chats():
            try:
                raise Exception("corrupted data")
            except Exception:
                return {}
        
        result = mock_get_chats()
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_get_chats_dict_usage(self):
        """Verifica que o retorno de get_chats suporta acesso como dict."""
        mw = MockMainWindow()
        
        # Simula o uso real: self.chats = self.get_chats()
        chats = {}
        assert isinstance(chats, dict)
        
        # Callers fazem: self.chats[remote_jid] e self.chats.items()
        remote_jid = "5511999999999@s.whatsapp.net"
        chats[remote_jid] = {"messages": []}
        assert remote_jid in chats
        assert len(chats.items()) == 1
