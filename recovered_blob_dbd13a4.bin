import threading
import time

import requests
import wx

class ChatStateService:
    """Manages per-chat state: mute, archive, delete, pin, unread tracking.

    All methods operate on ``self.mw`` (the ``MainWindow`` instance) so that
    UI-facing code continues to call ``main_window.xxx()`` while the actual
    logic lives here.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── Mute ─────────────────────────────────────────────────────────────────

    def is_chat_muted(self, jid: str) -> bool:
        muted = self.mw.settings.get("muted_chats", {})
        expiry = muted.get(jid)
        if expiry is None:
            return False
        if expiry == -1:
            return True
        return time.time() < expiry

    def mute_chat(self, jid: str, duration_secs: int):
        self.mw.settings.setdefault("muted_chats", {})
        if duration_secs == -1:
            self.mw.settings["muted_chats"][jid] = -1
        else:
            self.mw.settings["muted_chats"][jid] = int(time.time()) + duration_secs
        self.mw.save_settings()
        self._sync_mute_to_server(jid, duration_secs)

    def unmute_chat(self, jid: str):
        self.mw.settings.setdefault("muted_chats", {})
        self.mw.settings["muted_chats"].pop(jid, None)
        self.mw.save_settings()
        self._sync_mute_to_server(jid, 0)

    def _sync_mute_to_server(self, jid: str, duration_secs: int):
        def _do():
            try:
                if duration_secs == 0:
                    wpp_time, wpp_type = 0, "hours"
                elif duration_secs == -1:
                    wpp_time, wpp_type = 8766, "hours"
                else:
                    wpp_time = max(1, duration_secs // 3600)
                    wpp_type = "hours"
                url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-mute"
                payload = {
                    "phone": jid,
                    "time": wpp_time,
                    "type": wpp_type,
                    "isGroup": jid.endswith("@g.us"),
                }
                requests.post(
                    url,
                    json=payload,
                    headers=self.mw._api_headers({"Content-Type": None}),
                    timeout=10,
                )
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Archive ──────────────────────────────────────────────────────────────

    def is_chat_archived(self, jid: str) -> bool:
        chat = self.mw.chats.get(jid, {})
        return (
            jid in self.mw.settings.get("archived_chats", [])
            or chat.get("archived") is True
            or chat.get("archive") is True
            or str(chat.get("archived")).lower() == "true"
            or str(chat.get("archive")).lower() == "true"
        )

    def archive_chat(self, jid: str):
        lst = self.mw.settings.setdefault("archived_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.mw.save_settings()
        wx.CallAfter(self.mw.chat_list_builder.set_chats)
        self._api_archive_chat(jid, archive=True)

    def unarchive_chat(self, jid: str):
        lst = self.mw.settings.setdefault("archived_chats", [])
        if jid in lst:
            lst.remove(jid)
        self.mw.save_settings()
        wx.CallAfter(self.mw.chat_list_builder.set_chats)
        self._api_archive_chat(jid, archive=False)

    def _api_archive_chat(self, jid: str, archive: bool):
        url = (
            f"{self.mw.wpp_server}:{self.mw.wpp_port}"
            f"/api/{self.mw.token}/archive-chat"
        )
        headers = self.mw._api_headers()
        try:
            resp = requests.post(
                url,
                json={"phone": jid, "value": archive},
                headers=headers,
                timeout=10,
            )
            if not resp.ok:
                print(
                    f"[archive_chat] API error {resp.status_code} for {jid}: {resp.text[:200]}"
                )
        except Exception as exc:
            print(f"[archive_chat] Request failed for {jid}: {exc}")

    # ── Delete / Clear ───────────────────────────────────────────────────────

    def is_chat_deleted(self, jid: str) -> bool:
        return jid in self.mw.settings.get("deleted_chats", [])

    def delete_chat_local(self, jid: str):
        lst = self.mw.settings.setdefault("deleted_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.mw.save_settings()
        self.mw.chats.pop(jid, None)
        self.mw.data_persistence._schedule_save()
        wx.CallAfter(self.mw.chat_list_builder.set_chats)

    def clear_chat_messages_local(self, jid: str):
        chat = self.mw.chats.get(jid)
        if chat:
            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = []
            self.mw.settings.setdefault("cleared_chats", {})[jid] = int(time.time())
            self.mw.data_persistence._schedule_save()
            self.mw.save_settings()

    # ── Pin ───────────────────────────────────────────────────────────────────

    def is_chat_pinned(self, jid: str) -> bool:
        return jid in self.mw.settings.get("pinned_chats", [])

    def pin_chat(self, jid: str):
        lst = self.mw.settings.setdefault("pinned_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.mw.save_settings()
        wx.CallAfter(self.mw.chat_list_builder.set_chats)

    def unpin_chat(self, jid: str):
        lst = self.mw.settings.setdefault("pinned_chats", [])
        if jid in lst:
            lst.remove(jid)
        self.mw.save_settings()
        wx.CallAfter(self.mw.chat_list_builder.set_chats)

    # ── Real-time sync callbacks ─────────────────────────────────────────────

    def on_chat_unread_update(self, jid: str, unread_count: int):
        normalized = self.mw._normalize_jid(jid)
        chat = self.mw.chats.get(normalized)
        if chat is None:
            return
        if unread_count > 0:
            records = (
                (chat.get("messages") or {})
                .get("messages", {})
                .get("records", [])
            )
            if records:
                tail = records[-unread_count:] if unread_count <= len(records) else records
                own_count = sum(1 for m in tail if (m.get("key") or {}).get("fromMe"))
                unread_count = max(0, unread_count - own_count)
        old_count = int(chat.get("unreadCount") or 0)
        if old_count == unread_count:
            return
        chat["unreadCount"] = unread_count
        self.mw.data_persistence._schedule_save()
        self.mw.chat_list_builder._schedule_set_chats()

    def on_chat_archive_update(self, jid: str, archived: bool):
        normalized = self.mw._normalize_jid(jid)
        chat = self.mw.chats.get(normalized)
        if chat is None:
            return
        chat["archived"] = archived
        chat["archive"] = archived

        lst = self.mw.settings.setdefault("archived_chats", [])
        if archived:
            if normalized not in lst:
                lst.append(normalized)
        else:
            if normalized in lst:
                lst.remove(normalized)
        self.mw.save_settings()
        self.mw.chat_list_builder._schedule_set_chats()
