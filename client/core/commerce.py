"""Carts and orders: the contracts with the server and what a row says.

The cart is the buyer's: any account, in a chat with a business that has a
catalog and takes carts. Accepting, declining and updating an order, and
creating one for a customer, are a WhatsApp Business account's. Who may do
what is decided by the server (commerceController.ts), which reads it where
WhatsApp Web itself does; nothing here guesses it.

Every amount is an integer in thousandths of the currency unit, as WhatsApp
sends it (7500 is 7.50).

Pure: no wx, no main window.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

from core.api_client import api_get, api_post

ORDER_MESSAGE_TYPE = "orderMessage"
# The seller's follow-ups to an order: its details with the amount to pay, and
# each change of status. WhatsApp sends them as interactive "native flow"
# messages whose only button carries the data as JSON.
ORDER_UPDATE_MESSAGE_TYPE = "orderUpdateMessage"
ORDER_FLOWS = frozenset({"order_details", "order_status", "payment_info", "payment_status",
                         # The buyer's answer: "confirm" for an order paid outside
                         # the app (api_patches orderConfirmController.ts).
                         "payment_method"})
PAYMENT_METHODS = ("confirm", "payment_instruction")
# One item of a business's catalog, sent as a message.
PRODUCT_MESSAGE_TYPE = "productMessage"

# WhatsApp's own lists (WAWebOrderStatus / the library's enums), in the order
# an order goes through them.
ORDER_STATUSES = (
    "pending", "confirmed", "processing", "payment_requested", "preparing_to_ship",
    "partially_shipped", "shipped", "out_for_delivery", "delivered", "completed",
    "delayed", "canceled", "failed", "refunded",
)
PAYMENT_STATUSES = ("pending", "captured", "failed", "canceled")
# The order message's own state: 1 asked, 2 accepted, 3 declined.
INQUIRY, ACCEPTED, DECLINED = 1, 2, 3

QUANTITY_LIMIT = 99   # WhatsApp Web's CART_ITEM_MAX_QUANTITY
NOTE_LIMIT = 1024
_CHAT = re.compile(r"\d+@(?:c\.us|lid)")
_PRODUCT = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SYMBOLS = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£", "PLN": "zł", "TRY": "₺", "RON": "lei"}


class CommerceError(Exception):
    """A refusal with the server's own code, or "unavailable"."""

    def __init__(self, code="unavailable", cart=None):
        super().__init__(code)
        self.code = code
        self.cart = cart  # the cart as it is, when the refusal carried it


@dataclass(frozen=True)
class Account:
    business: bool
    cart_enabled: bool | None   # the account's own catalog setting; None unless business
    sellers: frozenset          # chats with a business, in WhatsApp's own id forms


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    description: str
    price: int | None
    currency: str
    available: bool


@dataclass(frozen=True)
class CartItem:
    id: str
    name: str
    quantity: int
    price: int | None
    currency: str


@dataclass(frozen=True)
class Cart:
    items: tuple
    total: int | None
    currency: str

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items)


@dataclass(frozen=True)
class Catalog:
    has_catalog: bool
    cart_enabled: bool
    products: tuple
    cart: Cart


@dataclass(frozen=True)
class Order:
    mine: bool
    status: int | None
    note: str
    items: tuple                # CartItem: what was ordered
    subtotal: int | None
    total: int | None
    currency: str
    can_answer: bool            # a business may accept or decline it
    can_update: bool            # a business may send a new status for it


# ── amounts ────────────────────────────────────────────────────────────────

def _amount(value):
    return value if type(value) is int and value >= 0 else None


def format_money(amount, currency, decimal_separator="."):
    """ "R$ 7,50" for 7500 BRL; the currency code when it has no usual sign."""
    if _amount(amount) is None:
        return ""
    whole, cents = divmod((amount + 5) // 10, 100)
    number = f"{whole}{decimal_separator}{cents:02d}"
    sign = _SYMBOLS.get(currency, currency if isinstance(currency, str) else "")
    return f"{sign} {number}".strip()


def parse_money(text):
    """Thousandths from what a person types ("12", "12,5", "1.234,56");
    None when it is not an amount."""
    text = text.strip().replace(" ", "") if isinstance(text, str) else ""
    # Groups of thousands share one separator, and the decimals use the other:
    # "12,345,6" is not an amount anyone meant.
    if not re.fullmatch(
            r"\d{1,3}(?:(?P<group>[.,])\d{3}(?:(?P=group)\d{3})*)(?:(?!(?P=group))[.,]\d{1,2})?"
            r"|\d+(?:[.,]\d{1,2})?", text):
        return None
    cut = max(text.rfind(","), text.rfind("."))
    # A last group of exactly three digits is thousands, not cents.
    if cut >= 0 and len(text) - cut - 1 != 3:
        whole, cents = text[:cut], text[cut + 1:]
    else:
        whole, cents = text, ""
    whole = re.sub(r"[.,]", "", whole) or "0"
    return int(whole) * 1000 + int((cents + "00")[:2]) * 10


# ── answers ────────────────────────────────────────────────────────────────

def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _items(rows):
    items = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or not _text(row.get("id")):
            continue
        quantity = row.get("quantity")
        if type(quantity) is not int or quantity < 1:
            continue
        items.append(CartItem(row["id"], _text(row.get("name")), quantity,
                              _amount(row.get("price")), _text(row.get("currency"))))
    return tuple(items)


def parse_cart(data):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CommerceError()
    return Cart(_items(data["items"]), _amount(data.get("total")), _text(data.get("currency")))


def parse_catalog(data):
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise CommerceError()
    products = tuple(
        Product(row["id"], _text(row.get("name")), _text(row.get("description")),
                _amount(row.get("price")), _text(row.get("currency")), row.get("available") is True)
        for row in data["products"] if isinstance(row, dict) and _text(row.get("id")))
    return Catalog(data.get("catalog") is True, data.get("cartEnabled") is True, products,
                   parse_cart(data.get("cart")))


def parse_order(data):
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, dict):
        raise CommerceError()
    status = order.get("status")
    return Order(order.get("mine") is True, status if status in (INQUIRY, ACCEPTED, DECLINED) else None,
                 _text(order.get("note")), _items(order.get("products")),
                 _amount(order.get("subtotal")), _amount(order.get("total")), _text(order.get("currency")),
                 order.get("canAnswer") is True, order.get("canUpdate") is True)


def parse_account(data):
    if not isinstance(data, dict) or type(data.get("business")) is not bool:
        raise CommerceError()
    enabled = data.get("cartEnabled")
    sellers = data.get("sellers")
    return Account(data["business"], enabled if type(enabled) is bool else None,
                   frozenset(jid for jid in sellers if isinstance(jid, str) and _CHAT.fullmatch(jid))
                   if isinstance(sellers, list) else frozenset())


# ── transport ──────────────────────────────────────────────────────────────

def _call(connection, path, payload=None, timeout=45):
    """One request to a commerce route: its `response`, or CommerceError."""
    server, port, token = connection
    url = f"{server}:{port}/api/{token}/commerce/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = (api_get(url, headers=headers, timeout=timeout) if payload is None
                    else api_post(url, json=payload, headers=headers, timeout=timeout))
        body = response.json()
    except Exception:
        raise CommerceError() from None
    if not isinstance(body, dict):
        raise CommerceError()
    data = body.get("response")
    if response.status_code != 200 or body.get("status") != "success":
        code = body.get("code")
        cart = None
        try:
            cart = parse_cart(data.get("cart")) if isinstance(data, dict) else None
        except CommerceError:
            cart = None
        raise CommerceError(code if isinstance(code, str) and code != "commerce_unavailable" else "unavailable", cart)
    return data


def _chat(chat):
    if not isinstance(chat, str) or not _CHAT.fullmatch(chat):
        raise CommerceError("invalid_request")
    return chat


def _product(product_id):
    if not isinstance(product_id, str) or not _PRODUCT.fullmatch(product_id):
        raise CommerceError("invalid_request")
    return product_id


def _note(note):
    note = note.strip() if isinstance(note, str) else ""
    if len(note) > NOTE_LIMIT:
        raise CommerceError("invalid_request")
    return note


def _message(message_id):
    if not isinstance(message_id, str) or not re.fullmatch(
            r"(?:true|false)_\d+@(?:c\.us|lid)_[A-Za-z0-9]{8,64}", message_id):
        raise CommerceError("not_an_order")
    return quote(message_id, safe="")


def read_account(connection):
    return parse_account(_call(connection, "account", timeout=20))


def read_catalog(connection, chat):
    return parse_catalog(_call(connection, f"catalog/{_chat(chat)}"))


def set_cart_quantity(connection, chat, product_id, quantity):
    """Put the product in the cart with this quantity, or change it."""
    if type(quantity) is not int or not 1 <= quantity <= QUANTITY_LIMIT:
        raise CommerceError("invalid_request")
    data = _call(connection, f"cart/{_chat(chat)}/set", {"productId": _product(product_id), "quantity": quantity})
    return parse_cart(data.get("cart"))


def remove_from_cart(connection, chat, product_id):
    return parse_cart(_call(connection, f"cart/{_chat(chat)}/remove", {"productId": _product(product_id)}).get("cart"))


def clear_cart(connection, chat):
    return parse_cart(_call(connection, f"cart/{_chat(chat)}/clear", {}).get("cart"))


def submit_cart(connection, chat, note=""):
    """Send the cart to the business as an order, once. Never retried: a lost
    answer may follow an order that was sent."""
    data = _call(connection, f"cart/{_chat(chat)}/submit", {"message": _note(note)}, timeout=90)
    if data.get("sent") is not True:
        raise CommerceError("unconfirmed")
    return parse_cart(data.get("cart"))


def read_order(connection, message_id):
    return parse_order(_call(connection, f"order/{_message(message_id)}"))


def _answered(data):
    if not isinstance(data, dict) or data.get("accepted") is not True:
        raise CommerceError("unconfirmed")
    status = data.get("status")
    return status if status in (INQUIRY, ACCEPTED, DECLINED) else None


@dataclass(frozen=True)
class BuyerOrder:
    """What the buyer may do with an order a seller created."""
    can_confirm: bool       # WhatsApp Web's "Confirm order info" applies
    confirmed: bool         # the account already sent that confirmation


def parse_buyer_order(data):
    if not isinstance(data, dict):
        raise CommerceError()
    return BuyerOrder(data.get("canConfirm") is True, data.get("confirmed") is True)


def should_read_buyer(msg, message_id):
    """Whether the order dialog asks what the buyer may do: only for an order
    someone else sent, with an id to ask about. The account's own order
    message has nothing for it to answer."""
    key = (msg.get("key") or {}) if isinstance(msg, dict) else {}
    return bool(message_id) and key.get("fromMe") is not True


def read_buyer_order(connection, message_id):
    return parse_buyer_order(_call(connection, f"order-details/{_message(message_id)}"))


def confirm_buyer_order(connection, message_id):
    """Confirm the order's information to the seller, once. Never retried: a
    lost answer may follow a confirmation that was sent."""
    data = _call(connection, f"order-details/{_message(message_id)}/confirm", {}, timeout=90)
    if not isinstance(data, dict) or data.get("confirmed") is not True:
        raise CommerceError("unconfirmed")


def accept_order(connection, message_id):
    """Returns the order message's state as the page then holds it."""
    return _answered(_call(connection, f"order/{_message(message_id)}/accept", {}, timeout=90))


def decline_order(connection, message_id, note=""):
    return _answered(_call(connection, f"order/{_message(message_id)}/decline", {"note": _note(note)}, timeout=90))


def update_order(connection, message_id, status, note="", payment_status=""):
    if status not in ORDER_STATUSES or payment_status not in ("",) + PAYMENT_STATUSES:
        raise CommerceError("invalid_request")
    payload = {"status": status, "note": _note(note)}
    if payment_status:
        payload["paymentStatus"] = payment_status
    return _answered(_call(connection, f"order/{_message(message_id)}/status", payload, timeout=90))


def _upstream(connection, endpoint, payload, accepted):
    """The two upstream routes, which answer the library's raw result."""
    server, port, token = connection
    try:
        response = api_post(f"{server}:{port}/api/{token}/{endpoint}", json=payload,
                            headers={"Authorization": f"Bearer {token}"}, timeout=90)
    except Exception:
        raise CommerceError() from None
    if response.status_code not in accepted:
        raise CommerceError("refused")


def set_cart_enabled(connection, enabled):
    """Whether this business account's catalog takes carts."""
    _upstream(connection, "set-cart-enabled", {"enabled": enabled is True}, (200, 201))


def send_order(connection, chat, items):
    """A business creates an order for a customer. *items* are (name, price in
    thousandths, quantity)."""
    rows = []
    for name, price, quantity in items:
        name = _text(name)
        if (not name or len(name) > 120 or _amount(price) is None or price == 0
                or type(quantity) is not int or not 1 <= quantity <= QUANTITY_LIMIT):
            raise CommerceError("invalid_request")
        rows.append({"type": "custom", "name": name, "price": price, "qnt": quantity})
    if not rows:
        raise CommerceError("invalid_request")
    _upstream(connection, "send-order-message", {"phone": _chat(chat), "isGroup": False, "items": rows},
              (200, 201))


def order_total(items):
    return sum(price * quantity for _name, price, quantity in items)


# ── messages ───────────────────────────────────────────────────────────────

def order_payload(wpp_msg):
    """What is kept of a WhatsApp `order` message (a cart someone sent)."""
    count = wpp_msg.get("itemCount")
    status = wpp_msg.get("status")
    total = wpp_msg.get("totalAmount1000")
    return {
        "itemCount": count if type(count) is int and count >= 0 else 0,
        "total": total if type(total) is int and total > 0 else None,
        "currency": _text(wpp_msg.get("totalCurrencyCode")),
        "note": _text(wpp_msg.get("message")),
        "status": status if status in (INQUIRY, ACCEPTED, DECLINED) else None,
    }


def product_payload(wpp_msg):
    """What is kept of a WhatsApp `product` message. Its `body` is the
    picture's thumbnail, never text, and is not read."""
    price = wpp_msg.get("salePriceAmount1000") or wpp_msg.get("priceAmount1000")
    product_id = wpp_msg.get("productId")
    return {
        "title": _text(wpp_msg.get("title"))[:200],
        "description": _text(wpp_msg.get("description"))[:1000],
        "price": price if type(price) is int and price > 0 else None,
        "currency": _text(wpp_msg.get("currencyCode")),
        "productId": product_id if isinstance(product_id, str) and _PRODUCT.fullmatch(product_id) else "",
    }


def product_message_label(msg, i18n):
    """ "Product: Bread, R$ 7,50. Fresh every morning" """
    data = (msg.get("message") or {}).get(PRODUCT_MESSAGE_TYPE) or {}
    parts = [_text(data.get("title")) or i18n.t("commerce_unnamed_product")]
    money = format_money(data.get("price"), data.get("currency"), _decimal(i18n))
    if money:
        parts.append(money)
    text = f"{i18n.t('commerce_product')}: {', '.join(parts)}"
    description = _text(data.get("description"))
    return f"{text}. {description}" if description else text


def _scaled(node):
    """{"value": 1500, "offset": 100} is 15.00: thousandths, or None."""
    if not isinstance(node, dict):
        return None
    value, offset = node.get("value"), node.get("offset", 1)
    if type(value) not in (int, float) or type(offset) is not int or offset < 1 or value < 0:
        return None
    return round(value * 1000 / offset)


#: Items of an order update kept for its details (WhatsApp's own limit is far
#: below anything a row could show).
UPDATE_ITEMS_LIMIT = 50


def _update_items(order):
    """The order's items as the seller wrote them: name, unit price in
    thousandths and quantity. WhatsApp Web reads `amount` as the unit price
    and multiplies by `quantity` (WAWebOrderDetails.paramsJsonToOrderInfo)."""
    rows = order.get("items") if isinstance(order.get("items"), list) else []
    items = []
    for row in rows[:UPDATE_ITEMS_LIMIT]:
        if not isinstance(row, dict):
            continue
        quantity = row.get("quantity")
        if isinstance(quantity, str) and quantity.strip().isdigit():
            quantity = int(quantity.strip())
        items.append({
            "name": _text(row.get("name"))[:120],
            "price": _scaled(row.get("amount")),
            "quantity": quantity if type(quantity) is int and 0 < quantity <= 10 ** 6 else None,
        })
    return items


def order_update_payload(wpp_msg):
    """What is kept of a seller's order follow-up, or None when the message is
    not one (any other interactive message is left to its own handling)."""
    if wpp_msg.get("nativeFlowName") not in ORDER_FLOWS:
        return None
    payload = wpp_msg.get("interactivePayload")
    buttons = payload.get("buttons") if isinstance(payload, dict) else None
    button = buttons[0] if isinstance(buttons, list) and buttons and isinstance(buttons[0], dict) else None
    try:
        data = json.loads(button.get("buttonParamsJson")) if button else None
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict) or not _text(data.get("reference_id")):
        return None
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    status = order.get("status")
    paid = payment.get("status") or data.get("payment_status")
    return {
        "reference": data["reference_id"].strip()[:64],
        "status": status if status in ORDER_STATUSES else "",
        "payment": paid if paid in PAYMENT_STATUSES else "",
        "total": _scaled(data.get("total_amount")),
        "currency": _text(data.get("currency")),
        "subtotal": _scaled(order.get("subtotal")),
        "items": _update_items(order),
        "method": data.get("payment_method") if data.get("payment_method") in PAYMENT_METHODS else "",
    }


def is_order_message(msg):
    return isinstance(msg, dict) and msg.get("messageType") == ORDER_MESSAGE_TYPE


def is_order_update_message(msg):
    return isinstance(msg, dict) and msg.get("messageType") == ORDER_UPDATE_MESSAGE_TYPE


def _decimal(i18n):
    return i18n.t("decimal_separator")


def items_label(count, i18n):
    return i18n.t("commerce_items_one") if count == 1 else i18n.t("commerce_items_many").format(count=count)


def order_label(msg, i18n):
    """ "Cart sent: 3 items, estimated total R$ 15,00, accepted. note" """
    data = (msg.get("message") or {}).get(ORDER_MESSAGE_TYPE) or {}
    mine = (msg.get("key") or {}).get("fromMe") is True
    parts = [items_label(data.get("itemCount") or 0, i18n)]
    money = format_money(data.get("total"), data.get("currency"), _decimal(i18n))
    if money:
        parts.append(i18n.t("commerce_estimated_total").format(amount=money))
    state = {ACCEPTED: "commerce_order_state_accepted", DECLINED: "commerce_order_state_declined"}.get(
        data.get("status"))
    if state:
        parts.append(i18n.t(state))
    head = i18n.t("commerce_order_sent" if mine else "commerce_order_received")
    text = f"{head}: {', '.join(parts)}"
    note = _text(data.get("note"))
    return f"{text}. {note}" if note else text


def order_update_label(msg, i18n):
    """ "Order update, reference ABC: shipped, payment: paid, total R$ 15,00" """
    data = (msg.get("message") or {}).get(ORDER_UPDATE_MESSAGE_TYPE) or {}
    parts = []
    if data.get("status") in ORDER_STATUSES:
        parts.append(i18n.t(f"commerce_status_{data['status']}"))
    if data.get("payment") in PAYMENT_STATUSES:
        parts.append(i18n.t("commerce_payment").format(status=i18n.t(f"commerce_payment_{data['payment']}")))
    money = format_money(data.get("total"), data.get("currency"), _decimal(i18n))
    if money:
        parts.append(i18n.t("commerce_total").format(amount=money))
    head = i18n.t("commerce_order_info_confirmed" if data.get("method") == "confirm"
                  else "commerce_order_update")
    reference = _text(data.get("reference"))
    if reference:
        head = f"{head}, {i18n.t('commerce_order_reference').format(reference=reference)}"
    return f"{head}: {', '.join(parts)}" if parts else head


def order_update_item_labels(msg, i18n):
    """ "2 × Bread, R$ 7,50 each" for each item an order update carries. One
    stored before the items were kept has none."""
    data = (msg.get("message") or {}).get(ORDER_UPDATE_MESSAGE_TYPE) or {}
    labels = []
    for item in data.get("items") or ():
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name")) or i18n.t("commerce_unnamed_product")
        quantity = item.get("quantity")
        parts = [f"{quantity} × {name}" if type(quantity) is int else name]
        money = format_money(item.get("price"), data.get("currency"), _decimal(i18n))
        if money:
            parts.append(i18n.t("commerce_each").format(amount=money))
        labels.append(", ".join(parts))
    return labels


def order_update_description(msg, i18n):
    """The details of an order update, one fact per line: what the row says,
    then how many items and the subtotal when it differs from the total."""
    data = (msg.get("message") or {}).get(ORDER_UPDATE_MESSAGE_TYPE) or {}
    lines = [order_update_label(msg, i18n)]
    items = [item for item in data.get("items") or () if isinstance(item, dict)]
    if items:
        count = sum(item["quantity"] if type(item.get("quantity")) is int else 1 for item in items)
        lines.append(items_label(count, i18n))
    subtotal = data.get("subtotal")
    money = format_money(subtotal, data.get("currency"), _decimal(i18n))
    if money and subtotal != data.get("total"):
        lines.append(i18n.t("commerce_subtotal").format(amount=money))
    return "\n".join(lines)


def message_label(msg, i18n):
    """The row text of an order or order follow-up message; None for another."""
    kind = msg.get("messageType") if isinstance(msg, dict) else None
    if kind == ORDER_MESSAGE_TYPE:
        return order_label(msg, i18n)
    if kind == ORDER_UPDATE_MESSAGE_TYPE:
        return order_update_label(msg, i18n)
    if kind == PRODUCT_MESSAGE_TYPE:
        return product_message_label(msg, i18n)
    return None


def product_label(product, i18n):
    parts = [product.name or i18n.t("commerce_unnamed_product")]
    money = format_money(product.price, product.currency, _decimal(i18n))
    if money:
        parts.append(money)
    if not product.available:
        parts.append(i18n.t("commerce_out_of_stock"))
    if product.description:
        parts.append(product.description)
    return ", ".join(parts)


def item_label(item, i18n):
    parts = [f"{item.quantity} × {item.name or i18n.t('commerce_unnamed_product')}"]
    money = format_money(item.price, item.currency, _decimal(i18n))
    if money:
        parts.append(i18n.t("commerce_each").format(amount=money))
    return ", ".join(parts)


def cart_summary(cart, i18n):
    if not cart.items:
        return i18n.t("commerce_cart_empty")
    parts = [items_label(cart.item_count, i18n)]
    money = format_money(cart.total, cart.currency, _decimal(i18n))
    if money:
        parts.append(i18n.t("commerce_estimated_total").format(amount=money))
    return ", ".join(parts)
