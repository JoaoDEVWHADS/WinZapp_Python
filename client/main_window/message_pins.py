"""Read the linked device's pinned messages without fetching phone history."""

from core.api_client import api_post


class MessagePinsMixin:
    def get_pinned_messages(self, jid: str) -> list:
        aliases = {jid, self._normalize_jid(jid)}
        for alias in tuple(aliases):
            aliases.add(getattr(self, "_phone_to_lid", {}).get(alias, ""))
            aliases.add(getattr(self, "_lid_to_phone", {}).get(alias, ""))
        targets = sorted({alias.replace("@s.whatsapp.net", "@c.us")
                          for alias in aliases if alias})
        response = api_post(
            f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/pinned-messages",
            json={"chatIds": targets},
            headers={"Authorization": f"Bearer {self.token}"}, timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Invalid pinned messages response")
        raw = body.get("response")
        if body.get("status") != "success" or not isinstance(raw, list):
            raise ValueError("Invalid pinned messages response")
        messages = self._normalize_fetched_messages(raw, jid)
        if messages is None or len(messages) != len(raw) or any(
            not (m.get("key") or {}).get("id")
            or not self._chat_jids_equivalent(jid, (m.get("key") or {}).get("remoteJid", ""))
            for m in messages
        ):
            raise ValueError("Incomplete pinned messages response")
        for message in messages:
            message["pinInChat"] = True
        return messages
