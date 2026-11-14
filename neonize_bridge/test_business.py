"""Business routes: what the client reads from `commerce/account` and
`commerce/catalog`, and the upstream catalog reads."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import business
import catalog_graphql
import raw_queries
from test_biz_iq import product, t

CLIENT = Path(__file__).resolve().parents[1] / "client"


def client_commerce():
    sys.path.insert(0, str(CLIENT))
    try:
        from core import commerce
    finally:
        sys.path.remove(str(CLIENT))
    return commerce


def test_account_without_commerce_is_read_by_the_client_as_without_commerce_features():
    account = client_commerce().parse_account(business.account_without_commerce())
    assert account.business is False
    assert account.cart_enabled is None
    assert account.sellers == frozenset()


def test_each_call_returns_a_new_body():
    business.account_without_commerce()["sellers"].append("x@c.us")
    assert business.account_without_commerce()["sellers"] == []


def test_an_account_body_the_client_reads():
    account = client_commerce().parse_account(
        business.account_body(True, False, ["5511@c.us", "5511@c.us", "99@lid"]))
    assert account.business is True and account.cart_enabled is False
    assert account.sellers == frozenset({"5511@c.us", "99@lid"})
    assert business.account_body(False, True, [])["cartEnabled"] is None


def test_a_catalog_body_the_client_reads():
    profile = {"catalogStatus": "catalog_exists", "profileOptions": {"cartEnabled": True}}
    import biz_iq
    products = [biz_iq.parse_product(product("1")), biz_iq.parse_product(product("2", hidden=True))]
    cart = {"items": [], "itemCount": 0, "total": None, "currency": "", "message": ""}
    catalog = client_commerce().parse_catalog(business.catalog_body(profile, products, cart))
    assert catalog.has_catalog and catalog.cart_enabled
    assert [p.id for p in catalog.products] == ["1"] and catalog.products[0].price == 7500
    assert business.catalog_body({}, products, cart)["products"] == []


def test_phone_of():
    assert business.phone_of("5511999@c.us") == "5511999@s.whatsapp.net"
    assert business.phone_of("5511999") == "5511999@s.whatsapp.net"
    assert business.phone_of("1203@g.us") == "" and business.phone_of("") == ""


class Client:
    """Answers the business IQs from canned nodes."""

    def __init__(self, business_name="", profile_children=(), products=()):
        self.business_name = business_name
        self.profile_children = list(profile_children)
        self.products = list(products)
        self.queries = []
        self.contact = N(get_contact=lambda jid: N(BusinessName="Loja" if "5511" in str(jid)
                                                   else ""))

    def get_me(self):
        return N(BussinessName=self.business_name)

    def get_pn_from_lid(self, jid):
        return "5511@s.whatsapp.net"

    def send_iq(self, query):
        self.queries.append(query)
        tag = query["content"][0]["tag"]
        if tag == "business_profile":
            return {"node": t("iq", children=[t("business_profile", children=[
                t("profile", attrs={"jid": "5511@s.whatsapp.net"},
                  children=self.profile_children)])])}
        if tag == "product_catalog":
            return {"node": t("iq", children=[t("product_catalog", children=self.products)])}
        if tag == "product_list":
            return {"node": t("iq", children=[t("product_list", children=self.products)])}
        if tag == "collections":
            return {"node": t("iq", children=[t("collections")])}
        raise AssertionError(tag)


CATALOG_PROFILE = [t("profile_options", children=[t("commerce_experience", "catalog"),
                                                   t("cart_enabled", "true")])]


@pytest.fixture(autouse=True)
def raw(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))


@pytest.fixture(autouse=True)
def graphql(monkeypatch):
    """No network: the catalog GraphQL refuses unless a test answers it, so
    these tests read the catalog by the IQ the bridge falls back to."""
    asked = []

    def refuse(jid, limit, after=""):
        asked.append((jid, limit))
        raise catalog_graphql.GraphQLError("offline", 500)
    monkeypatch.setattr(catalog_graphql, "get_catalog", refuse)
    return asked


def session(tmp_path, client):
    db = N(chats=lambda: [{"jid": "5511@s.whatsapp.net"}, {"jid": "77@s.whatsapp.net"},
                          {"jid": "1203@g.us"}])
    return N(name="acc", client=client, status="CONNECTED", folder=str(tmp_path), db=db,
             me="5599:3@s.whatsapp.net")


def run(s, method, path):
    async def main():
        app = web.Application()
        business.register_routes(app.router, session=lambda req: s,
                                 ok=lambda **kw: web.json_response(kw),
                                 jid_from_text=lambda text: text, jid_text=str)
        async with TestClient(TestServer(app)) as http:
            resp = await http.request(method, "/api/tok/" + path)
            return resp.status, await resp.json()
    return asyncio.run(main())


def test_commerce_account_of_a_business(tmp_path):
    s = session(tmp_path, Client("Padaria", CATALOG_PROFILE))
    status, body = run(s, "GET", "commerce/account")
    assert status == 200
    assert body["response"] == {"business": True, "cartEnabled": True, "sellers": ["5511@c.us"]}


def test_commerce_account_without_raw_queries_says_no_commerce(tmp_path):
    s = session(tmp_path, N())
    assert run(s, "GET", "commerce/account")[1]["response"] == \
        business.account_without_commerce()


def test_commerce_catalog_reads_profile_products_and_cart(tmp_path):
    s = session(tmp_path, Client(profile_children=CATALOG_PROFILE,
                                 products=[product("1"), product("2", hidden=True)]))
    status, body = run(s, "GET", "commerce/catalog/5511@c.us")
    assert status == 200
    catalog = client_commerce().parse_catalog(body["response"])
    assert [p.id for p in catalog.products] == ["1"] and catalog.cart.items == ()
    assert s.client.queries[0]["content"][0]["content"][0]["attrs"] == {
        "jid": {"jid": "5511@s.whatsapp.net"}}


def test_the_catalog_comes_from_whatsapp_web_s_graphql_query(tmp_path, monkeypatch):
    def answer(jid, limit, after=""):
        assert jid == "5511@s.whatsapp.net"
        return [catalog_graphql.product_from_graphql(
            {"id": "9", "name": "Bolo", "price": "12000", "currency": "BRL"})], ""
    monkeypatch.setattr(catalog_graphql, "get_catalog", answer)
    s = session(tmp_path, Client(profile_children=CATALOG_PROFILE, products=[product("1")]))
    status, body = run(s, "GET", "commerce/catalog/5511@c.us")
    assert status == 200
    assert [p.id for p in client_commerce().parse_catalog(body["response"]).products] == ["9"]
    assert [q["content"][0]["tag"] for q in s.client.queries] == ["business_profile"]


def test_a_seller_without_catalog_shows_none(tmp_path):
    s = session(tmp_path, Client(products=[product("1")]))
    body = run(s, "GET", "commerce/catalog/5511@c.us")[1]
    assert body["response"]["catalog"] is False and body["response"]["products"] == []
    assert [q["content"][0]["tag"] for q in s.client.queries] == ["business_profile"]


def test_upstream_reads(tmp_path):
    s = session(tmp_path, Client(products=[product("1")]))
    status, body = run(s, "GET", "get-products?phone=5511@c.us&qnt=5")
    assert status == 201 and [p["id"] for p in body["response"]] == ["1"]
    status, body = run(s, "GET", "get-product-by-id?phone=5511&id=1")
    assert status == 201 and body["response"]["name"] == "Pão"
    assert run(s, "GET", "get-collections?phone=5511")[1]["response"] == []
    status, body = run(s, "GET", "get-business-profiles-products?phone=5511@c.us")
    assert status == 201 and body["status"] == "Success"
    assert [p["id"] for p in body["response"]["data"][0]] == ["1"]
    assert run(s, "GET", "get-products")[0] == 401
