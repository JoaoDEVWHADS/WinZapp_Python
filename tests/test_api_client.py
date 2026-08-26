"""Tests for core/api_client.py — the single door to the embedded Node API.

Two things this exists to guarantee, both of which the 74 hand-rolled call
sites in main.py could not:

1. Every request carries an X-Request-Id, so a line in log.log and a line in
   wppconnect.log can be matched up. The Node middleware already generates one
   when the header is absent; it just never had one handed to it.

2. No URL is ever logged in full. WPPConnect authenticates by putting
   <session>:<token> in the PATH, so logging a URL publishes the credential
   that authorises every other call — and log.log is the file users are asked
   to send when something breaks. The log this replaces had 2,360 such lines.
"""

import logging

import pytest
import requests

from core.api_client import (
    api_get,
    api_headers,
    api_post,
    api_request,
    new_request_id,
    redact_api_url,
    redact_token,
)

TOKEN = "$2b$10$RlaSnVmEmmflWvfGGED9xe2xG_5UKxFoeyhB1zz6B._nbf4YOnfBi"
SESSION = "b5f5395519a599e1b7ca3d93817a815d"
URL = f"http://127.0.0.1:6300/api/{SESSION}:{TOKEN}/get-messages/5511@c.us?count=200"


class _Response:
    status_code = 200


class _Session:
    """Stands in for requests, recording what it was asked to do."""

    def __init__(self, exc=None):
        self.calls = []
        self._exc = exc

    def get(self, url, **kwargs):
        return self._record("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._record("POST", url, kwargs)

    def _record(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if self._exc:
            raise self._exc
        return _Response()


class TestTheCredentialNeverReachesTheLog:
    def test_the_token_is_stripped_from_a_logged_url(self):
        label = redact_api_url(URL)

        assert TOKEN not in label
        assert SESSION not in label
        assert label == "/get-messages/5511@c.us?count=200"

    def test_a_real_request_logs_no_token(self, caplog):
        session = _Session()

        with caplog.at_level(logging.INFO):
            api_request("GET", URL, token="tok", session=session)

        assert TOKEN not in caplog.text
        assert SESSION not in caplog.text
        assert "get-messages" in caplog.text

    def test_a_failed_request_logs_no_token_either(self, caplog):
        """The failure path is the one that gets pasted into a bug report."""
        session = _Session(exc=requests.ConnectionError("boom"))

        with caplog.at_level(logging.WARNING):
            with pytest.raises(requests.ConnectionError):
                api_request("POST", URL, token="tok", session=session)

        assert TOKEN not in caplog.text
        assert "boom" in caplog.text

    def test_a_non_api_url_is_still_reduced_to_its_path(self):
        assert redact_api_url("http://127.0.0.1:6300/healthz") == "/healthz"

    def test_an_empty_url_does_not_crash(self):
        assert redact_api_url("") == ""

    def test_redact_token_keeps_the_session_masks_the_secret(self):
        label = redact_token(f"{SESSION}:{TOKEN}")

        assert label == f"{SESSION}:***"
        assert TOKEN not in label

    def test_redact_token_on_an_empty_token_does_not_crash(self):
        assert redact_token("") == ""


class TestCorrelation:
    def test_every_request_carries_an_id(self):
        session = _Session()

        api_get(URL, token="tok", session=session)

        _method, _url, kwargs = session.calls[0]
        assert kwargs["headers"]["X-Request-Id"]

    def test_a_supplied_id_is_the_one_sent(self):
        session = _Session()

        api_post(URL, token="tok", request_id="abc123", session=session)

        assert session.calls[0][2]["headers"]["X-Request-Id"] == "abc123"

    def test_the_same_id_appears_in_the_log(self, caplog):
        session = _Session()

        with caplog.at_level(logging.INFO):
            api_get(URL, token="tok", request_id="abc123", session=session)

        assert "rid=abc123" in caplog.text

    def test_the_generated_id_is_one_the_node_side_accepts(self):
        """The middleware only honours /^[A-Za-z0-9._:-]{1,128}$/ and silently
        substitutes its own otherwise — which would break correlation with
        nothing to say why."""
        import re

        for _ in range(20):
            assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", new_request_id())


class TestTheHeaders:
    def test_it_authorises_and_correlates(self):
        headers = api_headers("tok", request_id="abc")

        assert headers["Authorization"] == "Bearer tok"
        assert headers["X-Request-Id"] == "abc"
        assert headers["Content-Type"] == "application/json"

    def test_a_body_less_request_asks_for_no_json_content_type(self):
        assert "Content-Type" not in api_headers("tok", json_body=False)

    def test_caller_supplied_headers_are_kept(self):
        session = _Session()

        api_get(URL, token="tok", session=session,
                headers={"Authorization": "Bearer other", "X-Custom": "1"})

        sent = session.calls[0][2]["headers"]
        assert sent["Authorization"] == "Bearer other"  # not overwritten
        assert sent["X-Custom"] == "1"
        assert sent["X-Request-Id"]


class TestTheDurationIsReported:
    def test_a_normal_call_logs_at_info(self, caplog):
        session = _Session()

        with caplog.at_level(logging.INFO):
            api_get(URL, token="tok", session=session)

        assert "-> 200 in" in caplog.text
        assert "WARNING" not in caplog.text

    def test_a_slow_call_is_a_warning(self, caplog, monkeypatch):
        """This is the loopback: a call this slow means the page or Puppeteer
        is busy, which is the thing worth noticing."""
        import core.api_client as mod

        ticks = iter([0.0, 5.0])
        monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))
        session = _Session()

        with caplog.at_level(logging.INFO):
            api_get(URL, token="tok", session=session)

        assert "WARNING" in caplog.text


class TestItStaysOutOfTheCallersWay:
    def test_the_exception_reaches_the_caller_unchanged(self):
        """Retry policy stays where the knowledge is: message_queue treats an
        ambiguous timeout differently from a definite failure on purpose."""
        session = _Session(exc=requests.Timeout("slow"))

        with pytest.raises(requests.Timeout):
            api_get(URL, token="tok", session=session)

    def test_extra_kwargs_are_passed_through(self):
        session = _Session()

        api_post(URL, token="tok", session=session, json={"a": 1}, stream=True)

        kwargs = session.calls[0][2]
        assert kwargs["json"] == {"a": 1}
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == 30
