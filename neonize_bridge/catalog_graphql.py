"""Orders through WhatsApp's catalog GraphQL endpoint, as WhatsApp Web places
and reads them (read over CDP on 2026-10-26: WAWebBizCreateOrderJob,
WAWebBizQueryOrderJob, WAWebRelayEnvironment, WAWebGraphQLConstants).

Its "whatsapp_catalog" environment is a plain HTTPS POST to
https://graph.whatsapp.com/graphql/catalog with a public application token
built into WhatsApp Web, the query's doc_id and its variables: no account
credential goes with it. What ties an order to its people is the order's own
id and token, which travel in the order message.

- place an order: doc 26486627094287046, {input: {order: {jid: <seller>,
  products: [{id, name, quantity, price (thousandths, a string), currency}]}}}
  -> xwa_checkout_place_order.order {order_id, token, price{subtotal_amount,
  total_amount, currency}};
- read an order: doc 26593811266898374, {request: {order: {jid: <seller>,
  token: {sensitive_string_value}, id, image_dimensions: {height, width}}}}
  -> xwa_checkout_get_order_info.order;
- read a seller's catalog: doc 30445081048424116 (WAWebQueryCatalogQuery),
  {request: {product_catalog: {jid, allow_shop_source: ALLOWSHOPSOURCE_TRUE,
  width, height, limit, after}}} (strings) ->
  xwa_product_catalog_get_product_catalog.product_catalog {products, paging}.
  The <product_catalog> IQ WhatsApp Web used before goes unanswered now;
- read some products: doc 30125049463760630 (WAWebQueryProductListCatalogJob),
  {request: {product_list: {jid, products: [{id}], width, height}}} ->
  xwa_product_catalog_get_product_list.product_list.products. One id the
  catalog no longer has fails the whole query (field_exception), so then each
  id is asked alone and the missing ones are left out, as the IQ's
  INVALID_PRODUCT did.

The pure functions are at the top (tested in test_catalog_graphql.py).
"""
import json

ENDPOINT = "https://graph.whatsapp.com/graphql/catalog"
ACCESS_TOKEN = "WA|787118555984857|7bb1544a3599aa180ac9a3f7688ba243"
PLACE_ORDER_DOC = "26486627094287046"
GET_ORDER_DOC = "26593811266898374"
CATALOG_DOC = "30445081048424116"
PRODUCT_LIST_DOC = "30125049463760630"
# WAWebBizParseProductGraphql's ProductAvailability, as WhatsApp Web keeps it
AVAILABILITY = {"IN_STOCK": "in stock", "OUT_OF_STOCK": "out of stock",
                "AVAILABLE_FOR_ANOTHER_POSTCODE": "available for another postcode"}
TIMEOUT = 30


class GraphQLError(Exception):
    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = int(code or 0)


def request_body(doc_id, variables, lang="en_US") -> dict:
    return {"access_token": ACCESS_TOKEN, "doc_id": doc_id, "variables": variables, "lang": lang}


def place_order_variables(seller_jid, items) -> dict:
    """`items`: [{id, name, quantity, price (thousandths) or None, currency}]."""
    products = []
    for item in items:
        product = {"id": str(item["id"]), "name": item.get("name") or "",
                   "quantity": int(item["quantity"])}
        if item.get("currency"):
            product["currency"] = item["currency"]
        if item.get("price") is not None:
            product["price"] = str(int(item["price"]))
        products.append(product)
    return {"input": {"order": {"jid": seller_jid, "products": products}}}


def get_order_variables(seller_jid, order_id, token, side=80) -> dict:
    return {"request": {"order": {"jid": seller_jid, "token": {"sensitive_string_value": token},
                                  "id": order_id,
                                  "image_dimensions": {"height": side, "width": side}}}}


def catalog_variables(seller_jid, limit, after="", side="100") -> dict:
    catalog = {"jid": seller_jid, "allow_shop_source": "ALLOWSHOPSOURCE_TRUE",
               "width": str(side), "height": str(side), "limit": str(int(limit))}
    if after:
        catalog["after"] = after
    return {"request": {"product_catalog": catalog}}


def product_from_graphql(p) -> dict:
    """A catalog product with the fields biz_iq.parse_product gives, from
    the GraphQL answer (WAWebBizParseProductGraphql)."""
    images = ((p.get("media") or {}).get("images") or [])
    urls = [[{"key": "requested", "value": i.get("request_image_url") or ""},
             {"key": "full", "value": i.get("original_image_url") or ""}] for i in images]
    status = p.get("status_info") or {}
    maximum = p.get("max_available")
    return {
        "id": str(p.get("id") or ""),
        "is_hidden": p.get("is_hidden") == "ISHIDDEN_TRUE",
        "url": p.get("url") or "",
        "name": p.get("name") or "",
        "description": p.get("description") or "",
        "availability": AVAILABILITY.get(p.get("product_availability"), "unknown"),
        "max_available": maximum if isinstance(maximum, int) else 99,
        "image_cdn_urls": urls[0] if urls else [],
        "additional_image_cdn_urls": urls[1:],
        "image_hashes_for_whatsapp": [str(i.get("id") or "") for i in images],
        "capability_to_review_status": [{"key": "WHATSAPP",
                                         "value": status.get("status") or "APPROVED"}],
        "currency": p.get("currency") or None,
        "price": str(p["price"]) if p.get("price") not in (None, "") else None,
        "retailer_id": p.get("retailer_id") or "",
    }


def parsed_catalog(answer) -> tuple:
    """([products], next page cursor) of a catalog answer; a seller without
    a catalog answers no product_catalog: ([], "")."""
    data = (answer or {}).get("data") or {}
    catalog = (data.get("xwa_product_catalog_get_product_catalog") or {}).get("product_catalog")
    if not isinstance(catalog, dict):
        return [], ""
    products = [product_from_graphql(p) for p in catalog.get("products") or []
                if isinstance(p, dict) and p.get("id") and p.get("name")]
    return products, ((catalog.get("paging") or {}).get("after") or "")


def product_list_variables(seller_jid, product_ids, side="100") -> dict:
    return {"request": {"product_list": {
        "jid": seller_jid, "products": [{"id": str(i)} for i in product_ids],
        "width": str(side), "height": str(side)}}}


def parsed_product_list(answer) -> list:
    data = (answer or {}).get("data") or {}
    listing = (data.get("xwa_product_catalog_get_product_list") or {}).get("product_list") or {}
    return [product_from_graphql(p) for p in listing.get("products") or []
            if isinstance(p, dict) and p.get("id") and p.get("name")]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def placed_order(answer) -> dict:
    """{id, token, subtotal, total, currency} of a place order answer."""
    order = ((answer or {}).get("data") or {}).get("xwa_checkout_place_order") or {}
    order = order.get("order") or {}
    if not order.get("order_id"):
        raise GraphQLError("the order was not placed", 500)
    price = order.get("price") or {}
    return {"id": str(order["order_id"]), "token": order.get("token") or "",
            "subtotal": _int(price.get("subtotal_amount")),
            "total": _int(price.get("total_amount")), "currency": price.get("currency") or ""}


def order_info(answer) -> dict:
    """The order of a get order answer, as WhatsApp Web reads it."""
    order = ((answer or {}).get("data") or {}).get("xwa_checkout_get_order_info") or {}
    order = order.get("order")
    if not isinstance(order, dict):
        raise GraphQLError("no such order", 404)
    details = order.get("price_details") or {}
    products = []
    for p in order.get("products") or ():
        images = ((p.get("media") or {}).get("images") or [{}])
        products.append({"id": str(p.get("id") or ""), "name": p.get("name") or "",
                         "price": _int(p.get("price")), "currency": p.get("currency") or "",
                         "quantity": _int(p.get("quantity")),
                         "thumbnailUrl": (images[0] or {}).get("request_image_url") or ""})
    return {"createdAt": _int(order.get("creation_time_stamp")),
            "currency": details.get("currency") or "",
            "subtotal": _int(details.get("subtotal_amount")),
            "total": _int(details.get("total_amount")), "products": products}


def answer_errors(answer):
    """GraphQLError for an answer that carries errors, else None."""
    errors = (answer or {}).get("errors") if isinstance(answer, dict) else None
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        return GraphQLError(first.get("message") or "graphql error", first.get("code") or 0)
    return None


def post(doc_id, variables, http=None) -> dict:
    """One query; the decoded answer, or GraphQLError. Runs on a thread."""
    import requests
    http = http or requests
    try:
        response = http.post(ENDPOINT, data=json.dumps(request_body(doc_id, variables)),
                             headers={"Accept": "application/json",
                                      "Content-Type": "application/json"},
                             timeout=TIMEOUT)
        answer = response.json()
    except Exception as error:
        raise GraphQLError(f"catalog endpoint unreachable ({type(error).__name__})") from None
    error = answer_errors(answer)
    if error is not None:
        raise error
    if getattr(response, "status_code", 200) >= 400:
        raise GraphQLError("catalog endpoint refused", response.status_code)
    return answer


def place_order(seller_jid, items, http=None) -> dict:
    return placed_order(post(PLACE_ORDER_DOC, place_order_variables(seller_jid, items), http))


def get_catalog(seller_jid, limit, after="", http=None) -> tuple:
    return parsed_catalog(post(CATALOG_DOC, catalog_variables(seller_jid, limit, after), http))


def gone(error) -> bool:
    """The server could not answer for a product (one the catalog lost),
    not that the endpoint was unreachable."""
    return "field_exception" in str(error)


def get_products(seller_jid, product_ids, http=None) -> list:
    """The products of `product_ids` the seller's catalog still has."""
    ids = [str(i) for i in product_ids]
    try:
        return parsed_product_list(post(PRODUCT_LIST_DOC, product_list_variables(seller_jid, ids), http))
    except GraphQLError as error:
        if not ids or not gone(error):
            raise
        if len(ids) == 1:
            return []              # the catalog no longer has it
    found = []
    for one in ids:
        found += get_products(seller_jid, [one], http)
    return found


def get_order(seller_jid, order_id, token, http=None) -> dict:
    return order_info(post(GET_ORDER_DOC, get_order_variables(seller_jid, order_id, token), http))
