"""MessageAckMixin — part of MainWindow (see main_window/__init__.py).

One call to the local WPPConnect server: the live delivered / read / played
times of one of our own sent messages, as WhatsApp itself holds them (the
``message-ack`` route in api_patches, which calls WPP.chat.getMessageACK).

It returns None on ANY failure — offline, a message WhatsApp no longer has, a
server hiccup — and the caller then falls back to whatever WinZapp recorded
locally. It never raises, and nothing about the message or the chat reaches the
log: a JID and a message id identify a person's conversation.

Methods run with ``self`` bound to the MainWindow instance.
"""

import logging

from core.api_client import api_post


class MessageAckMixin:
    """Live receipt info for our own sent messages."""

    #: Seconds. The window waits for this, and says it is waiting.
    _MESSAGE_ACK_TIMEOUT = 10

    def fetch_message_ack(self, remote_jid: str, msg_key: dict) -> "dict | None":
        """The ack info of a sent message — ``{"participants": [{"id", "deliveredAt",
        "readAt", "playedAt"}, ...], ...}`` — or None.

        Safe to call from a worker thread: it touches no wx object.
        """
        full_id = self._serialize_msg_id(remote_jid, msg_key or {})
        if not full_id:
            return None
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/message-ack"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            response = api_post(
                url, json={"messageId": full_id}, headers=headers,
                timeout=self._MESSAGE_ACK_TIMEOUT,
            )
            if response.status_code not in (200, 201):
                logging.warning("[fetch_message_ack] HTTP %s", response.status_code)
                return None
            body = response.json()
        except Exception as exc:
            logging.warning("[fetch_message_ack] %s", type(exc).__name__)
            return None
        answer = body.get("response") if isinstance(body, dict) else None
        return answer if isinstance(answer, dict) else None
