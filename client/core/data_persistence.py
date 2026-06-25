import logging
import os
import sys
import threading
import wx
from traceback import format_exc
from core.utils import encrypt_json, decrypt_json
from app_paths import data_path


class DataPersistence:
    """Encrypted data persistence layer for WinZapp.

    Owns all load/save operations for messages.dat (chats, contacts,
    lid caches, status updates) and the media directories.

    Receives the MainWindow instance as *mw* and accesses its attributes
    (``key``, ``chats``, ``contacts``, ``i18n``, …) via ``self.mw``.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── public helpers ───────────────────────────────────────────

    def create_basic_files(self):
        data_dir = data_path("")
        os.makedirs(data_dir, exist_ok=True)

        messages_file = data_path("messages.dat")
        if not os.path.isfile(messages_file):
            with open(messages_file, "wb") as f:
                f.write(encrypt_json({"chats": {}, "contacts": {}}, self.mw.key))

        os.makedirs(data_path("media"), exist_ok=True)
        os.makedirs(data_path("voice_messages"), exist_ok=True)

        log_dir = data_path("log")
        os.makedirs(log_dir, exist_ok=True)
        stderr_log = os.path.join(log_dir, "stderr.log")
        stdout_log = os.path.join(log_dir, "stdout.log")
        if not os.path.isfile(stderr_log):
            open(stderr_log, "w").close()
        if not os.path.isfile(stdout_log):
            open(stdout_log, "w").close()
        sys.stderr = open(stderr_log, "a")
        sys.stdout = open(stdout_log, "a")

    def get_chats(self):
        messages_file = data_path("messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.mw.key)
                    return decrypted_data.get("chats", {})
                else:
                    return {}
        except Exception as e:
            self.mw.error_sound.play()
            wx.MessageBox(
                f"{self.mw.i18n.t('chat_load_failed')} {format_exc()}",
                self.mw.i18n.t("error").format(app_name=self.mw.app_name),
                wx.OK | wx.ICON_ERROR,
            )
            return {}

    def get_contacts(self):
        messages_file = data_path("messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.mw.key)
                    return decrypted_data.get("contacts", {})
                else:
                    return {}
        except Exception as e:
            self.mw.error_sound.play()
            wx.MessageBox(
                f"{self.mw.i18n.t('contact_load_failed')} {format_exc()}",
                self.mw.i18n.t("error").format(app_name=self.mw.app_name),
                wx.OK | wx.ICON_ERROR,
            )
            return {}

    def save_data(self, chats, contacts):
        with self.mw._save_lock:
            messages_file = data_path("messages.dat")
            try:
                lid_to_phone = getattr(self.mw, "_lid_to_phone", {})
                unresolvable_lids = list(getattr(self.mw, "_unresolvable_lids", set()))
                unresolvable_names = list(getattr(self.mw, "_unresolvable_names", set()))
                encrypted_data = encrypt_json(
                    {
                        "chats": chats,
                        "contacts": contacts,
                        "lid_to_phone": lid_to_phone,
                        "unresolvable_lids": unresolvable_lids,
                        "unresolvable_names": unresolvable_names,
                        "status_updates": getattr(self.mw, "_status_updates", {}),
                    },
                    self.mw.key,
                )
                with open(messages_file, "wb") as f:
                    f.write(encrypted_data)
            except Exception:
                self.mw.error_sound.play()
                wx.CallAfter(
                    wx.MessageBox,
                    f"{self.mw.i18n.t('data_save_failed')} {format_exc()}",
                    self.mw.i18n.t("error").format(app_name=self.mw.app_name),
                    wx.OK | wx.ICON_ERROR,
                )

    def _do_save(self):
        self.save_data(self.mw.chats, self.mw.contacts)

    def _schedule_save(self):
        with self.mw._save_timer_lock:
            if self.mw._save_timer is not None:
                self.mw._save_timer.cancel()
            t = threading.Timer(0.15, self._do_save)
            t.daemon = True
            self.mw._save_timer = t
            t.start()

    def clear_local_data(self):
        logging.info("[clear_local_data] Clearing all local caches, media, and messages.dat...")
        self.mw.chats = {}
        self.mw.contacts = {}
        self.mw._status_updates = {}
        if hasattr(self.mw, "_lid_to_phone"):
            self.mw._lid_to_phone.clear()
        else:
            self.mw._lid_to_phone = {}
        if hasattr(self.mw, "_phone_to_lid"):
            self.mw._phone_to_lid.clear()
        else:
            self.mw._phone_to_lid = {}
        if hasattr(self.mw, "_unresolvable_lids"):
            self.mw._unresolvable_lids.clear()
        else:
            self.mw._unresolvable_lids = set()
        if hasattr(self.mw, "_unresolvable_names"):
            self.mw._unresolvable_names.clear()
        else:
            self.mw._unresolvable_names = set()
        if hasattr(self.mw, "_resolving_lids"):
            self.mw._resolving_lids.clear()
        else:
            self.mw._resolving_lids = set()

        messages_file = data_path("messages.dat")
        try:
            key = getattr(self.mw, "key", None)
            if key is None:
                key = self.mw.retrieve_secret_key()
            with open(messages_file, "wb") as f:
                f.write(encrypt_json({"chats": {}, "contacts": {}}, key))
            logging.info("[clear_local_data] Reset messages.dat successfully.")
        except Exception as e:
            logging.error(f"[clear_local_data] Failed to reset messages.dat: {e}")

        for subdir in ("media", "voice_messages"):
            path = data_path(subdir)
            if os.path.exists(path):
                import shutil

                try:
                    for filename in os.listdir(path):
                        file_path = os.path.join(path, filename)
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    logging.info(f"[clear_local_data] Cleared folder: {subdir}")
                except Exception as e:
                    logging.error(f"[clear_local_data] Failed to clear {subdir} folder: {e}")
