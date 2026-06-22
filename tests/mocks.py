import threading
import unittest.mock


class MockMainWindow:
    """Minimal mock of main_window for unit testing core modules."""

    def __init__(self):
        self.chats = {}
        self.contacts = {}
        self.settings = {
            "connection": {
                "evolution_server": "http://127.0.0.1",
                "evolution_port": 3414,
                "evolution_ws_server": "http://127.0.0.1",
            },
            "general": {
                "language": "pt-BR",
                "sounds_enabled": True,
                "notifications_enabled": True,
            },
            "user_interface": {
                "messages_page_size": 200,
            },
            "status": {},
            "privateinfo": {},
            "muted_chats": {},
            "archived_chats": [],
            "deleted_chats": [],
            "pinned_chats": [],
            "cleared_chats": {},
        }
        self.key = None
        self.offline_mode = False
        self._wa_connected = True
        self._own_sent_ids = set()
        self._own_sent_ids_lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self._sync_thread_lock = threading.Lock()
        self._media_pool = unittest.mock.MagicMock()
        self._media_pool._max_workers = 6
        self._last_send_error = ""
        self.evolution_server = "http://127.0.0.1"
        self.evolution_port = 3414
        self.evolution_ws_server = "http://127.0.0.1"
        self.evolution_api_key = ""
        self.token = ""
        self.my_jid = ""
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self._presence_cache = {}
        self._presence_pushname_map = {}
        self._composing_chats = {}
        self._presence_timers = {}
        self._sync_completed = False
        self.sync_thread = None
        self._tray_status = ""
        self.i18n = _MockI18n()
        self.speak_output = unittest.mock.MagicMock()
        self.error_sound = unittest.mock.MagicMock()
        self.pairing_code_updated_sound = unittest.mock.MagicMock()

    def _resolve_contact_name(self, chat):
        return ""

    def find_name_through_messages(self, chat):
        return ""

    def find_jid_through_messages(self, chat):
        return ""

    def _normalize_jid(self, jid):
        if not jid:
            return jid
        if jid.endswith("@c.us"):
            return jid.replace("@c.us", "@s.whatsapp.net")
        return jid

    def _schedule_save(self):
        pass

    def _schedule_set_chats(self):
        pass

    def _schedule_save_settings(self):
        pass

    def save_settings(self):
        pass

    def set_chats(self):
        pass

    def output(self, text, interrupt=True):
        pass

    def _set_status(self, status):
        self._tray_status = status

    def on_new_message(self, msg):
        pass

    def _on_message_sent(self, local_id, audio_path, real_id):
        pass

    def _on_message_failed(self, local_id, error, is_media):
        pass

    def send_text_message(self, *args, **kwargs):
        return True

    def send_audio_message(self, *args, **kwargs):
        return True

    def send_media_attachment(self, *args, **kwargs):
        return True

    def send_contact_attachment(self, *args, **kwargs):
        return True


class _MockI18n:
    """Mock do sistema de internacionalizacao."""

    def __init__(self):
        self._lang = "pt-BR"

    def get_language(self):
        return "pt-BR"

    def t(self, key):
        translations = {
            "wa_disconnected_temp": "WhatsApp desconectado temporariamente",
            "device_logged_out": "Dispositivo desconectado da conta",
            "error": "Erro",
            "qrcode_image_updated": "QR Code atualizado",
            "qrcode_updated": "Codigo de pareamento atualizado",
            "tray_wa_disconnected": "WhatsApp Desconectado",
            "no_contacts": "Nenhum contato encontrado",
            "no_groups_available": "Nenhum grupo disponivel",
            "no_results": "Nenhum resultado encontrado",
        }
        return translations.get(key, f"[{key}]")


class MockResponse:
    """Mock for requests.Response."""

    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {"content-type": "application/json"}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.ok:
            raise Exception(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
