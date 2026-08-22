"""Tests for WebSocketClient._normalize_wpp_message() preserving the PTT
(voice-note) flag on received audio messages.

Reported live: sequential playback of voice notes only chained for the user's
own recordings. WPPConnect reports voice notes with type="ptt", which
_normalize_wpp_message() maps to messageType "audioMessage" — but the raw
flag was dropped, so ConversationsPanel._is_voice_message() returned False
for every received voice note and the auto audio-chain never advanced past
them (own recordings carry ptt=True from their virtual message and chained
fine). The fix copies the flag into audioMessage so both sides behave the
same.

WebSocketClient needs a live Socket.IO client normally, but
_normalize_wpp_message()/_clean_jid() touch no I/O — exercised as plain
functions against a small stub, same approach as
tests/test_normalize_e2e_notification.py.
"""

from core.websocket_client import WebSocketClient


class _Stub:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _audio_msg(**overrides):
    msg = {
        "id": "false_5511999999999@c.us_ABC123",
        "from": "5511999999999@c.us",
        "to": "5511999999999@c.us",
        "fromMe": False,
        "timestamp": 1700000000,
        "type": "ptt",
        "duration": 5,
    }
    msg.update(overrides)
    return msg


def test_ptt_type_sets_audio_message_flag():
    result = _Stub()._normalize_wpp_message(_audio_msg())
    assert result["messageType"] == "audioMessage"
    assert result["message"]["audioMessage"]["ptt"] is True


def test_plain_audio_type_has_no_ptt_flag():
    result = _Stub()._normalize_wpp_message(_audio_msg(type="audio"))
    assert result["messageType"] == "audioMessage"
    assert result["message"]["audioMessage"].get("ptt") is None


def test_audio_type_with_media_data_ptt_is_preserved():
    result = _Stub()._normalize_wpp_message(
        _audio_msg(type="audio", mediaData={"ptt": True})
    )
    assert result["message"]["audioMessage"].get("ptt") is True


def test_seconds_parsed_from_duration():
    result = _Stub()._normalize_wpp_message(_audio_msg(duration=12.5))
    assert result["message"]["audioMessage"]["seconds"] == 12


def test_ptt_flag_feeds_voice_message_detection():
    # End-to-end with ConversationsPanel._is_voice_message(): the copied flag
    # must make a received PTT classify as a voice note, which is what the
    # sequential audio-chain relies on.
    from ui.conversations import ConversationsPanel

    result = _Stub()._normalize_wpp_message(_audio_msg())
    assert ConversationsPanel._is_voice_message(None, result) is True


def test_audio_mimetype_is_preserved_for_save_as_extension():
    result = _Stub()._normalize_wpp_message(
        _audio_msg(type="audio", mimetype="audio/mp4")
    )
    assert result["message"]["audioMessage"]["mimetype"] == "audio/mp4"


def test_audio_filename_is_preserved_from_media_data():
    result = _Stub()._normalize_wpp_message(
        _audio_msg(
            type="audio",
            mediaData={"mimetype": "audio/ogg", "fileName": "gravacao.ogg"},
        )
    )
    audio = result["message"]["audioMessage"]
    assert audio["mimetype"] == "audio/ogg"
    assert audio["fileName"] == "gravacao.ogg"

