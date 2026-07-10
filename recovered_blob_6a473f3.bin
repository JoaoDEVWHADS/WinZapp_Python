import logging
import os
import threading
import time

import requests
import wx

from app_paths import data_path


class SyncService:
    def __init__(self, main_window):
        self.mw = main_window

    def prepare_sync(self):
        os.makedirs(data_path(), exist_ok=True)
        self.mw._media_failed_lock = threading.Lock()
        self.mw._media_failed_ids  = self.mw.media_sync._load_media_failed_ids()
        self.mw.generate_secret_key()
        self.mw.key = self.mw.retrieve_secret_key()
        self.mw.data_persistence.create_basic_files()

        self.mw.chats = self.mw.data_persistence.get_chats()
        self.mw._load_local_lid_cache()
        self.mw._build_lid_to_phone_cache()
        self.mw.chats = self.mw.deduplicate_chats(self.mw.chats)
        self.mw.chats = self.mw.normalize_chats(self.mw.chats)
        self.mw.contacts = self.mw.data_persistence.get_contacts()
        self.mw.scan_all_cached_messages_for_mentions()
        self.mw.connected_sound.play()
        self.mw._sync_completed = False
        self.mw._status_updates: dict = {}
        self.mw.settings.setdefault("status", {})["messages_set_completed"] = False
        self.mw.save_settings()
        self.wait_messages_set()

    def start_sync(self):
        if not self.mw._ui_ready_event.wait(timeout=120):
            return

        self.mw._initial_sync_running = True
        logging.info("[start_sync] Waiting for WhatsApp connection before syncing...")
        self.mw.connection_manager.check_wa_connection_http()
        waited = 0
        while waited < 30:
            if getattr(self.mw, "_wa_connected", False):
                break
            time.sleep(1)
            waited += 1
        if not getattr(self.mw, "_wa_connected", False):
            logging.warning("[start_sync] Sync starting without active WhatsApp connection (timeout).")

        _CHAT_RETRIES  = 6
        _CHAT_DELAY    = 5
        has_local_chats = len(self.mw.chats) > 0
        for attempt in range(_CHAT_RETRIES):
            prev_len = len(self.mw.chats)
            result   = self.mw.get_remote_chats(dict(self.mw.chats))
            if result is not None:
                self.mw.chats = result
            if has_local_chats or len(self.mw.chats) > prev_len or attempt == _CHAT_RETRIES - 1:
                break
            if not self.mw.background_mode:
                wx.CallAfter(self.mw._set_status, self.mw.i18n.t("preparing_to_sync"))
            time.sleep(_CHAT_DELAY)
        self.mw.chats = self.mw.normalize_chats(self.mw.chats)

        self.mw.get_remote_contacts()

        self.mw.synchronizing_sound.play()
        if not self.mw.background_mode:
            wx.CallAfter(self.mw._set_status, self.mw.i18n.t("synchronizing"))
            self.mw.output(self.mw.i18n.t("synchronization_started"), interrupt=True)

        self.mw.start_background_lid_resolution()

        self.mw.sync_remote_chats()

        self.mw.chats = self.mw.deduplicate_chats(self.mw.chats)

        self.mw.get_remote_contacts()

        wx.CallAfter(self.mw.chat_list_builder.set_chats)
        wx.CallAfter(self.mw.chat_list_builder.preselect_conversations)
        self.mw.sync_complete_sound.play()
        if not self.mw.background_mode:
            wx.CallAfter(self.mw._set_status, "")
            self.mw.output(self.mw.i18n.t("sync_complete"))

        if not self.mw.background_mode:
            wx.CallAfter(self.mw._set_status, self.mw.i18n.t("downloading_media"))
        self.mw._media_sync_running = True
        try:
            self.mw.media_sync.sync_media_for_all_chats()
        finally:
            self.mw._media_sync_running = False
        if not self.mw.background_mode:
            wx.CallAfter(self.mw._set_status, "")
        wx.CallAfter(self.mw.chat_list_builder.set_chats)

        self.mw.start_periodic_contacts_sync()

        if len(self.mw.chats) > 0:
            self.mw._sync_completed = True
        else:
            self.mw._sync_completed = False
            def _retry_sync():
                time.sleep(15)
                if getattr(self.mw, "_wa_connected", False) and len(self.mw.chats) == 0:
                    logging.info("[start_sync] Retrying empty chats sync...")
                    self.mw.sync_thread = threading.Thread(target=self.mw.start_sync, daemon=True)
                    self.mw.sync_thread.start()
            threading.Thread(target=_retry_sync, daemon=True).start()
        self.mw._initial_sync_running = False

    def wait_messages_set(self):
        if not self.mw.background_mode:
            self.mw._set_status(self.mw.i18n.t("preparing_to_sync"))
        def _fallback():
            def _already_syncing() -> bool:
                if self.mw.settings.get("status", {}).get("messages_set_completed"):
                    return True
                existing = getattr(self.mw, "sync_thread", None)
                if existing and existing.is_alive():
                    return True
                return getattr(self.mw, "_sync_completed", False)

            def _probe_and_start() -> bool:
                if _already_syncing():
                    return True
                try:
                    url = (
                        f"{self.mw.wpp_server}:{self.mw.wpp_port}"
                        f"/api/{self.mw.token}/list-chats"
                    )
                    headers = self.mw._api_headers()
                    r = requests.post(url, headers=headers, timeout=5)
                    if r.ok and isinstance(r.json(), list):
                        self.mw.settings.setdefault("status", {})["messages_set_completed"] = True
                        self.mw.save_settings()
                        self.mw.sync_thread = threading.Thread(
                            target=self.mw.start_sync, daemon=True
                        )
                        self.mw.sync_thread.start()
                        return True
                except Exception:
                    pass
                return False

            if _probe_and_start():
                return

            for _ in range(12):
                time.sleep(5)
                if _probe_and_start():
                    return

            if not _already_syncing():
                self.mw.settings.setdefault("status", {})["messages_set_completed"] = True
                self.mw.save_settings()
                self.mw.sync_thread = threading.Thread(
                    target=self.mw.start_sync, daemon=True
                )
                self.mw.sync_thread.start()
        threading.Thread(target=_fallback, daemon=True).start()
