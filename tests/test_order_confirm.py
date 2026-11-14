"""The buyer's "Confirm order info" for an order a seller created and that is
paid outside the app (core/commerce.py, ui/dialogs/order_update_dialog.py).

Whether it applies is the server's decision, made the way WhatsApp Web makes
it (api_patches orderConfirmController.ts, with its own tests). What must hold
here: the button exists only after the server said yes, the confirmation is
asked first and sent once, it is announced as done only when a fresh reading
shows it, and one that may have gone is never offered again by itself.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from core import commerce
from core.commerce import BuyerOrder, CommerceError, ORDER_UPDATE_MESSAGE_TYPE
from core.websocket_client import WebSocketClient
from tests.mnemonics import load_strings
from ui.dialogs.order_update_dialog import OrderUpdateDialog

CONNECTION = ("http://localhost", 6300, "synthetic-token")
HEADERS = {"Authorization": "Bearer synthetic-token"}
BASE = "http://localhost:6300/api/synthetic-token/commerce/order-details/"
ORDER_ID = "false_777@lid_3EB0AAAAAAAAAAAAAAAA"
QUOTED = "false_777%40lid_3EB0AAAAAAAAAAAAAAAA"
STRINGS = load_strings("en-US")
I18N = SimpleNamespace(t=lambda key: STRINGS[key].replace("&", ""))


def answer(body, status=200):
    return SimpleNamespace(status_code=status, json=lambda: body)


def ok(data):
    return answer({"status": "success", "response": data})


class TestTheContract:
    def test_reading_is_a_get_that_says_what_the_buyer_may_do(self, monkeypatch):
        get = Mock(return_value=ok({"canConfirm": True, "confirmed": False}))
        monkeypatch.setattr(commerce, "api_get", get)
        assert commerce.read_buyer_order(CONNECTION, ORDER_ID) == BuyerOrder(True, False)
        get.assert_called_once_with(BASE + QUOTED, headers=HEADERS, timeout=45)

    @pytest.mark.parametrize("data, expected", [
        ({"canConfirm": "yes", "confirmed": 1}, BuyerOrder(False, False)),
        ({"confirmed": True}, BuyerOrder(False, True)),
    ])
    def test_only_a_true_is_a_yes(self, monkeypatch, data, expected):
        monkeypatch.setattr(commerce, "api_get", Mock(return_value=ok(data)))
        assert commerce.read_buyer_order(CONNECTION, ORDER_ID) == expected

    def test_confirming_is_one_post_that_needs_the_servers_word(self, monkeypatch):
        post = Mock(return_value=ok({"confirmed": True}))
        monkeypatch.setattr(commerce, "api_post", post)
        commerce.confirm_buyer_order(CONNECTION, ORDER_ID)
        post.assert_called_once_with(BASE + QUOTED + "/confirm", json={}, headers=HEADERS, timeout=90)
        monkeypatch.setattr(commerce, "api_post", Mock(return_value=ok({})))
        with pytest.raises(CommerceError) as error:
            commerce.confirm_buyer_order(CONNECTION, ORDER_ID)
        assert error.value.code == "unconfirmed"

    def test_a_refusal_keeps_the_servers_code(self, monkeypatch):
        monkeypatch.setattr(commerce, "api_post", Mock(return_value=answer(
            {"status": "error", "code": "already_confirmed"}, 409)))
        with pytest.raises(CommerceError) as error:
            commerce.confirm_buyer_order(CONNECTION, ORDER_ID)
        assert error.value.code == "already_confirmed"

    def test_a_group_message_is_never_sent(self, monkeypatch):
        post = Mock()
        monkeypatch.setattr(commerce, "api_post", post)
        with pytest.raises(CommerceError):
            commerce.confirm_buyer_order(CONNECTION, "false_111-0@g.us_3EB0AAAAAAAAAAAAAAAA")
        post.assert_not_called()


class _Normalizer:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def test_the_confirmation_in_the_chat_says_what_it_is():
    raw = {"id": "true_777@lid_3EB0DDDDDDDDDDDDDDDD", "type": "interactive", "t": 1790000200,
           "from": "999@lid", "to": "777@lid", "fromMe": True, "body": "", "nativeFlowName": "payment_method",
           "interactivePayload": {"buttons": [{"name": "payment_method", "buttonParamsJson": json.dumps({
               "reference_id": "REF1", "payment_method": "confirm", "currency": "BRL",
               "total_amount": {"value": 20000, "offset": 1000}, "order": {"status": "pending"}})}]},
           "chatId": {"server": "lid", "user": "777", "_serialized": "777@lid"}}
    message = _Normalizer()._normalize_wpp_message(raw)
    assert message["messageType"] == ORDER_UPDATE_MESSAGE_TYPE
    assert message["message"][ORDER_UPDATE_MESSAGE_TYPE]["method"] == "confirm"
    assert commerce.order_update_label(message, I18N) == \
        "Order information confirmed, reference REF1: Pending, total R$ 20.00"


# ── the dialog, on a stub ──────────────────────────────────────────────────

class _Dialog:
    for _name in ("_read", "_read_buyer", "_finish_read", "_show_buyer", "_on_confirm", "_finish_confirm"):
        locals()[_name] = getattr(OrderUpdateDialog, _name)
    del _name

    def __init__(self):
        self._connection, self._message, self._chat_name = CONNECTION, ORDER_ID, "Bakery"
        self._i18n = I18N
        self._busy = self._sent = False
        self._buyer = None
        self._mw = SimpleNamespace(speak_output=SimpleNamespace(output=Mock()))
        self._status = SimpleNamespace(SetLabel=Mock())
        shown = {"value": False}
        self._confirm = SimpleNamespace(IsShown=lambda: shown["value"],
                                        Show=lambda value: shown.update(value=value))
        self._details = SimpleNamespace(SetFocus=Mock())
        self.Layout = Mock()
        self.FindFocus = lambda: None
        self.work = []

    def _current(self):
        return True

    def _run_async(self, work, done):
        self.work.append((work, done))

    def run(self):
        work, done = self.work.pop()
        done(work())

    def _announce(self, text):
        self._status.SetLabel(text)
        self._mw.speak_output.output(text)

    def offered(self):
        return self._confirm.IsShown()

    def said(self):
        return self._mw.speak_output.output.call_args.args[0]


def _open(monkeypatch, buyer):
    dialog = _Dialog()
    monkeypatch.setattr(commerce, "read_buyer_order", Mock(return_value=buyer))
    dialog._read_buyer()
    dialog.run()
    return dialog


def test_the_button_exists_only_once_the_server_said_yes(monkeypatch):
    assert not _Dialog().offered()
    assert _open(monkeypatch, BuyerOrder(True, False)).offered()
    assert not _open(monkeypatch, BuyerOrder(False, False)).offered()


def test_an_order_already_confirmed_says_so_and_offers_nothing(monkeypatch):
    dialog = _open(monkeypatch, BuyerOrder(False, True))
    assert not dialog.offered()
    dialog._status.SetLabel.assert_called_with(STRINGS["commerce_order_confirm_already"])


@pytest.mark.parametrize("code", ["not_an_order", "unavailable"])
def test_an_order_of_another_kind_or_an_older_server_offers_nothing_and_says_nothing(monkeypatch, code):
    dialog = _Dialog()

    def _refuse(*_args):
        raise CommerceError(code)

    monkeypatch.setattr(commerce, "read_buyer_order", _refuse)
    dialog._read_buyer()
    dialog.run()
    assert not dialog.offered()
    dialog._mw.speak_output.output.assert_not_called()


def test_confirming_asks_first_sends_once_and_says_done_when_the_reading_shows_it(monkeypatch):
    dialog = _open(monkeypatch, BuyerOrder(True, False))
    asked = Mock(return_value=wx.YES)
    monkeypatch.setattr("ui.dialogs.order_update_dialog.wx.MessageBox", asked)
    sent = Mock()
    monkeypatch.setattr(commerce, "confirm_buyer_order", sent)
    monkeypatch.setattr(commerce, "read_buyer_order", Mock(return_value=BuyerOrder(False, True)))

    dialog._on_confirm(None)
    assert "Bakery" in asked.call_args.args[0]
    dialog._on_confirm(None)  # a second press while the first is out
    dialog.run()

    sent.assert_called_once_with(CONNECTION, ORDER_ID)
    assert dialog.said() == STRINGS["commerce_order_confirm_done"]
    assert not dialog.offered()


def test_saying_no_sends_nothing(monkeypatch):
    dialog = _open(monkeypatch, BuyerOrder(True, False))
    monkeypatch.setattr("ui.dialogs.order_update_dialog.wx.MessageBox", Mock(return_value=wx.NO))
    sent = Mock()
    monkeypatch.setattr(commerce, "confirm_buyer_order", sent)
    dialog._on_confirm(None)
    assert dialog.work == [] and dialog.offered()
    sent.assert_not_called()


@pytest.mark.parametrize("code, key", [
    ("unconfirmed", "commerce_order_confirm_unconfirmed"),
    ("unavailable", "commerce_order_confirm_unconfirmed"),
    ("cannot_confirm", "commerce_order_confirm_failed"),
    ("already_confirmed", "commerce_order_confirm_already"),
])
def test_a_confirmation_not_shown_by_the_reading_is_never_called_done_nor_offered_again(monkeypatch, code, key):
    dialog = _open(monkeypatch, BuyerOrder(True, False))
    monkeypatch.setattr("ui.dialogs.order_update_dialog.wx.MessageBox", Mock(return_value=wx.YES))

    def _refuse(*_args):
        raise CommerceError(code)

    monkeypatch.setattr(commerce, "confirm_buyer_order", _refuse)
    # Even a reading that still says "may confirm": one that may have gone is
    # not offered again from this dialog.
    monkeypatch.setattr(commerce, "read_buyer_order", Mock(return_value=BuyerOrder(True, False)))
    dialog._on_confirm(None)
    dialog.run()
    assert dialog.said() == STRINGS[key]
    assert not dialog.offered()


@pytest.mark.parametrize("msg, message_id, asks", [
    ({"key": {"fromMe": False}}, "false_1@c.us_X", True),
    ({"key": {}}, "false_1@c.us_X", True),
    ({"key": {"fromMe": True}}, "true_1@c.us_X", False),   # the account's own order
    ({"key": {"fromMe": False}}, "", False),                # nothing to ask about
    (None, "false_1@c.us_X", True),
])
def test_the_dialog_asks_only_about_someone_elses_order(msg, message_id, asks):
    assert commerce.should_read_buyer(msg, message_id) is asks


def test_the_dialog_asks_through_should_read_buyer():
    """Building the dialog would put a window up: only the wiring is read."""
    import inspect
    source = inspect.getsource(OrderUpdateDialog.__init__)
    assert "commerce.should_read_buyer(msg, message_id)" in source
