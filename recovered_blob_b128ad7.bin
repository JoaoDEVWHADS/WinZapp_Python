import logging
import requests


class MessageEditService:

    def __init__(self, main_window):
        self.mw = main_window

    def edit_message(self, remote_jid: str, message_id: str, new_text: str):
        lid_jid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid

        participant = ""
        chat = self.mw.chats.get(remote_jid)
        if chat:
            records = chat.get("messages", {}).get("messages", {}).get("records", [])
            for r in records:
                if r.get("key", {}).get("id") == message_id:
                    participant = r.get("key", {}).get("participant", "")
                    break

        url = (
            f"{self.mw.wpp_server}:{self.mw.wpp_port}"
            f"/api/{self.mw.token}/edit-message"
        )
        if remote_jid.endswith("@g.us"):
            if participant:
                participant_clean = participant.replace("@s.whatsapp.net", "@c.us")
                full_id = f"true_{remote_jid}_{message_id}_{participant_clean}"
            else:
                my_jid = getattr(self.mw, "my_jid", "")
                if my_jid:
                    my_jid_clean = my_jid.replace("@s.whatsapp.net", "@c.us")
                    full_id = f"true_{remote_jid}_{message_id}_{my_jid_clean}"
                else:
                    full_id = f"true_{remote_jid}_{message_id}"
        else:
            full_id = f"true_{remote_jid.replace('@s.whatsapp.net', '@c.us')}_{message_id}"

        payload = {
            "id":      full_id,
            "newText": new_text,
        }
        headers = self.mw._api_headers()
        try:
            requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass

    def delete_message_for_everyone(self, remote_jid: str, message_id: str, from_me: bool):
        lid_jid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid
        url = (
            f"{self.mw.wpp_server}:{self.mw.wpp_port}"
            f"/api/{self.mw.token}/delete-message"
        )
        if remote_jid.endswith("@g.us"):
            full_id = f"true_{remote_jid}_{message_id}"
        else:
            full_id = f"true_{remote_jid.replace('@s.whatsapp.net', '@c.us')}_{message_id}"

        payload = {
            "phone":     remote_jid,
            "messageId": full_id,
            "onlyLocal": False,
        }
        headers = self.mw._api_headers()
        try:
            requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass
