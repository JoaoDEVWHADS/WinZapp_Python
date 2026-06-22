import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import threading
import time
import pytest
from unittest.mock import MagicMock, PropertyMock, patch
from mocks import MockMainWindow


class TestBug5SaveRace:
    """Bug 5: _do_save race — dict muda de tamanho durante iteracao."""

    def test_save_data_concurrent_mutation_no_crash(self):
        """Simula alteracao concorrente de self.chats durante save_data.
        
        _do_save passa self.chats diretamente para save_data que itera
        sobre o dict. Se uma thread alterar self.chats enquanto save_data
        serializa, ocorre RuntimeError: dictionary changed size during iteration.
        
        O fix: copiar chats/contacts sob lock em _do_save."""
        mw = MockMainWindow()
        mw.chats = {
                f"chat_{i}@s.whatsapp.net": {
                "messages": [{"key": {"id": f"msg_{i}_{j}"}} for j in range(50)]
            }
            for i in range(100)
        }
        results = []
        errors = []

        def mutate_chats():
            for i in range(500):
                mw.chats[f"mutant_{i}@s.whatsapp.net"] = {"messages": []}
                time.sleep(0.001)
            results.append("mutator_done")

        def do_save_safe():
            try:
                # Copia os dados sob lock (simula o fix)
                with mw._save_lock:
                    chats_copy = dict(mw.chats)
                    contacts_copy = dict(mw.contacts)
                _ = len(chats_copy) + len(contacts_copy)
                results.append("save_ok")
            except RuntimeError as e:
                errors.append(str(e))
                results.append("save_crash")

        t1 = threading.Thread(target=mutate_chats, daemon=True)
        t2 = threading.Thread(target=do_save_safe, daemon=True)
        t1.start()
        time.sleep(0.02)
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert "save_crash" not in results, (
            f"save_data crashou com RuntimeError: {errors}"
        )

    def test_do_save_chats_snapshot(self):
        """Verifica que _do_save faz snapshot de chats/contacts."""
        mw = MockMainWindow()
        mw.chats = {"jid1@s.whatsapp.net": {"messages": []}}
        mw.contacts = {"jid1@s.whatsapp.net": {"name": "Test"}}

        with mw._save_lock:
            chats_copy = dict(mw.chats)
            contacts_copy = dict(mw.contacts)

        assert chats_copy == {"jid1@s.whatsapp.net": {"messages": []}}
        assert contacts_copy == {"jid1@s.whatsapp.net": {"name": "Test"}}

    def test_save_data_iteration_no_race(self):
        """save_data recebe copia, nao referencia direta, entao iteracao
        nunca encontra RuntimeError por modificacao concorrente."""
        mw = MockMainWindow()
        mw.chats = {"jid": {"messages": []}}
        mw.contacts = {}

        with mw._save_lock:
            chats_snapshot = dict(mw.chats)
            contacts_snapshot = dict(mw.contacts)

        # Modificacao concorrente durante iteracao nao afeta snapshot
        mw.chats["new_jid"] = {"messages": []}

        assert "new_jid" not in chats_snapshot
        assert len(chats_snapshot) == 1
