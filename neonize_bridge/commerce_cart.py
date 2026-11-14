"""A buyer's carts and sending one as an order (the routes commerce/cart/..
of WinZapp's WPPConnect, commerceController.ts).

A cart lives on the device, as in WhatsApp Web (WAWebSchemaCart: a local
table, WAWebBizCartBridge.updateCart): here `carts.json` in the session
folder, one cart per seller, each item with the price the catalog had when it
was added. Submitting it does what WhatsApp Web does (WPP.cart.submit, read
over CDP on 2026-10-26):

1. the order is placed through the catalog GraphQL endpoint
   (catalog_graphql.place_order), which answers its id, token and price;
2. an OrderMessage goes to the seller: orderID, token, sellerJID (the
   seller's number, @s.whatsapp.net), orderTitle (the chat's name), status
   INQUIRY, surface CATALOG, messageVersion 2, itemCount, message (the
   buyer's note), totalAmount1000 and totalCurrencyCode;
3. the cart is emptied.

Whether the seller takes carts is its own profile setting (cart_enabled); a
cart is neither filled nor sent to a seller that turned it off. The pure
functions are at the top (tested in test_commerce_cart.py). Not run against a
real account.
"""
import asyncio
import json
import logging
import os
import threading

from aiohttp import web

import catalog_graphql
import commerce_common as cc
import raw_queries as rq

log = logging.getLogger("bridge")

FILE = "carts.json"
INQUIRY = 1
SURFACE_CATALOG = 1
ORDER_MESSAGE_VERSION = 2


# ---------------------------------------------------------------- the store
def load(folder) -> dict:
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(folder, carts) -> None:
    path = os.path.join(folder, FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(carts, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def view(cart) -> dict:
    """The cart as the client reads it: items, itemCount, total, currency."""
    items = [dict(i) for i in (cart or {}).get("items") or ()]
    priced = [i for i in items if cc.amount(i.get("price")) is not None]
    total = sum(i["price"] * i["quantity"] for i in priced) if items and len(priced) == len(items) \
        else None
    return {"items": items, "itemCount": sum(i["quantity"] for i in items), "total": total,
            "currency": items[0].get("currency", "") if items else "",
            "message": (cart or {}).get("message", "")}


def set_item(cart, product, quantity) -> dict:
    """The cart with `quantity` of `product` (a catalog product)."""
    cart = {"items": [dict(i) for i in (cart or {}).get("items") or ()],
            "message": (cart or {}).get("message", "")}
    item = {"id": product["id"], "name": product["name"], "quantity": quantity,
            "price": cc.amount(product["price"]), "currency": product["currency"] or ""}
    for index, existing in enumerate(cart["items"]):
        if existing["id"] == product["id"]:
            cart["items"][index] = item
            break
    else:
        cart["items"].append(item)
    return cart


def remove_item(cart, product_id) -> dict:
    return {"items": [dict(i) for i in (cart or {}).get("items") or () if i["id"] != product_id],
            "message": (cart or {}).get("message", "")}


def order_message_fields(order, cart, seller_phone, title, note) -> dict:
    """The OrderMessage that sends the cart (WPP.cart.submit)."""
    fields = {"orderID": order["id"], "token": order["token"], "sellerJID": seller_phone,
              "orderTitle": title or "", "status": INQUIRY, "surface": SURFACE_CATALOG,
              "messageVersion": ORDER_MESSAGE_VERSION,
              "itemCount": view(cart)["itemCount"], "message": note or cart.get("message", "")}
    if order.get("total"):
        fields["totalAmount1000"] = order["total"]
    if order.get("currency"):
        fields["totalCurrencyCode"] = order["currency"]
    return fields


def register_routes(r, *, session, jid_from_text, jid_text, destination_of, store_sent):
    """Wire the cart routes to the aiohttp router `r`."""
    lock = threading.Lock()

    def failure(error):
        body = {"status": "error", "code": error.code}
        if error.cart is not None:
            body["response"] = {"cart": error.cart}
        return web.json_response(body, status=error.status)

    def ready(s):
        if s.client is None or s.status != "CONNECTED" or not rq.available(s.client):
            raise cc.CommerceRefused("commerce_unavailable")

    def chat_of(req):
        chat = req.match_info["chatId"]
        if not cc.CHAT.fullmatch(chat):
            raise cc.CommerceRefused("invalid_request")
        return chat

    def seller(s, chat):
        return cc.catalog_jid(s.client, chat, jid_from_text, jid_text)

    def change(s, chat, update):
        """Applies `update(cart) -> cart` to the chat's cart, kept."""
        with lock:
            carts = load(s.folder)
            key = cc.whatsmeow_chat(chat)
            cart = update(carts.get(key) or {"items": [], "message": ""})
            if cart["items"] or cart.get("message"):
                carts[key] = cart
            else:
                carts.pop(key, None)
            save(s.folder, carts)
        return view(cart)

    def cart_of(s, chat):
        return view(load(s.folder).get(cc.whatsmeow_chat(chat)))

    def cart_set(s, chat, product_id, quantity):
        ready(s)
        jid = seller(s, chat)
        if not cc.cart_enabled(cc.seller_profile(s.client, jid)):
            raise cc.CommerceRefused("cart_disabled")
        product = cc.products_by_id(s.client, jid, [product_id]).get(product_id)
        if (product is None or product["is_hidden"] or product["availability"] == "out of stock"
                or quantity > product["max_available"]):
            raise cc.CommerceRefused("product_unavailable", cart_of(s, chat))
        return {"cart": change(s, chat, lambda cart: set_item(cart, product, quantity))}

    def cart_submit(s, chat, note):
        ready(s)
        jid = seller(s, chat)
        if not cc.cart_enabled(cc.seller_profile(s.client, jid)):
            raise cc.CommerceRefused("cart_disabled")
        with lock:
            cart = load(s.folder).get(cc.whatsmeow_chat(chat))
        if not cart or not cart.get("items"):
            raise cc.CommerceRefused("cart_empty")
        order = catalog_graphql.place_order(jid, cart["items"])
        from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message, OrderMessage
        title = cc.chat_title(s.db, cc.whatsmeow_chat(chat))
        message = Message(orderMessage=OrderMessage(**order_message_fields(
            order, cart, jid if jid.endswith("@s.whatsapp.net") else cc.whatsmeow_chat(chat),
            title, note)))
        destination = destination_of(chat)
        resp = s.client.send_message(destination, message)
        change(s, chat, lambda _cart: {"items": [], "message": ""})
        return destination, resp

    async def run(req, func, *args):
        try:
            return await asyncio.get_running_loop().run_in_executor(None, func, *args)
        except cc.CommerceRefused:
            raise
        except Exception:
            log.exception("commerce cart")
            raise cc.CommerceRefused("commerce_unavailable")

    async def json_body(req):
        try:
            body = await req.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    def ok(response):
        return web.json_response({"status": "success", "response": response})

    async def cart(req):
        try:
            s, chat = session(req), chat_of(req)
            return ok({"cart": cart_of(s, chat)})
        except cc.CommerceRefused as e:
            return failure(e)

    async def cart_set_route(req):
        try:
            s, chat, body = session(req), chat_of(req), await json_body(req)
            product_id, quantity = body.get("productId"), body.get("quantity")
            if (not isinstance(product_id, str) or not cc.PRODUCT.fullmatch(product_id)
                    or type(quantity) is not int or not 1 <= quantity <= cc.QUANTITY_LIMIT):
                raise cc.CommerceRefused("invalid_request")
            return ok(await run(req, cart_set, s, chat, product_id, quantity))
        except cc.CommerceRefused as e:
            return failure(e)

    async def cart_remove(req):
        try:
            s, chat, body = session(req), chat_of(req), await json_body(req)
            product_id = body.get("productId")
            if not isinstance(product_id, str) or not cc.PRODUCT.fullmatch(product_id):
                raise cc.CommerceRefused("invalid_request")
            return ok({"cart": change(s, chat, lambda c: remove_item(c, product_id))})
        except cc.CommerceRefused as e:
            return failure(e)

    async def cart_clear(req):
        try:
            s, chat = session(req), chat_of(req)
            return ok({"cart": change(s, chat, lambda _c: {"items": [], "message": ""})})
        except cc.CommerceRefused as e:
            return failure(e)

    async def cart_submit_route(req):
        try:
            s, chat, body = session(req), chat_of(req), await json_body(req)
            note = body.get("message")
            note = "" if note in (None, "") else note
            if not isinstance(note, str) or len(note) > cc.NOTE_LIMIT:
                raise cc.CommerceRefused("invalid_request")
            destination, resp = await run(req, cart_submit, s, chat, note)
        except cc.CommerceRefused as e:
            return failure(e)
        sent = json.loads(store_sent(s, destination, resp).text)
        serial = sent["response"][0]["id"]
        return ok({"sent": True, "id": serial, "cart": cart_of(s, chat)})

    r.add_get("/api/{tok}/commerce/cart/{chatId}", cart)
    r.add_post("/api/{tok}/commerce/cart/{chatId}/set", cart_set_route)
    r.add_post("/api/{tok}/commerce/cart/{chatId}/remove", cart_remove)
    r.add_post("/api/{tok}/commerce/cart/{chatId}/clear", cart_clear)
    r.add_post("/api/{tok}/commerce/cart/{chatId}/submit", cart_submit_route)
    return {"cart_of": cart_of}
