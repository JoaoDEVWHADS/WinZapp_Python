"""Recognise "WhatsApp Web's VoIP never came up" in a call-control failure.

The Node side answers a failed offer/accept with the page's own error text
(callController.ts). When the pinned WhatsApp Web build's glue and Meta's live
worker bundle disagree, VoIP never initialises and every call fails with one
of the messages below (docs/traps/voice-calls.md). The raw text is a minified
stack trace, so the user is told the cause and the fix instead.
"""

#: Lower-case fragments of the three wordings the Node side produces.
_MARKERS = (
    "voip initialization failed",
    "initializer completed without becoming ready",
    "without successful voipinit",
)


class VoipUnavailableError(RuntimeError):
    """A call failed because WhatsApp Web's VoIP could not initialise."""


def is_voip_init_failure(text) -> bool:
    """True when a server error body says VoIP failed to initialise."""
    lowered = " ".join(str(text or "").split()).lower()
    return any(marker in lowered for marker in _MARKERS)
