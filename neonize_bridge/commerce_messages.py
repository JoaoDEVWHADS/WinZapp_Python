"""Commerce messages (order and product) in WhatsApp Web's format.

The client (`client/core/commerce.py`) reads `type: "order"` with `itemCount`,
`status`, `totalAmount1000`, `totalCurrencyCode`, `message`; and `type: "product"`
with `title`, `description`, `salePriceAmount1000`/`priceAmount1000`,
`currencyCode`, `productId`. Without this a seller account would not even see
the order arrive (everything fell into `unknown`). Pure functions; nothing here
was tested against a real account.
"""

# interactive message button name -> nativeFlowName the client knows
# (WAWebBizTemplateAndInteractiveMessagesUtils in WhatsApp Web)
FLOWS = {
    "review_and_pay": "order_details",
    "review_order": "order_status",
    "order_details": "order_details",
    "order_status": "order_status",
    "payment_info": "payment_info",
    "payment_status": "payment_status",
    "payment_method": "payment_method",
}


def native_flow(button_name) -> str:
    """The `nativeFlowName` of a native button, or '' if it is not an order/payment one."""
    return FLOWS.get(button_name or "", "")


def order_fields(order) -> dict:
    """Fields of an `OrderMessage`. `orderId`, `token` and `sellerJid` are what
    reading the order back needs (commerce_orders.py); WhatsApp Web's order
    message model keeps the same three."""
    return {"type": "order",
            "itemCount": int(order.itemCount or 0),
            "status": int(order.status or 0),
            "totalAmount1000": int(order.totalAmount1000 or 0),
            "totalCurrencyCode": order.totalCurrencyCode,
            "message": order.message,
            "orderId": order.orderID,
            "token": order.token,
            "sellerJid": order.sellerJID,
            "orderTitle": order.orderTitle,
            "body": order.orderTitle or order.message}


def product_fields(product) -> dict:
    """Fields of a `ProductMessage`. The `body` is the message text, never the
    image thumbnail."""
    p = product.product
    return {"type": "product",
            "productId": p.productID,
            "title": p.title,
            "description": p.description,
            "currencyCode": p.currencyCode,
            "priceAmount1000": int(p.priceAmount1000 or 0),
            "salePriceAmount1000": int(p.salePriceAmount1000 or 0),
            "body": product.body or p.title}
