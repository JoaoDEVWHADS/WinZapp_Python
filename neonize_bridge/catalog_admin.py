"""A business account's own catalog and profile: add-product, edit-product,
del-products, change-product-image, add-product-image, remove-product-image,
set-product-visibility, edit-business-profile and set-cart-enabled (the
upstream routes of WPPConnect's catalogController / businessController).

Sent as the business IQs biz_iq builds (product_catalog_add / _edit / _delete,
business_profile "delta"); a picture is uploaded first (media_upload.py) and
the product points at its URL. A picture already on WhatsApp's servers
(*.whatsapp.net) is kept by its URL, as Baileys does.

The collection routes (create-, edit-, del-collection) stay 501: WhatsApp Web
only loads that code on a Business account, so their stanzas could not be read
from a personal one, and no other client documents them.

`price` is the price in currency units ("88.90", "88,90" or 88.9); the
catalog keeps thousandths. The answers follow the upstream routes (201
{status, response}). The pure functions are at the top (tested in
test_catalog_admin.py). Not run against a real account (it needs a business).
"""
import asyncio
import logging
import re

from aiohttp import web

import biz_iq
import commerce_common as cc
import raw_queries as rq
from channels import image_from_text

log = logging.getLogger("bridge")

COLLECTION_REASON = ("the collection stanzas are not known: WhatsApp Web only loads them "
                     "on a Business account")
_MONEY = re.compile(r"\d+(?:[.,]\d{1,3})?\Z")


def price_thousandths(value):
    """Currency units -> thousandths; None when it is not a price."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value * 1000)) if value >= 0 else None
    text = str(value or "").strip()
    if not _MONEY.fullmatch(text):
        return None
    whole, _, decimals = text.replace(",", ".").partition(".")
    return int(whole) * 1000 + int((decimals + "000")[:3])


def product_fields(body) -> dict:
    """The fields biz_iq.product_node takes, from a route's body or `options`."""
    body = body if isinstance(body, dict) else {}
    fields = {}
    for key, name in (("name", "name"), ("description", "description"),
                      ("retailerId", "retailer_id"), ("url", "url"), ("currency", "currency")):
        if isinstance(body.get(key), str) and body[key].strip():
            fields[name] = body[key].strip()
    if body.get("priceAmount1000") is not None:
        fields["price"] = cc.amount(body["priceAmount1000"])
    elif body.get("price") not in (None, ""):
        fields["price"] = price_thousandths(body["price"])
    if "price" in fields and fields["price"] is None:
        raise ValueError("price must be an amount")
    hidden = body.get("isHidden", body.get("is_hidden"))
    if isinstance(hidden, bool):
        fields["is_hidden"] = hidden
    return fields


def image_urls(product) -> list:
    """The URLs of a product's pictures, the main one first."""
    def full(urls):
        found = {u.get("key"): u.get("value") for u in urls or ()}
        return found.get("full") or found.get("requested") or ""
    urls = [full(product.get("image_cdn_urls"))]
    urls += [full(more) for more in product.get("additional_image_cdn_urls") or ()]
    return [u for u in urls if u]


def own_jid(me) -> str:
    user = (me or "").split("@")[0].split(":")[0]
    return f"{user}@s.whatsapp.net" if user else ""


def register_routes(r, *, session, jid_from_text, jid_text):
    """Wire the routes to the aiohttp router `r`."""
    from groups_extra import photo_to_jpeg
    from media_upload import upload_product_image

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def refused(message, status=401):
        return web.json_response({"message": message}, status=status)

    def failed(label, status=500):
        return web.json_response({"status": "Error", "message": f"Error on {label}."},
                                 status=status)

    def answered(result):
        return web.json_response({"status": "success", "response": result}, status=201)

    def ready(s):
        return s.client is not None and s.status == "CONNECTED" and rq.available(s.client)

    def upload(s, base64_text):
        data = image_from_text(base64_text)
        if not data:
            raise ValueError("the picture is empty")
        return upload_product_image(s.client, photo_to_jpeg(data))

    def own_product(s, product_id):
        product = cc.products_by_id(s.client, own_jid(s.me), [product_id]).get(product_id)
        if product is None:
            raise LookupError("no such product")
        return product

    def edit(s, product_id, fields):
        response = rq.send_iq(s.client, biz_iq.product_write_query(
            "edit", biz_iq.product_node(fields, product_id)))
        return biz_iq.parse_product_write(response, "edit")

    async def body_of(req):
        try:
            body = await req.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    async def run(label, func, *args):
        try:
            return answered(await execute(func, *args))
        except (ValueError, LookupError) as error:
            return web.json_response({"status": "Error", "message": str(error)}, status=400)
        except Exception as error:
            log.warning("%s: %s", label, getattr(error, "code", "") or type(error).__name__)
            return failed(label)

    async def add_product(req):
        s, body = session(req), await body_of(req)
        if not body.get("name") or not body.get("image") or body.get("price") in (None, ""):
            return refused("name, price and image was not informed")
        if not ready(s):
            return failed("add product")

        def add():
            fields = product_fields(body)
            fields.setdefault("currency", "BRL")
            fields["is_hidden"] = bool(fields.get("is_hidden", False))
            fields["images"] = [upload(s, body["image"])]
            return biz_iq.parse_product_write(rq.send_iq(s.client, biz_iq.product_write_query(
                "add", biz_iq.product_node(fields))), "add")
        return await run("add product", add)

    async def edit_product(req):
        s, body = session(req), await body_of(req)
        if not body.get("id") or not isinstance(body.get("options"), dict):
            return refused("productId or options was not informed")
        if not ready(s):
            return failed("edit product")
        return await run("edit product", lambda: edit(s, str(body["id"]),
                                                      product_fields(body["options"])))

    async def del_products(req):
        s, body = session(req), await body_of(req)
        ids = body.get("id")
        ids = ids if isinstance(ids, list) else [ids] if ids else []
        if not ids:
            return refused("products Id was not informed")
        if not ready(s):
            return failed("delete product")

        def delete():
            deleted = biz_iq.parse_deleted(rq.send_iq(s.client, biz_iq.product_delete_query(
                [str(i) for i in ids])))
            return {"productsIds": body.get("id"), "status": 200 if deleted else 500}
        return await run("delete product", delete)

    async def image_route(req, label, change):
        s, body = session(req), await body_of(req)
        if not body.get("id") or not (body.get("base64") or "index" in body):
            return refused("productId and base64 was not informed")
        if not ready(s):
            return failed(label)

        def apply():
            product = own_product(s, str(body["id"]))
            urls = change(s, image_urls(product), body)
            if not urls:
                raise ValueError("a product keeps at least one picture")
            return edit(s, product["id"], {"images": urls})
        return await run(label, apply)

    async def change_product_image(req):
        return await image_route(req, "change product image",
                                 lambda s, urls, body: [upload(s, body["base64"])] + urls[1:])

    async def add_product_image(req):
        return await image_route(req, "add product image",
                                 lambda s, urls, body: urls + [upload(s, body["base64"])])

    async def remove_product_image(req):
        def remove(s, urls, body):
            index = body.get("index")
            if type(index) is not int or not 0 <= index < len(urls) - 1:
                raise ValueError("index is not an additional picture of the product")
            # WPPConnect's index counts the additional pictures only
            return urls[:1] + [u for i, u in enumerate(urls[1:]) if i != index]
        return await image_route(req, "remove product image", remove)

    async def set_product_visibility(req):
        s, body = session(req), await body_of(req)
        value = body.get("value")
        if not body.get("id") or not isinstance(value, bool):
            return refused("product id or value (false, true) was not informed")
        if not ready(s):
            return failed("set product visibility")
        # `value` is the visibility: false hides the product
        return await run("set product visibility", lambda: edit(
            s, str(body["id"]), {"is_hidden": not value}))

    async def edit_business_profile(req):
        s, body = session(req), await body_of(req)
        changes = {k: body[k] for k in ("address", "email", "description")
                   if isinstance(body.get(k), str)}
        websites = body.get("website")
        if isinstance(websites, str):
            websites = [websites]
        if isinstance(websites, list):
            changes["websites"] = [w.get("url") if isinstance(w, dict) else str(w)
                                   for w in websites if w]
        if not changes:
            return refused("Nothing to change in the business profile", 400)
        if not ready(s):
            return failed("edit business profile")

        def apply():
            rq.send_iq(s.client, biz_iq.business_profile_edit_query(changes))
            return cc.seller_profile(s.client, own_jid(s.me))
        return await run("edit business profile", apply)

    async def set_cart_enabled(req):
        s, body = session(req), await body_of(req)
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return refused("enabled (true or false) was not informed")
        if not ready(s):
            return failed("update cart enabled")

        def apply():
            rq.send_iq(s.client, biz_iq.business_profile_edit_query({"cart_enabled": enabled}))
            return {"cartEnabled": cc.cart_enabled(cc.seller_profile(s.client, own_jid(s.me)))}
        return await run("update cart enabled", apply)

    async def collections_unknown(req):
        return web.json_response({"status": "error", "code": "collections_unsupported",
                                  "message": COLLECTION_REASON}, status=501)

    r.add_post("/api/{tok}/add-product", add_product)
    r.add_post("/api/{tok}/edit-product", edit_product)
    r.add_post("/api/{tok}/del-products", del_products)
    r.add_post("/api/{tok}/change-product-image", change_product_image)
    r.add_post("/api/{tok}/add-product-image", add_product_image)
    r.add_post("/api/{tok}/remove-product-image", remove_product_image)
    r.add_post("/api/{tok}/set-product-visibility", set_product_visibility)
    r.add_post("/api/{tok}/edit-business-profile", edit_business_profile)
    r.add_post("/api/{tok}/set-cart-enabled", set_cart_enabled)
    for route in ("create-collection", "edit-collection", "del-collection"):
        r.add_post("/api/{tok}/" + route, collections_unknown)
