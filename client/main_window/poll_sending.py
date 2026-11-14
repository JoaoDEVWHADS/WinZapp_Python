"""PollSendingMixin — part of MainWindow (see main_window/__init__.py).

Sending a poll created in the attachment menu. The body is
core.polls.poll_send_payload(); the response is confirmed the way every other
send route is (core.send_contract.accepted_message_id).
"""

import logging

from core.api_client import api_post
from core.polls import poll_send_payload
from core.send_contract import (
    SendContractError,
    accepted_message_id,
    send_failure_is_ambiguous,
)


class PollSendingMixin:
    def send_poll_message(self, remote_jid: str, poll: dict):
        """Send *poll*; returns the confirmed message id, a failure dict for
        MessageQueue, or None when the request never got an answer worth
        reading (same contract as send_contact_attachment)."""
        remote_jid = self._resolve_jid_for_send(remote_jid)
        is_lid_target = remote_jid.endswith("@lid")
        is_group = remote_jid.endswith("@g.us")
        if is_group:
            remote_jid = remote_jid.split("@")[0]
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-poll-message"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = poll_send_payload(remote_jid, poll, is_group=is_group, is_lid=is_lid_target)

        def _parse(r):
            try:
                return accepted_message_id(r.json())
            except (ValueError, TypeError, SendContractError) as exc:
                logging.error("[send_poll_message] unconfirmed send: %s", exc)
                return {
                    "ok": False,
                    "error": self.i18n.t("send_not_confirmed_error"),
                    "retry": False,
                }

        try:
            r = api_post(url, json=payload, headers=headers, timeout=25)
            if r.status_code in (200, 201):
                return _parse(r)
            if self._check_wa_connection_closed(r):
                return {"ok": False, "error": f"HTTP {r.status_code}",
                        "retry": False, "disconnected": True}
            # A 4xx is the controller refusing before it did anything, so the
            # legacy-@c.us fallback is free; a 5xx may already be on its way
            # and is never resent (core.send_contract.send_failure_is_ambiguous).
            fb_phone = (
                self._legacy_phone_for_send(remote_jid)
                if is_lid_target and not send_failure_is_ambiguous(r.status_code) else ""
            )
            if fb_phone:
                payload["phone"] = [fb_phone]
                payload["isLid"] = False
                r = api_post(url, json=payload, headers=headers, timeout=25)
                if r.status_code in (200, 201):
                    return _parse(r)
            logging.error("[send_poll_message] HTTP %s: %s", r.status_code, r.text[:300])
            return {
                "ok": False, "error": f"HTTP {r.status_code}",
                "retry": r.status_code in (408, 429),
                "ambiguous": send_failure_is_ambiguous(r.status_code),
            }
        except Exception as exc:
            return self._classify_send_exception(exc, "send_poll_message")

    def fetch_poll_votes(self, messages: list) -> dict:
        """``{message key id: {"voters", "options"}}`` for the polls in
        *messages*, as WhatsApp Web counts them; {} when it cannot say."""
        ids = {}
        for msg in messages:
            key = msg.get("key") or {}
            serialized = self._serialize_msg_id(key.get("remoteJid", ""), key, msg)
            if serialized:
                ids[serialized] = key.get("id", "")
        if not ids:
            return {}
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/poll-votes"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            r = api_post(url, json={"messageIds": list(ids)}, headers=headers, timeout=15)
            if r.status_code != 200:
                return {}
            response = (r.json() or {}).get("response") or {}
        except Exception as exc:
            logging.warning("[fetch_poll_votes] %s", type(exc).__name__)
            return {}
        return {ids[serialized]: data for serialized, data in response.items() if serialized in ids}

    def fetch_poll_voters(self, msg: dict) -> dict:
        """``{"options": [{name, localId}], "voters": [{sender, mine, localIds}]}``
        for one poll, or {} when WhatsApp Web cannot say."""
        key = msg.get("key") or {}
        serialized = self._serialize_msg_id(key.get("remoteJid", ""), key, msg)
        if not serialized:
            return {}
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/poll-voters"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            r = api_post(url, json={"messageId": serialized}, headers=headers, timeout=15)
            if r.status_code != 200:
                return {}
            return (r.json() or {}).get("response") or {}
        except Exception as exc:
            logging.warning("[fetch_poll_voters] %s", type(exc).__name__)
            return {}

    def send_poll_vote(self, msg: dict, local_ids: list) -> bool:
        """Cast (or, with no ids, clear) the user's vote on poll *msg*."""
        key = msg.get("key") or {}
        serialized = self._serialize_msg_id(key.get("remoteJid", ""), key, msg)
        if not serialized:
            return False
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/vote-poll"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            r = api_post(url, json={"messageId": serialized, "localIds": local_ids},
                         headers=headers, timeout=20)
            return r.status_code == 200
        except Exception as exc:
            logging.warning("[send_poll_vote] %s", type(exc).__name__)
            return False
