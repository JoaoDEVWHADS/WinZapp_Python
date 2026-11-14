"""Orders: reading one, the seller's answers and the buyer's confirmation."""
import asyncio
import json
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import catalog_graphql
import commerce_orders as co
import raw_queries
from test_business import client_commerce

INFO = {"createdAt": 1700000000, "currency": "BRL", "subtotal": 15000, "total": 15000,
        "products": [{"id": "1", "name": "Pão", "price": 7500, "currency": "BRL", "quantity": 2,
                      "thumbnailUrl": ""}]}
ORDER_WPP = {"type": "order", "orderId": "O1", "token": "TK", "sellerJid": "5599@s.whatsapp.net",
             "status": 1, "message": "sem cebola", "id": {"_serialized": "false_5511@c.us_ABCDEFGH1"}}


def flow(name, button, params, from_me=False, serial="x"):
    return {"nativeFlowName": name, "id": {"fromMe": from_me, "_serialized": serial},
            "interactivePayload": {"buttons": [{"name": button,
                                                "buttonParamsJson": json.dumps(params)}]}}


def test_order_of_needs_id_and_token():
    assert co.order_of(ORDER_WPP) == {"id": "O1", "token": "TK", "sellerJid": "5599@s.whatsapp.net"}
    assert co.order_of({"type": "order"}) is None and co.order_of({"type": "chat"}) is None


def test_the_order_body_the_client_reads():
    order = client_commerce().parse_order({"order": co.order_body(ORDER_WPP, INFO, False, True)})
    assert order.can_answer and not order.can_update and order.total == 15000
    assert order.items[0].quantity == 2 and order.note == "sem cebola"
    accepted = dict(ORDER_WPP, status=2)
    assert co.order_body(accepted, INFO, False, True)["canUpdate"] is True
    assert co.order_body(ORDER_WPP, INFO, False, False)["canAnswer"] is False
    assert co.order_body(ORDER_WPP, INFO, True, True)["canAnswer"] is False


def test_the_params_are_wa_jss():
    details = co.order_details_params("O1", INFO, "payment_requested")
    assert details["reference_id"] == "O1" and details["order"]["status"] == "payment_requested"
    assert details["order"]["items"][0]["amount"] == {"value": 7500, "offset": 1000}
    status = co.status_params("O1", INFO, "shipped", "captured", now=1)
    assert status["payment_status"] == "captured" and status["payment_timestamp"] == 1
    assert co.status_params("O1", INFO, "pending", None, "confirm")["payment_method"] == "confirm"


def test_the_details_of_a_sellers_message_and_its_latest_status():
    params = co.order_details_params("R1", INFO, "pending")
    info = co.details_info(params)
    assert info["total"] == 15000 and info["products"][0]["price"] == 7500
    messages = [flow("order_details", "review_and_pay", params),
                flow("order_status", "review_order", {"reference_id": "R1",
                                                      "order": {"status": "shipped"}})]
    assert co.latest_status(messages, "R1") == "shipped"
    assert co.latest_status(messages, "R2") == ""


def test_the_buyer_confirms_a_pending_order_once():
    def mine(m):
        return m["id"]["fromMe"]
    details = flow("order_details", "review_and_pay", co.order_details_params("R1", INFO, "pending"))
    assert co.buyer_state(details, [details], mine) == {"canConfirm": True, "confirmed": False}
    confirmation = flow("payment_method", "payment_method",
                        {"reference_id": "R1", "payment_method": "confirm"}, from_me=True)
    assert co.buyer_state(details, [details, confirmation], mine) == {
        "canConfirm": False, "confirmed": True}
    in_app = co.order_details_params("R1", INFO, "pending")
    in_app["payment_settings"] = [{"type": "payment_link"}]
    paid = flow("order_details", "review_and_pay", in_app)
    assert co.buyer_state(paid, [paid], mine)["canConfirm"] is False


class Db:
    def __init__(self, messages):
        # a stored message comes back as a new dictionary each time, as from the database
        messages = json.loads(json.dumps(messages))
        self.by_id = {m["id"]["_serialized"].split("_")[-1]: m for m in messages}
        self.history = list(messages)
        self.saved = []

    def wpp_message(self, msg_id):
        return self.by_id.get(msg_id)

    def messages(self, chat, quantity):
        return self.history

    def message(self, chat, wpp):
        self.saved.append((chat, dict(wpp)))


class Seller:
    def __init__(self, business_name="Loja"):
        self.business_name, self.sent = business_name, []

    def get_me(self):
        return N(BussinessName=self.business_name)

    def send_iq(self, query):
        raise AssertionError("orders go through GraphQL")

    def send_message(self, destination, message):
        self.sent.append(message)
        return N(ID=f"S{len(self.sent)}")


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))
    monkeypatch.setattr(catalog_graphql, "get_order", lambda seller, oid, token: INFO)


def run(s, *requests):
    async def main():
        app = web.Application()
        co.register_routes(app.router, session=lambda req: s, jid_from_text=lambda x: x,
                           jid_text=str, destination_of=lambda chat: chat,
                           store_sent=lambda s, d, r: web.json_response({}),
                           quoted_context=lambda s, quoted: None)
        async with TestClient(TestServer(app)) as http:
            out = []
            for method, path, body in requests:
                resp = await http.request(method, "/api/tok/" + path, json=body)
                out.append((resp.status, await resp.json()))
            return out
    return asyncio.run(main())


def session(client, messages):
    return N(name="acc", client=client, status="CONNECTED", db=Db(messages))


SERIAL = "false_5511@c.us_ABCDEFGH1"


def params_of(message):
    return json.loads(message.interactiveMessage.nativeFlowMessage.buttons[0].buttonParamsJSON)


def test_read_and_accept(tmp_path):
    s = session(Seller(), [ORDER_WPP])
    (status, body), = run(s, ("GET", f"commerce/order/{SERIAL}", None))
    assert status == 200 and body["response"]["order"]["canAnswer"] is True
    (status, body), = run(s, ("POST", f"commerce/order/{SERIAL}/accept", {}))
    assert body["response"] == {"accepted": True, "status": 2}
    (sent,) = s.client.sent
    assert sent.interactiveMessage.nativeFlowMessage.buttons[0].name == "review_and_pay"
    assert params_of(sent)["order"]["status"] == "payment_requested"
    assert s.db.saved[0][1]["status"] == 2


def test_decline_sends_the_status_then_the_canceled_details(tmp_path):
    s = session(Seller(), [ORDER_WPP])
    (status, body), = run(s, ("POST", f"commerce/order/{SERIAL}/decline", {"note": "acabou"}))
    assert body["response"]["status"] == 3
    names = [m.interactiveMessage.nativeFlowMessage.buttons[0].name for m in s.client.sent]
    assert names == ["review_order", "review_and_pay"]
    assert s.client.sent[0].interactiveMessage.body.text == "acabou"
    assert params_of(s.client.sent[1])["order"]["status"] == "canceled"


def test_a_status_needs_an_answered_order_and_a_known_status(tmp_path):
    s = session(Seller(), [ORDER_WPP])
    assert run(s, ("POST", f"commerce/order/{SERIAL}/status", {"status": "shipped"}))[0][0] == 400
    s = session(Seller(), [dict(ORDER_WPP, status=2)])
    assert run(s, ("POST", f"commerce/order/{SERIAL}/status", {"status": "lost"}))[0][0] == 400
    (status, body), = run(s, ("POST", f"commerce/order/{SERIAL}/status",
                              {"status": "shipped", "paymentStatus": "captured"}))
    assert status == 200 and params_of(s.client.sent[0])["order"]["status"] == "shipped"


def test_only_a_business_answers_and_never_its_own_order(tmp_path):
    s = session(Seller(business_name=""), [ORDER_WPP])
    assert run(s, ("POST", f"commerce/order/{SERIAL}/accept", {}))[0] == (
        403, {"status": "error", "code": "not_business"})
    own = dict(ORDER_WPP, id={"_serialized": "true_5511@c.us_ABCDEFGH1"})
    s = session(Seller(), [own])
    assert run(s, ("POST", "commerce/order/true_5511@c.us_ABCDEFGH1/accept", {}))[0][1]["code"] \
        == "own_order"


def test_not_an_order_and_an_invalid_id(tmp_path):
    s = session(Seller(), [])
    assert run(s, ("GET", f"commerce/order/{SERIAL}", None))[0] == (
        404, {"status": "error", "code": "not_an_order"})
    assert run(s, ("GET", "commerce/order/nonsense", None))[0][0] == 400


def test_the_buyer_reads_and_confirms(tmp_path):
    details = flow("order_details", "review_and_pay", co.order_details_params("R1", INFO, "pending"),
                   serial=SERIAL)
    s = session(Seller(), [details])
    (status, body), = run(s, ("GET", f"commerce/order-details/{SERIAL}", None))
    assert body["response"] == {"canConfirm": True, "confirmed": False}
    (status, body), = run(s, ("POST", f"commerce/order-details/{SERIAL}/confirm", {}))
    assert body["response"] == {"confirmed": True}
    (sent,) = s.client.sent
    assert sent.interactiveMessage.nativeFlowMessage.buttons[0].name == "payment_method"
    assert params_of(sent)["payment_method"] == "confirm"


def test_get_order_by_message_id_is_upstreams(tmp_path):
    s = session(Seller(), [ORDER_WPP])
    (status, body), = run(s, ("GET", f"get-order-by-messageId/{SERIAL}", None))
    assert status == 201 and body["status"] == "Success"
    assert body["response"]["data"]["id"] == "O1" and body["response"]["data"]["total"] == 15000
