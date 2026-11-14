"""Orders through the catalog GraphQL endpoint WhatsApp Web uses."""
import json
from types import SimpleNamespace as N

import pytest

import catalog_graphql as cg


def test_the_request_is_whatsapp_webs():
    body = cg.request_body("123", {"a": 1})
    assert body == {"access_token": cg.ACCESS_TOKEN, "doc_id": "123", "variables": {"a": 1},
                    "lang": "en_US"}
    assert cg.ENDPOINT == "https://graph.whatsapp.com/graphql/catalog"


def test_place_order_variables():
    variables = cg.place_order_variables("5511@s.whatsapp.net", [
        {"id": "1", "name": "Pão", "quantity": 2, "price": 7500, "currency": "BRL"},
        {"id": "2", "name": "Sem preço", "quantity": 1, "price": None, "currency": ""}])
    assert variables == {"input": {"order": {"jid": "5511@s.whatsapp.net", "products": [
        {"id": "1", "name": "Pão", "quantity": 2, "currency": "BRL", "price": "7500"},
        {"id": "2", "name": "Sem preço", "quantity": 1}]}}}


def test_get_order_variables():
    assert cg.get_order_variables("5511@s.whatsapp.net", "O1", "TK") == {"request": {"order": {
        "jid": "5511@s.whatsapp.net", "token": {"sensitive_string_value": "TK"}, "id": "O1",
        "image_dimensions": {"height": 80, "width": 80}}}}


def test_a_placed_order():
    answer = {"data": {"xwa_checkout_place_order": {"order": {
        "order_id": "O1", "token": "TK",
        "price": {"subtotal_amount": "15000", "total_amount": "15000", "currency": "BRL"}}}}}
    assert cg.placed_order(answer) == {"id": "O1", "token": "TK", "subtotal": 15000,
                                       "total": 15000, "currency": "BRL"}
    with pytest.raises(cg.GraphQLError):
        cg.placed_order({"data": {"xwa_checkout_place_order": {"order": {}}}})


def test_an_order_read_back():
    answer = {"data": {"xwa_checkout_get_order_info": {"order": {
        "creation_time_stamp": "1700000000",
        "products": [{"id": "1", "name": "Pão", "price": "7500", "currency": "BRL",
                      "quantity": "2", "media": {"images": [{"request_image_url": "u"}]}}],
        "price_details": {"subtotal_amount": "15000", "total_amount": "15000",
                          "currency": "BRL"}}}}}
    info = cg.order_info(answer)
    assert info["createdAt"] == 1700000000 and info["total"] == 15000
    assert info["products"] == [{"id": "1", "name": "Pão", "price": 7500, "currency": "BRL",
                                 "quantity": 2, "thumbnailUrl": "u"}]
    with pytest.raises(cg.GraphQLError):
        cg.order_info({"data": {}})


class Http:
    def __init__(self, answer, status=200):
        self.answer, self.status, self.sent = answer, status, []

    def post(self, url, data, headers, timeout):
        self.sent.append((url, json.loads(data), headers))
        return N(status_code=self.status, json=lambda: self.answer)


def test_post_sends_json_and_raises_graphql_errors():
    http = Http({"data": {"x": 1}})
    assert cg.post("9", {"v": 1}, http) == {"data": {"x": 1}}
    url, body, headers = http.sent[0]
    assert url == cg.ENDPOINT and body["doc_id"] == "9" and body["variables"] == {"v": 1}
    assert headers["Content-Type"] == "application/json"
    with pytest.raises(cg.GraphQLError) as caught:
        cg.post("9", {}, Http({"errors": [{"message": "nope", "code": 451}]}))
    assert caught.value.code == 451


def test_place_order_end_to_end():
    http = Http({"data": {"xwa_checkout_place_order": {"order": {"order_id": "O1", "token": "T",
                                                                  "price": {}}}}})
    order = cg.place_order("5511@s.whatsapp.net", [{"id": "1", "name": "P", "quantity": 1}], http)
    assert order["id"] == "O1" and http.sent[0][1]["doc_id"] == cg.PLACE_ORDER_DOC


def test_the_catalog_query_is_whatsapp_web_s():
    assert cg.catalog_variables("5511@s.whatsapp.net", 100, after="c1") == {"request": {
        "product_catalog": {"jid": "5511@s.whatsapp.net", "allow_shop_source": "ALLOWSHOPSOURCE_TRUE",
                            "width": "100", "height": "100", "limit": "100", "after": "c1"}}}
    assert "after" not in cg.catalog_variables("5511@s.whatsapp.net", 10)["request"]["product_catalog"]


def test_a_graphql_product_has_the_fields_of_an_iq_product():
    p = cg.product_from_graphql({
        "id": "311", "name": "Plano VIP", "price": "35000", "currency": "BRL", "is_hidden": None,
        "max_available": 5, "product_availability": "IN_STOCK", "retailer_id": None,
        "media": {"images": [{"id": "a", "request_image_url": "r1", "original_image_url": "o1"},
                             {"id": "b", "request_image_url": "r2", "original_image_url": "o2"}]},
        "status_info": {"status": "PENDING"}})
    assert p["id"] == "311" and p["price"] == "35000" and p["currency"] == "BRL"
    assert p["is_hidden"] is False and p["max_available"] == 5 and p["availability"] == "in stock"
    assert p["image_cdn_urls"] == [{"key": "requested", "value": "r1"}, {"key": "full", "value": "o1"}]
    assert p["additional_image_cdn_urls"] == [[{"key": "requested", "value": "r2"},
                                               {"key": "full", "value": "o2"}]]
    assert p["image_hashes_for_whatsapp"] == ["a", "b"] and p["retailer_id"] == ""
    assert p["capability_to_review_status"] == [{"key": "WHATSAPP", "value": "PENDING"}]
    hidden = cg.product_from_graphql({"id": "1", "name": "x", "is_hidden": "ISHIDDEN_TRUE"})
    assert hidden["is_hidden"] is True and hidden["price"] is None and hidden["max_available"] == 99


def test_the_catalog_answer_gives_products_and_the_next_page():
    answer = {"data": {"xwa_product_catalog_get_product_catalog": {"product_catalog": {
        "products": [{"id": "1", "name": "a"}, {"id": "2"}, None],
        "paging": {"before": "", "after": "next"}}}}}
    products, after = cg.parsed_catalog(answer)
    assert [p["id"] for p in products] == ["1"] and after == "next"
    assert cg.parsed_catalog({"data": {"xwa_product_catalog_get_product_catalog": None}}) == ([], "")


def test_get_catalog_posts_the_catalog_doc():
    class Http:
        sent = []

        def post(self, url, data, headers, timeout):
            self.sent.append(json.loads(data))
            return N(status_code=200, json=lambda: {"data": {
                "xwa_product_catalog_get_product_catalog": {"product_catalog": {
                    "products": [{"id": "1", "name": "a"}]}}}})
    http = Http()
    products, after = cg.get_catalog("5511@s.whatsapp.net", 10, http=http)
    assert [p["id"] for p in products] == ["1"] and after == ""
    assert http.sent[0]["doc_id"] == cg.CATALOG_DOC


class Answers:
    """An http whose answers depend on the product ids asked."""

    def __init__(self, known):
        self.known, self.asked = known, []

    def post(self, url, data, headers, timeout):
        ids = [p["id"] for p in json.loads(data)["variables"]["request"]["product_list"]["products"]]
        self.asked.append(ids)
        if any(i not in self.known for i in ids):
            return N(status_code=200, json=lambda: {"errors": [
                {"message": "A server error field_exception occured."}]})
        products = [{"id": i, "name": "p" + i} for i in ids]
        return N(status_code=200, json=lambda: {"data": {
            "xwa_product_catalog_get_product_list": {"product_list": {"products": products}}}})


def test_products_by_id_leave_out_the_ones_the_catalog_lost():
    http = Answers({"1", "3"})
    products = cg.get_products("5511@s.whatsapp.net", ["1", "2", "3"], http=http)
    assert [p["id"] for p in products] == ["1", "3"]
    assert http.asked == [["1", "2", "3"], ["1"], ["2"], ["3"]]
    assert cg.get_products("5511@s.whatsapp.net", ["1"], http=Answers({"1"}))[0]["name"] == "p1"


def test_an_unreachable_endpoint_is_not_a_missing_product():
    class Down:
        def post(self, *a, **k):
            raise OSError("down")
    with pytest.raises(cg.GraphQLError):
        cg.get_products("5511@s.whatsapp.net", ["1"], http=Down())
