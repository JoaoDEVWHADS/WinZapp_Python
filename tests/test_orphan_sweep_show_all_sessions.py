"""The orphan sweep lists server sessions the way WPPConnect Server 2.10.70
accepts: POST /api/show-all-sessions with the secret in `x-secret-key`.

The URL form (`GET /api/<key>/show-all-sessions`) answers 410 from 2.10.70 on,
which would silently turn the sweep into "skipping" under a custom API. A
remote server still on an older release answers 404, so the sweep falls back.
"""

import types

from main_window import wpp_server
from main_window.wpp_server import WppServerMixin


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def _stub():
    return types.SimpleNamespace(
        wpp_server="http://remote", wpp_port=6300, wpp_api_key="SECRET",
        token="mine:tok", _shutdown_audit=lambda line: None,
    )


def _run(monkeypatch, post, get):
    monkeypatch.setattr(wpp_server, "api_post", post)
    monkeypatch.setattr(wpp_server, "api_get", get)
    WppServerMixin._close_orphaned_server_sessions(_stub())


def test_the_listing_is_a_post_with_the_secret_in_a_header(monkeypatch):
    posts = []

    def post(url, **kwargs):
        posts.append((url, kwargs.get("headers", {})))
        return _Resp(200, {"response": []})

    def get(url, **kwargs):
        raise AssertionError("the URL form answers 410 on 2.10.70")

    _run(monkeypatch, post, get)

    assert posts[0][0] == "http://remote:6300/api/show-all-sessions"
    assert posts[0][1]["x-secret-key"] == "SECRET"
    assert "SECRET" not in posts[0][0]


def test_an_older_server_without_the_post_route_is_listed_the_old_way(monkeypatch):
    gets = []

    def post(url, **kwargs):
        return _Resp(404)

    def get(url, **kwargs):
        gets.append(url)
        return _Resp(200, {"response": []})

    _run(monkeypatch, post, get)

    assert gets == ["http://remote:6300/api/SECRET/show-all-sessions"]


def test_a_gone_answer_is_not_retried_with_the_url_form(monkeypatch):
    def post(url, **kwargs):
        return _Resp(410)

    def get(url, **kwargs):
        raise AssertionError("410 means the URL form is gone")

    _run(monkeypatch, post, get)
