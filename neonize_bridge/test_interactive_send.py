"""Interactive and commerce messages."""
import asyncio
import json
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import interactive_send as isend
import raw_queries
from test_biz_iq import product, t


def test_buttons_are_wa_jss_native_flow():
    buttons = isend.native_flow_buttons([
        {"id": "a", "text": "Sim"}, {"text": "Talvez"}])
    assert [b["name"] for b in buttons] == ["quick_reply", "quick_reply"]
    assert json.loads(buttons[1]["buttonParamsJSON"]) == {"display_text": "Talvez", "id": "1"}
    actions = isend.native_flow_buttons([{"url": "https://a", "text": "Site"},
                                         {"phoneNumber": "+5511", "text": "Ligar"},
                                         {"code": "X1", "text": "Copiar"}])
    assert [b["name"] for b in actions] == ["cta_url", "cta_call", "cta_copy"]
    assert json.loads(actions[0]["buttonParamsJSON"])["merchant_url"] == "https://a"


@pytest.mark.parametrize("buttons", [[], [{"text": "a"}] * 4, None,
                                     [{"id": "a", "text": "Sim"}, {"url": "u", "text": "x"}],
                                     [{"id": "a"}]])
def test_invalid_buttons(buttons):
    with pytest.raises(isend.SendRefused):
        isend.native_flow_buttons(buttons)


def test_a_list_message():
    fields = isend.list_message({"buttonText": "Escolha", "description": "Menu", "sections": [
        {"title": "Pães", "rows": [{"rowId": "p1", "title": "Francês", "description": "Quente"}]}]})
    message = isend.to_message(fields).listMessage
    assert (message.buttonText, message.description, message.listType) == ("Escolha", "Menu", 1)
    assert message.sections[0].rows[0].rowID == "p1"
    with pytest.raises(isend.SendRefused):
        isend.list_message({"sections": []})


def test_the_pix_key_order():
    params = isend.pix_params("PHONE", "Padaria", "+5511", "pague")
    pix = params["payment_settings"][0]
    assert pix == {"type": "pix_static_code",
                   "pix_static_code": {"key_type": "PHONE", "merchant_name": "Padaria",
                                       "key": "+5511"}}
    assert params["order"]["order_type"] == "ORDER_WITHOUT_AMOUNT" and params["currency"] == "BRL"


def test_a_charge():
    items = isend.charge_items([{"name": "Pão", "price": 7500, "qnt": 2},
                                {"id": "1"}], {"1": {"id": "1", "name": "Leite", "price": "5000"}})
    params = isend.charge_params(items, {"shipping": 1000, "discount": 500}, "BRL")
    assert params["total_amount"] == {"value": 15000 + 5000 + 1000 - 500, "offset": 1000}
    assert params["order"]["items"][1] == {"retailer_id": "1", "name": "Leite",
                                           "amount": {"value": 5000, "offset": 1000}, "quantity": 1,
                                           "isCustomItem": False, "isQuantitySet": True}
    assert params["order"]["items"][0]["isCustomItem"] is True
    assert params["order"]["tax"] is None and params["order"]["shipping"]["value"] == 1000
    with pytest.raises(isend.SendRefused):
        isend.charge_items([{"id": "9"}], {})


def test_currency_by_phone():
    assert isend.currency_of("5511999") == "BRL"
    assert isend.currency_of("351912") == "EUR"
    assert isend.currency_of("1415") == "USD"


class Sender:
    def __init__(self):
        self.sent = []

    def send_iq(self, query):
        return {"node": t("iq", children=[t("product_list", children=[product("1")])])}

    def send_message(self, destination, message):
        self.sent.append((destination, message))
        return N(ID=f"M{len(self.sent)}")


@pytest.fixture(autouse=True)
def raw(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))


def run(s, path, body):
    async def main():
        app = web.Application()
        isend.register_routes(app.router, session=lambda req: s, destination_of=lambda p: p,
                              store_sent=lambda s, d, r: web.json_response(
                                  {"response": [{"id": f"true_{d}_{r.ID}", "ack": 1}]}),
                              jid_from_text=lambda x: x)
        async with TestClient(TestServer(app)) as http:
            resp = await http.post("/api/tok/" + path, json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


def session():
    return N(client=Sender(), status="CONNECTED", me="5599@s.whatsapp.net")


def flow_name(message):
    return message.interactiveMessage.nativeFlowMessage.buttons[0].name


def test_send_buttons_to_each_phone():
    s = session()
    status, body = run(s, "send-buttons", {"phone": ["5511", "5522"], "message": "Quer?",
                                           "options": {"buttons": [{"id": "s", "text": "Sim"}],
                                                       "footer": "rodapé"}})
    assert status == 201 and [r["id"] for r in body["response"]] == ["true_5511_M1", "true_5522_M2"]
    message = s.client.sent[0][1]
    assert flow_name(message) == "quick_reply" and message.interactiveMessage.body.text == "Quer?"
    assert run(s, "send-buttons", {"phone": "5511", "options": {}})[0] == 400


def test_send_list_pix_and_order():
    s = session()
    assert run(s, "send-list-message", {"phone": "5511", "sections": [
        {"title": "A", "rows": [{"rowId": "1", "title": "x"}]}]})[0] == 201
    assert s.client.sent[-1][1].HasField("listMessage")
    assert run(s, "send-pix-key", {"phone": "5511", "keyType": "PHONE", "name": "N",
                                   "key": "+55"})[0] == 201
    pix = s.client.sent[-1][1]
    assert flow_name(pix) == "payment_info" and len(pix.messageContextInfo.messageSecret) == 32
    assert run(s, "send-pix-key", {"phone": "5511", "keyType": "PHONE"})[0] == 400
    assert run(s, "send-order-message", {"phone": "5511", "items": [
        {"name": "Pão", "price": 7500, "qnt": 2}, {"id": "1"}],
        "options": {"notes": "obrigado"}})[0] == 201
    order = s.client.sent[-1][1]
    assert flow_name(order) == "review_and_pay"
    params = json.loads(order.interactiveMessage.nativeFlowMessage.buttons[0].buttonParamsJSON)
    assert params["total_amount"]["value"] == 15000 + 7500 and params["currency"] == "BRL"


def test_send_link_catalog():
    s = session()
    status, body = run(s, "send-link-catalog", {"phones": ["5511"], "message": "Veja"})
    assert status == 200 and body["response"] == [{"phone": "5511", "status": "true_5511_M1"}]
    message = s.client.sent[0][1].interactiveMessage
    assert message.body.text == "Veja https://wa.me/c/5599"
    assert message.nativeFlowMessage.buttons[0].name == "cta_url"
    assert run(s, "send-link-catalog", {"message": "x"})[0] == 401
