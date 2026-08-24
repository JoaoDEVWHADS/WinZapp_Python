"""One way in and out of WinZapp's embedded Node API.

Today there are 74 places in main.py that call the local WPPConnect server, 59
of which build the same Authorization header by hand. Each of them decides for
itself what to log, how long to wait, and what a failure means — which is why
the same class of problem keeps having to be diagnosed from scratch every time,
and why two of the bugs open right now (a status reply that failed once and
worked seconds later; a sync that is slow somewhere between Python and the
page) have no evidence to work from.

WHAT THIS ADDS

*Correlation.* Every request carries an `X-Request-Id`. The Node side already
generates one when the header is absent and threads it through its own logger
(see requestInstrumentation in src/middleware/instrumentation.ts) — it simply
never had one handed to it. With the header sent from here, a line in log.log
and a line in wppconnect.log can finally be matched up.

*Duration.* Each call logs how long it took, so "the sync is slow" can name
which endpoint.

*A redacted URL.* This matters more than it looks. WPPConnect authenticates by
putting `<session>:<token>` in the PATH, so every URL logged in full publishes
the token that authorises every other call. The current log has 2,360 such
lines — in the file users are asked to send when something breaks. Nothing here
ever logs a full URL.

WHAT THIS DELIBERATELY DOES NOT DO

No retries and no error translation. Callers already implement their own retry
policies, and those policies encode real knowledge — message_queue treats an
ambiguous timeout differently from a definite failure precisely because
retrying the ambiguous case used to duplicate real sends. A blanket retry here
would quietly undo that.
"""

import logging
import time
import uuid

import requests

# The Node middleware only accepts an id matching /^[A-Za-z0-9._:-]{1,128}$/ and
# silently generates its own otherwise, which would break correlation without
# anything saying so. A uuid4 hex is inside that set by construction.
_REQUEST_ID_HEADER = "X-Request-Id"

# Anything slower than this is worth a warning rather than an info line: it is
# the local loopback, so a call this slow means the page (or Puppeteer) is
# busy, which is the thing worth noticing.
SLOW_REQUEST_SECONDS = 2.0


def new_request_id() -> str:
    """A correlation id both sides accept."""
    return uuid.uuid4().hex


def redact_api_url(url: str) -> str:
    """A log-safe label for an API URL: no token, just the endpoint.

    WPPConnect's routes are /api/<session>:<token>/<endpoint>/..., so the
    credential sits in the path rather than a header. Everything before the
    endpoint is dropped, and what remains is what a reader actually wants.
    """
    if not url:
        return ""
    marker = "/api/"
    index = url.find(marker)
    if index == -1:
        # Not an API URL (health checks, /metrics, ...): keep the path only.
        without_scheme = url.split("://", 1)[-1]
        return "/" + without_scheme.split("/", 1)[1] if "/" in without_scheme else url
    rest = url[index + len(marker):]
    # rest is "<session>:<token>/<endpoint>/<...>" — drop the credential segment.
    parts = rest.split("/", 1)
    endpoint = parts[1] if len(parts) > 1 else ""
    return "/" + endpoint if endpoint else "/api/"


def api_headers(token: str, *, json_body: bool = True,
                request_id: str = "") -> dict:
    """The headers every call to the Node API should carry."""
    headers = {
        "Authorization": f"Bearer {token}",
        _REQUEST_ID_HEADER: request_id or new_request_id(),
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def api_request(method: str, url: str, *, token: str = "", request_id: str = "",
                timeout: float = 30, session: requests.Session = None,
                **kwargs) -> requests.Response:
    """Perform one call to the Node API, logged and correlated.

    Raises whatever requests raises — the caller's own error handling stays in
    charge, and every existing call site already has one.
    """
    request_id = request_id or new_request_id()
    headers = dict(kwargs.pop("headers", None) or {})
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    headers.setdefault(_REQUEST_ID_HEADER, request_id)

    label = redact_api_url(url)
    started = time.monotonic()
    # Dispatched as requests.get/requests.post rather than requests.request on
    # purpose: that is the seam the existing suite already patches
    # (monkeypatch.setattr(main.requests, "post", ...)), and routing through
    # .request() instead would have quietly slipped past every one of those
    # stubs — turning unit tests into real HTTP calls against a local server
    # that may or may not be running. Caught exactly that way: the suite went
    # from 24s to 177s and 21 tests started failing on timeouts.
    caller = getattr(session or requests, method.lower())
    try:
        response = caller(url, headers=headers, timeout=timeout, **kwargs)
    except Exception as exc:
        logging.warning(
            "[api] rid=%s %s %s failed after %.0fms: %s",
            request_id, method.upper(), label,
            (time.monotonic() - started) * 1000, exc,
        )
        raise
    elapsed = time.monotonic() - started
    log = logging.warning if elapsed >= SLOW_REQUEST_SECONDS else logging.info
    log(
        "[api] rid=%s %s %s -> %s in %.0fms",
        request_id, method.upper(), label, response.status_code, elapsed * 1000,
    )
    return response


def api_get(url: str, **kwargs) -> requests.Response:
    return api_request("GET", url, **kwargs)


def api_post(url: str, **kwargs) -> requests.Response:
    return api_request("POST", url, **kwargs)
