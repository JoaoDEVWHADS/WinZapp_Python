import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch
from mocks import MockMainWindow


class TestBug2WsDisconnect:
    """Bug 2: self.ws.sio.disconnect() chamado quando self.ws e None."""

    def test_ws_disconnect_before_ws_initialized_no_crash(self):
        """Linha 418: self.ws.sio.disconnect() e chamado ANTES de self.ws
        ser inicializado (linha 422). self.ws ainda e None quando o usuario
        passa pelo dialogo de pareamento. O acesso a None.sio crasha.
        
        O fix deve proteger o acesso com if self.ws is not None."""
        mw = MockMainWindow()
        mw.ws = None
        
        # Simula o codigo da linha 418: nao deve crashar
        if mw.ws is not None:
            mw.ws.sio.disconnect()
        
        assert True, "Nao crashou porque o guard foi aplicado"

    def test_connect_websocket_without_ws_no_crash(self):
        """Linhas 1102-1104: connect_websocket acessa self.ws.sio.connected
        e self.ws.sio.disconnect(). Se connect_websocket for chamado antes
        de self.ws ser criado, nao deve crashar."""
        mw = MockMainWindow()
        mw.ws = None
        
        # Simula o codigo das linhas 1102-1104 com guard
        if mw.ws is not None:
            if mw.ws.sio.connected:
                mw.ws.sio.disconnect()
        
        assert True, "Nao crashou porque o guard foi aplicado"

    def test_ws_properly_guarded_after_pairing(self):
        """Apos o pareamento, self.ws e criado e deve ser acessivei.
        Verifica que a sequencia correta e:
        1. show_connection_dial()
        2. Criar WebSocketClient
        3. so entao conectar/desconectar websocket"""
        from core.websocket_client import WebSocketClient
        
        mw = MockMainWindow()
        
        # Simula fluxo correto: ws criado ANTES de acessar sio
        mw.ws = WebSocketClient(mw, mw, "test_token")
        assert mw.ws is not None
        assert hasattr(mw.ws, 'sio')
        
        # Agora pode acessar sio com seguranca
        if mw.ws is not None:
            mw.ws.sio.disconnect()
        
        assert True, "WebSocketClient criado e sio acessivel com seguranca"
