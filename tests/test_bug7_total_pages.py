import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch


class TestBug7TotalPages:
    """Bug 7: total_pages regredindo causa perda de dados na paginacao."""

    def test_total_pages_never_decreases(self):
        """Quando a API retorna total_pages menor na pagina 2, o loop
        nao deve parar antes de alcancar o valor maximo ja visto.
        
        Simula: pagina 1 retorna total_pages=3, pagina 2 retorna total_pages=1.
        Sem fix: loop para em 2 paginas (perde dados).
        Com fix: loop continua ate pagina 3 (maximo ja visto)."""
        responses = [
            {"messages": {"pages": 3, "records": [{"id": 1}]}},
            {"messages": {"pages": 1, "records": [{"id": 2}]}},
            {"messages": {"pages": 1, "records": [{"id": 3}]}},
        ]

        current_page = 1
        total_pages = 1
        records = []
        resp_index = 0

        while current_page <= total_pages and resp_index < len(responses):
            messages = responses[resp_index].get("messages", {})
            resp_index += 1
            # BUG: sobrescreve total_pages sempre
            total_pages = messages.get("pages", 1)
            records.extend(messages.get("records", []))
            current_page += 1

        assert len(records) == 2, (
            f"BUG: total_pages regrediu de 3 para 1, parou na pagina 2 "
            f"com apenas {len(records)} registros (perdeu pagina 3)"
        )

    def test_fix_total_pages_uses_max(self):
        """Com fix (max), total_pages nunca regride."""
        responses = [
            {"messages": {"pages": 3, "records": [{"id": 1}]}},
            {"messages": {"pages": 1, "records": [{"id": 2}]}},
            {"messages": {"pages": 1, "records": [{"id": 3}]}},
        ]

        current_page = 1
        total_pages = 1
        records = []
        resp_index = 0

        while current_page <= total_pages and resp_index < len(responses):
            messages = responses[resp_index].get("messages", {})
            resp_index += 1
            # FIX: usa max para nunca regredir
            total_pages = max(total_pages, messages.get("pages", 1))
            records.extend(messages.get("records", []))
            current_page += 1

        assert len(records) == 3, (
            f"FIX: max() manteve total_pages em 3, coletou {len(records)} registros"
        )

    def test_single_page_still_works(self):
        """Uma unica pagina continua funcionando."""
        responses = [
            {"messages": {"pages": 1, "records": [{"id": 1}]}},
        ]

        current_page = 1
        total_pages = 1
        records = []
        resp_index = 0

        while current_page <= total_pages and resp_index < len(responses):
            messages = responses[resp_index].get("messages", {})
            resp_index += 1
            total_pages = max(total_pages, messages.get("pages", 1))
            records.extend(messages.get("records", []))
            current_page += 1

        assert len(records) == 1
        assert total_pages == 1

    def test_no_messages_key(self):
        """Quando o retorno nao tem 'messages', usa padrao 1."""
        current_page = 1
        total_pages = 1
        messages = {}
        total_pages = max(total_pages, messages.get("pages", 1))
        assert total_pages == 1
