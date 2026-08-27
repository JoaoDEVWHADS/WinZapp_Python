"""Tests distinguishing voice messages (PTT / mensagem de voz) from generic audio files.

Feature: In both the conversation messages list and the chat list preview,
WinZapp must distinguish PTT voice notes ("mensagem de voz" / "voice message")
from generic attached audio files ("áudio" / "audio").
"""

import sys
import types
from unittest.mock import MagicMock

try:
    import wx
    import wx.adv
except ImportError:
    for _mod in ("wx", "wx.adv"):
        if _mod not in sys.modules:
            mod = types.ModuleType(_mod)
            if "." not in _mod:
                mod.__path__ = []
            sys.modules[_mod] = mod
    class _FakeWxModule(types.ModuleType):
        ACC_OK = 0
        ACC_NOT_IMPLEMENTED = -1
        def __getattr__(self, name):
            if name == "__file__":
                return "<fake_wx>"
            if name == "CallAfter":
                return lambda fn, *a, **k: fn(*a, **k)
            if name.startswith("ID_") or name.startswith("wxID_") or name in ("HORIZONTAL", "VERTICAL", "EXPAND", "ALL"):
                return 1000
            if name in ("Frame", "Panel", "Dialog", "Accessible", "Timer", "App", "Window", "Control", "Button"):
                return object
            return MagicMock
    sys.modules["wx"].__class__ = _FakeWxModule
    sys.modules["wx.adv"].__class__ = _FakeWxModule
    wx = sys.modules["wx"]

try:
    import accessible_output2
    from accessible_output2 import outputs
except ImportError:
    if "accessible_output2" not in sys.modules:
        sys.modules["accessible_output2"] = types.ModuleType("accessible_output2")
    sys.modules["accessible_output2.outputs"] = types.ModuleType("accessible_output2.outputs")
    sys.modules["accessible_output2"].outputs = sys.modules["accessible_output2.outputs"]

try:
    import sound_lib
    from sound_lib import stream, output, main, effects
except ImportError:
    for _mod in (
        "sound_lib",
        "sound_lib.output",
        "sound_lib.stream",
        "sound_lib.main",
        "sound_lib.effects",
    ):
        if _mod not in sys.modules:
            mod = types.ModuleType(_mod)
            if "." not in _mod:
                mod.__path__ = []
            sys.modules[_mod] = mod

    sys.modules["sound_lib.main"].bass_call = lambda *a, **k: None
    sys.modules["sound_lib.stream"].FileStream = object
    sys.modules["sound_lib.output"].Output = object
    sys.modules["sound_lib.effects"].Tempo = object

from core.utils import is_voice_message
from ui.conversations import ConversationsPanel


class _FakeI18n:
    def __init__(self, lang="pt-BR"):
        self.lang = lang
        self.dict = {
            "pt-BR": {
                "message_type_audio": "áudio",
                "message_type_voice_message": "mensagem de voz",
                "duration": "duração",
                "minute": "minuto",
                "minutes": "minutos",
                "second": "segundo",
                "seconds": "segundos",
                "and": "e",
                "photo": "foto",
                "video": "vídeo",
                "document": "documento",
                "sticker": "figurinha",
                "contact_label": "contato",
            },
            "en-US": {
                "message_type_audio": "audio",
                "message_type_voice_message": "voice message",
                "duration": "duration",
                "minute": "minute",
                "minutes": "minutes",
                "second": "second",
                "seconds": "seconds",
                "and": "and",
                "photo": "photo",
                "video": "video",
                "document": "document",
                "sticker": "sticker",
                "contact_label": "contact",
            }
        }

    def t(self, key):
        return self.dict.get(self.lang, {}).get(key, key)


class _FakeConvPanel:
    _get_message_content = ConversationsPanel._get_message_content
    _format_duration = ConversationsPanel._format_duration
    _get_quoted_preview = ConversationsPanel._get_quoted_preview
    _resolve_mentions_in_text = ConversationsPanel._resolve_mentions_in_text

    def __init__(self, lang="pt-BR"):
        self.main_window = types.SimpleNamespace(
            i18n=_FakeI18n(lang),
            settings={"accessibility": {"show_link_previews": True}},
        )
        self.contact_names = {}
        self._download_progress = {}


class TestIsVoiceMessageHelper:
    def test_voice_message_with_ptt_in_audio_message(self):
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": True}},
        }
        assert is_voice_message(msg) is True

    def test_voice_message_with_is_ptt(self):
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "isPtt": True}},
        }
        assert is_voice_message(msg) is True

    def test_voice_message_with_top_level_ptt(self):
        msg = {
            "type": "ptt",
            "message": {"audioMessage": {"seconds": 72}},
        }
        assert is_voice_message(msg) is True

    def test_voice_message_with_is_voice_recording(self):
        msg = {
            "messageType": "audioMessage",
            "_is_voice_recording": True,
            "message": {"audioMessage": {"seconds": 72}},
        }
        assert is_voice_message(msg) is True

    def test_generic_audio_file(self):
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": False}},
        }
        assert is_voice_message(msg) is False


class TestConversationGetMessageContent:
    def test_ptt_voice_message_content_pt_br(self):
        panel = _FakeConvPanel("pt-BR")
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": True}},
        }
        assert panel._get_message_content(msg) == "mensagem de voz, duração: 1 minuto e 12 segundos"

    def test_generic_audio_message_content_pt_br(self):
        panel = _FakeConvPanel("pt-BR")
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": False}},
        }
        assert panel._get_message_content(msg) == "áudio, duração: 1 minuto e 12 segundos"

    def test_ptt_voice_message_content_en_us(self):
        panel = _FakeConvPanel("en-US")
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": True}},
        }
        assert panel._get_message_content(msg) == "voice message, duration: 1 minute and 12 seconds"

    def test_generic_audio_message_content_en_us(self):
        panel = _FakeConvPanel("en-US")
        msg = {
            "messageType": "audioMessage",
            "message": {"audioMessage": {"seconds": 72, "ptt": False}},
        }
        assert panel._get_message_content(msg) == "audio, duration: 1 minute and 12 seconds"


class TestQuotedAudioPreview:
    def test_quoted_ptt_preview(self):
        panel = _FakeConvPanel("pt-BR")
        quoted = {
            "messageType": "audioMessage",
            "audioMessage": {"ptt": True},
        }
        assert panel._get_quoted_preview(quoted) == "Mensagem de voz"

    def test_quoted_generic_audio_preview(self):
        panel = _FakeConvPanel("pt-BR")
        quoted = {
            "messageType": "audioMessage",
            "audioMessage": {"ptt": False},
        }
        assert panel._get_quoted_preview(quoted) == "Áudio"
