"""Refusal responses in the format the WinZapp client recognizes.

The real server (WPPConnect) has fixed formats for the refusals the client
handles on its own; a generic error ("status":"error") is not recognized:

* no connection: HTTP 404 `{"response": null, "status": "Disconnected", ...}`
  (middleware statusConnection.ts). This is what makes the client pause the
  queue, not try the @c.us address of a @lid destination, and leave the
  message queued instead of giving the send up for lost
  (main_window/sending.py `_check_wa_connection_closed`,
  core/message_edit.py `response_not_sent`).
* missing quote: HTTP 500 with `code: quoted_message_not_found`
  (api_patches/src/util/quotedMessagePreflight.ts, core/reply_failure.py): only
  this way does the client know nothing was sent and put the text back in the
  field.
* edit refused before sending: the body carries "Cannot edit this message"
  (main_window/message_actions.py).

Pure functions over aiohttp, tested in test_responses.py. None of them touches
neonize.
"""
from aiohttp import web

#: the text the real server sends along with Disconnected. It stays in
#: Portuguese on purpose: the client recognizes it
#: (main_window/backfill.py) and the real server's middleware sends exactly it.
DISCONNECTED_MESSAGE = "A sessão do WhatsApp não está ativa."

#: the client looks for this snippet in the body (main_window/message_actions.py)
EDIT_REFUSED_TEXT = "Cannot edit this message"


def connected(s):
    """Does the session have a neonize client and is it CONNECTED?"""
    return s.client is not None and s.status == "CONNECTED"


def disconnected():
    """404 Disconnected, like the real server's statusConnection middleware."""
    return web.json_response(
        {"response": None, "status": "Disconnected", "message": DISCONNECTED_MESSAGE},
        status=404)


def without_connection(s):
    """The Disconnected response if the session is not connected, else None."""
    return None if connected(s) else disconnected()


def missing_quote():
    """500 telling the client the quote does not exist and that NOTHING was sent
    (reply_failure.quote_missing_before_send requires each of these fields)."""
    return web.json_response(
        {"status": "error", "code": "quoted_message_not_found",
         "stage": "quote_resolution", "sendAttempted": False}, status=500)


def edit_refused(reason):
    """Edit refusal that the client knows happened before anything was sent;
    `reason` (not_mine, not_stored, outside_window) only helps reading the log."""
    return web.json_response(
        {"status": "error", "message": EDIT_REFUSED_TEXT, "reason": reason},
        status=400)
