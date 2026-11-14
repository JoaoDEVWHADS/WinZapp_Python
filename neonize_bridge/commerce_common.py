"""What the commerce routes share: the forms of a seller's address, its
business profile and its products, read through biz_iq.

A chat arrives as WhatsApp Web names it ('<digits>@c.us' or '<digits>@lid');
the catalog and the profile are asked for under the number
('<digits>@s.whatsapp.net'), or the LID when no number is known
(WAWebGetFormattedCatalogJid). All amounts are thousandths of the currency.
"""
import re

import biz_iq
import catalog_graphql
import msgmap
import raw_queries as rq

CHAT = re.compile(r"\d+@(c\.us|lid)\Z")
PRODUCT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MESSAGE = re.compile(r"(true|false)_\d+@(c\.us|lid)_[A-Za-z0-9]{8,64}\Z")
QUANTITY_LIMIT = 99          # WAWebBizCartConstants.CART_ITEM_MAX_QUANTITY
NOTE_LIMIT = 1024


class CommerceRefused(Exception):
    """A refusal with one of the commerce routes' codes."""

    STATUS = {"invalid_request": 400, "not_business": 403, "own_order": 403,
              "not_an_order": 404, "cart_disabled": 409, "product_unavailable": 409,
              "cart_empty": 409, "already_confirmed": 409, "cannot_confirm": 409,
              "confirm_unconfirmed": 502, "commerce_unavailable": 503}

    def __init__(self, code, cart=None):
        super().__init__(code)
        self.code = code
        self.cart = cart

    @property
    def status(self):
        return self.STATUS.get(self.code, 503)


def amount(value):
    """A non-negative integer amount, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def whatsmeow_chat(chat) -> str:
    """'<digits>@c.us' -> '<digits>@s.whatsapp.net'; a LID stays."""
    return msgmap.jid_whatsmeow(chat)


def message_key(serialized) -> tuple:
    """(from me, chat as WhatsApp Web names it, id) of 'true_<chat>_<id>'."""
    mine, chat, msg_id = serialized.split("_", 2)
    return mine == "true", chat, msg_id


def catalog_jid(client, chat, jid_from_text, jid_text) -> str:
    """The address a seller's catalog and profile are asked for under."""
    jid = whatsmeow_chat(chat)
    if jid.endswith("@lid"):
        try:
            phone = jid_text(client.get_pn_from_lid(jid_from_text(jid)))
        except Exception:
            phone = ""
        if phone.endswith("@s.whatsapp.net"):
            return phone
    return jid


def seller_profile(client, jid) -> dict:
    """The business profile of `jid` ({} when it has none). Runs on a thread."""
    profiles = biz_iq.parse_business_profiles(
        rq.send_iq(client, biz_iq.business_profile_query([jid])))
    return profiles[0] if profiles else {}


def cart_enabled(profile) -> bool:
    return (profile.get("profileOptions") or {}).get("cartEnabled") is True


def products_by_id(client, jid, ids) -> dict:
    """{id: product} of the products the catalog still has. Runs on a thread."""
    if not ids:
        return {}
    try:
        products = catalog_graphql.get_products(jid, list(ids))
    except catalog_graphql.GraphQLError:
        # WhatsApp Web's GraphQL query first; the old IQ, which WhatsApp no
        # longer answers, only when it fails (business.read_catalog).
        products = biz_iq.parse_product_list(
            rq.send_iq(client, biz_iq.product_list_query(jid, list(ids))))
    return {p["id"]: p for p in products}


def product_row(product) -> dict:
    """A product as the client's catalog reads it (core/commerce.py)."""
    return {"id": product["id"], "name": product["name"],
            "description": product["description"], "price": amount(product["price"]),
            "currency": product["currency"] or "",
            "available": product["availability"] in ("in stock", "unknown")}


def wpp_chat(jid) -> str:
    """'<digits>@s.whatsapp.net' -> '<digits>@c.us' (how the client names chats)."""
    return msgmap.jid_wpp(jid)


def chat_title(db, jid) -> str:
    """The chat's name as the account knows it: the saved name, else the nickname."""
    try:
        found = db.contact_of(jid) or {}
    except Exception:
        return ""
    return found.get("name") or found.get("pushname") or ""
