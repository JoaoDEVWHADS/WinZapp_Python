"""A reply that @-mentions someone must still be a reply on the recipient's side.

Reported by testers: replying to a message while mentioning someone showed up
as a reply in WinZapp's own list, with no error, but the recipients got an
ORIGINAL (unquoted) message. Replies without mentions worked.

Mechanism: send_text_message() took the /send-mentioned branch whenever there
were mentions and only computed the quote id in the ``else`` — so the quote was
silently dropped, and so was it on the legacy-@c.us retry. On the Node side
wppconnect's client.sendMentioned() has no quote parameter either, so
messageController.ts now makes the same WPP.chat.sendTextMessage call with
``quotedMsg`` added when the payload carries ``messageId``.

MainWindow is a wx.Frame: send_text_message() is bound onto a stub, as in
tests/test_ambiguous_send_is_not_resent.py. The Node half is asserted against
the source (the code is a string evaluated inside WhatsApp Web), like
tests/test_status_reply_quotes_the_live_model.py.
"""

import json
import types
from pathlib import Path

import pytest

from main import MainWindow
from core.message_queue import PendingMessage
from core.send_contract import quote_is_status
from tests.god_modules import patch_main_global

PHONE = "5511999999999@s.whatsapp.net"
LID = "123456@lid"
GROUP = "120363426331215016@g.us"
MENTION = "5511888888888@s.whatsapp.net"
QUOTED = {"key": {"id": "3EB0AAA", "remoteJid": GROUP, "fromMe": False}}
QUOTED_ID = "false_120363426331215016@g.us_3EB0AAA"
STATUS = {"key": {"id": "3EB0STATUS", "remoteJid": "status@broadcast",
                  "fromMe": False, "participant": "5511777777777@s.whatsapp.net"}}
CONTROLLER = (
    Path(__file__).resolve().parents[1]
    / "client" / "api_patches" / "src" / "controller" / "messageController.ts"
)


class _Response:
    def __init__(self, status_code, payload=None):
        self._payload = payload if payload is not None else {
            "status": "error", "message": "boom",
        }
        self.status_code = status_code
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


_OK = {"status": "success", "response": {"id": "3EB0NEW", "ack": 1}}


class _Stub:
    send_text_message = MainWindow.send_text_message
    _check_wa_connection_closed = MainWindow._check_wa_connection_closed
    _serialize_quoted_id = MainWindow._serialize_quoted_id
    _canonical_mention_jids = MainWindow._canonical_mention_jids
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _classify_send_exception = MainWindow._classify_send_exception
    _is_self_jid = MainWindow._is_self_jid
    _phone_digits_equivalent = staticmethod(MainWindow._phone_digits_equivalent)
    _build_link_preview_options = staticmethod(
        MainWindow._build_link_preview_options)

    def __init__(self):
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "tok"
        self.my_jid = "5500000000000@s.whatsapp.net"
        self.my_lid = ""
        self.i18n = types.SimpleNamespace(t=lambda key: key)
        self._lid_to_phone = {}

    def _serialize_msg_id(self, remote_jid, key):
        return f"{str(bool(key.get('fromMe'))).lower()}_{remote_jid}_{key['id']}"

    def _resolve_jid_for_send(self, jid):
        return jid

    def _legacy_phone_for_send(self, jid):
        return jid.replace("@lid", "@c.us")

    def output(self, text, interrupt=False):
        pass

    def _set_wa_connected(self, connected, reason="", **kwargs):
        pass

    def check_wa_connection_http(self):
        pass


def _answer(monkeypatch, *responses):
    """Return each response in turn; record every (route, payload) sent."""
    calls = []
    queue = list(responses)

    def _fake_api_post(url, **kwargs):
        calls.append((url.rsplit("/", 1)[-1], kwargs.get("json")))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    patch_main_global(monkeypatch, "api_post", _fake_api_post)
    return calls


class TestPayloads:
    def test_mention_and_quote_carry_the_message_id(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(201, _OK))

        _Stub().send_text_message(
            GROUP, "oi @x", quoted=QUOTED, mentioned_jids=[MENTION])

        route, payload = calls[0]
        assert route == "send-mentioned"
        assert payload["messageId"] == QUOTED_ID
        assert payload["mentioned"] == ["5511888888888@c.us"]

    def test_mention_only_payload_is_unchanged(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(201, _OK))

        _Stub().send_text_message(GROUP, "oi @x", mentioned_jids=[MENTION])

        route, payload = calls[0]
        assert route == "send-mentioned"
        assert "messageId" not in payload
        assert set(payload) == {
            "phone", "message", "mentioned", "isGroup", "isLid", "options"}

    def test_quote_only_still_uses_send_reply(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(201, _OK))

        _Stub().send_text_message(GROUP, "oi", quoted=QUOTED)

        route, payload = calls[0]
        assert route == "send-reply"
        assert payload["messageId"] == QUOTED_ID
        assert "mentioned" not in payload

    def test_an_unserializable_ordinary_quote_matches_the_plain_path(
            self, monkeypatch):
        """Same as a reply without mentions: no id, an ordinary chat quote
        goes out plain (the mentions are kept)."""
        calls = _answer(monkeypatch, _Response(201, _OK))

        _Stub().send_text_message(
            GROUP, "oi", quoted={"key": {}}, mentioned_jids=[MENTION])

        assert calls[0][0] == "send-mentioned"
        assert "messageId" not in calls[0][1]


class TestStatusQuotes:
    def test_a_status_reply_with_mentions_goes_through_send_reply(
            self, monkeypatch):
        calls = _answer(monkeypatch, _Response(201, _OK))

        _Stub().send_text_message(
            PHONE, "oi @x", quoted=STATUS, mentioned_jids=[MENTION])

        route, payload = calls[0]
        assert route == "send-reply"
        assert "status@broadcast" in payload["messageId"]
        assert "mentioned" not in payload

    def test_a_status_without_a_serializable_id_is_refused(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(201, _OK))
        broken = {"key": {"remoteJid": "status@broadcast"}}

        result = _Stub().send_text_message(
            PHONE, "oi", quoted=broken, mentioned_jids=[MENTION])

        assert calls == []
        assert result["ok"] is False
        assert result["retry"] is False

    @pytest.mark.parametrize("quoted, quoted_id, expected", [
        (STATUS, None, True),
        (None, "false_status@broadcast_3EB0_x@lid", True),
        (QUOTED, QUOTED_ID, False),
        (None, None, False),
    ])
    def test_quote_is_status(self, quoted, quoted_id, expected):
        assert quote_is_status(quoted, quoted_id) is expected

    def test_a_status_is_never_degraded_after_a_failure(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(400))

        result = _Stub().send_text_message(
            PHONE, "oi", quoted=STATUS, mentioned_jids=[MENTION])

        assert [c[0] for c in calls] == ["send-reply"]
        assert result["ok"] is False


class TestFailurePathsMatchAReplyWithoutMentions:
    def test_legacy_retry_carries_the_message_id(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(400), _Response(201, _OK))

        _Stub().send_text_message(
            LID, "oi @x", quoted=QUOTED, mentioned_jids=[MENTION])

        assert [c[0] for c in calls] == ["send-mentioned", "send-mentioned"]
        assert calls[0][1]["messageId"] == QUOTED_ID
        retry = calls[1][1]
        assert retry["phone"] == ["123456@c.us"]
        assert retry["messageId"] == QUOTED_ID
        assert retry["mentioned"] == ["5511888888888@c.us"]

    def test_an_ambiguous_failure_sends_nothing_more(self, monkeypatch):
        calls = _answer(monkeypatch, _Response(500))

        result = _Stub().send_text_message(
            GROUP, "oi @x", quoted=QUOTED, mentioned_jids=[MENTION])

        assert len(calls) == 1
        assert result["ambiguous"] is True
        assert result["retry"] is False

    def test_a_definite_refusal_strips_the_quote_but_keeps_the_mentions(
            self, monkeypatch, wx_app):
        calls = _answer(monkeypatch, _Response(400), _Response(201, _OK))

        result = _Stub().send_text_message(
            GROUP, "oi @x", quoted=QUOTED, mentioned_jids=[MENTION])

        assert [c[0] for c in calls] == ["send-mentioned", "send-mentioned"]
        fallback = calls[1][1]
        assert "messageId" not in fallback
        assert fallback["mentioned"] == ["5511888888888@c.us"]
        assert result["ok"] is True
        assert result["quote_lost"] is True


class TestTheQueueKeepsBoth:
    def test_a_pending_message_holds_the_quote_and_the_mentions(self):
        pm = PendingMessage("loc", GROUP, text="oi @x", quoted=QUOTED,
                            mentioned_jids=[MENTION])

        assert pm.quoted is QUOTED
        assert pm.mentioned_jids == [MENTION]


class TestTheNodeSideQuotes:
    @pytest.fixture()
    def source(self):
        text = CONTROLLER.read_text(encoding="utf-8")
        start = text.index("async function sendMentionedWithQuote")
        return text[start:text.index("export async function sendImageAsSticker")]

    def test_both_options_reach_wa_js(self, source):
        assert "detectMentioned: true" in source
        assert "mentionedList: mentioned" in source
        assert "quotedMsg," in source

    def test_the_quote_is_only_used_when_a_message_id_came_in(self, source):
        assert "typeof messageId === 'string' && messageId" in source
        assert "req.client.sendMentioned(`${contato}`, message, mentioned)" in source

    def test_the_result_is_audited_like_before(self, source):
        assert "'send-mentioned'" in source
        assert "auditSendResult(" in source

    def test_a_status_quote_is_refused_not_degraded(self, source):
        assert "status@broadcast" in source
        assert "throw new Error" in source
