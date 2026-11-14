"""Mac verification failures retain their cause, stage and bounded retry policy.

No sockets, GUI or real sleep: a fake HTTPS opener models both architectures'
shared verification path, including a failure after some body bytes arrived.
"""

import io
import json
import pathlib
import socket
import ssl
import sys
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "macos"))
from winzapp_mac import provenance as P  # noqa: E402

URL = f"https://api.github.com/repos/{P.OFFICIAL_REPO}/git/ref/tags/v3.0.0.4573alpha"
ASSET = "https://github.com/rocco-labs/WinZapp_Python/releases/download/v3.0.0.4573alpha/provenance.json"


class Clock:
    now = 0.0
    sleeps = None

    def __init__(self):
        self.sleeps = []

    def monotonic(self):
        return self.now

    def time(self):
        return 1_800_000_000 + self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response(io.BytesIO):
    status = 200

    def __init__(self, body=b"{}", status=200, headers=None, fail_read=None):
        super().__init__(body)
        self.status, self.headers, self.fail_read = status, headers or {}, fail_read

    def geturl(self):
        return self.url

    def read1(self, size):
        if self.fail_read and self.tell():
            raise self.fail_read
        return self.read(min(size, 1) if self.fail_read else size)


class Opener:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        outcome.url = request.full_url
        return outcome


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(P, "time", clock)
    monkeypatch.setattr(P, "_RATE_LIMITS", {})
    return clock


def fetch_error(monkeypatch, clock, outcome, expected, attempts=1):
    opener = Opener(*[outcome() for _ in range(attempts)])
    monkeypatch.setattr(P, "_API_OPENER", opener)
    with pytest.raises(P.ProvenanceError) as caught:
        P.fetch_official(URL)
    assert caught.value.code == expected
    assert len(opener.calls) == attempts
    return caught.value


@pytest.mark.parametrize("make,code,attempts", [
    (lambda: urllib.error.URLError(socket.gaierror(-2, "private DNS text")), "dns", 2),
    (lambda: TimeoutError("private timeout text"), "timeout", 2),
    (lambda: urllib.error.URLError(ConnectionResetError("private proxy")), "connection", 2),
    (lambda: urllib.error.URLError(ssl.SSLCertVerificationError(1, "private certificate")), "tls", 1),
    (lambda: ssl.SSLError("private handshake"), "tls", 1),
    (lambda: RuntimeError("private internal detail"), "unexpected", 1),
    (lambda: urllib.error.HTTPError(URL, 403, "private reason", {}, None), "access_denied", 1),
    (lambda: urllib.error.HTTPError(URL, 404, "private reason", {}, None), "not_found", 1),
    (lambda: urllib.error.HTTPError(URL, 503, "private reason", {}, None), "server", 2),
    (lambda: Response(status=502), "server", 2),
])
def test_distinguishes_causes_without_exposing_exception_text(monkeypatch, clock, make, code, attempts):
    error = fetch_error(monkeypatch, clock, make, code, attempts)
    assert "private" not in str(error)
    assert clock.sleeps == ([1] if attempts == 2 else [])


def test_a_transient_failure_can_recover_with_one_retry(monkeypatch, clock):
    opener = Opener(TimeoutError(), Response(b"verified"))
    monkeypatch.setattr(P, "_API_OPENER", opener)
    assert P.fetch_official(URL) == b"verified"
    assert len(opener.calls) == 2
    assert all(call[1] <= P.TIMEOUT for call in opener.calls)


def test_retry_discards_a_partially_read_response(monkeypatch, clock):
    first = Response(b"old", fail_read=ConnectionResetError())
    opener = Opener(first, Response(b"fresh"))
    monkeypatch.setattr(P, "_API_OPENER", opener)
    assert P.fetch_official(URL) == b"fresh"
    assert first.closed


@pytest.mark.parametrize("status,headers,wait", [
    (429, {"Retry-After": "90"}, 90),
    (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000120"}, 120),
    (403, {"Retry-After": "30"}, 30),
    (429, {}, 60),
    (429, {"Retry-After": "invalid", "X-RateLimit-Reset": "private"}, 60),
])
def test_rate_limits_wait_without_retrying_or_hammering_other_tags(monkeypatch, clock, status, headers, wait):
    opener = Opener(urllib.error.HTTPError(URL, status, "limited", headers, None), Response())
    monkeypatch.setattr(P, "_API_OPENER", opener)
    for url in (URL, URL.replace("4573", "4574")):
        with pytest.raises(P.ProvenanceError) as caught:
            P.fetch_official(url)
        assert caught.value.code == "rate_limited"
        assert caught.value.retry_after == wait
    assert len(opener.calls) == 1 and clock.sleeps == []
    clock.now += wait
    assert P.fetch_official(URL) == b"{}"


def test_a_rate_limit_on_api_does_not_block_the_release_asset_host(monkeypatch, clock):
    api = Opener(Response(status=429, headers={"Retry-After": "60"}))
    asset = Opener(Response(b"asset"))
    monkeypatch.setattr(P, "_API_OPENER", api)
    monkeypatch.setattr(P, "_ASSET_OPENER", asset)
    with pytest.raises(P.ProvenanceError):
        P.fetch_official(URL)
    assert P.fetch_release_asset(ASSET) == b"asset"


def test_no_retry_after_request_budget_is_spent(monkeypatch, clock):
    class SlowOpener(Opener):
        def open(self, request, timeout):
            clock.now += P.DEADLINE
            return super().open(request, timeout)
    opener = SlowOpener(TimeoutError())
    monkeypatch.setattr(P, "_API_OPENER", opener)
    with pytest.raises(P.ProvenanceError) as caught:
        P.fetch_official(URL)
    assert caught.value.code == "timeout"
    assert len(opener.calls) == 1 and clock.sleeps == []


def test_the_second_attempt_only_gets_the_remaining_budget(monkeypatch, clock):
    class SlowFirstAttempt(Opener):
        def open(self, request, timeout):
            if not self.calls:
                clock.now += 20
            return super().open(request, timeout)
    opener = SlowFirstAttempt(TimeoutError(), Response(b"ok"))
    monkeypatch.setattr(P, "_API_OPENER", opener)
    assert P.fetch_official(URL) == b"ok"
    assert [call[1] for call in opener.calls] == [15, 9]


def test_failure_metadata_survives_the_verification_result(monkeypatch, clock):
    raw = json.dumps({"schema": 1, "version": "v3.0.0.4573alpha", "source_repo": P.OFFICIAL_REPO,
                      "source_commit": "a" * 40, "artifacts": {"app.zip": "b" * 64}}).encode()
    def failed(url):
        raise P.ProvenanceError("safe", code="tls")
    ok, detail = P.verify_release(raw, "v3.0.0.4573alpha", "v3.0.0.4557alpha", failed)
    assert not ok and isinstance(detail, str)
    assert (detail.code, detail.stage) == ("tls", "official_tag")


@pytest.mark.parametrize("stage", ["official_tag", "verification_file"])
def test_each_language_explains_the_stage_and_rate_limit_without_raw_exception(stage):
    from tests.locales import load_strings, registered_locale_codes
    from winzapp_mac.provenance_messages import user_detail

    detail = P.ProvenanceError("raw technical text", code="rate_limited", retry_after=90).detail(stage)
    for locale in registered_locale_codes():
        strings = load_strings(locale)
        text = user_detail(detail, strings.__getitem__)
        assert "90" in text and "raw technical text" not in text
        assert strings["mac_update_verify_rate_limited"] in text
        assert "{" not in text and "mac_update_verify_" not in text


def test_non_network_refusals_keep_the_existing_reason():
    from winzapp_mac.provenance_messages import user_detail
    assert user_detail("the tag points at another commit", lambda key: pytest.fail(key)) == (
        "the tag points at another commit")


def test_retry_after_date_and_quota_reset_use_the_longer_wait(monkeypatch, clock):
    from email.utils import formatdate
    headers = {"Retry-After": formatdate(clock.time() + 90, usegmt=True),
               "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(clock.time() + 120))}
    error = fetch_error(monkeypatch, clock,
                        lambda: urllib.error.HTTPError(URL, 403, "limited", headers, None), "rate_limited")
    assert error.retry_after == 120


def test_server_retry_after_is_shown_without_an_early_retry(monkeypatch, clock):
    from tests.locales import load_strings
    from winzapp_mac.provenance_messages import user_detail
    error = fetch_error(monkeypatch, clock,
                        lambda: urllib.error.HTTPError(URL, 503, "busy", {"Retry-After": "90"}, None),
                        "server")
    assert error.retry_after == 90 and clock.sleeps == []
    text = user_detail(error.detail("official_tag"), load_strings("en-US").__getitem__)
    assert "90 seconds" in text and "server error" in text


@pytest.mark.parametrize("status", [301, 302, 401, 404])
def test_http_refusals_do_not_trigger_retry(monkeypatch, clock, status):
    opener = Opener(urllib.error.HTTPError(URL, status, "do not retry", {}, None))
    monkeypatch.setattr(P, "_API_OPENER", opener)
    with pytest.raises(P.ProvenanceError):
        P.fetch_official(URL)
    assert len(opener.calls) == 1 and not clock.sleeps
