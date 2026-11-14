"""Business accounts and catalogs, read: `commerce/account` and
`commerce/catalog/:chatId` (WinZapp's own, commerceController.ts) and the
upstream reads get-products, get-product-by-id, get-collections and
get-business-profiles-products.

Everything is asked through the business IQs (biz_iq.py) on WinZapp's
neonize build. What WhatsApp Web decides from, read over CDP on 2026-10-26:

- a business account: WAWebMobilePlatforms.isSMB(); here, the business name
  whatsmeow keeps for one (neonize's Device.BussinessName);
- its own cart setting: profile_options.cart_enabled of its business profile;
- a seller's catalog: WAWebBusinessProfileUtils.hasCatalog (biz_iq.has_catalog);
- the sellers: the one-to-one chats whose contact is a business, which the
  contact store knows by its verified name.

The answers follow the routes they stand for. The pure functions are at the
top (tested in test_business.py). Not run against a real account.
"""
import asyncio
import logging
import time

from aiohttp import web

import biz_iq
import catalog_graphql
import commerce_cart
import commerce_common as cc
import raw_queries as rq

log = logging.getLogger("bridge")

SELLERS_TTL = 600          # seconds a list of business chats is reused


def account_without_commerce() -> dict:
    """The body of `commerce/account` when the engine cannot tell: no
    business, no cart option, no seller chats (what an older neonize build
    answers)."""
    return {"business": False, "cartEnabled": None, "sellers": []}


def account_body(business, cart_enabled, sellers) -> dict:
    return {"business": bool(business),
            "cartEnabled": cart_enabled if business and isinstance(cart_enabled, bool) else None,
            "sellers": sorted(set(sellers))}


def catalog_body(profile, products, cart) -> dict:
    """The body of `commerce/catalog/:chatId` (core/commerce.py parse_catalog)."""
    has = biz_iq.has_catalog(profile)
    return {"catalog": has, "cartEnabled": cc.cart_enabled(profile),
            "products": [cc.product_row(p) for p in products
                         if has and p["id"] and not p["is_hidden"]],
            "cart": cart}


def upstream_body(contact, session_name, data) -> dict:
    """WPPConnect's orderController/deviceController returnSucess."""
    return {"status": "Success", "response": {"message": "Information retrieved successfully.",
                                              "contact": contact, "session": session_name,
                                              "data": data}}


def read_catalog(client, jid, limit) -> tuple:
    """([products], next cursor) of a seller's catalog, by WhatsApp Web's
    GraphQL query; the old <product_catalog> IQ only when that fails (WhatsApp
    no longer answers the IQ). Runs on a thread."""
    try:
        return catalog_graphql.get_catalog(jid, limit)
    except catalog_graphql.GraphQLError as error:
        log.warning("catalog: GraphQL refused (%s), trying the IQ", error.code or "no code")
    return biz_iq.parse_catalog(rq.send_iq(client, biz_iq.catalog_query(jid, limit)))


def phone_of(text) -> str:
    """'5511999@c.us', '5511999' -> '5511999@s.whatsapp.net'; '' otherwise."""
    text = str(text or "").strip()
    user, _, server = text.partition("@")
    if not user.isdigit() or server not in ("", "c.us", "s.whatsapp.net"):
        return ""
    return f"{user}@s.whatsapp.net"


def _int(value, default, low=1, high=100):
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def register_routes(r, *, session, ok, jid_from_text, jid_text):
    """Wire the business routes to the aiohttp router `r`."""
    sellers_cache = {}

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def failure(code, status):
        return web.json_response({"status": "error", "code": code}, status=status)

    def ready(s):
        return s.client is not None and s.status == "CONNECTED" and rq.available(s.client)

    def own_business(s):
        try:
            return bool(getattr(s.client.get_me(), "BussinessName", ""))
        except Exception:
            return False

    def business_chats(s):
        """The one-to-one chats with a business, as the client names them."""
        cached = sellers_cache.get(s.name)
        if cached and time.time() - cached[0] < SELLERS_TTL:
            return cached[1]
        found = []
        for chat in s.db.chats():
            jid = chat["jid"]
            if not jid.endswith("@s.whatsapp.net"):
                continue
            try:
                info = s.client.contact.get_contact(jid_from_text(jid))
            except Exception:
                continue
            if (getattr(info, "BusinessName", "") or "").strip():
                found.append(cc.wpp_chat(jid))
        sellers_cache[s.name] = (time.time(), found)
        return found

    def account(s):
        business = own_business(s)
        cart_enabled = None
        if business:
            me = (s.me or "").split(":")[0].split("@")[0] + "@s.whatsapp.net"
            try:
                cart_enabled = cc.cart_enabled(cc.seller_profile(s.client, me))
            except Exception:
                cart_enabled = None
        return account_body(business, cart_enabled, business_chats(s))

    def catalog(s, chat):
        jid = cc.catalog_jid(s.client, chat, jid_from_text, jid_text)
        profile = cc.seller_profile(s.client, jid)
        products = []
        if biz_iq.has_catalog(profile):
            products, _after = read_catalog(s.client, jid, biz_iq.MAX_PRODUCTS)
        cart = commerce_cart.view(commerce_cart.load(s.folder).get(cc.whatsmeow_chat(chat)))
        return catalog_body(profile, products, cart)

    async def commerce_account(req):
        s = session(req)
        if not ready(s):
            return ok(status="success", response=account_without_commerce())
        try:
            return ok(status="success", response=await execute(account, s))
        except Exception:
            log.exception("commerce/account")
            return failure("commerce_unavailable", 503)

    async def commerce_catalog(req):
        s = session(req)
        chat = req.match_info["chatId"]
        if not cc.CHAT.fullmatch(chat):
            return failure("invalid_request", 400)
        if not ready(s):
            return failure("commerce_unavailable", 503)
        try:
            return ok(status="success", response=await execute(catalog, s, chat))
        except Exception:
            log.exception("commerce/catalog")
            return failure("commerce_unavailable", 503)

    async def upstream(req, label, run):
        """An upstream read: 401 without the number, 201 with the data."""
        s = session(req)
        phone = phone_of(req.query.get("phone"))
        if not phone:
            return web.json_response({"message": "Please send the contact number."}, status=401)
        if not ready(s):
            return web.json_response({"status": "Error", "message": "Disconnected"}, status=500)
        try:
            data = await execute(run, s, phone)
        except Exception as error:
            log.warning("%s: %s", label, type(error).__name__)
            return web.json_response({"status": "Error", "message": f"Error on {label}"},
                                     status=500)
        return web.json_response({"status": "success", "response": data}, status=201)

    async def get_products(req):
        limit = _int(req.query.get("qnt"), 10)
        return await upstream(req, "get products",
                              lambda s, jid: read_catalog(s.client, jid, limit)[0])

    async def get_product_by_id(req):
        product_id = str(req.query.get("id") or "")
        if not cc.PRODUCT.fullmatch(product_id):
            return web.json_response({"message": "Please send the contact number and productId."},
                                     status=401)
        return await upstream(req, "get product", lambda s, jid: cc.products_by_id(
            s.client, jid, [product_id]).get(product_id))

    async def get_collections(req):
        collections = _int(req.query.get("qnt"), 10)
        items = _int(req.query.get("max"), 10)
        return await upstream(req, "get collections", lambda s, jid: biz_iq.parse_collections(
            rq.send_iq(s.client, biz_iq.collections_query(jid, collections, items))))

    async def business_profiles_products(req):
        s = session(req)
        phone = phone_of(req.query.get("phone"))
        if not phone or not ready(s):
            return web.json_response({"status": "error", "message": "Error on get products"},
                                     status=400 if not phone else 500)
        try:
            products, _after = await execute(read_catalog, s.client, phone, biz_iq.MAX_PRODUCTS)
        except Exception as error:
            log.warning("get-business-profiles-products: %s", type(error).__name__)
            return web.json_response({"status": "error", "message": "Error on get products"},
                                     status=500)
        return web.json_response(upstream_body(req.query.get("phone"), s.name, [products]),
                                 status=201)

    r.add_get("/api/{tok}/commerce/account", commerce_account)
    r.add_get("/api/{tok}/commerce/catalog/{chatId}", commerce_catalog)
    r.add_get("/api/{tok}/get-products", get_products)
    r.add_get("/api/{tok}/get-product-by-id", get_product_by_id)
    r.add_get("/api/{tok}/get-collections", get_collections)
    r.add_get("/api/{tok}/get-business-profiles-products", business_profiles_products)
