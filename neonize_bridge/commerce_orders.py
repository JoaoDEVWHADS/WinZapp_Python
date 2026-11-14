"""Orders: reading one, the seller's accept / decline / status update, the
buyer's "Confirm order info", and the upstream get-order-by-messageId
(WinZapp's commerceController.ts and orderConfirmController.ts).

An order message carries its id, token and seller (commerce_messages keeps
them); the order itself is read from the catalog GraphQL endpoint
(catalog_graphql.get_order). What each answer sends, as wa-js and WhatsApp
Web do (read over CDP on 2026-10-26: WPP.order.accept / decline / update,
WAWebBizSendOrderAction, orderConfirmController.ts):

- accept: a native flow "order_details" message (button review_and_pay) with
  the order, status "payment_requested", quoting the order;
- decline: an "order_status" message (button review_order), status
  "canceled", then the order_details "canceled";
- a new status: an "order_status" message with the status, the payment's
  status and the seller's note;
- the buyer's confirmation: a "payment_method" message (button
  payment_method, payment_method "confirm") quoting the seller's
  order_details, only while the order is "pending", has items and a
  subtotal, carries no in-app payment and was not confirmed already.

Amounts go as {value: thousandths, offset: 1000}. Only a business account
answers an order it received. The pure functions are at the top (tested in
test_commerce_orders.py). Not run against a real account.
"""
import asyncio
import json
import logging
import time

from aiohttp import web

import catalog_graphql
import commerce_common as cc
import raw_queries as rq
from interactive_send import interactive, to_message

log = logging.getLogger("bridge")

OFFSET = 1000
INQUIRY, ACCEPTED, DECLINED = 1, 2, 3
ORDER_STATUSES = ("pending", "processing", "partially_shipped", "shipped", "completed", "canceled",
                  "payment_requested", "preparing_to_ship", "delivered", "confirmed", "delayed",
                  "failed", "out_for_delivery", "refunded")
PAYMENT_STATUSES = ("pending", "captured", "failed", "canceled")
IN_APP_PAYMENTS = ("pix_dynamic_code", "payment_link", "boleto")


def order_of(wpp) -> dict:
    """{id, token, sellerJid} of a stored order message, or None."""
    if not isinstance(wpp, dict) or wpp.get("type") != "order":
        return None
    if not (wpp.get("orderId") and wpp.get("token")):
        return None
    return {"id": wpp["orderId"], "token": wpp["token"], "sellerJid": wpp.get("sellerJid") or ""}


def order_body(wpp, info, mine, business) -> dict:
    """The `order` of commerce/order/:messageId (core/commerce.py parse_order)."""
    status = wpp.get("status")
    status = status if status in (INQUIRY, ACCEPTED, DECLINED) else None
    products = [{"id": p["id"], "name": p["name"], "price": p["price"],
                 "currency": p["currency"], "quantity": p["quantity"] or 0}
                for p in info["products"]]
    return {"mine": mine, "status": status, "note": wpp.get("message") or "",
            "products": products, "subtotal": info["subtotal"], "total": info["total"],
            "currency": info["currency"], "createdAt": info["createdAt"],
            "canAnswer": business and not mine and status not in (ACCEPTED, DECLINED),
            "canUpdate": business and not mine and status in (ACCEPTED, DECLINED)}


def order_items(info) -> list:
    return [{"retailer_id": p["id"], "name": p["name"],
             "amount": {"value": p["price"] or 0, "offset": OFFSET},
             "quantity": p["quantity"] or 1, "isCustomItem": False, "isQuantitySet": True}
            for p in info["products"]]


def order_details_params(order_id, info, status) -> dict:
    """The order of an order_details message (WPP.order.accept / decline)."""
    return {"reference_id": order_id, "type": "physical-goods",
            "payment_configuration": "merchant_categorization_code", "currency": info["currency"],
            "total_amount": {"value": info["total"] or 0, "offset": OFFSET},
            "order_type": "ORDER",
            "order": {"status": status, "items": order_items(info),
                      "subtotal": {"value": info["subtotal"] or 0, "offset": OFFSET},
                      "tax": None}}


def status_params(reference, info, status, payment_status, payment_method=None, now=None) -> dict:
    """The order of an order_status / payment_method message
    (WAWebBizSendOrderAction, the function behind sendOrderStatusMessageAsMerchant)."""
    params = {"reference_id": reference, "payment_timestamp": int(now or time.time()),
              "currency": info["currency"], "payment_status": payment_status,
              "total_amount": {"value": info["total"] or 0, "offset": OFFSET},
              "order": {"status": status, "items": order_items(info),
                        "subtotal": {"value": info["subtotal"] or 0, "offset": OFFSET}}}
    if payment_method:
        params["payment_method"] = payment_method
    return params


def flow_params(wpp):
    """The JSON of a native flow message's button, or None."""
    buttons = ((wpp or {}).get("interactivePayload") or {}).get("buttons") or []
    try:
        return json.loads(buttons[0].get("buttonParamsJson")) if buttons else None
    except (TypeError, ValueError, AttributeError):
        return None


def details_info(params) -> dict:
    """An order_details message's order, as get_order answers one."""
    order = params.get("order") or {}

    def thousandths(node):
        node = node or {}
        value, offset = node.get("value"), node.get("offset") or OFFSET
        return round(value * OFFSET / offset) if isinstance(value, (int, float)) else None
    products = [{"id": str(i.get("retailer_id") or ""), "name": i.get("name") or "",
                 "price": thousandths(i.get("amount")), "currency": params.get("currency") or "",
                 "quantity": i.get("quantity")} for i in order.get("items") or ()]
    return {"currency": params.get("currency") or "", "products": products,
            "subtotal": thousandths(order.get("subtotal")),
            "total": thousandths(params.get("total_amount")), "createdAt": None}


def latest_status(messages, reference) -> str:
    """The order's status after the chat's order messages (WAWebOrderStatus.findOrderStatus)."""
    status = ""
    for wpp in messages:
        params = flow_params(wpp)
        if params and params.get("reference_id") == reference:
            status = (params.get("order") or {}).get("status") or status
    return status


def buyer_state(wpp, messages, me_sent) -> dict:
    """{canConfirm, confirmed} of a seller's order_details message."""
    params = flow_params(wpp) or {}
    reference = params.get("reference_id")
    order = params.get("order") or {}
    confirmed = any(m.get("nativeFlowName") == "payment_method" and me_sent(m)
                    and (flow_params(m) or {}).get("reference_id") == reference
                    and (flow_params(m) or {}).get("payment_method") == "confirm"
                    for m in messages)
    pays_in_app = any(isinstance(p, dict) and p.get("type") in IN_APP_PAYMENTS
                      for p in params.get("payment_settings") or ())
    can = (not me_sent(wpp) and latest_status(messages, reference) == "pending"
           and bool(order.get("items")) and order.get("subtotal") is not None
           and not pays_in_app and not confirmed)
    return {"canConfirm": bool(can), "confirmed": bool(confirmed)}


def register_routes(r, *, session, jid_from_text, jid_text, destination_of, store_sent,
                    quoted_context):
    """Wire the order routes to the aiohttp router `r`."""

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def failure(error):
        return web.json_response({"status": "error", "code": error.code}, status=error.status)

    def ready(s):
        if s.client is None or s.status != "CONNECTED" or not rq.available(s.client):
            raise cc.CommerceRefused("commerce_unavailable")

    def business(s):
        try:
            return bool(getattr(s.client.get_me(), "BussinessName", ""))
        except Exception:
            return False

    def message_of(req):
        serialized = req.match_info["messageId"]
        if not cc.MESSAGE.fullmatch(serialized):
            raise cc.CommerceRefused("invalid_request")
        return serialized

    def stored(s, serialized):
        mine, chat, msg_id = cc.message_key(serialized)
        return mine, chat, s.db.wpp_message(msg_id)

    def read_order(s, serialized):
        mine, chat, wpp = stored(s, serialized)
        order = order_of(wpp)
        if order is None:
            raise cc.CommerceRefused("not_an_order")
        info = catalog_graphql.get_order(order["sellerJid"], order["id"], order["token"])
        return mine, chat, wpp, order, info

    def send_flow(s, chat, button, params, caption, quoting):
        destination = destination_of(chat)
        fields = interactive(caption or "", [{"name": button,
                                             "buttonParamsJSON": json.dumps(params)}])
        message = to_message(fields)
        if quoting:
            ctx = quoted_context(s, quoting)
            if ctx is not None:
                message.interactiveMessage.contextInfo.CopyFrom(ctx)
        return destination, s.client.send_message(destination, message)

    def chat_messages(s, chat):
        return s.db.messages(cc.whatsmeow_chat(chat), 300)

    def details_message_of(s, chat, reference):
        """The serialized id of the account's order_details for `reference`."""
        for wpp in reversed(chat_messages(s, chat)):
            if wpp.get("nativeFlowName") == "order_details" \
                    and (flow_params(wpp) or {}).get("reference_id") == reference:
                return wpp["id"]["_serialized"]
        return ""

    def answer(s, serialized, action, note="", status="", payment=""):
        ready(s)
        if not business(s):
            raise cc.CommerceRefused("not_business")
        mine, chat, wpp, order, info = read_order(s, serialized)
        if mine:
            raise cc.CommerceRefused("own_order")
        sends = []
        if action == "accept":
            sends.append(("review_and_pay", order_details_params(order["id"], info,
                                                                 "payment_requested"), "",
                          serialized))
            new_status = ACCEPTED
        elif action == "decline":
            quote = details_message_of(s, chat, order["id"]) or serialized
            sends.append(("review_order", status_params(order["id"], info, "canceled", "pending"),
                          note, quote))
            sends.append(("review_and_pay", order_details_params(order["id"], info, "canceled"),
                          "", serialized))
            new_status = DECLINED
        else:
            if wpp.get("status") not in (ACCEPTED, DECLINED):
                raise cc.CommerceRefused("invalid_request")
            quote = details_message_of(s, chat, order["id"]) or serialized
            sends.append(("review_order", status_params(order["id"], info, status,
                                                        payment or "pending"), note, quote))
            new_status = wpp.get("status")
        out = [send_flow(s, chat, *send) for send in sends]
        wpp["status"] = new_status
        s.db.message(cc.whatsmeow_chat(chat), wpp)
        return out, new_status

    def buyer(s, serialized, confirm):
        ready(s)
        mine, chat, wpp = stored(s, serialized)
        if not wpp or wpp.get("nativeFlowName") != "order_details" or not flow_params(wpp):
            raise cc.CommerceRefused("not_an_order")
        messages = chat_messages(s, chat)
        state = buyer_state(wpp, messages, lambda m: (m.get("id") or {}).get("fromMe") is True)
        if not confirm:
            return state, None
        if not state["canConfirm"]:
            raise cc.CommerceRefused("already_confirmed" if state["confirmed"]
                                     else "cannot_confirm")
        params = flow_params(wpp)
        info = details_info(params)
        reference = params["reference_id"]
        send = send_flow(s, chat, "payment_method",
                         status_params(reference, info, latest_status(messages, reference),
                                       None, "confirm"), "", serialized)
        return {"confirmed": True}, send

    def record(s, sends):
        for destination, resp in sends:
            store_sent(s, destination, resp)

    def success(response):
        return web.json_response({"status": "success", "response": response})

    async def guarded(req, func):
        try:
            return await func()
        except cc.CommerceRefused as error:
            return failure(error)
        except Exception as error:
            log.warning("commerce order: %s", getattr(error, "code", "") or type(error).__name__)
            return failure(cc.CommerceRefused("commerce_unavailable"))

    async def order(req):
        async def run():
            s, serialized = session(req), message_of(req)
            ready(s)
            mine, _chat, wpp, _order, info = await execute(read_order, s, serialized)
            return success({"order": order_body(wpp, info, mine, await execute(business, s))})
        return await guarded(req, run)

    async def body_of(req):
        try:
            body = await req.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    def note_of(body, key="note"):
        note = body.get(key)
        note = "" if note in (None, "") else note
        if not isinstance(note, str) or len(note) > cc.NOTE_LIMIT:
            raise cc.CommerceRefused("invalid_request")
        return note

    async def act(req, action):
        async def run():
            s, serialized, body = session(req), message_of(req), await body_of(req)
            note = note_of(body) if action != "accept" else ""
            status = payment = ""
            if action == "status":
                status, payment = body.get("status"), body.get("paymentStatus") or ""
                if status not in ORDER_STATUSES or (payment and payment not in PAYMENT_STATUSES):
                    raise cc.CommerceRefused("invalid_request")
            sends, new_status = await execute(answer, s, serialized, action, note, status,
                                              payment)
            record(s, sends)
            return success({"accepted": True, "status": new_status})
        return await guarded(req, run)

    async def order_accept(req):
        return await act(req, "accept")

    async def order_decline(req):
        return await act(req, "decline")

    async def order_status(req):
        return await act(req, "status")

    async def order_details(req, confirm):
        async def run():
            s, serialized = session(req), message_of(req)
            state, send = await execute(buyer, s, serialized, confirm)
            if send is not None:
                record(s, [send])
            return success(state)
        return await guarded(req, run)

    async def read_details(req):
        return await order_details(req, False)

    async def confirm_details(req):
        return await order_details(req, True)

    async def order_by_message(req):
        s = session(req)
        serialized = req.match_info["messageId"]
        try:
            ready(s)
            _mine, _chat, _wpp, order, info = await execute(read_order, s, serialized)
        except Exception as error:
            return web.json_response({"status": "error", "message": "Error on get order",
                                      "error": getattr(error, "code", "")}, status=500)
        data = {"id": order["id"], "products": info["products"],
                "itemCount": len(info["products"]), "subtotal": info["subtotal"], "tax": None,
                "total": info["total"], "currency": info["currency"],
                "createdAt": info["createdAt"], "sellerJid": order["sellerJid"]}
        return web.json_response({"status": "Success", "response": {
            "message": "Information retrieved successfully.", "contact": None,
            "session": s.name, "data": data}}, status=201)

    r.add_get("/api/{tok}/commerce/order/{messageId}", order)
    r.add_post("/api/{tok}/commerce/order/{messageId}/accept", order_accept)
    r.add_post("/api/{tok}/commerce/order/{messageId}/decline", order_decline)
    r.add_post("/api/{tok}/commerce/order/{messageId}/status", order_status)
    r.add_get("/api/{tok}/commerce/order-details/{messageId}", read_details)
    r.add_post("/api/{tok}/commerce/order-details/{messageId}/confirm", confirm_details)
    r.add_get("/api/{tok}/get-order-by-messageId/{messageId}", order_by_message)
