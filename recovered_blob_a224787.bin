import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

import types
import unittest.mock


def _create_mock_module(name, attrs=None):
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_wx_mock = _create_mock_module("wx", {
    "App": unittest.mock.MagicMock,
    "Frame": unittest.mock.MagicMock,
    "Panel": unittest.mock.MagicMock,
    "Dialog": unittest.mock.MagicMock,
    "BoxSizer": unittest.mock.MagicMock,
    "StaticText": unittest.mock.MagicMock,
    "TextCtrl": unittest.mock.MagicMock,
    "Button": unittest.mock.MagicMock,
    "ListCtrl": unittest.mock.MagicMock,
    "CheckBox": unittest.mock.MagicMock,
    "RadioButton": unittest.mock.MagicMock,
    "ComboBox": unittest.mock.MagicMock,
    "Notebook": unittest.mock.MagicMock,
    "Gauge": unittest.mock.MagicMock,
    "Timer": unittest.mock.MagicMock,
    "Menu": unittest.mock.MagicMock,
    "MessageBox": unittest.mock.MagicMock,
    "CallAfter": lambda func, *args, **kwargs: func(*args, **kwargs),
    "CallLater": lambda delay, func, *args, **kwargs: (
        func(*args, **kwargs) if hasattr(func, "__call__") else None
    ),
    "ID_OK": 5100,
    "ID_CANCEL": 5101,
    "ID_ANY": 9999,
    "ID_APPLY": 5102,
    "OK": 0,
    "CANCEL": 1,
    "YES": 2,
    "NO": 4,
    "YES_NO": 36,
    "ICON_ERROR": 16,
    "ICON_INFORMATION": 64,
    "ICON_QUESTION": 32,
    "ICON_WARNING": 48,
    "DEFAULT_DIALOG_STYLE": 0,
    "RESIZE_BORDER": 0,
    "TE_MULTILINE": 0,
    "TE_READONLY": 0,
    "TE_DONTWRAP": 0,
    "TE_PROCESS_ENTER": 0,
    "CB_READONLY": 0,
    "LC_REPORT": 0,
    "LC_SINGLE_SEL": 0,
    "LC_HRULES": 0,
    "LB_NEEDED_SB": 0,
    "GA_HORIZONTAL": 0,
    "GA_SMOOTH": 0,
    "HSCROLL": 0,
    "EXPAND": 0,
    "ALL": 0,
    "LEFT": 0,
    "RIGHT": 0,
    "TOP": 0,
    "BOTTOM": 0,
    "ALIGN_CENTER": 0,
    "ALIGN_RIGHT": 0,
    "EVT_BUTTON": None,
    "EVT_TEXT": None,
    "EVT_TEXT_ENTER": None,
    "EVT_KEY_DOWN": None,
    "EVT_CHAR": None,
    "EVT_SET_FOCUS": None,
    "EVT_TIMER": None,
    "EVT_CLOSE": None,
    "EVT_CONTEXT_MENU": None,
    "EVT_CHECKLISTBOX": None,
    "EVT_LIST_ITEM_ACTIVATED": None,
    "EVT_LIST_ITEM_FOCUSED": None,
    "EVT_LIST_ITEM_SELECTED": None,
    "WXK_TAB": 9,
    "WXK_RETURN": 13,
    "WXK_SPACE": 32,
    "WXK_DELETE": 127,
    "WXK_BACK": 8,
    "WXK_LEFT": 314,
    "WXK_RIGHT": 315,
    "WXK_UP": 316,
    "WXK_DOWN": 317,
    "WXK_F1": 340,
    "WXK_NUMPAD_ENTER": 347,
    "NOT_FOUND": -1,
    "ACC_OK": 0,
    "ROLE_SYSTEM_HOTKEYFIELD": 0x0D,
    "TE_READONLY": 0,
    "RB_GROUP": 0,
    "LB_NEEDED_SB": 0,
    "ST_NO_AUTORESIZE": 0,
    "CLOSE_BOX": 0,
    "StdDialogButtonSizer": unittest.mock.MagicMock,
    "StaticBox": unittest.mock.MagicMock,
    "StaticBoxSizer": unittest.mock.MagicMock,
    "CheckListBox": unittest.mock.MagicMock,
    "Accessible": unittest.mock.MagicMock,
    "FileDialog": unittest.mock.MagicMock,
    "Slider": unittest.mock.MagicMock,
})

_wx_adv_mock = _create_mock_module("wx.adv", {})

_sound_lib_output = types.ModuleType("sound_lib.output")
_sound_lib_output.Output = unittest.mock.MagicMock
_sound_lib_mock = _create_mock_module("sound_lib", {
    "output": _sound_lib_output,
    "__path__": [],
})
sys.modules["sound_lib.output"] = _sound_lib_output
_sound_lib_mock.output.Output = unittest.mock.MagicMock

_sound_lib_stream_mock = _create_mock_module("sound_lib.stream", {
    "FileStream": type("FileStream", (), {}),
})

_accessible_output2_mock = _create_mock_module("accessible_output2", {
    "outputs": types.ModuleType("accessible_output2.outputs"),
})
_accessible_output2_mock.outputs.auto = unittest.mock.MagicMock

_autostart_mock = _create_mock_module("autostart", {
    "acquire_single_instance_mutex": lambda: True,
    "activate_existing_window": lambda: None,
    "is_autostart_enabled": lambda: False,
    "set_autostart": lambda enable: None,
})


import pytest


@pytest.fixture
def mock_wx():
    return _wx_mock


@pytest.fixture
def mock_settings():
    return {
        "connection": {
            "evolution_server": "http://127.0.0.1",
            "evolution_port": 3414,
            "evolution_ws_server": "ws://127.0.0.1",
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
