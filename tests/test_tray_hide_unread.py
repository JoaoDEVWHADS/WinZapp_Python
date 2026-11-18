"""The hide_tray_unread_count option (Settings > Notifications): the tray
tooltip shows only the app name, with no unread count and no status tail.

TrayIcon is a wx.adv.TaskBarIcon and can't be instantiated without a running
wx.App, so update_tooltip is exercised as a plain function bound to a
lightweight stub — same approach as tests/test_tray_unread.py.
"""

from core.tray_manager import TrayIcon
from core.unread_badge import HIDE_TRAY_UNREAD_KEY, tray_unread_hidden


class _I18n:
    def get_language(self):
        pass

    def t(self, key):
        return {
            "tray_no_unread": "no unread messages",
            "tray_unread_singular": "1 unread message from {names}",
            "tray_unread_plural": "{count} unread messages from {names}",
            "tray_offline_mode": "offline mode",
            "and": "and",
        }[key]


class _MainWindowStub:
    def __init__(self, settings=None, chats=None, account_name="Midzi"):
        self.chats = chats or {}
        self._sync_completed = True
        self._deleted_chats = set()
        self.settings = settings if settings is not None else {}
        self.account_name = account_name
        self.multi_account = False
        self.offline_mode = False
        self._tray_status = ""

    def _is_multi_account(self):
        return self.multi_account

    def is_chat_archived(self, jid):
        return False

    def is_chat_locked(self, jid):
        return False

    def is_chat_muted(self, jid):
        return False

    def _resolve_contact_name(self, chat):
        return chat.get("name", "")

    def find_name_through_messages(self, chat):
        return ""

    def find_jid_through_messages(self, chat):
        return ""


def _chat(unread, name="mother"):
    return {
        "unreadCount": unread,
        "name": name,
        "messages": {"messages": {"records": [{"key": {"id": "1"}}]}},
    }


class _TrayStub:
    update_tooltip = TrayIcon.update_tooltip
    _app_label = TrayIcon._app_label
    _build_tooltip = TrayIcon._build_tooltip
    _get_unread_info = TrayIcon._get_unread_info

    def __init__(self, main_window):
        self.main_window = main_window
        self.i18n = _I18n()
        self._icon = object()
        self.removed = 0
        self.icon_text = None
        self._last_tooltip = None

    def RemoveIcon(self):
        self.removed += 1

    def SetIcon(self, icon, tooltip):
        self.icon_text = tooltip


def test_tray_unread_hidden_defaults_to_false():
    assert tray_unread_hidden(None) is False
    assert tray_unread_hidden({}) is False
    assert tray_unread_hidden({"general": {}}) is False
    assert tray_unread_hidden({"general": {HIDE_TRAY_UNREAD_KEY: False}}) is False
    assert tray_unread_hidden({"general": {HIDE_TRAY_UNREAD_KEY: True}}) is True


def test_hidden_tray_tooltip_is_the_app_name_only():
    mw = _MainWindowStub(
        {"general": {HIDE_TRAY_UNREAD_KEY: True}},
        chats={"a@s.whatsapp.net": _chat(4)},
    )
    tray = _TrayStub(mw)

    tray.update_tooltip()

    assert tray.icon_text == "WinZapp"


def test_hidden_tray_tooltip_keeps_the_account_label_when_paired_with_more_than_one():
    mw = _MainWindowStub(
        {"general": {HIDE_TRAY_UNREAD_KEY: True}},
        chats={"a@s.whatsapp.net": _chat(4)},
    )
    mw.multi_account = True
    tray = _TrayStub(mw)

    tray.update_tooltip()

    assert tray.icon_text == "WinZapp — Midzi"


def test_visible_tray_tooltip_counts_unread_as_before():
    mw = _MainWindowStub(
        {},
        chats={"a@s.whatsapp.net": _chat(4)},
    )
    tray = _TrayStub(mw)

    tray.update_tooltip()

    assert tray.icon_text == "WinZapp | 4 unread messages from mother"


def test_enabling_the_option_refreshes_the_icon_text():
    mw = _MainWindowStub(
        {"general": {}},
        chats={"a@s.whatsapp.net": _chat(4)},
    )
    tray = _TrayStub(mw)

    tray.update_tooltip()
    assert tray.icon_text == "WinZapp | 4 unread messages from mother"

    mw.settings["general"][HIDE_TRAY_UNREAD_KEY] = True
    tray.update_tooltip()

    assert tray.icon_text == "WinZapp"
    assert tray.removed >= 1
