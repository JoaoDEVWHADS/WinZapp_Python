"""The business IQs: what is asked and how the answers are read."""
import base64

import biz_iq


def t(tag, text=None, attrs=None, children=None):
    """An answer node as send_iq gives it: text arrives as base64 bytes."""
    node = {"tag": tag}
    if attrs:
        node["attrs"] = attrs
    if children is not None:
        node["content"] = children
    elif text is not None:
        node["content"] = {"bytes": base64.b64encode(text.encode()).decode()}
    return node


def product(pid="1", hidden=False, price="7500", images=1, **extra):
    media = [t("image", children=[t("id", f"img{i}"), t("request_image_url", f"req{i}"),
                                  t("original_image_url", f"full{i}")]) for i in range(images)]
    children = [t("id", pid), t("name", "Pão"), t("description", "Fresco"), t("price", price),
                t("currency", "BRL"), t("retailer_id", "SKU1"), t("url", "https://x"),
                t("media", children=media),
                t("status_info", children=[t("status", "APPROVED")])]
    attrs = {"is_hidden": "true" if hidden else "false", **extra}
    return t("product", attrs=attrs, children=children)


def test_the_catalog_query_is_baileys():
    query = biz_iq.catalog_query("5511@s.whatsapp.net", 500, after="c1")
    assert (query["namespace"], query["type"]) == ("w:biz:catalog", "get")
    (catalog,) = query["content"]
    assert catalog["attrs"] == {"jid": {"jid": "5511@s.whatsapp.net"}, "allow_shop_source": "true"}
    assert [(c["tag"], c["content"]) for c in catalog["content"]] == [
        ("limit", "100"), ("width", "100"), ("height", "100"), ("after", "c1")]


def test_the_product_list_and_collections_carry_their_smax_id():
    query = biz_iq.product_list_query("5511@s.whatsapp.net", ["a", "b"])
    assert query["smax_id"] == "21"
    ids = [p["content"][0]["content"] for p in query["content"][0]["content"] if p["tag"] == "product"]
    assert ids == ["a", "b"]
    query = biz_iq.collections_query("5511@s.whatsapp.net", 3, 4)
    assert query["smax_id"] == "35"
    assert query["content"][0]["attrs"] == {"biz_jid": {"jid": "5511@s.whatsapp.net"}}


def test_the_business_profile_query_is_whatsapp_webs():
    query = biz_iq.business_profile_query(["5511@s.whatsapp.net"])
    assert (query["namespace"], query["type"]) == ("w:biz", "get")
    assert query["content"][0]["attrs"] == {"v": "116"}
    assert query["content"][0]["content"] == [
        {"tag": "profile", "attrs": {"jid": {"jid": "5511@s.whatsapp.net"}}}]


def test_a_product_is_read_with_whatsapp_webs_names():
    p = biz_iq.parse_product(product(images=2, availability="in stock", max_available="5"))
    assert p["id"] == "1" and p["name"] == "Pão" and p["price"] == "7500"
    assert p["availability"] == "in stock" and p["max_available"] == 5
    assert p["image_cdn_urls"] == [{"key": "requested", "value": "req0"},
                                   {"key": "full", "value": "full0"}]
    assert p["additional_image_cdn_urls"] == [[{"key": "requested", "value": "req1"},
                                               {"key": "full", "value": "full1"}]]
    assert p["capability_to_review_status"] == [{"key": "WHATSAPP", "value": "APPROVED"}]
    assert biz_iq.parse_product(product(hidden=True))["is_hidden"] is True


def test_catalog_paging_and_a_product_the_catalog_no_longer_has():
    answer = t("iq", children=[t("product_catalog", children=[
        product("1"), product("2"), t("paging", children=[t("after", "next")])])])
    products, after = biz_iq.parse_catalog(answer)
    assert [p["id"] for p in products] == ["1", "2"] and after == "next"
    gone = t("product", children=[t("id", "3"), t("status", "INVALID_PRODUCT")])
    answer = t("iq", children=[t("product_list", children=[product("1"), gone])])
    assert [p["id"] for p in biz_iq.parse_product_list(answer)] == ["1"]


def test_collections():
    answer = t("iq", children=[t("collections", children=[t("collection", children=[
        t("id", "c1"), t("name", "Pães"), product("1"),
        t("status_info", children=[t("status", "APPROVED"), t("can_appeal", "false")])])])])
    (collection,) = biz_iq.parse_collections(answer)
    assert (collection["id"], collection["name"], collection["status"]) == ("c1", "Pães", "APPROVED")
    assert [p["id"] for p in collection["products"]] == ["1"]


def test_product_writes():
    node = biz_iq.product_node({"name": "Pão", "price": 7500, "currency": "BRL",
                                "images": ["https://mmg.whatsapp.net/x"], "is_hidden": False}, "9")
    assert node["attrs"] == {"is_hidden": "false"}
    assert [c["tag"] for c in node["content"]] == ["id", "name", "media", "price", "currency"]
    query = biz_iq.product_write_query("edit", node)
    assert query["type"] == "set" and query["content"][0]["tag"] == "product_catalog_edit"
    assert query["content"][0]["attrs"] == {"v": "1"}
    answer = t("iq", children=[t("product_catalog_edit", children=[product("9")])])
    assert biz_iq.parse_product_write(answer, "edit")["id"] == "9"
    delete = biz_iq.product_delete_query(["1", "2"])
    assert delete["content"][0]["tag"] == "product_catalog_delete"
    answer = t("iq", children=[t("product_catalog_delete", attrs={"deleted_count": "2"})])
    assert biz_iq.parse_deleted(answer) == 2


def test_the_business_profile_edit_is_a_delta():
    query = biz_iq.business_profile_edit_query({"description": "Padaria", "websites": ["https://a"],
                                                "cart_enabled": True})
    (profile,) = query["content"]
    assert profile["attrs"] == {"v": "3", "mutation_type": "delta"}
    assert [c["tag"] for c in profile["content"]] == ["description", "website", "profile_options"]
    assert profile["content"][2]["content"] == [{"tag": "cart_enabled", "content": "true"}]


def test_a_business_profile_and_its_catalog():
    answer = t("iq", children=[t("business_profile", children=[t("profile", attrs={
        "jid": "5511@s.whatsapp.net", "tag": "1"}, children=[
        t("description", "Padaria"), t("website", "https://a"),
        t("profile_options", children=[t("commerce_experience", "catalog"),
                                       t("cart_enabled", "true")]),
        t("business_hours", attrs={"timezone": "America/Sao_Paulo"}, children=[
            t("business_hours_config", attrs={"day_of_week": "mon", "mode": "open_24h"})])])])])
    (profile,) = biz_iq.parse_business_profiles(answer)
    assert profile["description"] == "Padaria" and profile["website"] == [{"url": "https://a"}]
    assert profile["profileOptions"] == {"commerceExperience": "catalog", "cartEnabled": True}
    assert profile["businessHours"]["config"][0]["day_of_week"] == "mon"
    assert biz_iq.has_catalog(profile)


def test_whatsapp_webs_rule_for_a_catalog():
    assert biz_iq.has_catalog({"catalogStatus": "catalog_exists"})
    assert biz_iq.has_catalog({"profileOptions": {"commerceExperience": "smb_meta_catalog"}})
    assert not biz_iq.has_catalog({"profileOptions": {"commerceExperience": "none"}})
    assert not biz_iq.has_catalog({})
