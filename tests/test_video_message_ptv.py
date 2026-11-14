"""A video message (type "ptv") is a video, not an incompatible message (#536)."""
from client.core.websocket_client import WebSocketClient

PEER = "5511999999999@s.whatsapp.net"


class _Normalizer:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _raw_ptv():
    return {
        "id": f"false_{PEER}_3EB0ABCDEF",
        "type": "ptv", "t": 1790222611, "timestamp": 1790222611,
        "from": PEER, "to": "5511888888888@s.whatsapp.net", "fromMe": False,
        "duration": 7, "mimetype": "video/mp4", "caption": "",
    }


def test_ptv_is_normalized_as_a_video_message():
    result = _Normalizer()._normalize_wpp_message(_raw_ptv())
    assert result["messageType"] == "videoMessage"
    assert "videoMessage" in result["message"]
    assert result["message"]["videoMessage"]["ptv"] is True


def test_plain_video_is_not_a_video_message():
    raw = _raw_ptv()
    raw["type"] = "video"
    result = _Normalizer()._normalize_wpp_message(raw)
    assert result["message"]["videoMessage"]["ptv"] is False


def test_label_key():
    from client.core.utils import video_label

    class _I18n:
        def t(self, key):
            return f"[{key}]"

    assert video_label({"ptv": True}, _I18n()) == "[video_message]"
    assert video_label({"ptv": False}, _I18n()) == "[video]"
    assert video_label({}, _I18n()) == "[video]"
