"""The unencrypted upload of a catalog product's picture, as WhatsApp Web does
it (WAWebMediaProduct.uploadProductImage -> WAWebUploadManager.
unencryptedUpload, type PRODUCT_CATALOG_IMAGE; read over CDP on 2026-10-26):
the JPEG goes as it is to https://<media host>/product/image/<token>?auth=..
&token=.., the token being the URL-safe base64 of its SHA-256, and the
product points at https://mmg.whatsapp.net<direct_path> of the answer.

The host and auth come from whatsmeow's media connection (`media_conn`,
WinZapp's neonize build). Baileys uploads the same way (Defaults:
'product-catalog-image': '/product/image').
"""
import base64
import hashlib
from urllib.parse import urlencode

PATH = "/product/image"
URL_BASE = "https://mmg.whatsapp.net"
ORIGIN = "https://web.whatsapp.com"
TIMEOUT = 60


class UploadError(Exception):
    pass


def upload_token(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii")


def upload_url(host, auth, data: bytes) -> str:
    token = upload_token(data)
    return f"https://{host}{PATH}/{token}?" + urlencode({"auth": auth, "token": token})


def picture_url(answer) -> str:
    """The product's picture URL from the upload's answer."""
    path = (answer or {}).get("direct_path") if isinstance(answer, dict) else None
    if not isinstance(path, str) or not path.startswith("/"):
        raise UploadError("the upload gave no path")
    return URL_BASE + path


def upload_product_image(client, data: bytes, http=None) -> str:
    """Uploads the JPEG `data`; its URL for the product. Runs on a thread."""
    import requests
    http = http or requests
    if not hasattr(client, "media_conn"):
        raise UploadError("this neonize build cannot upload a product picture")
    conn = client.media_conn()
    if conn.get("error") or not conn.get("hosts"):
        conn = client.media_conn(True)
    hosts = conn.get("hosts") or []
    if not hosts or not conn.get("auth"):
        raise UploadError("no media host")
    response = http.post(upload_url(hosts[0], conn["auth"], data), data=data, timeout=TIMEOUT,
                         headers={"Origin": ORIGIN, "Content-Type": "application/octet-stream"})
    try:
        answer = response.json()
    except ValueError:
        answer = None
    if getattr(response, "status_code", 200) >= 400:
        raise UploadError(f"upload refused ({response.status_code})")
    return picture_url(answer)
