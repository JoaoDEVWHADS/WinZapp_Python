import logging

import requests
import wx


class MessageSyncService:
    def __init__(self, main_window):
        self.mw = main_window

    def sync_remote_chats(self):
        for chat in list(self.mw.chats.values()):
            try:
                self.sync_chat_messages(chat.copy())
            except Exception:
                jid = chat.get("remoteJid", "?")
                print(f"[sync_remote_chats] failed to sync {jid}, continuing")

    def sync_chat_messages(self, chat):
        remote_jid = self.mw._normalize_jid(chat.get("remoteJid", ""))
        chat["remoteJid"] = remote_jid
        lid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
        if lid:
            phone = lid
        elif remote_jid.endswith("@s.whatsapp.net"):
            phone = remote_jid.split("@")[0] + "@c.us"
        else:
            phone = remote_jid

        limit = int(self.mw.settings.get("user_interface", {}).get("messages_page_size", 200))
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/get-messages/{phone}?count={limit}"
        headers = self.mw._api_headers()

        all_messages = []
        try:
            logging.info(f"[sync_chat_messages] Querying URL: {url} for chat: {remote_jid}")
            response = requests.get(url, headers=headers, timeout=30)
            logging.info(f"[sync_chat_messages] URL: {url} returned status: {response.status_code}")
            if response.status_code in (200, 201):
                body = response.json()
                wpp_messages = body.get("response", []) if isinstance(body, dict) else []
                logging.info(f"[sync_chat_messages] Fetched {len(wpp_messages)} messages from API for {remote_jid}")
                if not isinstance(wpp_messages, list):
                    wpp_messages = []
                for wm in wpp_messages:
                    if isinstance(wm, dict) and self.mw.ws:
                        try:
                            normalized = self.mw.ws._normalize_wpp_message(wm)
                            all_messages.append(normalized)
                        except Exception as e:
                            logging.error(f"[sync_chat_messages] Failed to normalize message in {remote_jid}: {e}")
            else:
                logging.error(f"[sync_chat_messages] API returned error status {response.status_code} for {remote_jid}: {response.text}")
        except Exception as e:
            logging.error(f"[sync_chat_messages] failed to get messages for {remote_jid}: {e}")

        if all_messages:
            for msg in all_messages:
                self.mw._extract_lid_mapping(msg)
            local_chat    = self.mw.chats.get(remote_jid, {})
            local_records = (local_chat.get("messages", {})
                             .get("messages", {})
                             .get("records", []))
            if local_records:
                api_ids = {r.get("key", {}).get("id") for r in all_messages}
                extra   = [r for r in local_records
                           if r.get("key", {}).get("id") and
                              r.get("key", {}).get("id") not in api_ids]
                if extra:
                    all_messages = all_messages + extra

            if "messages" not in chat:
                chat["messages"] = {}
            chat["messages"]["messages"] = {
                "total": len(all_messages),
                "pages": 1,
                "currentPage": 1,
                "records": all_messages
            }

        if chat.get("messages", {}) and chat["messages"] != self.mw.chats.get(remote_jid, {}).get("messages", {}):
            self.mw.chats[remote_jid] = chat
            if not getattr(self.mw, "_initial_sync_running", False):
                wx.CallAfter(self.mw.chat_list_builder._schedule_set_chats)
            self.mw.data_persistence.save_data(self.mw.chats, self.mw.contacts)

    def fetch_older_messages(self, remote_jid, oldest_msg):
        """Fetch older messages from server starting before the oldest_msg."""
        remote_jid = self.mw._normalize_jid(remote_jid)
        lid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
        if lid:
            phone = lid
        elif remote_jid.endswith("@s.whatsapp.net"):
            phone = remote_jid.split("@")[0] + "@c.us"
        else:
            phone = remote_jid

        _key = oldest_msg.get("key", {})
        msg_id = _key.get("id", "")
        if msg_id and "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]

        if msg_id:
            from_me = _key.get("fromMe", False)
            from_me_str = "true" if from_me else "false"
            msg_id = f"{from_me_str}_{phone}_{msg_id}"
            if phone.endswith("@g.us"):
                participant = _key.get("participant", "")
                if participant:
                    if participant.endswith("@s.whatsapp.net") or participant.endswith("@c.us"):
                        participant = participant.split("@")[0] + "@c.us"
                    msg_id = f"{msg_id}_{participant}"

        limit = int(self.mw.settings.get("user_interface", {}).get("messages_page_size", 200))
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/get-messages/{phone}?count={limit}&direction=before&id={msg_id}"
        headers = self.mw._api_headers()

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code in (200, 201):
                body = response.json()
                wpp_messages = body.get("response", []) if isinstance(body, dict) else []
                if not isinstance(wpp_messages, list):
                    wpp_messages = []

                fetched_messages = []
                for wm in wpp_messages:
                    if isinstance(wm, dict) and self.mw.ws:
                        try:
                            normalized = self.mw.ws._normalize_wpp_message(wm)
                            self.mw._extract_lid_mapping(normalized)
                            fetched_messages.append(normalized)
                        except Exception:
                            pass

                if fetched_messages:
                    chat = self.mw.chats.get(remote_jid, {})
                    if chat:
                        local_records = chat.get("messages", {}).get("messages", {}).get("records", [])
                        existing_ids = {r.get("key", {}).get("id") for r in local_records}
                        new_records = [m for m in fetched_messages if m.get("key", {}).get("id") not in existing_ids]
                        if new_records:
                            all_records = new_records + local_records
                            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = all_records
                            chat["messages"]["messages"]["total"] = len(all_records)
                            self.mw.data_persistence.save_data(self.mw.chats, self.mw.contacts)
                    return fetched_messages
        except Exception as e:
            logging.error(f"[fetch_older_messages] failed to get older messages for {remote_jid}: {e}")
        return []
