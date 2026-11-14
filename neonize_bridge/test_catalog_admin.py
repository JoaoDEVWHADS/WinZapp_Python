"""A business account's own catalog and profile."""
import asyncio
import base64
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import catalog_admin as ca
import media_upload
import raw_queries
from test_biz_iq import product, t


@pytest.mark.parametrize("value,expected", [
    ("88.90", 88900), ("88,9", 88900), (88.9, 88900), (12, 12000), ("0", 0), ("1.234", 1234),
    ("abc", None), (-1, None), (True, None), ("1.2345", None)])
def test_price_thousandths(value, expected):
    assert ca.price_thousandths(value) == expected


def test_product_fields():
    fields = ca.product_fields({"name": " Pão ", "price": "7,50", "currency": "BRL",
                                "retailerId": "SKU", "isHidden": True, "url": ""})
    assert fields == {"name": "Pão", "price": 7500, "currency": "BRL", "retailer_id": "SKU",
                      "is_hidden": True}
    assert ca.product_fields({"priceAmount1000": 7500})["price"] == 7500
    with pytest.raises(ValueError):
        ca.product_fields({"price": "muito"})


def test_image_urls_main_first():
    import biz_iq
    p = biz_iq.parse_product(product(images=3))
    assert ca.image_urls(p) == ["full0", "full1", "full2"]
    assert ca.own_jid("5599:3@s.whatsapp.net") == "5599@s.whatsapp.net"


class Owner:
    def __init__(self, images=2):
        self.queries = []
        self.images = images

    def send_iq(self, query):
        self.queries.append(query)
        tag = query["content"][0]["tag"]
        if tag == "product_list":
            return {"node": t("iq", children=[t("product_list", children=[
                product("1", images=self.images)])])}
        if tag in ("product_catalog_add", "product_catalog_edit"):
            node = query["content"][0]["content"][0]
            pid = next((c["content"] for c in node.get("content", []) if c["tag"] == "id"), "new")
            return {"node": t("iq", children=[t(tag, children=[product(pid)])])}
        if tag == "product_catalog_delete":
            return {"node": t("iq", children=[t(tag, attrs={"deleted_count": "1"})])}
        if tag == "business_profile":
            if query["type"] == "set":
                return {"node": t("iq")}
            return {"node": t("iq", children=[t("business_profile", children=[t(
                "profile", attrs={"jid": "5599@s.whatsapp.net"}, children=[
                    t("profile_options", children=[t("cart_enabled", "true")])])])])}
        raise AssertionError(tag)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))
    monkeypatch.setattr(media_upload, "upload_product_image",
                        lambda client, data: "https://mmg.whatsapp.net/new")
    import groups_extra
    monkeypatch.setattr(groups_extra, "photo_to_jpeg", lambda data: data)


def run(s, path, body):
    async def main():
        app = web.Application()
        ca.register_routes(app.router, session=lambda req: s, jid_from_text=lambda x: x,
                           jid_text=str)
        async with TestClient(TestServer(app)) as http:
            resp = await http.post("/api/tok/" + path, json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


def session(client=None):
    return N(client=client or Owner(), status="CONNECTED", me="5599@s.whatsapp.net")


def edited(s):
    node = s.client.queries[-1]["content"][0]["content"][0]
    return node


PNG = base64.b64encode(b"img").decode()


def test_add_product_uploads_the_picture_first():
    s = session()
    status, body = run(s, "add-product", {"name": "Pão", "image": PNG, "price": "7.5"})
    assert status == 201 and body["response"]["id"] == "new"
    node = edited(s)
    assert s.client.queries[-1]["content"][0]["tag"] == "product_catalog_add"
    tags = {c["tag"]: c for c in node["content"]}
    assert tags["price"]["content"] == "7500" and tags["currency"]["content"] == "BRL"
    assert tags["media"]["content"][0]["content"][0]["content"] == "https://mmg.whatsapp.net/new"
    assert run(s, "add-product", {"name": "Pão"})[0] == 401


def test_edit_delete_and_visibility():
    s = session()
    assert run(s, "edit-product", {"id": "1", "options": {"name": "Pão francês"}})[0] == 201
    assert edited(s)["content"][1] == {"tag": "name", "content": "Pão francês"}
    status, body = run(s, "del-products", {"id": ["1"]})
    assert body["response"] == {"productsIds": ["1"], "status": 200}
    run(s, "set-product-visibility", {"id": "1", "value": False})
    assert edited(s)["attrs"] == {"is_hidden": "true"}
    assert run(s, "set-product-visibility", {"id": "1"})[0] == 401


def test_pictures_change_add_and_remove():
    s = session(Owner(images=2))
    run(s, "change-product-image", {"id": "1", "base64": PNG})
    urls = [i["content"][0]["content"] for i in
            next(c for c in edited(s)["content"] if c["tag"] == "media")["content"]]
    assert urls == ["https://mmg.whatsapp.net/new", "full1"]
    run(s, "add-product-image", {"id": "1", "base64": PNG})
    urls = [i["content"][0]["content"] for i in
            next(c for c in edited(s)["content"] if c["tag"] == "media")["content"]]
    assert urls == ["full0", "full1", "https://mmg.whatsapp.net/new"]
    run(s, "remove-product-image", {"id": "1", "index": 0})
    urls = [i["content"][0]["content"] for i in
            next(c for c in edited(s)["content"] if c["tag"] == "media")["content"]]
    assert urls == ["full0"]
    assert run(s, "remove-product-image", {"id": "1", "index": 5})[0] == 400


def test_business_profile_and_cart_setting():
    s = session()
    status, body = run(s, "edit-business-profile", {"description": "Padaria",
                                                    "website": ["https://a"]})
    assert status == 201 and body["response"]["profileOptions"]["cartEnabled"] is True
    sent = [q for q in s.client.queries if q["type"] == "set"][0]
    assert [c["tag"] for c in sent["content"][0]["content"]] == ["description", "website"]
    status, body = run(s, "set-cart-enabled", {"enabled": True})
    assert status == 201 and body["response"] == {"cartEnabled": True}
    assert run(s, "set-cart-enabled", {"enabled": "yes"})[0] == 401


def test_collections_stay_unsupported():
    for route in ("create-collection", "edit-collection", "del-collection"):
        status, body = run(session(), route, {"name": "x"})
        assert status == 501 and body["code"] == "collections_unsupported"
