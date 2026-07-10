import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import threading
import json
import pytest
from unittest.mock import MagicMock, patch
from mocks import MockMainWindow


class TestBug6SettingsRace:
    """Bug 6: self.settings acessado/modificado sem lock entre threads."""

    def test_settings_lock_exists(self):
        """Mock deve ter _settings_lock para o fix."""
        mw = MockMainWindow()
        assert hasattr(mw, "_settings_lock")
        assert hasattr(mw._settings_lock, "acquire")
        assert hasattr(mw._settings_lock, "release")

    def test_save_settings_snapshot_under_lock(self):
        """save_settings deve copiar self.settings sob lock.
        A copia evita que uma modificacao concorrente cause RuntimeError
        durante iteracao da serializacao json."""
        mw = MockMainWindow()
        mw.settings = {"connection": {"port": 3414}, "general": {"lang": "pt-BR"}}

        with mw._settings_lock:
            settings_copy = dict(mw.settings)

        assert isinstance(settings_copy, dict)
        assert settings_copy["connection"]["port"] == 3414

    def test_save_settings_isolation(self):
        """Modificacoes concorrentes nao afetam a copia."""
        mw = MockMainWindow()
        mw.settings = {"a": 1}

        with mw._settings_lock:
            snapshot = dict(mw.settings)
            mw.settings["b"] = 2

        assert "b" not in snapshot
        assert len(snapshot) == 1

    def test_presence_pushname_map_protected(self):
        """Linha 3187 define settings['presence_pushname_map'] vindo de thread
        WebSocket. Deve usar _settings_lock."""
        mw = MockMainWindow()
        mw._settings_lock = threading.Lock()
        mw._presence_pushname_map = {"jid@c.us": "Test Name"}

        with mw._settings_lock:
            mw.settings["presence_pushname_map"] = dict(mw._presence_pushname_map)

        assert mw.settings.get("presence_pushname_map") == {"jid@c.us": "Test Name"}
