"""View-once messages, which WhatsApp never delivers to a linked device.

A view-once voice message, photo or video is opened on the phone only.
WhatsApp does not fan its content out to linked devices, so WhatsApp Web —
and WinZapp through it — gets a stand-in: a message model of type
`ciphertext` with subtype `view_once_unavailable_fanout` (inspected over CDP
on a live install: no media fields, no hint of voice/photo/video, and it never
turns into anything else).

WinZapp used to read that as an ordinary undecrypted placeholder. The live
funnel drops those while waiting for the decrypted copy under the same id
(MainWindow._is_undecrypted_placeholder), which for a view-once message never
comes: no badge, no sound, no notification — "completely ignored" (issue
#47). A sync stored it instead and it rendered "waiting for this message",
which was never going to be true either.

So it becomes a message type of its own at the normalizer, carried by nothing
but the type: it counts, notifies and reads out as "view-once message, open it
on your phone". Which kind of media it was is not available to say.
"""

from __future__ import annotations

# WinZapp's canonical messageType for the stand-in.
VIEW_ONCE_UNAVAILABLE_TYPE = "viewOnceUnavailableMessage"


def is_view_once_unavailable(wpp_msg) -> bool:
    """Whether a WPPConnect message payload is the view-once stand-in.

    Matched on the subtype's `view_once` prefix rather than the one value
    seen so far, since WhatsApp Web names these per reason
    (`view_once_unavailable_fanout` for a linked device); the type has to be
    the undecryptable one, so a real message that happens to carry a subtype
    is never taken for it.
    """
    if not isinstance(wpp_msg, dict):
        return False
    if (wpp_msg.get("type") or "") != "ciphertext":
        return False
    return str(wpp_msg.get("subtype") or "").startswith("view_once")
