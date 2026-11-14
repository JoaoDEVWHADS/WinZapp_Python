"""A buyer's carts and sending one as an order."""
import asyncio
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import catalog_graphql
import commerce_cart as cart
import raw_queries
from test_biz_iq import product, t
from test_business import CATALOG_PROFILE, Client, client_commerce

PRODUCT = {"id": "1", "name": "Pão", "price": "7500", "currency": "BRL"}


def test_view_counts_and_totals():
    assert cart.view({}) == {"items": [], "itemCount": 0, "total": None, "currency": "",
                             "message": ""}
    full = cart.set_item({}, PRODUCT, 2)
    full = cart.set_item(full, {"id": "2", "name": "Leite", "price": "5000", "currency": "BRL"}, 1)
    view = cart.view(full)
    assert view["itemCount"] == 3 and view["total"] == 20000 and view["currency"] == "BRL"
    assert client_commerce().parse_cart(view).item_count == 3


def test_an_unpriced_item_leaves_the_total_unknown():
    full = cart.set_item({}, {"id": "1", "name": "?", "price": None, "currency": ""}, 1)
    assert cart.view(full)["total"] is None


def test_setting_again_replaces_the_quantity_and_removing():
    full = cart.set_item(cart.set_item({}, PRODUCT, 2), PRODUCT, 5)
    assert [i["quantity"] for i in full["items"]] == [5]
    assert cart.remove_item(full, "1")["items"] == []


def test_the_order_message_is_wa_jss():
    fields = cart.order_message_fields(
        {"id": "O1", "token": "TK", "total": 15000, "currency": "BRL"},
        cart.set_item({}, PRODUCT, 2), "5511@s.whatsapp.net", "Padaria", "sem cebola")
    assert fields == {"orderID": "O1", "token": "TK", "sellerJID": "5511@s.whatsapp.net",
                      "orderTitle": "Padaria", "status": 1, "surface": 1, "messageVersion": 2,
                      "itemCount": 2, "message": "sem cebola", "totalAmount1000": 15000,
                      "totalCurrencyCode": "BRL"}


class Buyer(Client):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.sent = []

    def send_message(self, destination, message):
        self.sent.append((destination, message))
        return N(ID="M1")


@pytest.fixture(autouse=True)
def raw(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))


def session(tmp_path, client):
    db = N(contact_of=lambda jid: {"name": "Padaria"})
    return N(name="acc", client=client, status="CONNECTED", folder=str(tmp_path), db=db)


def run(s, *requests):
    async def main():
        app = web.Application()
        cart.register_routes(
            app.router, session=lambda req: s, jid_from_text=lambda text: text, jid_text=str,
            destination_of=lambda chat: chat,
            store_sent=lambda s, dest, resp: web.json_response(
                {"response": [{"id": f"true_{dest}_{resp.ID}", "ack": 1}]}))
        async with TestClient(TestServer(app)) as http:
            out = []
            for method, path, body in requests:
                resp = await http.request(method, "/api/tok/commerce/cart/" + path, json=body)
                out.append((resp.status, await resp.json()))
            return out
    return asyncio.run(main())


def test_fill_remove_and_clear(tmp_path):
    s = session(tmp_path, Buyer(profile_children=CATALOG_PROFILE, products=[product("1")]))
    (status, body), (_, read) = run(s, ("POST", "5511@c.us/set", {"productId": "1", "quantity": 2}),
                                    ("GET", "5511@c.us", None))
    assert status == 200 and body["response"]["cart"]["itemCount"] == 2
    assert read["response"]["cart"]["total"] == 15000
    (status, body), = run(s, ("POST", "5511@c.us/remove", {"productId": "1"}))
    assert body["response"]["cart"]["items"] == []
    (status, body), = run(s, ("POST", "5511@c.us/clear", {}))
    assert status == 200 and body["response"]["cart"]["itemCount"] == 0


def test_a_seller_without_carts_and_a_product_gone(tmp_path):
    s = session(tmp_path, Buyer(products=[product("1")]))
    (status, body), = run(s, ("POST", "5511@c.us/set", {"productId": "1", "quantity": 1}))
    assert (status, body["code"]) == (409, "cart_disabled")
    s = session(tmp_path, Buyer(profile_children=CATALOG_PROFILE, products=[]))
    (status, body), = run(s, ("POST", "5511@c.us/set", {"productId": "9", "quantity": 1}))
    assert (status, body["code"]) == (409, "product_unavailable")
    assert body["response"]["cart"]["items"] == []


def test_invalid_requests(tmp_path):
    s = session(tmp_path, Buyer())
    for path, body in (("1203@g.us/set", {"productId": "1", "quantity": 1}),
                       ("5511@c.us/set", {"productId": "1", "quantity": 100}),
                       ("5511@c.us/set", {"productId": "a b", "quantity": 1})):
        assert run(s, ("POST", path, body))[0][0] == 400


def test_submit_places_the_order_sends_it_and_empties_the_cart(tmp_path, monkeypatch):
    placed = []

    def place(seller, items):
        placed.append((seller, [dict(i) for i in items]))
        return {"id": "O1", "token": "TK", "total": 15000, "currency": "BRL"}
    monkeypatch.setattr(catalog_graphql, "place_order", place)
    s = session(tmp_path, Buyer(profile_children=CATALOG_PROFILE, products=[product("1")]))
    run(s, ("POST", "5511@c.us/set", {"productId": "1", "quantity": 2}))
    (status, body), = run(s, ("POST", "5511@c.us/submit", {"message": "sem cebola"}))
    assert status == 200 and body["response"]["sent"] is True
    assert body["response"]["id"] == "true_5511@c.us_M1"
    assert body["response"]["cart"]["items"] == []
    assert placed[0][0] == "5511@s.whatsapp.net" and placed[0][1][0]["quantity"] == 2
    (_dest, message), = s.client.sent
    order = message.orderMessage
    assert (order.orderID, order.token, order.sellerJID, order.message) == (
        "O1", "TK", "5511@s.whatsapp.net", "sem cebola")
    assert order.totalAmount1000 == 15000 and order.itemCount == 2


def test_an_empty_cart_is_not_sent(tmp_path):
    s = session(tmp_path, Buyer(profile_children=CATALOG_PROFILE))
    (status, body), = run(s, ("POST", "5511@c.us/submit", {}))
    assert (status, body["code"]) == (409, "cart_empty") and s.client.sent == []
