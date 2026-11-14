"""HTTPS that verifies the way the rest of Windows does.

`requests` verifies against the CA list baked into `certifi`, which is a fixed
file and knows nothing about the machine it is running on. On a machine whose
TLS is intercepted locally — an antivirus with HTTPS scanning switched on, a
corporate proxy, an MDM profile — the certificate the app is shown is signed by
a root that only exists in *Windows'* own store, and every download fails with
CERTIFICATE_VERIFY_FAILED. Measured here against huggingface.co, nodejs.org and
api.github.com: all three fail, and all three succeed once verification goes
through the system store. That is the same reason pip carries `truststore`.

It matters more than it looks: the three things this affects are the Whisper
models (up to 3 GB, and the transcription simply cannot happen without them),
the portable Node.js runtime WinZapp needs to talk to WhatsApp at all, and the
updater. A user in that situation currently sees three unrelated features fail
for reasons none of them explain.

**Never raises for its own sake.** `truststore` missing, or refusing to build a
context on some future Windows, leaves the caller with an ordinary Session
verifying the ordinary way — exactly the behaviour of the code that was here
before. Downloads failing is a bad day; the updater dying on import because a
certificate helper was unavailable would be a worse one. Which path was taken
is logged once, because "why does it work on his machine" is the question this
module exists to answer.
"""

from __future__ import annotations

import logging
import ssl

import requests
from requests.adapters import HTTPAdapter

# Logged on the first session built and not again: this is asked once per
# process, and a line per HTTP request would bury the log of a 3 GB download.
_reported = False


class _SystemTrustAdapter(HTTPAdapter):
    """An HTTPAdapter whose connections verify against the OS trust store."""

    def __init__(self, ssl_context, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        # The proxy path needs it just as much, and is not the same code path:
        # a machine that intercepts TLS is very often the same machine that
        # routes through a proxy, and missing this would fix the plain case and
        # leave the intercepted one broken.
        kwargs["ssl_context"] = self._ssl_context
        # And once more for the leg *to* the proxy, when the proxy's own URL is
        # https://. urllib3 verifies that hop against `proxy_ssl_context`, a
        # separate setting that would otherwise fall back to the bundled CA
        # list — on the corporate machines this module exists for.
        kwargs["proxy_ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)


def system_ssl_context():
    """An SSLContext verifying through the OS trust store, or None.

    None means "carry on as before" and is not an error: on a machine with no
    truststore, or a Python too old for it, the bundled CA list is what there
    always was.
    """
    global _reported
    try:
        import truststore

        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception as exc:
        if not _reported:
            _reported = True
            logging.info(
                "[tls] verifying HTTPS against the bundled CA list — the system "
                "trust store is unavailable (%s: %s)", type(exc).__name__, exc,
            )
        return None
    if not _reported:
        _reported = True
        logging.info("[tls] verifying HTTPS against the system trust store")
    return context


def create_session() -> requests.Session:
    """A `requests.Session` that verifies through the OS trust store if it can.

    Plain HTTP is left alone — there is nothing to verify — so only the https
    adapter is replaced.
    """
    session = requests.Session()
    context = system_ssl_context()
    if context is not None:
        try:
            session.mount("https://", _SystemTrustAdapter(context))
        except Exception as exc:
            # Building the adapter runs HTTPAdapter.__init__ → init_poolmanager,
            # which hands `ssl_context` to urllib3. urllib3 is a pinned
            # dependency that gets bumped like any other, and a version that
            # renames or validates that keyword would raise here — taking the
            # model download, the Node download and the background update check
            # down together, which is the single failure this module exists to
            # prevent. Losing the system trust store is survivable; losing every
            # download is not.
            logging.warning(
                "[tls] the system-trust adapter could not be installed "
                "(%s: %s) — falling back to the bundled CA list",
                type(exc).__name__, exc,
            )
    return session


def get(url, **kwargs):
    """`requests.get`, verifying through the OS trust store if it can.

    A session per call, closed afterwards, which is exactly what
    `requests.get()` itself does — so a caller swapped over to this one keeps
    the connection lifetime it had, including for `stream=True`, where the
    response goes on reading from a connection the closed session no longer
    pools.
    """
    with create_session() as session:
        return session.get(url, **kwargs)
