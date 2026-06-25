import json
import os
import shutil
import sys
import threading
import wx

from app_paths import data_path, resource_path
from traceback import format_exc


class SettingsService:

    def __init__(self, main_window):
        self.mw = main_window

    def load_settings(self):
        settings_file = data_path("settings.json")
        if not os.path.isfile(settings_file):
            default_file = resource_path("data", "settings_default.json")
            if os.path.isfile(default_file):
                os.makedirs(os.path.dirname(settings_file), exist_ok=True)
                shutil.copy2(default_file, settings_file)
        try:
            with open(settings_file, "r") as f:
                self.mw.settings = json.load(f)
        except Exception:
            if hasattr(self.mw, 'i18n'):
                msg   = self.mw.i18n.t('settings_load_failed')
                title = self.mw.i18n.t("error").format(app_name=self.mw.app_name)
            else:
                from core.i18n import _load_translations
                _pt   = _load_translations("pt-BR")
                msg   = _pt.get("settings_load_failed",
                                "Erro ao carregar o arquivo de configuração:")
                title = _pt.get("error", "{app_name} Erro").format(
                    app_name=self.mw.app_name)
            if hasattr(self.mw, 'error_sound'):
                self.mw.error_sound.play()
            wx.MessageBox(f"{msg}\n{format_exc()}", title, wx.OK | wx.ICON_ERROR)
            sys.exit()
        self._migrate_settings()

    def _migrate_settings(self):
        changed = False
        if "audio_default_speed" in self.mw.settings.get("general", {}):
            speed = self.mw.settings["general"].pop("audio_default_speed")
            self.mw.settings.setdefault("audio_playback", {})["audio_default_speed"] = speed
            changed = True
        if "ui" in self.mw.settings and "user_interface" not in self.mw.settings:
            self.mw.settings["user_interface"] = self.mw.settings.pop("ui")
            changed = True
        if changed:
            self.save_settings()

    def save_settings(self):
        try:
            with open(data_path("settings.json"), "w") as f:
                json.dump(self.mw.settings, f, indent=4)
        except Exception:
            self.mw.error_sound.play()
            wx.MessageBox(f"{self.mw.i18n.t('settings_save_failed')} {format_exc()}", self.mw.i18n.t("error").format(app_name=self.mw.app_name), wx.OK | wx.ICON_ERROR)

    def _on_mark_all_read(self, event=None):
        def _worker():
            for jid, chat in list(self.mw.chats.items()):
                if int(chat.get("unreadCount") or 0) > 0:
                    try:
                        self.mw.mark_conversation_as_read(jid)
                    except Exception:
                        pass
        threading.Thread(target=_worker, daemon=True).start()

    def _schedule_save_settings(self):
        with self.mw._save_timer_lock:
            existing = getattr(self.mw, "_settings_save_timer", None)
            if existing is not None:
                existing.cancel()
            t = threading.Timer(2.0, self.save_settings)
            t.daemon = True
            self.mw._settings_save_timer = t
            t.start()
