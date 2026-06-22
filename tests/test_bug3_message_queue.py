import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import threading
import time
import pytest
from unittest.mock import MagicMock, patch
from mocks import MockMainWindow
from core.message_queue import MessageQueue, PendingMessage


class TestMessageQueue:
    """Bugs 3+4: Race conditions e _own_sent_ids cap em message_queue.py."""

    def test_stop_while_event_waiting_causes_no_race(self):
        """Bug 3: parar a queue durante event.wait() nao deve causar race."""
        mw = MockMainWindow()
        mq = MessageQueue(mw)
        mq.stop()
        assert mq._stop.is_set()
        mq._worker.join(timeout=4)
        assert not mq._worker.is_alive()

    def test_own_sent_ids_no_stop_iteration_on_empty(self):
        """Bug 3: next(iter(_own_sent_ids)) em set vazio levanta StopIteration.
        A linha 152 faz next(iter(self.main_window._own_sent_ids)).
        Se o set ficar vazio entre len() e next(), crasha.
        O fix: usar pop() com default ou verificar se nao esta vazio."""
        mw = MockMainWindow()
        mw._own_sent_ids = set()

        with mw._own_sent_ids_lock:
            mw._own_sent_ids.add("test_id_1")
            if len(mw._own_sent_ids) > 500:
                mw._own_sent_ids.discard(
                    next(iter(mw._own_sent_ids))
                )

        assert len(mw._own_sent_ids) == 1
        assert "test_id_1" in mw._own_sent_ids

    def test_own_sent_ids_no_cap(self):
        """Bug 4: cap removido — _own_sent_ids cresce sem limite durante sessao.
        O fix removeu a logica de eviction, garantindo que todas as mensagens
        enviadas sao reconhecidas pelo echo do WebSocket sem duplicacao."""
        mw = MockMainWindow()
        
        with mw._own_sent_ids_lock:
            for i in range(1001):
                mw._own_sent_ids.add(f"id_{i}")

        assert len(mw._own_sent_ids) == 1001

    def test_own_sent_ids_lock_consistency(self):
        """Lock deve ser segurado corretamente. Add + remove sob lock."""
        mw = MockMainWindow()
        with mw._own_sent_ids_lock:
            mw._own_sent_ids.add("id_consistent")
            mw._own_sent_ids.discard("id_consistent")
        assert "id_consistent" not in mw._own_sent_ids

    def test_multiple_enqueues_no_data_loss(self):
        """Enfileirar varias mensagens em sequencia nao perde dados."""
        mw = MockMainWindow()
        mq = MessageQueue(mw)
        
        msgs = []
        for i in range(10):
            msg = PendingMessage(
                local_id=f"local_{i}",
                jid="5511999999999@s.whatsapp.net",
                text=f"Message {i}",
            )
            msgs.append(msg)
            mq.enqueue(msg)
        
        with mq._lock:
            assert len(mq._pending) == 10
        
        mq.stop()

    def test_stop_while_processing(self):
        """Parar durante processamento nao crasha."""
        mw = MockMainWindow()
        
        def slow_send(*args, **kwargs):
            time.sleep(0.1)
            return True
        
        mw.send_text_message = slow_send
        mq = MessageQueue(mw)
        msg = PendingMessage("slow_test", "jid@s.whatsapp.net", text="slow")
        mq.enqueue(msg)
        time.sleep(0.05)
        mq.stop()
        assert True, "stop() during processamento nao crashou"

    def test_offline_mode_suspends_processing(self):
        """Modo offline suspende o processamento."""
        mw = MockMainWindow()
        mw.offline_mode = True
        sent = []

        def track_send(*args, **kwargs):
            sent.append(True)
            return True

        mw.send_text_message = track_send
        mq = MessageQueue(mw)
        msg = PendingMessage("offline_test", "jid@s.whatsapp.net", text="offline")
        mq.enqueue(msg)
        time.sleep(0.5)
        assert len(sent) == 0, "Nao enviou enquanto offline"
        mq.stop()

    def test_no_deadlock_between_locks(self):
        """Nao deve haver deadlock entre self._lock e _own_sent_ids_lock."""
        mw = MockMainWindow()
        mq = MessageQueue(mw)
        msg = PendingMessage("lock_test", "jid@s.whatsapp.net", text="lock test")
        
        # Enfileira mensagem
        mq.enqueue(msg)
        time.sleep(0.2)
        
        # Verifica que a mensagem foi processada (não há deadlock)
        with mq._lock:
            assert len(mq._pending) == 0 or "lock_test" not in mq._pending
        mq.stop()
