import logging
import time

import requests
import wx

from traceback import format_exc


class ChatSyncService:
    def __init__(self, main_window):
        self.mw = main_window

    def get_remote_chats(self, chats):
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/all-chats"
        headers = self.mw._api_headers()
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code not in (200, 201):
                logging.error(f"[get_remote_chats] API error {response.status_code}: {response.text[:200]}")
                return chats
            try:
                body = response.json()
            except Exception as json_err:
                logging.error(f"[get_remote_chats] Failed to parse JSON response: {json_err}. Response body: {response.text[:200]}")
                return chats
            response_data = body.get("response", []) if isinstance(body, dict) else []
            if not isinstance(response_data, list):
                response_data = []

            for chat in response_data:
                if not isinstance(chat, dict):
                    continue
                wpp_id = chat.get("id")
                jid_str = wpp_id.get("_serialized") if isinstance(wpp_id, dict) else wpp_id
                if jid_str:
                    chat["remoteJid"] = jid_str.replace("@c.us", "@s.whatsapp.net")
            lid_chats = [c for c in response_data if isinstance(c, dict) and c.get("remoteJid", "").endswith("@lid")]
            if lid_chats:
                logging.info(f"[get_remote_chats] RAW LID CHAT KEYS: {list(lid_chats[0].keys())}")
                logging.info(f"[get_remote_chats] RAW LID CHAT DATA: {lid_chats[0]}")

            for chat in response_data:
                if not isinstance(chat, dict):
                    continue
                jid = self.mw._normalize_jid(chat.get("remoteJid", ""))

                last_msg = chat.get("lastMessage")
                if isinstance(last_msg, dict):
                    key = last_msg.get("key")
                    if isinstance(key, dict):
                        remote = key.get("remoteJid", "")
                        alt = key.get("remoteJidAlt", "")
                        if remote and alt:
                            if remote.endswith("@lid") and alt.endswith("@s.whatsapp.net"):
                                if not hasattr(self.mw, "_lid_to_phone"):
                                    self.mw._lid_to_phone = {}
                                if not hasattr(self.mw, "_phone_to_lid"):
                                    self.mw._phone_to_lid = {}
                                if self.mw._lid_to_phone.get(remote) != alt:
                                    self.mw._lid_to_phone[remote] = alt
                                    self.mw._phone_to_lid[alt] = remote
                                    logging.info(f"[LID Mapping] Extracted mapping from lastMessage in get_remote_chats: {remote} <-> {alt}")
                            elif alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                                if not hasattr(self.mw, "_lid_to_phone"):
                                    self.mw._lid_to_phone = {}
                                if not hasattr(self.mw, "_phone_to_lid"):
                                    self.mw._phone_to_lid = {}
                                if self.mw._lid_to_phone.get(alt) != remote:
                                    self.mw._lid_to_phone[alt] = remote
                                    self.mw._phone_to_lid[remote] = alt
                                    logging.info(f"[LID Mapping] Extracted mapping from lastMessage in get_remote_chats (alt): {alt} <-> {remote}")

                if not jid or jid.endswith("@broadcast"):
                    continue
                if jid and not jid.endswith("@g.us"):
                    name = chat.get("name")
                    pushName = chat.get("pushName")
                    if jid not in self.mw.contacts:
                        self.mw.contacts[jid] = {"id": jid, "remoteJid": jid}
                    if name:
                        self.mw.contacts[jid]["name"] = name
                    if pushName:
                        self.mw.contacts[jid]["pushName"] = pushName

                    phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid)
                    if phone_jid:
                        if phone_jid not in self.mw.contacts:
                            self.mw.contacts[phone_jid] = {"id": phone_jid, "remoteJid": phone_jid}
                        if name:
                            self.mw.contacts[phone_jid]["name"] = name
                        if pushName:
                            self.mw.contacts[phone_jid]["pushName"] = pushName

                    lid_jid = getattr(self.mw, "_phone_to_lid", {}).get(jid)
                    if lid_jid:
                        if lid_jid not in self.mw.contacts:
                            self.mw.contacts[lid_jid] = {"id": lid_jid, "remoteJid": lid_jid}
                        if name:
                            self.mw.contacts[lid_jid]["name"] = name
                        if pushName:
                            self.mw.contacts[lid_jid]["pushName"] = pushName

                if jid.endswith("@lid"):
                    phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid)
                    if phone_jid and phone_jid in chats:
                        continue
                if jid not in chats:
                    if "messages" not in chat:
                        chat["messages"] = {"messages": {"records": []}}
                    chat["remoteJid"] = jid
                    chats[jid] = chat
                else:
                    for k, v in chat.items():
                        if k in ("messages", "remoteJid"):
                            continue
                        if k == "unreadCount" and int(chats[jid].get("unreadCount") or 0) == 0:
                            continue
                        chats[jid][k] = v
            muted_chats = self.mw.settings.setdefault("muted_chats", {})
            now = int(time.time())
            for chat in response_data:
                if not isinstance(chat, dict):
                    continue
                jid = chat.get("remoteJid", "")
                if not jid:
                    continue
                mute_expiry = chat.get("muteExpiration", 0)
                if mute_expiry == -1 or (isinstance(mute_expiry, (int, float)) and mute_expiry > now):
                    muted_chats[jid] = int(mute_expiry)
                elif jid in muted_chats:
                    del muted_chats[jid]

            self.mw.data_persistence.save_data(chats, self.mw.contacts)
            return chats
        except Exception as e:
            self.mw.error_sound.play()
            wx.MessageBox(f"{self.mw.i18n.t('chat_retrieval_failed')} {format_exc()}", self.mw.i18n.t("error").format(app_name=self.mw.app_name), wx.OK | wx.ICON_ERROR, self.mw)

    def normalize_chats(self, chats):
        settings_changed = False
        archived = self.mw.settings.setdefault("archived_chats", [])
        normalized = {}
        for key, chat in chats.items():
            if key.endswith("@newsletter") or chat.get("remoteJid", "").endswith("@newsletter"):
                continue
            if chat.get("unreadCount") is None:
                chat["unreadCount"] = 0
            is_arch = (
                chat.get("archived") is True
                or chat.get("archive") is True
                or str(chat.get("archived")).lower() == "true"
                or str(chat.get("archive")).lower() == "true"
            )
            if is_arch:
                if key not in archived:
                    archived.append(key)
                    settings_changed = True
            normalized[key] = chat
        if settings_changed:
            self.mw.save_settings()
        return normalized

    def deduplicate_chats(self, chats: dict) -> dict:
        def _merge_records(dst_records: list, src_records: list):
            if not src_records:
                return
            dst_ids = {r.get("key", {}).get("id") for r in dst_records}
            for r in src_records:
                if r.get("key", {}).get("id") not in dst_ids:
                    dst_records.append(r)

        cus_jids = [j for j in list(chats.keys()) if j.endswith("@c.us")]
        for cus_jid in cus_jids:
            if cus_jid not in chats:
                continue
            normalized = self.mw._normalize_jid(cus_jid)
            cus_chat   = chats.pop(cus_jid)
            cus_chat["remoteJid"] = normalized

            if normalized in chats:
                dst_records = (
                    chats[normalized]
                    .setdefault("messages", {})
                    .setdefault("messages", {})
                    .setdefault("records", [])
                )
                src_records = (
                    cus_chat.get("messages", {})
                    .get("messages", {})
                    .get("records", [])
                )
                _merge_records(dst_records, src_records)
            else:
                chats[normalized] = cus_chat

        temp_cache = {}
        for jid_key, chat_obj in chats.items():
            for msg in chat_obj.get("messages", {}).get("messages", {}).get("records", []):
                key    = msg.get("key", {})
                remote = key.get("remoteJid", "")
                alt    = key.get("remoteJidAlt", "")
                if alt and alt.endswith("@s.whatsapp.net"):
                    if remote.endswith("@lid"):
                        temp_cache[remote] = alt
                    participant = key.get("participant", "")
                    if participant.endswith("@lid"):
                        temp_cache[participant] = alt
                elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                    temp_cache[alt] = remote

        lid_jids = [j for j in list(chats.keys()) if j.endswith("@lid")]
        for lid_jid in lid_jids:
            if lid_jid not in chats:
                continue
            lid_chat = chats[lid_jid]
            alt_jid  = self.mw._find_alt_jid_from_messages(lid_chat) or temp_cache.get(lid_jid)
            if not alt_jid:
                alt_jid = getattr(self.mw, "_lid_to_phone", {}).get(lid_jid, "")
            if not alt_jid:
                continue

            src_records = (
                lid_chat.get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            if alt_jid in chats:
                dst_records = (
                    chats[alt_jid]
                    .setdefault("messages", {})
                    .setdefault("messages", {})
                    .setdefault("records", [])
                )
                _merge_records(dst_records, src_records)

                unread_dst = int(chats[alt_jid].get("unreadCount") or 0)
                unread_src = int(lid_chat.get("unreadCount") or 0)
                chats[alt_jid]["unreadCount"] = unread_dst + unread_src
            else:
                lid_chat["remoteJid"] = alt_jid
                chats[alt_jid] = lid_chat
            del chats[lid_jid]

        return chats
