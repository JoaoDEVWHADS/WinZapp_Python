"""Tests for reading WPPConnect's 'qrCode' Socket.IO event.

WPPConnect Server emits, from exportQR() in createSessionUtil.ts:

    req.io.emit('qrCode', {data: 'data:image/png;base64,…', session: …})

so ``info["data"]`` is a plain string. on_qrcode_update() read it as
``info["data"]["qrcode"]["base64"]``, which raises AttributeError on a string —
on every event, silently, because python-socketio swallows handler exceptions
and runs here with logging disabled.

That handler is the only thing that refreshes the QR. WhatsApp rotates the code
roughly every 20 s, so the dialog kept showing the one-shot copy fetched from
status-session when it opened. By the time a phone was pointed at it the code
had long expired and was rejected as invalid — reported as "o QR Code não lê".

The pairing-code refresh for phone mode rides on the same event and was equally
dead, three lines before the wx.IsDestroyed() bug previously fixed inside it.
"""

import pytest

from core.websocket_client import WebSocketClient


extract = WebSocketClient._extract_qr_payload

DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"


class TestTheRealPayload:
    def test_the_shape_wppconnect_actually_emits(self):
        img, code = extract({"data": DATA_URI, "session": "abc"})
        assert img == DATA_URI
        assert code == ""

    def test_a_session_key_alongside_is_ignored(self):
        img, _ = extract({"data": DATA_URI, "session": "x", "extra": 1})
        assert img == DATA_URI


class TestOtherShapesStillWork:
    def test_nested_qrcode_object(self):
        img, code = extract({"data": {"qrcode": {"base64": "XYZ", "pairingCode": "AB12CD34"}}})
        assert (img, code) == ("XYZ", "AB12CD34")

    def test_nested_pairing_code_only(self):
        """Phone-pairing mode: WPPConnect carries the code on this event too."""
        img, code = extract({"data": {"qrcode": {"pairingCode": "ABCD1234"}}})
        assert (img, code) == ("", "ABCD1234")

    def test_nested_qrcode_as_a_string(self):
        img, _ = extract({"data": {"qrcode": DATA_URI}})
        assert img == DATA_URI

    def test_base64_directly_under_data(self):
        img, _ = extract({"data": {"base64": DATA_URI}})
        assert img == DATA_URI

    def test_top_level_keys_as_a_last_resort(self):
        assert extract({"qrcode": DATA_URI})[0] == DATA_URI
        assert extract({"base64": DATA_URI})[0] == DATA_URI
        assert extract({"pairingCode": "ABCD1234"})[1] == "ABCD1234"


class TestJunkIsSurvived:
    @pytest.mark.parametrize("bad", [None, "a string", 42, [], {"foo": 1}, {"data": None},
                                     {"data": []}, {"data": {}}, {"data": {"qrcode": None}}])
    def test_never_raises_and_returns_empty(self, bad):
        assert extract(bad) == ("", "")

    def test_a_non_string_image_is_dropped(self):
        """Whatever comes back must be safe to hand to base64.b64decode()."""
        img, _ = extract({"data": {"base64": 12345}})
        assert img == ""

    def test_a_numeric_pairing_code_is_stringified(self):
        _, code = extract({"pairingCode": 12345678})
        assert code == "12345678"


def test_the_old_expression_would_have_raised_on_the_real_payload():
    """Pins why this existed: if WPPConnect ever changes to the nested shape,
    this test fails and the extra tolerance above can be reconsidered."""
    real = {"data": DATA_URI, "session": "abc"}
    with pytest.raises(AttributeError):
        real.get("data", {}).get("qrcode", {})
