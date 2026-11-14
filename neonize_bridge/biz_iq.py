"""The business info queries (IQ) of catalogs, products, collections and
business profiles, and what their answers mean.

Sources (2026-10-26):

- the queries are Baileys' (src/Socket/business.ts, still maintained and in
  use): `w:biz:catalog` product_catalog, collections (smax_id 35),
  product_catalog_add / _edit / _delete, and `w:biz` business_profile with
  mutation_type "delta" to edit one;
- WhatsApp Web's own IQs read over CDP: the product list (smax_id 21,
  WAWebQueryProductListCatalogJob, the fallback of its GraphQL query), the
  business profile query (WAWebQueryBusinessProfileJob, v=116 on a personal
  account), and how both answers are read (WAWebBizCatalogParseProduct,
  WAWebCommonParsersParseBusinessProfile), whose field names the parsed
  products keep (they are WPPConnect's too);
- WhatsApp Web now edits a catalog through GraphQL with a Facebook ad account
  token; the IQs above are the path every other client still uses.

Pure: builds query dictionaries for raw_queries.send_iq and reads its answers.
"""
import raw_queries as rq

CATALOG_NS = "w:biz:catalog"
PROFILE_NS = "w:biz"
PROFILE_QUERY_VERSION = "116"    # WAWebBusinessProfileVersioningBridge on a personal account
PRODUCT_LIST_SMAX = "21"         # WAWapDeprecatedSmaxID.CatalogGetProductList
COLLECTIONS_SMAX = "35"          # WAWapDeprecatedSmaxID.CatalogGetCollections
IMAGE_SIDE = "100"
MAX_PRODUCTS = 100


def _n(tag, value=None, attrs=None):
    return rq.node(tag, attrs, None if value is None else str(value))


# ------------------------------------------------------------------ queries
def catalog_query(catalog_jid, limit=10, after="") -> dict:
    content = [_n("limit", max(1, min(int(limit or 10), MAX_PRODUCTS))),
               _n("width", IMAGE_SIDE), _n("height", IMAGE_SIDE)]
    if after:
        content.append(_n("after", after))
    return {"namespace": CATALOG_NS, "type": "get", "content": [rq.node(
        "product_catalog", {"jid": rq.jid(catalog_jid), "allow_shop_source": "true"}, content)]}


def product_list_query(catalog_jid, product_ids) -> dict:
    products = [rq.node("product", None, [_n("id", pid)]) for pid in product_ids]
    return {"namespace": CATALOG_NS, "type": "get", "smax_id": PRODUCT_LIST_SMAX, "content": [
        rq.node("product_list", {"jid": rq.jid(catalog_jid)},
                products + [_n("width", IMAGE_SIDE), _n("height", IMAGE_SIDE)])]}


def collections_query(catalog_jid, collection_limit=10, item_limit=10) -> dict:
    return {"namespace": CATALOG_NS, "type": "get", "smax_id": COLLECTIONS_SMAX, "content": [
        rq.node("collections", {"biz_jid": rq.jid(catalog_jid)}, [
            _n("collection_limit", collection_limit), _n("item_limit", item_limit),
            _n("width", IMAGE_SIDE), _n("height", IMAGE_SIDE)])]}


def business_profile_query(jids) -> dict:
    return {"namespace": PROFILE_NS, "type": "get", "content": [rq.node(
        "business_profile", {"v": PROFILE_QUERY_VERSION},
        [rq.node("profile", {"jid": rq.jid(j)}) for j in jids])]}


# ---------------------------------------------------------- catalog writes
def product_node(fields, product_id=None) -> dict:
    """A <product> of product_catalog_add / _edit (Baileys' toProductNode).
    `fields`: name, description, retailer_id, url, images ([url, ...]),
    price (thousandths), currency, is_hidden."""
    content, attrs = [], {}
    if product_id is not None:
        content.append(_n("id", product_id))
    for key in ("name", "description", "retailer_id", "url"):
        if fields.get(key) is not None:
            content.append(_n(key, fields[key]))
    images = fields.get("images")
    if images:
        content.append(rq.node("media", None, [
            rq.node("image", None, [_n("url", url)]) for url in images]))
    if fields.get("price") is not None:
        content.append(_n("price", int(fields["price"])))
    if fields.get("currency") is not None:
        content.append(_n("currency", fields["currency"]))
    if fields.get("is_hidden") is not None:
        attrs["is_hidden"] = "true" if fields["is_hidden"] else "false"
    return rq.node("product", attrs or None, content)


def product_write_query(kind, product) -> dict:
    """kind: "add" or "edit"."""
    return {"namespace": CATALOG_NS, "type": "set", "content": [rq.node(
        f"product_catalog_{kind}", {"v": "1"},
        [product, _n("width", IMAGE_SIDE), _n("height", IMAGE_SIDE)])]}


def product_delete_query(product_ids) -> dict:
    return {"namespace": CATALOG_NS, "type": "set", "content": [rq.node(
        "product_catalog_delete", {"v": "1"},
        [rq.node("product", None, [_n("id", pid)]) for pid in product_ids])]}


def business_profile_edit_query(changes) -> dict:
    """`changes`: address, email, description (text), websites ([url]),
    cart_enabled (bool). Only what is given is sent ("delta")."""
    content = [_n(key, changes[key]) for key in ("address", "email", "description")
               if changes.get(key) is not None]
    for url in changes.get("websites") or ():
        content.append(_n("website", url))
    if changes.get("cart_enabled") is not None:
        content.append(rq.node("profile_options", None, [
            _n("cart_enabled", "true" if changes["cart_enabled"] else "false")]))
    return {"namespace": PROFILE_NS, "type": "set", "content": [rq.node(
        "business_profile", {"v": "3", "mutation_type": "delta"}, content)]}


# ----------------------------------------------------------------- answers
def _images(media):
    """(image_cdn_urls, additional_image_cdn_urls, image ids) as WhatsApp Web keeps them."""
    first, more, ids = [], [], []
    for image in rq.children(media, "image"):
        urls = [{"key": "requested", "value": rq.child_text(image, "request_image_url")},
                {"key": "full", "value": rq.child_text(image, "original_image_url")}]
        if not first:
            first = urls
        else:
            more.append(urls)
        ids.append(rq.child_text(image, "id"))
    return first, more, ids


def parse_product(node) -> dict:
    """A <product> answer, with WhatsApp Web's field names
    (WAWebBizCatalogParseProduct); price in thousandths, as a string."""
    first, more, ids = _images(rq.child(node, "media"))
    status = rq.child(node, "status_info")
    review = rq.child_text(status, "status") if status else ""
    max_available = rq.attr(node, "max_available") or rq.child_text(node, "max_available")
    return {
        "id": rq.child_text(node, "id"),
        "is_hidden": rq.attr(node, "is_hidden") == "true",
        "url": rq.child_text(node, "url"),
        "name": rq.child_text(node, "name"),
        "description": rq.child_text(node, "description"),
        "availability": rq.attr(node, "availability") or "unknown",
        "max_available": int(max_available) if max_available.isdigit() else 99,
        "image_cdn_urls": first,
        "additional_image_cdn_urls": more,
        "image_hashes_for_whatsapp": ids,
        "capability_to_review_status": [{"key": "WHATSAPP", "value": review or "APPROVED"}],
        "currency": rq.child_text(node, "currency") or None,
        "price": rq.child_text(node, "price") or None,
        "retailer_id": rq.child_text(node, "retailer_id"),
    }


def parse_catalog(response) -> tuple:
    """([products], next page cursor) of a product_catalog answer."""
    catalog = rq.child(response, "product_catalog")
    products = [parse_product(p) for p in rq.children(catalog, "product")]
    paging = rq.child(catalog, "paging")
    return products, rq.child_text(paging, "after") if paging else ""


def parse_product_list(response) -> list:
    """The products of a product_list answer; one the catalog no longer has
    ("INVALID_PRODUCT") is left out."""
    products = []
    for node in rq.children(rq.child(response, "product_list"), "product"):
        if rq.child_text(node, "status") == "INVALID_PRODUCT" or not rq.child(node, "name"):
            continue
        products.append(parse_product(node))
    return products


def parse_collections(response) -> list:
    out = []
    for node in rq.children(rq.child(response, "collections"), "collection"):
        status = rq.child(node, "status_info")
        out.append({"id": rq.child_text(node, "id"), "name": rq.child_text(node, "name"),
                    "products": [parse_product(p) for p in rq.children(node, "product")],
                    "status": rq.child_text(status, "status") if status else "",
                    "canAppeal": rq.child_text(status, "can_appeal") == "true"})
    return out


def parse_product_write(response, kind) -> dict:
    """The product a product_catalog_add / _edit answered, or {}."""
    product = rq.child(rq.child(response, f"product_catalog_{kind}"), "product")
    return parse_product(product) if product else {}


def parse_deleted(response) -> int:
    count = rq.attr(rq.child(response, "product_catalog_delete"), "deleted_count", "0")
    return int(count) if count.isdigit() else 0


def parse_business_profile(profile) -> dict:
    """One <profile> of a business_profile answer, as WhatsApp Web keeps it
    (WAWebCommonParsersParseBusinessProfile), WPPConnect's field names."""
    options = rq.child(profile, "profile_options")
    categories = rq.child(profile, "categories")
    hours = rq.child(profile, "business_hours")
    catalog = rq.child(profile, "catalog_status")
    out = {
        "id": rq.attr(profile, "jid"),
        "tag": rq.attr(profile, "tag"),
        "address": rq.child_text(profile, "address") or None,
        "description": rq.child_text(profile, "description") or None,
        "email": rq.child_text(profile, "email") or None,
        "website": [{"url": rq.text(w)} for w in rq.children(profile, "website")],
        "categories": [{"id": rq.attr(c, "id"), "localized_display_name": rq.text(c)}
                       for c in rq.children(categories, "category")] if categories else [],
        "catalogStatus": rq.attr(catalog, "status") if catalog else None,
        "profileOptions": {
            "commerceExperience": rq.child_text(options, "commerce_experience") or "none",
            "cartEnabled": rq.child_text(options, "cart_enabled") == "true",
        } if options else {},
    }
    if hours:
        out["businessHours"] = {"timezone": rq.attr(hours, "timezone") or None, "config": [
            {"day_of_week": rq.attr(c, "day_of_week"), "mode": rq.attr(c, "mode"),
             "open_time": int(rq.attr(c, "open_time", "0") or 0),
             "close_time": int(rq.attr(c, "close_time", "0") or 0)}
            for c in rq.children(hours, "business_hours_config")]}
    return out


def parse_business_profiles(response) -> list:
    return [parse_business_profile(p)
            for p in rq.children(rq.child(response, "business_profile"), "profile")]


def has_catalog(profile) -> bool:
    """Does the business have a catalog to show? WhatsApp Web's rule
    (WAWebBusinessProfileUtils.hasCatalog): a catalog commerce experience, or
    catalog_status "catalog_exists"."""
    profile = profile or {}
    experience = (profile.get("profileOptions") or {}).get("commerceExperience")
    return experience in ("catalog", "smb_meta_catalog") or \
        profile.get("catalogStatus") == "catalog_exists"
