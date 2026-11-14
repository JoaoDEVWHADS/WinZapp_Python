"""The unencrypted upload of a catalog product's picture."""
import base64
import hashlib
from types import SimpleNamespace as N

import pytest

import media_upload as mu


def test_the_token_is_the_urlsafe_sha256():
    data = b"jpeg"
    assert mu.upload_token(data) == base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode()


def test_the_upload_url_is_the_product_image_path():
    url = mu.upload_url("mmg.whatsapp.net", "AUTH", b"jpeg")
    token = mu.upload_token(b"jpeg")
    assert url.startswith(f"https://mmg.whatsapp.net/product/image/{token}?")
    assert "auth=AUTH" in url and "token=" in url


def test_the_picture_url_is_the_direct_path_on_mmg():
    assert mu.picture_url({"direct_path": "/v/t1/x"}) == "https://mmg.whatsapp.net/v/t1/x"
    with pytest.raises(mu.UploadError):
        mu.picture_url({"url": "x"})


class Client:
    def __init__(self, answers):
        self.answers, self.forced = list(answers), []

    def media_conn(self, force=False):
        self.forced.append(force)
        return self.answers.pop(0)


class Http:
    def __init__(self, answer, status=200):
        self.answer, self.status, self.posts = answer, status, []

    def post(self, url, data, timeout, headers):
        self.posts.append((url, data, headers))
        return N(status_code=self.status, json=lambda: self.answer)


def test_upload_asks_again_for_a_fresh_connection_when_the_first_has_no_host():
    client = Client([{"error": "x"}, {"auth": "A", "hosts": ["h1", "h2"]}])
    http = Http({"direct_path": "/p"})
    assert mu.upload_product_image(client, b"jpeg", http) == "https://mmg.whatsapp.net/p"
    assert client.forced == [False, True]
    url, data, headers = http.posts[0]
    assert url.startswith("https://h1/product/image/") and data == b"jpeg"
    assert headers["Origin"] == "https://web.whatsapp.com"


def test_upload_refusals():
    with pytest.raises(mu.UploadError):
        mu.upload_product_image(N(), b"x", Http({}))
    client = Client([{"auth": "A", "hosts": ["h"]}])
    with pytest.raises(mu.UploadError):
        mu.upload_product_image(client, b"x", Http({}, status=403))
