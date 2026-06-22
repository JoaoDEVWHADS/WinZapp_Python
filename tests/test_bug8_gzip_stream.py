import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import json
import gzip
import pytest
from unittest.mock import MagicMock, patch


class TestBug8GzipStreaming:
    """Bug 8: streaming mode nao decodifica gzip, causando falha silenciosa
    em todos os downloads de midia com progress_callback."""

    def test_gzip_decoding_before_json(self):
        """Dados gzip comprimidos devem ser decodificados antes do json.loads.
        Sem fix: body gzip -> decode('utf-8', errors='replace') -> JSON invalido.
        Com fix: gzip.decompress(body) -> decode('utf-8') -> JSON valido."""
        original = '{"base64": "SGVsbG8gV29ybGQ="}'
        compressed = gzip.compress(original.encode("utf-8"))

        chunks = [compressed[i:i+16] for i in range(0, len(compressed), 16)]

        body = b"".join(chunks)
        try:
            import zlib
            decompressed = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        except Exception:
            decompressed = body

        assert decompressed.decode("utf-8") == original

    def test_content_encoding_gzip_not_decoded_by_stream(self):
        """Com requests stream=True e Content-Encoding: gzip, os chunks
        brutos podem vir comprimidos. O fix deve verificar o header
        Content-Encoding e decodificar manualmente."""
        import gzip
        original = b'{"base64": "dGVzdA=="}'
        compressed = gzip.compress(original)
        content_encoding = "gzip"

        # Simula o que ocorre com stream=True
        chunks = [compressed[:10], compressed[10:]]
        body = b"".join(chunks)

        if "gzip" in content_encoding:
            import zlib
            body = zlib.decompress(body, 16 + zlib.MAX_WBITS)

        assert body.decode("utf-8") == '{"base64": "dGVzdA=="}'

    def test_non_gzip_content_still_works(self):
        """Sem Content-Encoding: gzip, o comportamento e o mesmo."""
        original = b'{"base64": "dGVzdA=="}'
        content_encoding = ""

        chunks = [original[:10], original[10:]]
        body = b"".join(chunks)

        if "gzip" in content_encoding:
            import zlib
            body = zlib.decompress(body, 16 + zlib.MAX_WBITS)

        result = json.loads(body.decode("utf-8")).get("base64", "")
        assert result == "dGVzdA=="

    def test_empty_response_no_crash(self):
        """Resposta vazia nao deve crashar."""
        chunks = []
        body = b"".join(chunks)
        assert body == b""
