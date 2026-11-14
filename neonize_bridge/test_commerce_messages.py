import json

from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

import commerce_messages as cm
import msgmap

CHAT = "5511999990000@s.whatsapp.net"


def _build(message):
    return msgmap.build(chat=CHAT, from_me=False, id="ID1", sender=CHAT,
                        ts=1700000000, message=message)


def test_order_arrives_as_order_with_the_fields_the_client_reads():
    msg = Message()
    msg.orderMessage.orderID = "123"
    msg.orderMessage.itemCount = 3
    msg.orderMessage.status = 1
    msg.orderMessage.totalAmount1000 = 45500
    msg.orderMessage.totalCurrencyCode = "BRL"
    msg.orderMessage.message = "no onions"
    m = _build(msg)
    assert m["type"] == "order"
    assert (m["itemCount"], m["status"], m["totalAmount1000"]) == (3, 1, 45500)
    assert m["totalCurrencyCode"] == "BRL" and m["message"] == "no onions"


def test_product_arrives_as_product_with_price_and_id():
    msg = Message()
    msg.productMessage.product.productID = "98765"
    msg.productMessage.product.title = "Bread"
    msg.productMessage.product.description = "Fresh"
    msg.productMessage.product.currencyCode = "BRL"
    msg.productMessage.product.priceAmount1000 = 7500
    m = _build(msg)
    assert m["type"] == "product" and m["productId"] == "98765"
    assert m["title"] == "Bread" and m["description"] == "Fresh"
    assert m["priceAmount1000"] == 7500 and m["currencyCode"] == "BRL"
    assert m["body"] == "Bread"           # never the image thumbnail


def test_order_notice_gets_the_flow_name():
    msg = Message()
    button = msg.interactiveMessage.nativeFlowMessage.buttons.add()
    button.name = "review_order"
    button.buttonParamsJSON = json.dumps({"reference_id": "R1"})
    m = _build(msg)
    assert m["nativeFlowName"] == "order_status"
    assert m["interactivePayload"]["buttons"][0]["name"] == "review_order"


def test_ordinary_native_button_does_not_get_a_flow_name():
    msg = Message()
    button = msg.interactiveMessage.nativeFlowMessage.buttons.add()
    button.name = "quick_reply"
    assert "nativeFlowName" not in _build(msg)


def test_known_flows():
    assert cm.native_flow("review_and_pay") == "order_details"
    assert cm.native_flow("payment_info") == "payment_info"
    assert cm.native_flow("other") == "" and cm.native_flow(None) == ""
