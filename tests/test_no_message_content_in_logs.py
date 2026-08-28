"""Tests that incoming message payloads never reach log.log in the clear.

A leftover debug hook in `WebSocketClient` logged the ENTIRE raw WPPConnect
payload at INFO whenever the message body was literally ".." or "oi". "oi" is
the commonest Portuguese greeting, so it fired constantly on real installs —
61 times in a single afternoon on one account. Each line carried the message
text, both parties' @lid and @c.us JIDs, the sender's real name, and
`messageSecret`: the per-message 32-byte key, printed as a decimal array.

Two things make that worse than untidy logging:

* `message_json` is Fernet-encrypted at rest precisely because message content
  is sensitive (CLAUDE.md). This wrote the same content in the clear, into
  log.log, in the same folder.
* CLAUDE.md tells anyone diagnosing a startup or pairing problem to ask the
  user for log.log. So every such request also asked for their conversations
  and per-message keys.

Being triggered by message *content*, it was invisible in testing and unbounded
in production. These tests exist so a debug hook of that shape cannot come back
unnoticed.
"""

import inspect
import re

from core.websocket_client import WebSocketClient


def _module_source():
    import core.websocket_client as mod

    return inspect.getsource(mod)


class TestTheDebugHookIsGone:
    def test_the_raw_payload_dump_is_removed(self):
        assert "[Raw Message Debug]" not in _module_source()

    def test_no_body_triggered_logging_remains(self):
        """The trigger was the message body itself, which is why no amount of
        testing would have surfaced it."""
        source = _module_source()
        assert "body_text in ('..', 'oi')" not in source
        assert 'body_text in ("..", "oi")' not in source


class TestNoWholePayloadIsEverLogged:
    """The specific hook is gone; this is the general rule it broke."""

    #: Names the raw WPPConnect payload travels under in this module.
    PAYLOAD_NAMES = ("wpp_msg", "payload", "raw_msg")

    def test_no_log_call_interpolates_a_raw_payload(self):
        offenders = []
        for lineno, line in enumerate(_module_source().splitlines(), 1):
            if "logging." not in line:
                continue
            for name in self.PAYLOAD_NAMES:
                # f-string interpolation, %-formatting argument, or str()
                if re.search(r"[{(,]\s*%s\s*[})\],]" % re.escape(name), line):
                    offenders.append((lineno, line.strip()))
        assert offenders == [], (
            "these log calls appear to pass a whole message payload: %r" % offenders
        )

    def test_the_per_message_key_is_never_named_in_a_log_call(self):
        """messageSecret has no diagnostic value and is key material."""
        for line in _module_source().splitlines():
            if "logging." in line:
                assert "messageSecret" not in line, line


class TestTheHandlerStillWorks:
    """Removing the hook must not have disturbed the surrounding parse."""

    def test_the_normalizer_is_still_callable(self):
        assert callable(getattr(WebSocketClient, "on_messages_upsert", None))

    def test_forwarding_detection_survived_around_the_removal(self):
        """The hook sat between the isForwarded read and the quote handling;
        both sides have to still be there."""
        source = _module_source()
        assert "isForwarded" in source
        assert "quotedMessage" in source
