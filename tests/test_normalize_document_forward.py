"""Tests for WebSocketClient._normalize_wpp_message()'s "document" branch.

Reported live: forwarding a PDF to another conversation showed up with the
generic "Document" placeholder and a 0-byte size instead of the real
filename/size. A normal (non-forwarded) document send/receive gets its
top-level `filename`/`fileName`/`title` and `size`/`fileLength` populated by
WPPConnect's wa-js model on the raw message object passed to onAnyMessage,
but a FORWARDED document doesn't get those top-level convenience fields
populated the same way — only the nested `mediaData` carries the real
name/size. The audio/video branches immediately above this one already fall
back into `mediaData` for duration; the document branch had no equivalent
fallback for fileName/fileLength, so both lookups came up empty and hit the
hardcoded "Document"/0 defaults.

WebSocketClient needs a live Socket.IO client normally, but
_normalize_wpp_message()/_clean_jid() touch no I/O — exercised as plain
functions against a small stub, same approach as
tests/test_message_bookmarks.py.
"""

from core.websocket_client import WebSocketClient


class _Stub:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _base_msg(**overrides):
    msg = {
        "id": "true_5511999999999@c.us_ABC123",
        "from": "5511999999999@c.us",
        "to": "5511999999999@c.us",
        "fromMe": True,
        "timestamp": 1700000000,
        "type": "document",
    }
    msg.update(overrides)
    return msg


class TestDocumentNormalization:
    def test_ordinary_document_uses_top_level_fields(self):
        stub = _Stub()
        msg = _base_msg(filename="report.pdf", size=12345)

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "report.pdf"
        assert doc["fileLength"] == 12345

    def test_forwarded_document_falls_back_to_media_data(self):
        """The reported bug: top-level filename/size are absent on a
        forwarded document, but mediaData carries the real values."""
        stub = _Stub()
        msg = _base_msg(mediaData={"filename": "invoice.pdf", "size": 98765})

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "invoice.pdf"
        assert doc["fileLength"] == 98765

    def test_media_data_filename_variant_keys_are_also_checked(self):
        stub = _Stub()
        msg = _base_msg(mediaData={"fileName": "contract.docx", "fileLength": 555})

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "contract.docx"
        assert doc["fileLength"] == 555

    def test_top_level_fields_still_win_over_media_data(self):
        stub = _Stub()
        msg = _base_msg(filename="top.pdf", size=1, mediaData={"filename": "nested.pdf", "size": 2})

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "top.pdf"
        assert doc["fileLength"] == 1

    def test_nothing_anywhere_falls_back_to_the_generic_placeholder(self):
        stub = _Stub()
        msg = _base_msg()

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "Document"
        assert doc["fileLength"] == 0

    def test_a_non_dict_media_data_is_ignored_safely(self):
        stub = _Stub()
        msg = _base_msg(mediaData="not-a-dict")

        result = stub._normalize_wpp_message(msg)

        doc = result["message"]["documentMessage"]
        assert doc["fileName"] == "Document"
        assert doc["fileLength"] == 0

    def test_plain_text_caption_is_preserved_for_the_recipient(self):
        stub = _Stub()

        result = stub._normalize_wpp_message(
            _base_msg(filename="report.pdf", caption="Relatório mensal")
        )

        assert result["message"]["documentMessage"]["caption"] == "Relatório mensal"

    def test_link_caption_is_preserved_as_ordinary_caption_text(self):
        stub = _Stub()
        caption = "Confira em https://example.com/documento"

        result = stub._normalize_wpp_message(
            _base_msg(filename="report.pdf", caption=caption)
        )

        assert result["message"]["documentMessage"]["caption"] == caption

    def test_document_body_is_not_mistaken_for_a_caption(self):
        stub = _Stub()

        result = stub._normalize_wpp_message(
            _base_msg(filename="report.pdf", body="A" * 5000)
        )

        assert result["message"]["documentMessage"]["caption"] == ""
