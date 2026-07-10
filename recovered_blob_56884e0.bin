import os
import sys
import time
import shutil
import socket as _socket
import subprocess
import threading
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import base64
import socketio
import atexit
import ctypes
import ctypes.wintypes
from accessible_output2 import outputs
from core.sound_system import SoundSystem, Sound
from core.i18n import I18n
from core.websocket_client import WebSocketClient
from core.utils import encrypt, decrypt, encrypt_json, decrypt_json, generate_and_save_key, retrieve_key, format_number, is_phone_like
from app_paths import resource_path, data_path
from core.message_queue import MessageQueue, PendingMessage
import wx
import wx.adv
from ui.dialogs.connect import Connect
from ui.navigation import NavigationPanel
from ui.conversations import ConversationsPanel, ArchivedConversationsPanel
from status_panel import StatusPanel
from version import __version__
import json
from traceback import format_exc, format_exception
import pyperclip

# Tell Windows to use "WinZapp" as the App User Model ID so notifications
# show the correct name instead of the executable filename.
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WinZapp")
except Exception:
    pass


def _is_elevated() -> bool:
    """Return True when the current process holds an elevated (admin) token."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class _Win32Proc:
    """Minimal Popen-compatible wrapper around a Win32 process handle returned by
    CreateProcessWithTokenW (used when de-elevating the Node.js child process)."""

    __slots__ = ("_h", "pid")

    def __init__(self, h_process, pid: int):
        self._h  = h_process
        self.pid = pid

    def poll(self):
        ec = ctypes.wintypes.DWORD(0)
        ctypes.windll.kernel32.GetExitCodeProcess(self._h, ctypes.byref(ec))
        return None if ec.value == 259 else int(ec.value)  # 259 = STILL_ACTIVE

    def terminate(self):
        try:
            ctypes.windll.kernel32.TerminateProcess(self._h, 1)
        except Exception:
            pass
        finally:
            try:
                ctypes.windll.kernel32.CloseHandle(self._h)
            except Exception:
                pass


class _HotkeyManager:
    """
    Registers a Windows global hotkey (RegisterHotKey) and calls a callback
    on the wx main thread when the hotkey is pressed from any application.

    A background thread owns the Win32 message loop (GetMessageW) so WM_HOTKEY
    is received even when WinZapp is minimised or in the background.
    """

    _WM_HOTKEY = 0x0312
    _HOTKEY_ID = 1

    def __init__(self, vk: int, mod: int, callback):
        self._vk       = vk
        self._mod      = mod
        self._callback = callback
        self._stop     = threading.Event()
        self._thread   = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.wintypes.LONG), ("y", ctypes.wintypes.LONG)]

        class _MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd",    ctypes.wintypes.HWND),
                ("message", ctypes.wintypes.UINT),
                ("wParam",  ctypes.wintypes.WPARAM),
                ("lParam",  ctypes.wintypes.LPARAM),
                ("time",    ctypes.wintypes.DWORD),
                ("pt",      _POINT),
            ]

        if not user32.RegisterHotKey(None, self._HOTKEY_ID, self._mod, self._vk):
            print(f"[HotkeyManager] RegisterHotKey failed: {kernel32.GetLastError()}")
            return

        msg = _MSG()
        while not self._stop.is_set():
            # MsgWaitForMultipleObjects with a 200 ms timeout so we can check _stop.
            # 0x0088 = QS_HOTKEY | QS_POSTMESSAGE — wake up immediately when a
            # WM_HOTKEY (posted message) arrives instead of waiting for the timeout.
            result = ctypes.windll.user32.MsgWaitForMultipleObjects(
                0, None, False, 200, 0x0088  # QS_HOTKEY | QS_POSTMESSAGE
            )
            if self._stop.is_set():
                break
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                if msg.message == self._WM_HOTKEY:
                    wx.CallAfter(self._callback)

        user32.UnregisterHotKey(None, self._HOTKEY_ID)

    def stop(self):
        self._stop.set()


def _vk_mod_to_str(vk: int, mod: int) -> str:
    """Convert a (vk, mod) pair to a human-readable string like 'Ctrl+Shift+A'."""
    parts = []
    if mod & 0x0002: parts.append("Ctrl")   # MOD_CONTROL
    if mod & 0x0001: parts.append("Alt")    # MOD_ALT
    if mod & 0x0004: parts.append("Shift")  # MOD_SHIFT
    if mod & 0x0008: parts.append("Win")    # MOD_WIN
    vk_names = {
        0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
        0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End",
        0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right",
        0x28: "Down", 0x2D: "Ins", 0x2E: "Del", 0x70: "F1",
        0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6",
        0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
        0x7A: "F11", 0x7B: "F12",
    }
    if vk in vk_names:
        parts.append(vk_names[vk])
    elif 0x30 <= vk <= 0x39:
        parts.append(chr(vk))
    elif 0x41 <= vk <= 0x5A:
        parts.append(chr(vk))
    else:
        parts.append(f"#{vk:02X}")
    return "+".join(parts)


def _get_short_path_name(long_path: str) -> str:
    """Return Windows short (8.3) path to avoid PostgreSQL initdb failures
    when the install path contains accented characters (e.g. 'Área de Trabalho')."""
    try:
        buf_size = ctypes.windll.kernel32.GetShortPathNameW(long_path, None, 0)
        if buf_size:
            buf = ctypes.create_unicode_buffer(buf_size)
            if ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, buf_size):
                return buf.value
    except Exception:
        pass
    return long_path


def _spawn_delevated(cmd: list, cwd: str, log_fh, main_window) -> bool:
    """
    Launch *cmd* as a restricted (non-admin) process using the Windows Safer API.

    SaferCreateLevel(SAFER_LEVELID_NORMALUSER) produces a token where the
    Administrators SID is marked DENY_ONLY, so PostgreSQL's pgwin32_is_admin()
    / CheckTokenMembership() returns FALSE even when the parent holds an
    elevated token, allowing initdb to proceed.

    Returns True and sets main_window.evolution_process on success.
    Returns False when de-elevation is impossible or the API call fails.
    """
    import msvcrt

    SAFER_SCOPEID_USER        = 1
    SAFER_LEVELID_NORMALUSER  = 0x20000
    SAFER_LEVEL_OPEN          = 1
    SAFER_TOKEN_NULL_IF_EQUAL = 4
    LOGON_WITH_PROFILE        = 0x00000001
    CREATE_NO_WINDOW          = 0x08000000
    STARTF_USESHOWWINDOW      = 0x00000001
    STARTF_USESTDHANDLES      = 0x00000100
    SW_HIDE                   = 0
    DUPLICATE_SAME_ACCESS     = 0x00000002

    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb",              ctypes.wintypes.DWORD),
            ("lpReserved",      ctypes.wintypes.LPWSTR),
            ("lpDesktop",       ctypes.wintypes.LPWSTR),
            ("lpTitle",         ctypes.wintypes.LPWSTR),
            ("dwX",             ctypes.wintypes.DWORD),
            ("dwY",             ctypes.wintypes.DWORD),
            ("dwXSize",         ctypes.wintypes.DWORD),
            ("dwYSize",         ctypes.wintypes.DWORD),
            ("dwXCountChars",   ctypes.wintypes.DWORD),
            ("dwYCountChars",   ctypes.wintypes.DWORD),
            ("dwFillAttribute", ctypes.wintypes.DWORD),
            ("dwFlags",         ctypes.wintypes.DWORD),
            ("wShowWindow",     ctypes.wintypes.WORD),
            ("cbReserved2",     ctypes.wintypes.WORD),
            ("lpReserved2",     ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput",       ctypes.wintypes.HANDLE),
            ("hStdOutput",      ctypes.wintypes.HANDLE),
            ("hStdError",       ctypes.wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess",    ctypes.wintypes.HANDLE),
            ("hThread",     ctypes.wintypes.HANDLE),
            ("dwProcessId", ctypes.wintypes.DWORD),
            ("dwThreadId",  ctypes.wintypes.DWORD),
        ]

    try:
        # ── Step 1: create a SAFER level for a normal (non-admin) user ───────
        h_level = ctypes.wintypes.HANDLE(0)
        if not advapi32.SaferCreateLevel(
            SAFER_SCOPEID_USER,
            SAFER_LEVELID_NORMALUSER,
            SAFER_LEVEL_OPEN,
            ctypes.byref(h_level),
            None,
        ):
            print(f"[_spawn_delevated] SaferCreateLevel failed: {kernel32.GetLastError()}")
            return False

        # ── Step 2: compute a restricted token from the current process token ─
        # NULL input token = use the calling thread's primary token (elevated).
        # The result has the Administrators SID as DENY_ONLY so
        # CheckTokenMembership(adminSID) returns FALSE inside node/PostgreSQL.
        h_restricted = ctypes.wintypes.HANDLE(0)
        ok = advapi32.SaferComputeTokenFromLevel(
            h_level, None, ctypes.byref(h_restricted),
            SAFER_TOKEN_NULL_IF_EQUAL, None,
        )
        advapi32.SaferCloseLevel(h_level)

        if not ok or not h_restricted:
            print(f"[_spawn_delevated] SaferComputeTokenFromLevel failed: {kernel32.GetLastError()}")
            return False

        # ── Step 3: duplicate the log file handle for child inheritance ───────
        h_proc    = kernel32.GetCurrentProcess()
        h_log     = msvcrt.get_osfhandle(log_fh.fileno())
        h_log_dup = ctypes.wintypes.HANDLE(0)
        kernel32.DuplicateHandle(
            h_proc, ctypes.wintypes.HANDLE(h_log), h_proc,
            ctypes.byref(h_log_dup), 0, True, DUPLICATE_SAME_ACCESS,
        )

        si             = _STARTUPINFOW()
        si.cb          = ctypes.sizeof(_STARTUPINFOW)
        si.dwFlags     = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES
        si.wShowWindow = SW_HIDE
        si.hStdOutput  = h_log_dup
        si.hStdError   = h_log_dup
        si.hStdInput   = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE

        # ── Step 4: launch node.exe under the restricted token ────────────────
        pi      = _PROCESS_INFORMATION()
        cmd_str = subprocess.list2cmdline(cmd)
        ok = advapi32.CreateProcessWithTokenW(
            h_restricted, LOGON_WITH_PROFILE, None,
            ctypes.create_unicode_buffer(cmd_str),
            CREATE_NO_WINDOW, None,
            ctypes.create_unicode_buffer(cwd),
            ctypes.byref(si), ctypes.byref(pi),
        )

        kernel32.CloseHandle(h_restricted)
        kernel32.CloseHandle(h_log_dup)

        if not ok:
            print(f"[_spawn_delevated] CreateProcessWithTokenW failed: {kernel32.GetLastError()}")
            return False

        kernel32.CloseHandle(pi.hThread)
        main_window.evolution_process = _Win32Proc(pi.hProcess, int(pi.dwProcessId))
        print("[_spawn_delevated] node.exe launched de-elevated via Safer API")
        return True

    except Exception as e:
        print(f"[_spawn_delevated] failed: {e}")
        return False


class MediaExpiredError(Exception):
    """CDN URL for this media has expired (HTTP 403 or 410 from WhatsApp)."""


class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(None)
        self.app_name = "WinZapp"
        self.SetTitle(self.app_name)

        # Detect no-UI background mode (started via --background flag by Windows
        # autostart).  When True: no dialogs, no sounds, no visible window.
        self.background_mode = "--background" in sys.argv

        #Initialize screen reader/sapi output
        self.speak_output = outputs.auto.Auto()

        #Initialize sound system
        self.sound_system = SoundSystem(self, sound_dir=resource_path("sounds"))
        self.sound_system.start()
        self.load_sounds()
        self.settings = {}
        self.load_settings()

        # ── Language selection on first launch ─────────────────────────────────
        # Show before everything else so the user can pick their language
        # before any module installation or connection dialogs appear.
        if not self.background_mode:
            self._ensure_language_selected()

        #Initialize helper classes
        self.connect = Connect(self)
        self.i18n = I18n(self)
        self.i18n.get_language()

        # Terms of service – show once before anything else happens
        if not self.background_mode:
            self._check_terms_acceptance()

        #bind exception global handler for unexpected errors
        sys.excepthook = self.exception_handler

        self.ws = None

        #Get connection settings (no authentication_server - Evolution runs locally)
        self.evolution_server = self.settings.get("connection", {}).get("evolution_server", "http://127.0.0.1")
        self.evolution_port = self.settings.get("connection", {}).get("evolution_port", 3414)
        self.evolution_ws_server = self.settings.get("connection", {}).get("evolution_ws_server", "ws://127.0.0.1")
        self.evolution_api_key = self.settings.get("connection", {}).get("evolution_api_key", "wz-local-api-key")

        #Set basic variables
        self.chats = {}
        self.chat_names = []
        self.contacts = {}
        # Set by init_UI() when all wx widgets are ready.  start_sync() waits
        # on this before making any wx.CallAfter calls so it never touches
        # widgets that don't exist yet (e.g. when ShowModal() is blocking init_UI).
        self._ui_ready_event = threading.Event()

        # Check and install API modules if needed (first run only)
        self.ensure_api_modules_installed()

        # Check that the installed Evolution API meets the minimum required version
        self.ensure_evolution_version()

        #Start local Evolution API (if bundled)
        self.evolution_process = None
        self.ensure_evolution_running()

        # First-run dialogs: autostart and global hotkey (normal mode only, once ever)
        if not self.background_mode:
            self._check_first_run()
            self._check_hotkey_first_run()

        self.offline_mode = False
        # True while the Baileys/WhatsApp WebSocket is connected; False after a
        # "Connection Closed" error. The MessageQueue checks this before sending.
        self._wa_connected = True
        # IDs of messages sent by WinZapp itself (via MessageQueue).  Used by
        # WebSocketClient.on_messages_upsert to distinguish "echo of our own
        # send" (skip — already in UI) from "sent on another device" (show).
        # Populated from the MessageQueue worker thread immediately after the
        # API returns the real message ID, so it is always populated before the
        # corresponding WebSocket echo event can be processed.
        self._own_sent_ids: set = set()
        self._own_sent_ids_lock = threading.Lock()
        # Serialises concurrent writes to messages.dat (one lock, two helpers below).
        self._save_lock = threading.Lock()
        self._save_timer: "threading.Timer | None" = None
        self._save_timer_lock = threading.Lock()
        # Status text shown in the title bar and tray tooltip (e.g. "sincronizando")
        self._tray_status = ""

        #Play startup sound (skipped in background mode)
        if not self.background_mode:
            self.startup_sound.play()

        # Track whether the user went through the pairing flow this session
        self._just_paired = False

        #Check for what window should be shown (skipped in background mode)
        if not self.background_mode:
            if not self.connect.check_connection_status():
                self.connect.show_connection_dial()
                self.ws.sio.disconnect()
                self._just_paired = True
        self.retrieve_token()
        #Initialize websocket
        self.ws = WebSocketClient(self, self.connect, self.token)

        self.prepare_sync()
        # Initialise outgoing-message queue (must exist before init_UI so the
        # ConversationsPanel can call self.main_window.message_queue.enqueue).
        self.message_queue = MessageQueue(self)
        try:
            self.connect_websocket()
        except Exception:
            self.error_sound.play()
            wx.MessageBox(
                self.i18n.t("websocket_failed_reconnect"),
                self.i18n.t("connection_error"),
                wx.OK | wx.ICON_WARNING,
            )
            self.connect.show_connection_dial()
            self._just_paired = True
        self.init_UI()


    def init_UI(self):
        self.SetMinSize((400, 300))
        self.main_panel = wx.Panel(self)

        self.navigation_panel = NavigationPanel(self, self.main_panel)
        self.content_panel = wx.Panel(self.main_panel)
        self.conversations_panel = ConversationsPanel(self, self.content_panel)
        self.archived_conversations_panel = ArchivedConversationsPanel(
            self, self.content_panel
        )
        self.archived_conversations_panel.Hide()
        self.status_panel = StatusPanel(self, self.content_panel)
        self.status_panel.Hide()

        # Content panel: all panels fill it; only one is shown at a time
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self.conversations_panel, 1, wx.EXPAND)
        content_sizer.Add(self.archived_conversations_panel, 1, wx.EXPAND)
        content_sizer.Add(self.status_panel, 1, wx.EXPAND)
        self.content_panel.SetSizer(content_sizer)

        # Main panel: nav sidebar on left, content on right
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        main_sizer.Add(self.navigation_panel, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(self.content_panel, 1, wx.EXPAND | wx.ALL, 5)
        self.main_panel.SetSizer(main_sizer)

        # Frame sizer
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self.main_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        self.create_accelerator_table()

        # ── Menu bar ──────────────────────────────────────────────────────────
        self._update_checker = None
        self._build_menubar()

        # ── Online presence (sendPresence) ────────────────────────────────────
        # Sends "available" while the window is focused; "unavailable" otherwise.
        self._presence_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER,    self._on_presence_timer,   self._presence_timer)
        self.Bind(wx.EVT_ACTIVATE, self._on_window_activate)

        # ── System tray icon ──────────────────────────────────────────────────
        self.tray_icon = None
        # True while the window is physically hidden to tray (set in _on_close,
        # cleared in restore_window).  Used to suppress tray-tooltip redraws
        # while the window is visible — prevents NVDA focus disruption.
        self._window_hidden = self.background_mode
        self._init_tray()

        # ── Notification manager ──────────────────────────────────────────────
        from core.notification_manager import NotificationManager
        self.notification_manager = NotificationManager(self)

        # ── Global hotkey ─────────────────────────────────────────────────────
        self._hotkey_manager = None
        self._apply_global_hotkey()

        # Intercept window-close: hide to tray instead of quitting (when tray active)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # In background mode the window is intentionally hidden; it can be
        # restored later by a second instance or a future tray-icon action.
        if not self.background_mode:
            self.Show()
        #Set offline chats for the first time
        self.set_chats()
        # All widgets exist and the initial chat list is painted — unblock any
        # sync thread that was waiting for the UI to be ready.
        self._ui_ready_event.set()

        # ── Quick tip after first pairing ─────────────────────────────────────
        if not self.background_mode and self._just_paired:
            wx.CallAfter(self._check_quick_tip)

        # ── Auto-updater ──────────────────────────────────────────────────────
        if not self.background_mode:
            wx.CallLater(2000, self._start_update_checker)

        app.MainLoop()

    # ── Menu bar ─────────────────────────────────────────────────────────────

    def _build_menubar(self):
        """Create the menu bar with Arquivo and Ajuda menus."""
        self._ID_MARK_ALL_READ = wx.NewIdRef()
        self._ID_SHORTCUTS     = wx.NewIdRef()
        self._ID_FORCE_UPDATE  = wx.NewIdRef()
        self._ID_ABOUT         = wx.NewIdRef()

        menubar = wx.MenuBar()

        # ── Arquivo ───────────────────────────────────────────────────────────
        file_menu = wx.Menu()
        file_menu.Append(
            self._ID_MARK_ALL_READ,
            f"{self.i18n.t('menu_mark_all_read')}\tCtrl+Shift+Alt+M",
        )
        menubar.Append(file_menu, self.i18n.t("menu_file"))

        # ── Ajuda ─────────────────────────────────────────────────────────────
        help_menu = wx.Menu()
        help_menu.Append(
            self._ID_SHORTCUTS,
            f"{self.i18n.t('menu_shortcuts')}\tF1",
        )
        help_menu.AppendSeparator()
        help_menu.Append(self._ID_FORCE_UPDATE, self.i18n.t("menu_force_update"))
        help_menu.AppendSeparator()
        help_menu.Append(self._ID_ABOUT, self.i18n.t("menu_about"))
        menubar.Append(help_menu, self.i18n.t("menu_help"))

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self._on_mark_all_read, id=self._ID_MARK_ALL_READ)
        self.Bind(wx.EVT_MENU, self.on_f1,             id=self._ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self._on_force_update,  id=self._ID_FORCE_UPDATE)
        self.Bind(wx.EVT_MENU, self._on_about,         id=self._ID_ABOUT)

    def _refresh_menubar(self):
        """Retranslate the menu bar labels after a language change."""
        mb = self.GetMenuBar()
        if mb is None:
            return
        mb.SetMenuLabel(0, self.i18n.t("menu_file"))
        mb.GetMenu(0).FindItemById(self._ID_MARK_ALL_READ).SetItemLabel(
            f"{self.i18n.t('menu_mark_all_read')}\tCtrl+Shift+Alt+M"
        )
        mb.SetMenuLabel(1, self.i18n.t("menu_help"))
        mb.GetMenu(1).FindItemById(self._ID_SHORTCUTS).SetItemLabel(
            f"{self.i18n.t('menu_shortcuts')}\tF1"
        )
        mb.GetMenu(1).FindItemById(self._ID_FORCE_UPDATE).SetItemLabel(
            self.i18n.t("menu_force_update")
        )
        mb.GetMenu(1).FindItemById(self._ID_ABOUT).SetItemLabel(
            self.i18n.t("menu_about")
        )

    def _on_about(self, event=None):
        """Show application authorship, version and license information."""
        info = "\n".join(
            textwrap.fill(line, width=100, break_long_words=False, break_on_hyphens=False)
            for line in (
                "Desenvolvido originalmente por: Gabriel Haberkamp.",
                "",
                "Agradecimentos especiais:",
                "Wendrill Aksenow Brandão: pela tradução do programa WinZapp para Português de Portugal.",
                "Fabiano Ferreira, Tadeu Junior, Wagner Soares da Silva, Ruan Matews Rebelo Santos e todos da comunidade que ajudaram, seja testando, implementando melhorias ou dando sugestões / relatórios de bugs.",
                "",
                f"Versão atual: {__version__}.",
                "Licenciado sob a licença GNU Lesser General Public License V3 (GPLV3).",
            )
        )

        dialog = wx.Dialog(
            self,
            title=self.i18n.t("about_dialog_title"),
            size=(620, 260),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)
        info_ctrl = wx.TextCtrl(
            panel,
            value=info,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        sizer.Add(info_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        close_btn = wx.Button(panel, id=wx.ID_OK, label=self.i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()

    def _on_mark_all_read(self, event=None):
        """Mark every conversation with unread messages as read."""
        def _worker():
            for jid, chat in list(self.chats.items()):
                if int(chat.get("unreadCount") or 0) > 0:
                    try:
                        self.mark_conversation_as_read(jid)
                    except Exception:
                        pass
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_global_hotkey(self):
        """Register (or unregister) the global hotkey from settings."""
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()
            self._hotkey_manager = None
        hk = self.settings.get("general", {}).get("global_hotkey")
        if not hk or not isinstance(hk, dict):
            return
        vk  = hk.get("vk", 0)
        mod = hk.get("mod", 0)
        if vk:
            self._hotkey_manager = _HotkeyManager(vk, mod, self.restore_window)

    def set_global_hotkey(self, vk: int, mod: int):
        """Save and apply a new global hotkey (vk=0 removes it)."""
        self.settings.setdefault("general", {})
        if vk:
            self.settings["general"]["global_hotkey"] = {"vk": vk, "mod": mod}
        else:
            self.settings["general"].pop("global_hotkey", None)
        self.save_settings()
        self._apply_global_hotkey()

    def _set_status(self, status: str):
        """Update window title and tray tooltip to reflect current status."""
        self._tray_status = status
        self._update_title()
        if getattr(self, "tray_icon", None) is not None and self._window_hidden:
            self.tray_icon.update_tooltip()

    def _update_title(self):
        """
        Rebuild the frame title from the app name, the number of conversations
        with unread messages and the current status, e.g.:
          "WinZapp"
          "WinZapp (2)"
          "WinZapp (2) | modo offline"
          "WinZapp (3) | baixando mídias"
        """
        title   = self.i18n.t("app_name")
        deleted = set(self.settings.get("deleted_chats", []))
        unread_chats = sum(
            1 for jid, chat in self.chats.items()
            if jid not in deleted and int(chat.get("unreadCount") or 0) > 0
        )
        if unread_chats:
            title += f" ({unread_chats})"
        if self.offline_mode:
            title += f" | {self.i18n.t('tray_offline_mode')}"
        if self._tray_status:
            title += f" | {self._tray_status}"
        self.SetTitle(title)

    def _allow_ui_focus_changes(self) -> bool:
        """Return True only when WinZapp is already visible and active."""
        return (
            not self.background_mode
            and not getattr(self, "_window_hidden", False)
            and self.IsShown()
            and not self.IsIconized()
            and self.IsActive()
        )

    def toggle_offline_mode(self):
        """
        Toggle the user-controlled offline mode (tray menu item).
        While offline the outgoing message queue is suspended; disabling it
        wakes the queue so pending messages are sent immediately.
        """
        self.offline_mode = not self.offline_mode
        self.offline_mode_sound.play()
        if self.offline_mode:
            self.output(self.i18n.t("offline_mode_enabled"), interrupt=True)
        else:
            self.output(self.i18n.t("offline_mode_disabled"), interrupt=True)
            if getattr(self, "message_queue", None) is not None:
                self.message_queue.flush()
        self._update_title()
        if getattr(self, "tray_icon", None) is not None and self._window_hidden:
            self.tray_icon.update_tooltip()

    def _on_force_update(self, event):
        if self._update_checker is None:
            self._start_update_checker(force=True)
        else:
            self._update_checker.force_check()

    # ── Auto-updater ──────────────────────────────────────────────────────────

    def _start_update_checker(self, force: bool = False):
        updates_enabled = self.settings.get("general", {}).get("updates_enabled", True)
        if not updates_enabled and not force:
            return
        from updater import UpdateChecker
        self._update_checker = UpdateChecker(self)
        if force:
            self._update_checker.force_check()
        else:
            self._update_checker.start()

    # ── Tray / window lifecycle ───────────────────────────────────────────────

    # ── Online presence ───────────────────────────────────────────────────────

    def _on_window_activate(self, event):
        """
        Fired by wxPython when the main window gains or loses OS focus.
        - Gained focus  → send "available" immediately, then every 20 s
        - Lost focus    → stop the timer, send "unavailable" once
        """
        if self.background_mode:
            event.Skip()
            return
        token = getattr(self, "token", None)
        if not token:
            event.Skip()
            return
        if event.GetActive():
            threading.Thread(
                target=self._send_presence, args=("available",), daemon=True
            ).start()
            if not self._presence_timer.IsRunning():
                self._presence_timer.Start(20_000)   # refresh every 20 s
        else:
            self._presence_timer.Stop()
            threading.Thread(
                target=self._send_presence, args=("unavailable",), daemon=True
            ).start()
        event.Skip()

    def _on_presence_timer(self, event):
        """Periodic keep-alive: resend 'available' while window is focused."""
        token = getattr(self, "token", None)
        if token:
            threading.Thread(
                target=self._send_presence, args=("available",), daemon=True
            ).start()

    def _send_presence(self, presence: str):
        """
        POST /instance/setPresence/{token}  (Evolution API v2)
        Body: {"presence": "available" | "unavailable"}

        Always runs on a background thread — never blocks the UI.
        """
        token = getattr(self, "token", None)
        if not token:
            return
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/instance/setPresence/{token}"
        )
        headers = {"apikey": token, "Content-Type": "application/json"}
        try:
            requests.post(url, json={"presence": presence}, headers=headers, timeout=5)
        except Exception:
            pass

    def _init_tray(self):
        """Create the system-tray icon if the setting is enabled."""
        show = self.settings.get("general", {}).get("show_tray_icon", True)
        if show:
            from core.tray_manager import TrayIcon
            self.tray_icon = TrayIcon(self)

    def _on_close(self, event):
        """
        Intercept the window-close button.
        If the tray icon is active, hide the window instead of exiting.

        Uses Win32 ShowWindow(SW_HIDE) directly so that the window is
        physically hidden even when wx's internal IsShown() state has drifted
        out of sync (e.g. after another process showed the window via Win32
        without going through wx's Show() path).
        """
        if self.tray_icon is not None:
            try:
                import ctypes
                ctypes.windll.user32.ShowWindow(self.GetHandle(), 0)  # SW_HIDE = 0
            except Exception:
                self.Hide()
            self._window_hidden = True
            # One authoritative tray update now that the window is hidden.
            self.tray_icon.update_tooltip()
            event.Veto()
        else:
            self.real_exit()

    def restore_window(self):
        """Bring the WinZapp window to the foreground.

        Uses Win32 ShowWindow + SetForegroundWindow directly to avoid wx
        state-drift: _on_close hides the window via SW_HIDE which bypasses
        wx's internal visibility tracking, so wx-level Show()/Raise() calls
        may silently no-op. SW_RESTORE also handles any minimized state.
        Also refreshes the chat list in case sync updates happened while the
        window was hidden.
        """
        import ctypes
        hwnd = self.GetHandle()
        SW_RESTORE = 9
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        self._window_hidden = False
        if hasattr(self, "conversations_panel"):
            wx.CallAfter(self.add_chats_to_ui)

    def real_exit(self):
        """Completely close WinZapp, removing the tray icon and stopping all threads."""
        # Stop the presence keep-alive timer before tearing down
        if hasattr(self, "_presence_timer") and self._presence_timer.IsRunning():
            self._presence_timer.Stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.RemoveIcon()
                self.tray_icon.Destroy()
            except Exception:
                pass
            self.tray_icon = None
        if hasattr(self, "message_queue"):
            self.message_queue.stop()
        if self._update_checker is not None:
            self._update_checker.stop()
        wx.GetApp().ExitMainLoop()

    # ── Navigate to conversation by JID ──────────────────────────────────────

    def navigate_to_conversation_jid(self, jid: str):
        """Bring the window to front and open the conversation matching jid.

        Only calls restore_window() when the window is actually hidden; if it
        is already visible the caller (e.g. _do_open) has already restored it
        and a second SetForegroundWindow call would steal focus at an unexpected
        moment (e.g. the user has already moved to another app after clicking
        the toast).
        """
        if self._window_hidden:
            self.restore_window()
        if hasattr(self, "conversations_panel"):
            self.conversations_panel.navigate_to_jid(jid)

    # ── Incoming real-time messages ───────────────────────────────────────────

    @staticmethod
    def _normalize_jid(jid: str) -> str:
        """Normalize WhatsApp JID: replace the legacy @c.us suffix with @s.whatsapp.net.
        @g.us (groups) and @lid (linked-device IDs) are left unchanged."""
        if jid and jid.endswith("@c.us"):
            return jid[:-5] + "@s.whatsapp.net"
        return jid

    def _merge_lid_into_phone(self, lid_jid: str, phone_jid: str):
        """Merge a @lid chat entry into the canonical phone (@s.whatsapp.net) entry.

        If only @lid exists, renames it.
        If both exist, copies @lid messages into phone_jid (dedup by ID), then
        removes the @lid entry.
        """
        if lid_jid not in self.chats:
            return
        if phone_jid in self.chats:
            dst_records = (
                self.chats[phone_jid]
                .setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
            )
            src_records = (
                self.chats[lid_jid]
                .get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            dst_ids = {r.get("key", {}).get("id") for r in dst_records}
            for r in src_records:
                if r.get("key", {}).get("id") not in dst_ids:
                    dst_records.append(r)
        else:
            lid_chat = self.chats.pop(lid_jid)
            lid_chat["remoteJid"] = phone_jid
            self.chats[phone_jid] = lid_chat
        self.chats.pop(lid_jid, None)

    def on_new_message(self, msg: dict):
        """
        Called on the main thread (via wx.CallAfter) when a new message
        arrives via the messages.upsert WebSocket event.
        Adds the message to local storage, updates the UI, and sends a
        notification if appropriate.
        """
        key        = msg.get("key", {})
        from_me    = key.get("fromMe", False)
        remote_jid = self._normalize_jid(key.get("remoteJid", ""))
        msg_id     = key.get("id", "")

        if not remote_jid:
            return

        # Statuses (stories) arrive as messages on status@broadcast; they are
        # handled by the Status tab, not as a conversation.
        if remote_jid.endswith("@broadcast"):
            return

        # Reaction messages only update the live display of an existing message;
        # they must not be added to records, unread counts, or notifications.
        if msg.get("messageType") == "reactionMessage":
            if hasattr(self, "conversations_panel"):
                self.conversations_panel.on_incoming_message(remote_jid, msg)
            return

        # ── Resolve canonical JID, merging @lid duplicates ───────────────────
        # Handles both API key formats and all combinations of which entries exist:
        #   OLD format: remoteJid=@lid,  remoteJidAlt=@s.whatsapp.net
        #   NEW format: remoteJid=phone, remoteJidAlt=@lid
        #   Cache-only: no remoteJidAlt, but @lid known from prior messages
        alt_jid = self._normalize_jid(key.get("remoteJidAlt", ""))

        if remote_jid.endswith("@lid"):
            # OLD format — redirect to canonical phone JID
            phone_jid = (
                alt_jid if alt_jid.endswith("@s.whatsapp.net")
                else getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
            )
            if phone_jid:
                self._merge_lid_into_phone(remote_jid, phone_jid)
                remote_jid = phone_jid
        elif alt_jid.endswith("@lid"):
            # NEW format — merge the @lid side into the phone chat
            self._merge_lid_into_phone(alt_jid, remote_jid)
        elif remote_jid.endswith("@s.whatsapp.net"):
            # No remoteJidAlt — consult cache for any @lid counterpart
            lid_jid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
            if lid_jid:
                self._merge_lid_into_phone(lid_jid, remote_jid)

        # ── Ensure the chat record exists ─────────────────────────────────────
        if remote_jid not in self.chats:
            self.chats[remote_jid] = {
                "remoteJid":   remote_jid,
                "unreadCount": 0,
                "pushName":    msg.get("pushName", ""),
                "messages":    {"messages": {
                    "records":     [],
                    "total":       0,
                    "pages":       1,
                    "currentPage": 1,
                }},
            }

        chat = self.chats[remote_jid]

        # ── Avoid duplicate insertions ────────────────────────────────────────
        records = (
            chat.setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
        )
        if msg_id:
            for existing in records:
                if existing.get("key", {}).get("id") == msg_id:
                    return  # already stored

        records.append(msg)

        # ── Update unread count (only for messages we received) ───────────────
        if not from_me:
            # Don't increment unread for the conversation already open — it is
            # immediately visible to the user and will be marked as read.
            _cp   = getattr(self, "conversations_panel", None)
            _open = (
                _cp is not None
                and _cp.conversation is not None
                and _cp.conversation.get("remoteJid") == remote_jid
            )
            _visible = (
                not getattr(self, "_window_hidden", False)
                and self.IsShown()
                and not self.IsIconized()
            )
            if not (_open and _visible):
                chat["unreadCount"] = int(chat.get("unreadCount") or 0) + 1

        # ── Persist in background — debounced so rapid bursts produce one write ─
        self._schedule_save()

        # ── Update conversation list UI (debounced to avoid rapid rebuilds) ───
        self._schedule_set_chats()

        # ── Add message to the open conversation panel (if visible) ──────────
        if hasattr(self, "conversations_panel"):
            self.conversations_panel.on_incoming_message(remote_jid, msg)

        # ── Download media in background ──────────────────────────────────────
        media_types = {"audioMessage", "imageMessage", "videoMessage",
                       "documentMessage", "stickerMessage"}
        if msg.get("messageType") in media_types:
            threading.Thread(
                target=self.sync_if_media, args=(msg,), daemon=True
            ).start()

        # ── Send notification ─────────────────────────────────────────────────
        if from_me:
            return
        if self.is_chat_muted(remote_jid):
            return
        if self.is_chat_archived(remote_jid):
            return
        if not self.settings.get("general", {}).get("notifications_enabled", True):
            return

        from core.notification_manager import (
            format_notification_title, format_notification_body,
            format_foreground_sender,
        )

        body  = format_notification_body(msg, self.i18n)

        # Check if the WinZapp window is currently active/focused
        window_active = (
            not getattr(self, "_window_hidden", False)
            and self.IsShown()
            and not self.IsIconized()
            and self.IsActive()
        )

        if window_active:
            # Determine if the incoming message is for the currently-open conversation
            cp = getattr(self, "conversations_panel", None)
            current_jid = (
                cp.conversation.get("remoteJid", "")
                if cp is not None and cp.conversation is not None
                else ""
            )
            is_current_conv = (current_jid == remote_jid)

            if is_current_conv:
                # Scenario 1: message in the ACTIVE conversation
                # Play current-conversation sound, speak "Sender: body" via AO2
                self.message_current_sound.play()
                sender = format_foreground_sender(msg, self, self.i18n)
                self.output(f"{sender}: {body}")
                # Mark the active conversation as read immediately
                threading.Thread(
                    target=self.mark_conversation_as_read,
                    args=(remote_jid,),
                    daemon=True,
                ).start()
            else:
                # Scenario 2: message in a DIFFERENT conversation (window active)
                # Play foreground sound, speak "Nova mensagem de X: body" via AO2
                self.message_foreground_sound.play()
                title = format_notification_title(msg, self, self.i18n)
                spoken = self.i18n.t("fg_new_msg").format(name=title) + f": {body}"
                self.output(spoken)
            return  # never send system toast when window is active

        # Window is not focused → send system toast notification
        if not self.settings.get("general", {}).get("show_tray_icon", True):
            return
        title = format_notification_title(msg, self, self.i18n)
        if hasattr(self, "notification_manager"):
            self.notification_manager.send(title, body, remote_jid)

    def connect_websocket(self):
        """Connect to the Evolution API WebSocket namespace.

        Retries up to 3 times with a 2-second delay to handle the brief window
        after instance creation where the namespace isn't registered yet on the
        socket.io server (race condition that causes 'namespace failed' errors).
        """
        last_exc = None
        for attempt in range(3):
            try:
                if self.ws.sio.connected:
                    self.ws.sio.disconnect()
                self.ws.sio.connect(
                    f"{self.evolution_ws_server}:{self.evolution_port}/",
                    socketio_path="socket.io",
                    headers={"apikey": self.token},
                    namespaces=[f"/{self.token}"],
                )
                return
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(2)
        raise last_exc

    # ── First-run module installation ──────────────────────────────────────

    def ensure_api_modules_installed(self):
        """
        Ensure the Evolution API is cloned, compiled, and has its node_modules.

        node/node.exe is mandatory in all scenarios — it is the portable Node.js
        runtime bundled with WinZapp that drives both npm and the API itself.
        Its absence is always a fatal error.

        Depending on what is present inside api/:

          dist/main.js absent  →  API not yet cloned/compiled.
                                   Show ApiSetupDialog (git clone + npm install
                                   + npm run build).  This is the expected state
                                   for a fresh install or first developer run.

          dist/main.js present
          node_modules absent  →  API compiled but modules were removed.
                                   Show ModuleInstallDialog (npm install only).

          Both present         →  Nothing to do.

        In background mode dialogs are never shown; if the setup is incomplete
        the process exits silently.
        """
        node_exe     = resource_path("node", "node.exe")
        dist_main    = resource_path("api",  "dist", "main.js")
        node_modules = resource_path("api",  "node_modules")

        # node.exe is mandatory — without it neither npm nor the API can run.
        if not os.path.isfile(node_exe):
            wx.MessageBox(
                "O Node.js portátil não foi encontrado (node/node.exe).\n\n"
                "Este arquivo é essencial para o funcionamento do WinZapp. "
                "Por favor, reinstale o programa.",
                "Node.js não encontrado",
                wx.OK | wx.ICON_ERROR,
            )
            sys.exit(1)

        # Everything already set up — nothing to do.
        if os.path.isfile(dist_main) and os.path.isdir(node_modules):
            return

        if self.background_mode:
            sys.exit(0)

        if not os.path.isfile(dist_main):
            # API not cloned/built yet → full setup (clone + install + build)
            from ui.dialogs.api_setup import ApiSetupDialog
            dlg    = ApiSetupDialog(self)
            result = dlg.ShowModal()
            dlg.Destroy()
        else:
            # API built but node_modules missing → npm install only
            from ui.dialogs.module_install import ModuleInstallDialog
            dlg    = ModuleInstallDialog(self)
            result = dlg.ShowModal()
            dlg.Destroy()

        if result != wx.ID_OK:
            sys.exit(0)

    # ── Evolution API version gate ────────────────────────────────────────────

    def _read_env_value(self, key: str, default: str = "") -> str:
        """Read a value from the bundled client .env file."""
        env_path = resource_path(".env")
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip()
        except Exception:
            pass
        return default

    def _get_installed_evolution_version(self) -> str:
        """Read the Evolution API version from api/package.json."""
        pkg_path = resource_path("api", "package.json")
        try:
            with open(pkg_path, encoding="utf-8") as fh:
                import json as _json
                pkg = _json.load(fh)
            return pkg.get("version", "")
        except Exception:
            return ""

    @staticmethod
    def _version_is_below(installed: str, minimum: str) -> bool:
        """
        Return True when *installed* is strictly older than *minimum*.
        Handles standard semver and pre-release suffixes (e.g. "2.4.0-rc2").
        Returns False on any parsing error so the check never blocks startup
        due to an unexpected version string format.
        """
        if not installed or not minimum:
            return False
        try:
            from packaging.version import Version
            return Version(installed) < Version(minimum)
        except Exception:
            return False

    def ensure_evolution_version(self):
        """
        Compare the installed Evolution API version against the minimum required
        by this WinZapp build (EVOLUTION_API_MINIMUM_VERSION in client/.env).

        If the installed version is older the user is prompted to:
          • Update now   — re-download + rebuild via ApiSetupDialog, then continue
          • Exit         — terminate WinZapp
          • Continue     — proceed without updating (not recommended)

        The check is skipped when:
          - Running in background mode (no UI)
          - api/package.json is absent (setup not done yet)
          - EVOLUTION_API_MINIMUM_VERSION is not defined in the .env
        """
        if self.background_mode:
            return

        dist_main = resource_path("api", "dist", "main.js")
        if not os.path.isfile(dist_main):
            return  # API not installed yet — setup dialog will handle it

        minimum  = self._read_env_value("EVOLUTION_API_MINIMUM_VERSION")
        if not minimum:
            return  # No minimum defined — nothing to check

        installed = self._get_installed_evolution_version()
        if not installed:
            return  # Could not determine installed version — skip silently

        if not self._version_is_below(installed, minimum):
            return  # Installed version meets (or exceeds) the minimum — all good

        # ── Installed version is older than the minimum ───────────────────────
        from ui.dialogs.api_version_check import (
            ApiVersionOutdatedDialog,
            RESULT_UPDATE, RESULT_EXIT, RESULT_CONTINUE,
        )

        dlg    = ApiVersionOutdatedDialog(self, self.i18n, installed, minimum)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == RESULT_EXIT:
            sys.exit(0)

        if result == RESULT_CONTINUE:
            return  # Proceed with the outdated version — user's choice

        # RESULT_UPDATE: re-download and rebuild using the minimum-version tag
        from ui.dialogs.api_setup import ApiSetupDialog
        update_dlg = ApiSetupDialog(
            self,
            title_override=self.i18n.t("api_update_dialog_title"),
            forced_tag=minimum,
        )
        update_result = update_dlg.ShowModal()
        update_dlg.Destroy()

        if update_result != wx.ID_OK:
            # Update was cancelled or failed — exit to avoid running an
            # incompatible API version
            sys.exit(0)

    # ── Evolution API lifecycle ─────────────────────────────────────────────

    def _is_evolution_running(self):
        """Return True if the Evolution API is already listening on the configured port."""
        try:
            with _socket.create_connection(("127.0.0.1", self.evolution_port), timeout=1):
                return True
        except OSError:
            return False

    def _start_evolution_background(self):
        """
        Launch the bundled Evolution API node process in the background.
        stdout and stderr are redirected to api/evolution.log so that startup
        errors can be shown to the user if the port never opens.
        Does nothing if the node or start.js files are not present (dev mode).

        When the current process is elevated (run as Administrator) the child
        is spawned using the non-elevated linked token via CreateProcessWithTokenW
        so that PostgreSQL's initdb can start (it refuses to run as root/admin).
        """
        node_exe = resource_path("node", "node.exe")
        start_js  = resource_path("api",  "start.js")
        if not os.path.isfile(node_exe) or not os.path.isfile(start_js):
            return  # Not bundled — developer runs Evolution separately
        try:
            self._evolution_log_path = resource_path("api", "evolution.log")
            log_fh = open(self._evolution_log_path, "w",
                          encoding="utf-8", errors="replace")
            # Use the short (8.3) path so PostgreSQL's initdb doesn't choke on
            # accented characters in the install path (e.g. "Área de Trabalho").
            cwd = _get_short_path_name(resource_path("api"))
            self.evolution_process = None

            spawned = False
            if _is_elevated():
                spawned = _spawn_delevated([node_exe, start_js], cwd, log_fh, self)

            if not spawned:
                self.evolution_process = subprocess.Popen(
                    [node_exe, start_js],
                    cwd=cwd,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=log_fh,
                    stderr=log_fh,
                )
            # Release Python's file handle now that node.exe has inherited it.
            # This avoids a double-lock on evolution.log so an update extraction
            # can overwrite the file once WinZapp exits (only node.exe holds a
            # lock while it is running — we don't need it on the Python side).
            log_fh.close()
            self._evolution_log_fh = None
            atexit.register(self._stop_evolution)
        except Exception:
            pass

    def _stop_evolution(self):
        """Terminate the Evolution API process."""
        if self.evolution_process and self.evolution_process.poll() is None:
            try:
                self.evolution_process.terminate()
            except Exception:
                pass

    def ensure_evolution_running(self):
        """
        Start the local Evolution API if it is not already listening.

        Normal mode   — shows a progress dialog while waiting (up to 3 min).
        Background mode — polls silently; exits with code 1 on timeout.

        Originally:
        wait up to 3 minutes for it to become ready via a progress dialog.
        On first launch the database initialisation and migrations can take
        60-90 s; subsequent starts are much faster.
        """
        if self._is_evolution_running():
            return  # Already up (e.g. left running from a previous session)

        node_exe  = resource_path("node", "node.exe")
        start_js  = resource_path("api",  "start.js")
        dist_main = resource_path("api",  "dist", "main.js")

        # All three files are required to start the bundled API.
        # If any is missing (setup incomplete or not yet run), skip silently —
        # ensure_api_modules_installed() already handled the missing node.exe
        # case; dist/main.js absence means setup was cancelled or not done yet.
        if not (os.path.isfile(node_exe)
                and os.path.isfile(start_js)
                and os.path.isfile(dist_main)):
            return

        self._evolution_log_path = None
        self._evolution_log_fh   = None
        self._start_evolution_background()

        if self.background_mode:
            # Silent wait — no dialog, no speech.  Timeout → exit code 1.
            deadline = time.time() + 120
            while time.time() < deadline:
                if self._is_evolution_running():
                    return
                time.sleep(2)
            sys.exit(1)

        from ui.dialogs.api_startup import ApiStartupDialog
        dlg    = ApiStartupDialog(self, self.evolution_port)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result != wx.ID_OK:
            # Collect the last 40 lines of the evolution log for diagnosis
            details = ""
            log_path = getattr(self, "_evolution_log_path", None)
            if log_path and os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    details = "".join(lines[-40:]).strip()
                except Exception:
                    pass
            msg = self.i18n.t("api_startup_warning")
            if details:
                msg = f"{msg}\n\n{details}"
            wx.MessageBox(msg, self.app_name, wx.OK | wx.ICON_ERROR)
            sys.exit(1)

    def create_accelerator_table(self):
        #Set IDs
        self.ID_ALT_1      = wx.NewIdRef()
        self.ID_ALT_4      = wx.NewIdRef()
        self.ID_ALT_5      = wx.NewIdRef()
        self.ID_CTRL_COMMA = wx.NewIdRef()
        self.ID_F1         = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT,    ord('1'),    self.ID_ALT_1),
            (wx.ACCEL_ALT,    ord('4'),    self.ID_ALT_4),
            (wx.ACCEL_ALT,    ord('5'),    self.ID_ALT_5),
            (wx.ACCEL_CTRL,   ord(','),    self.ID_CTRL_COMMA),
            (wx.ACCEL_NORMAL, wx.WXK_F1,  self.ID_F1),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_alt_1,       id=self.ID_ALT_1)
        self.Bind(wx.EVT_MENU, self.on_alt_4,       id=self.ID_ALT_4)
        self.Bind(wx.EVT_MENU, self.on_alt_5,       id=self.ID_ALT_5)
        self.Bind(wx.EVT_MENU, self.on_ctrl_comma,  id=self.ID_CTRL_COMMA)
        self.Bind(wx.EVT_MENU, self.on_f1,          id=self.ID_F1)

    def on_f1(self, event):
        from ui.dialogs.shortcuts_dialog import ShortcutsDialog
        dlg = ShortcutsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def on_ctrl_comma(self, event):
        self.open_settings()

    def open_settings(self):
        from ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def apply_language_changes(self):
        """Refresh all visible translatable text after a language change."""
        self.navigation_panel.refresh_labels()
        self.conversations_panel.refresh_labels()
        if hasattr(self, "archived_conversations_panel"):
            self.archived_conversations_panel.refresh_labels()
        if hasattr(self, "status_panel"):
            self.status_panel.refresh_labels()
        # Update frame title (unread indicator + any status suffix)
        self._update_title()
        self.main_panel.Layout()
        # Refresh tray icon tooltip with new language
        if self.tray_icon is not None:
            self.tray_icon.refresh_labels()
        # Refresh menu bar labels
        self._refresh_menubar()

    def on_alt_1(self, event):
        if hasattr(self, "archived_conversations_panel"):
            self.archived_conversations_panel.Hide()
        if hasattr(self, "status_panel"):
            self.status_panel.Hide()
        self.conversations_panel.Show()
        self.content_panel.Layout()
        self.conversations_panel.conversations_list.SetFocus()

    def on_alt_4(self, event):
        self.conversations_panel.Hide()
        if hasattr(self, "status_panel"):
            self.status_panel.Hide()
        if hasattr(self, "archived_conversations_panel"):
            self.archived_conversations_panel.Show()
            self.content_panel.Layout()
            self.archived_conversations_panel.conversations_list.SetFocus()

    def on_alt_5(self, event):
        self.conversations_panel.Hide()
        if hasattr(self, "archived_conversations_panel"):
            self.archived_conversations_panel.Hide()
        if hasattr(self, "status_panel"):
            self.status_panel.Show()
            self.content_panel.Layout()
            self.status_panel._add_status_btn.SetFocus()
            self.status_panel.on_show()

    def output(self, text, interrupt=False):
        self.speak_output.output(text, interrupt=interrupt)

    # ── Language selection ────────────────────────────────────────────────────

    def _ensure_language_selected(self):
        """
        Show the language-selection dialog if no language has been stored yet
        in settings.  On Cancel the application exits immediately.
        """
        lang_already_set = bool(
            self.settings.get("general", {}).get("language")
        )
        if lang_already_set:
            return

        from ui.dialogs.language_dialog import LanguageSelectionDialog
        dlg    = LanguageSelectionDialog(parent=None)
        result = dlg.ShowModal()
        lang   = dlg.selected_language
        dlg.Destroy()

        if result != wx.ID_OK:
            sys.exit(0)

        self.settings.setdefault("general", {})["language"] = lang
        self.save_settings()

    # ── First-run / autostart ─────────────────────────────────────────────────

    def _check_first_run(self):
        """
        Show the autostart-offer dialog exactly once per installation.
        The ``first_run`` flag in settings is cleared immediately to prevent
        re-showing on a subsequent launch if the app crashes after this point.
        """
        if not self.settings.get("general", {}).get("first_run", True):
            return
        # Mark as done before showing the dialog
        self.settings.setdefault("general", {})["first_run"] = False
        self.save_settings()

        result = wx.MessageBox(
            self.i18n.t("autostart_ask_message"),
            self.i18n.t("autostart_ask_title"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if result == wx.YES:
            self._apply_autostart(enable=True)
        else:
            self.settings.setdefault("general", {})["autostart"] = False
            self.save_settings()

    def _check_hotkey_first_run(self):
        """
        Show a one-time dialog offering the user a global hotkey to open WinZapp
        from any application.  Guards on ``hotkey_first_run_asked`` so it only
        shows once per installation, right after the autostart prompt.

        The chosen (vk, mod) pair is written to settings immediately; the
        _HotkeyManager is created later in init_UI via _apply_global_hotkey().
        """
        gen = self.settings.get("general", {})
        if gen.get("hotkey_first_run_asked", False):
            return
        # Already has a hotkey configured — mark done without asking again.
        if gen.get("global_hotkey"):
            self.settings.setdefault("general", {})["hotkey_first_run_asked"] = True
            self.save_settings()
            return

        self.settings.setdefault("general", {})["hotkey_first_run_asked"] = True
        self.save_settings()

        from ui.dialogs.settings_dialog import _HotkeyCapture

        dlg = wx.Dialog(
            None,
            title=self.i18n.t("hotkey_first_run_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        msg_ctrl = wx.StaticText(dlg, label=self.i18n.t("hotkey_first_run_message"))
        msg_ctrl.Wrap(480)
        sizer.Add(msg_ctrl, 0, wx.ALL, 15)

        capture = _HotkeyCapture(
            dlg,
            accessible_name=self.i18n.t("global_hotkey_label"),
        )
        capture.SetHint(self.i18n.t("global_hotkey_hint"))
        sizer.Add(capture, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn   = wx.Button(dlg, wx.ID_OK,     self.i18n.t("ok"))
        skip_btn = wx.Button(dlg, wx.ID_CANCEL, self.i18n.t("hotkey_first_run_skip"))
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(skip_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(sizer)
        sizer.Fit(dlg)
        dlg.CenterOnScreen()

        result = dlg.ShowModal()
        vk  = capture._vk
        mod = capture._mod
        dlg.Destroy()

        if result == wx.ID_OK and vk:
            self.settings.setdefault("general", {})["global_hotkey"] = {"vk": vk, "mod": mod}
            self.save_settings()
            wx.MessageBox(
                self.i18n.t("hotkey_first_run_success").format(hotkey=_vk_mod_to_str(vk, mod)),
                self.i18n.t("autostart_success_title"),
                wx.OK | wx.ICON_INFORMATION,
            )

    def _apply_autostart(self, enable: bool):
        """
        Enable or disable the Windows Run registry entry for WinZapp.

        On success with ``enable=True``: shows a confirmation dialog.
        On failure: shows an error dialog and stores ``autostart=False``.
        Called from ``_check_first_run()`` and from the Settings dialog.
        """
        from autostart import enable_autostart, disable_autostart
        if enable:
            try:
                enable_autostart()
                self.settings.setdefault("general", {})["autostart"] = True
                self.save_settings()
                wx.MessageBox(
                    self.i18n.t("autostart_success_message"),
                    self.i18n.t("autostart_success_title"),
                    wx.OK | wx.ICON_INFORMATION,
                )
            except Exception as exc:
                self.settings.setdefault("general", {})["autostart"] = False
                self.save_settings()
                wx.MessageBox(
                    f"{self.i18n.t('autostart_error_message')}\n\n{exc}",
                    self.i18n.t("error").format(app_name=self.app_name),
                    wx.OK | wx.ICON_ERROR,
                )
        else:
            disable_autostart()
            self.settings.setdefault("general", {})["autostart"] = False
            self.save_settings()

    # ── Quick tip ─────────────────────────────────────────────────────────────

    def _check_quick_tip(self):
        """
        Show the "quick tip" (F1 shortcut hint) once after the user's first
        successful pairing.  Guarded by the ``quick_tip_shown`` setting so it
        never shows twice.
        """
        if self.settings.get("general", {}).get("quick_tip_shown", False):
            return
        self.settings.setdefault("general", {})["quick_tip_shown"] = True
        self.save_settings()
        wx.MessageBox(
            self.i18n.t("quick_tip_message"),
            self.i18n.t("quick_tip_title"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    # ── Terms of service ─────────────────────────────────────────────────────

    def _check_terms_acceptance(self):
        """
        Show the terms-of-service dialog exactly once.
        If the user declines, the application exits immediately.
        """
        if self.settings.get("general", {}).get("terms_alert_displayed", False):
            return

        dlg = wx.Dialog(
            None,
            title=self.i18n.t("terms_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        msg_ctrl = wx.StaticText(dlg, label=self.i18n.t("terms_message"))
        msg_ctrl.Wrap(480)
        sizer.Add(msg_ctrl, 0, wx.ALL, 15)

        btn_sizer = wx.StdDialogButtonSizer()
        accept_btn = wx.Button(dlg, wx.ID_OK,     self.i18n.t("terms_accept"))
        decline_btn = wx.Button(dlg, wx.ID_CANCEL, self.i18n.t("terms_decline"))
        btn_sizer.AddButton(accept_btn)
        btn_sizer.AddButton(decline_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(sizer)
        sizer.Fit(dlg)
        dlg.CenterOnScreen()

        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_OK:
            self.settings.setdefault("general", {})["terms_alert_displayed"] = True
            self.save_settings()
        else:
            sys.exit(0)

    def load_settings(self):
        settings_file = data_path("settings.json")
        # Bootstrap from default on first run
        if not os.path.isfile(settings_file):
            default_file = resource_path("data", "settings_default.json")
            if os.path.isfile(default_file):
                os.makedirs(os.path.dirname(settings_file), exist_ok=True)
                shutil.copy2(default_file, settings_file)
        try:
            with open(settings_file, "r") as f:
                self.settings = json.load(f)
        except Exception:
            if hasattr(self, 'i18n'):
                msg   = self.i18n.t('settings_load_failed')
                title = self.i18n.t("error").format(app_name=self.app_name)
            else:
                # i18n not yet initialised — load pt-BR directly as default
                from core.i18n import _load_translations
                _pt   = _load_translations("pt-BR")
                msg   = _pt.get("settings_load_failed",
                                "Erro ao carregar o arquivo de configuração:")
                title = _pt.get("error", "{app_name} Erro").format(
                    app_name=self.app_name)
            if hasattr(self, 'error_sound'):
                self.error_sound.play()
            wx.MessageBox(f"{msg}\n{format_exc()}", title, wx.OK | wx.ICON_ERROR)
            sys.exit()
        self._migrate_settings()

    def _migrate_settings(self):
        """Migrate settings from old section names to current ones."""
        changed = False
        # audio_default_speed: general → audio_playback
        if "audio_default_speed" in self.settings.get("general", {}):
            speed = self.settings["general"].pop("audio_default_speed")
            self.settings.setdefault("audio_playback", {})["audio_default_speed"] = speed
            changed = True
        # ui → user_interface
        if "ui" in self.settings and "user_interface" not in self.settings:
            self.settings["user_interface"] = self.settings.pop("ui")
            changed = True
        if changed:
            self.save_settings()

    def save_settings(self):
        try:
            with open(data_path("settings.json"), "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('settings_save_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)

    def _schedule_save_settings(self):
        """Debounce save_settings: coalesce rapid calls into one write after 2 s.

        Used when background events (e.g. presence.update bursts) update settings
        frequently — avoids hammering the disk on every event.
        """
        with self._save_timer_lock:
            existing = getattr(self, "_settings_save_timer", None)
            if existing is not None:
                existing.cancel()
            t = threading.Timer(2.0, self.save_settings)
            t.daemon = True
            self._settings_save_timer = t
            t.start()

    def load_sounds(self):
        self.startup_sound = Sound(self.sound_system, "startup.ogg")
        self.error_sound = Sound(self.sound_system, "error.ogg")
        self.qrcode_loaded_sound = Sound(self.sound_system, "qrcode_loaded.ogg")
        self.waiting_pairing_sound = Sound(self.sound_system, "waiting_pairing.ogg")
        self.pairing_code_updated_sound = Sound(self.sound_system, "pairing_code_updated.ogg")
        self.connected_sound = Sound(self.sound_system, "connected.ogg")
        self.synchronizing_sound = Sound(self.sound_system, "synchronizing.ogg")
        self.sync_complete_sound = Sound(self.sound_system, "sync_complete.ogg")
        self.offline_mode_sound = Sound(self.sound_system, "offline_mode.ogg")
        # Voice recording sounds
        self.voicemsg_startrecording_sound  = Sound(self.sound_system, "voicemsg_startrecording.ogg")
        self.voicemsg_pauserecording_sound  = Sound(self.sound_system, "voicemsg_pauserecording.ogg")
        self.voicemsg_discard_sound         = Sound(self.sound_system, "voicemsg_discard.ogg")
        self.voicemsg_send_sound            = Sound(self.sound_system, "voicemsg_send.ogg")
        # Background notification sound
        self.message_background_sound       = Sound(self.sound_system, "message_background.ogg")
        # Foreground notification sounds
        self.message_current_sound          = Sound(self.sound_system, "message_current.ogg")
        self.message_foreground_sound       = Sound(self.sound_system, "message_foreground.ogg")
        # Message sent confirmation sound
        self.message_sent_sound             = Sound(self.sound_system, "message_sent.ogg")

    def retrieve_token(self):
        token = self.settings.get("privateinfo", {}).get("WA_token", "").strip()
        if not token:
            # Migration: read from legacy token.tk if WA_token not yet present
            try:
                with open(data_path("token.tk"), "r") as f:
                    token = f.read().strip()
                if token:
                    if "privateinfo" not in self.settings:
                        self.settings["privateinfo"] = {}
                    self.settings["privateinfo"]["WA_token"] = token
                    self.save_settings()
            except Exception:
                pass
        if not token:
            if self.background_mode:
                # No token means WhatsApp has never been paired — exit silently.
                sys.exit(0)
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('token_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            sys.exit()
        self.token = token

    def prepare_sync(self):
        os.makedirs(data_path(), exist_ok=True)
        self._media_failed_lock = threading.Lock()
        self._media_failed_ids  = self._load_media_failed_ids()
        self.generate_secret_key()
        self.key = self.retrieve_secret_key()
        self.create_basic_files()

        #Get Local Chats
        self.chats = self.get_chats()
        # Build cache first so deduplicate_chats() can use it as a fallback
        # for @lid chats whose messages carry no remoteJidAlt bridge field.
        self._build_lid_to_phone_cache()
        self.chats = self.deduplicate_chats(self.chats)
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_contacts()
        self.connected_sound.play()
        # Reset per-session sync guard so on_messages_set() can start a fresh
        # sync.  Without this, _sync_completed stays True from the previous
        # session and messages.set never triggers start_sync() again.
        self._sync_completed = False
        # Reset so the 60-s fallback and on_messages_set() can fire.
        # The flag persisted as True across restarts, blocking re-sync on
        # reconnection when the Evolution API doesn't re-send messages.set.
        self.settings.setdefault("status", {})["messages_set_completed"] = False
        self.save_settings()
        self.wait_messages_set()

    def start_sync(self):
        # Block until init_UI() completes.  This prevents wx.CallAfter calls
        # below from referencing panels that don't exist yet (which happens when
        # the websocket failed and ShowModal() is still blocking init_UI()).
        if not self._ui_ready_event.wait(timeout=120):
            return  # UI never initialized; bail out silently

        # After first pairing the API may need a few seconds to populate chats.
        # Retry only when starting cold (no local cache); if we already have
        # local chats just refresh once and move on — the API is ready.
        _CHAT_RETRIES  = 6
        _CHAT_DELAY    = 5  # seconds between retries
        has_local_chats = len(self.chats) > 0
        for attempt in range(_CHAT_RETRIES):
            prev_len = len(self.chats)
            result   = self.get_remote_chats(dict(self.chats))
            if result is not None:
                self.chats = result
            # Exit the retry loop as soon as either:
            #  (a) we already had local chats (reconnection — no need to wait), or
            #  (b) the API returned at least one new chat (first pairing ready), or
            #  (c) we've exhausted retries.
            if has_local_chats or len(self.chats) > prev_len or attempt == _CHAT_RETRIES - 1:
                break
            if not self.background_mode:
                wx.CallAfter(self._set_status, self.i18n.t("preparing_to_sync"))
            time.sleep(_CHAT_DELAY)
        self.chats = self.normalize_chats(self.chats)

        # Quick initial contacts fetch — may be incomplete on first QR pairing
        # because WhatsApp delivers contacts to the Evolution API concurrently
        # with messages.  We'll do a second, definitive fetch after messages are
        # synced (by then the API has received all contacts from WhatsApp).
        _initial_contacts = self.get_remote_contacts()
        if _initial_contacts:
            self.contacts = _initial_contacts

        self.synchronizing_sound.play()
        if not self.background_mode:
            wx.CallAfter(self._set_status, self.i18n.t("synchronizing"))
            self.output(self.i18n.t("synchronization_started"), interrupt=True)

        # ── Phase 1: sync all messages ────────────────────────────────────
        self.sync_remote_chats()

        # After messages are loaded, remoteJidAlt bridge fields are available
        # so @lid ↔ @s.whatsapp.net duplicates (introduced because the API
        # returned both JID formats before messages were fetched) can now be
        # fully resolved and merged.
        self.chats = self.deduplicate_chats(self.chats)

        # Re-fetch contacts now that sync_remote_chats() has finished.  The
        # message sync takes long enough that by this point the Evolution API
        # has received all contacts from WhatsApp — solving the first-pairing
        # issue where names were missing because the initial fetch was too early.
        _fresh_contacts = self.get_remote_contacts()
        if _fresh_contacts:
            self.contacts = _fresh_contacts

        # Conversations are fully sorted as soon as messages are synced.
        # Sort, display, play sync-complete sound, and announce to the user
        # NOW — before the slower media-download phase begins.
        wx.CallAfter(self.set_chats)
        wx.CallAfter(self.preselect_conversations)
        self.sync_complete_sound.play()
        if not self.background_mode:
            wx.CallAfter(self._set_status, "")
            self.output(self.i18n.t("sync_complete"))

        # ── Phase 2: download media (silent) ──────────────────────────────
        if not self.background_mode:
            wx.CallAfter(self._set_status, self.i18n.t("downloading_media"))
        self.sync_media_for_all_chats()
        if not self.background_mode:
            wx.CallAfter(self._set_status, "")
        # Final refresh so any media-resolved previews appear in the list.
        wx.CallAfter(self.set_chats)

        # Mark sync as done for this session so late-arriving messages.set
        # events (Evolution API sends them in batches) don't restart the full
        # sync process after it already completed successfully.
        self._sync_completed = True

    def wait_messages_set(self):
        if not self.background_mode:
            self._set_status(self.i18n.t("preparing_to_sync"))
        # Fallback: if messages.set never arrives (the API was already fully synced
        # before our WebSocket connected so Baileys won't re-fire the event), poll
        # the API every 5 s for up to 60 s and start sync as soon as it responds.
        # This means a ready API triggers sync in ≤5 s instead of always waiting 60 s.
        def _fallback():
            for _ in range(12):   # 12 × 5 s = 60 s maximum
                time.sleep(5)
                # messages.set WebSocket event already triggered sync — nothing to do
                if self.settings.get("status", {}).get("messages_set_completed"):
                    return
                existing = getattr(self, "sync_thread", None)
                if existing and existing.is_alive():
                    return
                if getattr(self, "_sync_completed", False):
                    return
                # Probe the API: if it already has chats, start sync immediately
                try:
                    url = (
                        f"{self.evolution_server}:{self.evolution_port}"
                        f"/chat/findChats/{self.token}"
                    )
                    r = requests.post(
                        url,
                        headers={"apikey": self.token, "Content-Type": "application/json"},
                        timeout=5,
                    )
                    if r.ok and isinstance(r.json(), list) and r.json():
                        self.settings.setdefault("status", {})["messages_set_completed"] = True
                        self.save_settings()
                        self.sync_thread = threading.Thread(
                            target=self.start_sync, daemon=True
                        )
                        self.sync_thread.start()
                        return
                except Exception:
                    pass
        threading.Thread(target=_fallback, daemon=True).start()

    def create_basic_files(self):
        data_dir = data_path("")
        os.makedirs(data_dir, exist_ok=True)

        #Create empty messages.dat if not exists
        messages_file = data_path("messages.dat")
        if not os.path.isfile(messages_file):
            with open(messages_file, "wb") as f:
                f.write(encrypt_json({"chats": {}, "contacts": {}}, self.key))

        #Create media/voice message directories
        os.makedirs(data_path("media"), exist_ok=True)
        os.makedirs(data_path("voice_messages"), exist_ok=True)

        #Create stderr/stdout log files
        log_dir = data_path("log")
        os.makedirs(log_dir, exist_ok=True)
        stderr_log = os.path.join(log_dir, "stderr.log")
        stdout_log = os.path.join(log_dir, "stdout.log")
        if not os.path.isfile(stderr_log):
            open(stderr_log, "w").close()
        if not os.path.isfile(stdout_log):
            open(stdout_log, "w").close()
        #Set stderr and stdout
        sys.stderr = open(stderr_log, "a")
        sys.stdout = open(stdout_log, "a")

    def get_chats(self):
        messages_file = data_path("messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.key)
                    return decrypted_data.get("chats", {})
                else:
                    return []
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_load_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            return []

    def get_remote_chats(self, chats):
        url = f"{self.evolution_server}:{self.evolution_port}/chat/findChats/{self.token}"
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(url, headers=headers)
            response_data = response.json()
            if not isinstance(response_data, list):
                response_data = []
            for chat in response_data:
                if not isinstance(chat, dict):
                    continue
                jid = self._normalize_jid(chat.get("remoteJid", ""))
                # Skip status@broadcast — statuses are shown in the Status tab
                if not jid or jid.endswith("@broadcast"):
                    continue
                # If this is a @lid JID and we already have the canonical
                # @s.whatsapp.net entry (from the _lid_to_phone cache built at
                # startup), skip the @lid entirely — it's a duplicate.
                if jid.endswith("@lid"):
                    phone_jid = getattr(self, "_lid_to_phone", {}).get(jid)
                    if phone_jid and phone_jid in chats:
                        continue
                if jid not in chats:
                    if "messages" not in chat:
                        chat["messages"] = {"messages": {"records": []}}
                    chat["remoteJid"] = jid
                    chats[jid] = chat
                else:
                    # Chat already in local cache: refresh metadata from the
                    # server without overwriting local messages or the normalised
                    # remoteJid.
                    for k, v in chat.items():
                        if k in ("messages", "remoteJid"):
                            continue
                        # Don't let a stale server unreadCount re-mark a
                        # conversation the user already read locally.
                        # mark_conversation_as_read() sets it to 0 in-memory
                        # and notifies the server, but the server may not have
                        # propagated the change yet when this sync runs.
                        if k == "unreadCount" and int(chats[jid].get("unreadCount") or 0) == 0:
                            continue
                        chats[jid][k] = v
            self.save_data(chats, self.contacts)
            return chats
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR, self)

    def normalize_chats(self, chats):
        for key, chat in chats.items():
            if chat.get("unreadCount") is None:
                chat["unreadCount"] = 0
            chats[key] = chat
        return chats

    def deduplicate_chats(self, chats: dict) -> dict:
        """
        Merge duplicate chat entries that refer to the same contact but use
        different JID formats:

          1. @c.us (legacy) vs @s.whatsapp.net (modern) for the same phone number.
             Both formats identify the same conversation; we keep @s.whatsapp.net
             and merge any messages from the @c.us entry into it.

          2. @lid (Linked-Device ID) vs @s.whatsapp.net when the @lid chat's
             messages contain a key.remoteJidAlt bridge field that maps
             back to a phone-number JID already present in the chats dict.
             We merge the @lid messages into the @s.whatsapp.net entry and drop
             the @lid duplicate.

        New keys are normalised to @s.whatsapp.net during the merge so that
        subsequent lookups always hit the canonical entry.
        """
        def _merge_records(dst_records: list, src_records: list):
            """Append src messages that are not already in dst (dedup by msg ID)."""
            if not src_records:
                return
            dst_ids = {r.get("key", {}).get("id") for r in dst_records}
            for r in src_records:
                if r.get("key", {}).get("id") not in dst_ids:
                    dst_records.append(r)

        # ── Pass 1: normalise @c.us → @s.whatsapp.net ────────────────────────
        cus_jids = [j for j in list(chats.keys()) if j.endswith("@c.us")]
        for cus_jid in cus_jids:
            if cus_jid not in chats:
                continue
            normalized = self._normalize_jid(cus_jid)
            cus_chat   = chats.pop(cus_jid)
            cus_chat["remoteJid"] = normalized

            if normalized in chats:
                # Both exist — merge messages into the @s.whatsapp.net entry
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
                # Only the @c.us version existed — rename it
                chats[normalized] = cus_chat

        # ── Pass 2: merge or rename @lid to its @s.whatsapp.net equivalent ───
        lid_jids = [j for j in list(chats.keys()) if j.endswith("@lid")]
        for lid_jid in lid_jids:
            if lid_jid not in chats:
                continue
            lid_chat = chats[lid_jid]
            alt_jid  = self._find_alt_jid_from_messages(lid_chat)
            if not alt_jid:
                # Fallback: consult the pre-built _lid_to_phone cache
                alt_jid = getattr(self, "_lid_to_phone", {}).get(lid_jid, "")
            if not alt_jid:
                continue  # no phone-number JID found anywhere — keep @lid as-is

            src_records = (
                lid_chat.get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            if alt_jid in chats:
                # Both exist — merge @lid messages into the @s.whatsapp.net entry
                dst_records = (
                    chats[alt_jid]
                    .setdefault("messages", {})
                    .setdefault("messages", {})
                    .setdefault("records", [])
                )
                _merge_records(dst_records, src_records)
            else:
                # Only the @lid version exists — rename it to @s.whatsapp.net
                lid_chat["remoteJid"] = alt_jid
                chats[alt_jid] = lid_chat
            del chats[lid_jid]

        return chats

    def save_data(self, chats, contacts):
        """Write encrypted chat+contact data to disk.

        Protected by _save_lock so concurrent callers (background threads)
        never write the same file at the same time, which would corrupt it.
        """
        with self._save_lock:
            messages_file = data_path("messages.dat")
            try:
                encrypted_data = encrypt_json({"chats": chats, "contacts": contacts}, self.key)
                with open(messages_file, "wb") as f:
                    f.write(encrypted_data)
            except Exception:
                self.error_sound.play()
                wx.CallAfter(
                    wx.MessageBox,
                    f"{self.i18n.t('data_save_failed')} {format_exc()}",
                    self.i18n.t("error").format(app_name=self.app_name),
                    wx.OK | wx.ICON_ERROR,
                )

    def _do_save(self):
        """Timer callback: persist current self.chats / self.contacts."""
        self.save_data(self.chats, self.contacts)

    def _schedule_save(self):
        """Debounce save_data: coalesce rapid calls into one write after 150 ms.

        Replaces bare ``threading.Thread(target=self.save_data, ...).start()``
        calls so that a burst of incoming messages (e.g. 50 messages arriving
        during a group sync) triggers exactly ONE disk write instead of 50
        concurrent threads all racing to overwrite messages.dat.
        """
        with self._save_timer_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            t = threading.Timer(0.15, self._do_save)
            t.daemon = True
            self._save_timer = t
            t.start()

    def get_contacts(self):
        messages_file = data_path("messages.dat")
        try:
            with open(messages_file, "rb") as f:
                encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = decrypt_json(encrypted_data, self.key)
                    return decrypted_data.get("contacts", {})
                else:
                    return {}
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_load_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            return {}

    def get_remote_contacts(self):
        url = f"{self.evolution_server}:{self.evolution_port}/chat/findContacts/{self.token}"
        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(url, headers=headers)
            response_data = response.json()
            if not isinstance(response_data, list):
                response_data = []
            contacts = {}
            for contact in response_data:
                if not isinstance(contact, dict):
                    continue
                if contact.get("type", "") == "contact":
                    # Normalise @c.us → @s.whatsapp.net so lookups are consistent
                    jid = self._normalize_jid(contact.get("remoteJid", ""))
                    if not jid:
                        continue
                    contact = dict(contact)
                    contact["remoteJid"] = jid
                    contacts[jid] = contact
            self.save_data(self.chats, contacts)
            return contacts
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR, self)

    def _is_self_jid(self, jid: str) -> bool:
        """Return True if jid refers to the user's own WhatsApp account.
        Bridges @lid JIDs via cache and strips Baileys device suffixes (':N')
        so self-chats stored under any JID variant are correctly detected.
        """
        if not jid or jid.endswith("@g.us"):
            return False
        my_jid = getattr(self, "my_jid", "")
        if not my_jid:
            return False
        compare = jid
        if jid.endswith("@lid"):
            compare = getattr(self, "_lid_to_phone", {}).get(jid, jid)
        def _phone_part(j: str) -> str:
            return j.rsplit("@", 1)[0].split(":")[0]
        return _phone_part(compare) == _phone_part(my_jid)

    def _compute_chat_lists(self):
        """Compute sorted/filtered chat lists. Safe to run on a background thread."""
        deleted  = set(self.settings.get("deleted_chats",  []))
        archived = set(self.settings.get("archived_chats", []))
        pinned   = set(self.settings.get("pinned_chats",   []))
        my_jid   = getattr(self, "my_jid", "")

        main_chats, main_names = [], []
        arch_chats, arch_names = [], []

        for jid, chat in list(self.chats.items()):
            if jid in deleted:
                continue
            # Priority: saved contact name → chat pushName (group/profile fallback)
            # → phone number. @lid JIDs must be converted via cache before format_number.
            name = self._resolve_contact_name(chat) or chat.get("pushName", "")
            if not name:
                if jid.endswith("@lid"):
                    phone = getattr(self, "_lid_to_phone", {}).get(jid, "")
                    name = format_number(phone) if phone else ""
                else:
                    name = format_number(jid)
            if my_jid and not jid.endswith("@g.us") and self._is_self_jid(jid):
                name = self.i18n.t("self_chat_name")
            if jid in archived:
                arch_chats.append(chat)
                arch_names.append(name)
            else:
                main_chats.append(chat)
                main_names.append(name)

        # Pinned chats float to the top; within each group sort by most-recent
        # message timestamp descending (newest first), then alphabetically.
        def _chat_last_ts(c):
            ts = 0
            for m in c.get("messages", {}).get("messages", {}).get("records", []):
                t = int(m.get("messageTimestamp", 0) or 0)
                if t > ts:
                    ts = t
            return ts

        def _sort_key(pair):
            c, n = pair
            j   = c.get("remoteJid", "")
            pin = 0 if j in pinned else 1
            return (pin, -_chat_last_ts(c), n.lower())

        pairs = sorted(zip(main_chats, main_names), key=_sort_key)
        main_chats = [c for c, _ in pairs]
        main_names = [n for _, n in pairs]
        return main_chats, main_names, arch_chats, arch_names

    def _apply_chat_lists(self, main_chats, main_names, arch_chats, arch_names):
        """Apply sorted chat lists to panels and refresh UI. Must run on main thread."""
        self.chat_names = main_names
        # _all_chats_list / _all_chat_names always hold the full sorted list.
        # add_chats_to_ui() reads these to apply search / filter, then writes
        # back to chats_list / chat_names so indices stay consistent.
        self.conversations_panel._all_chats_list = main_chats
        self.conversations_panel._all_chat_names = main_names
        self.conversations_panel.chats_list = main_chats
        self.conversations_panel.chat_names = main_names

        if hasattr(self, "archived_conversations_panel"):
            self.archived_conversations_panel._all_chats_list = arch_chats
            self.archived_conversations_panel._all_chat_names = arch_names
            self.archived_conversations_panel.chats_list = arch_chats
            self.archived_conversations_panel.chat_names = arch_names

        if self.IsShown():
            self.add_chats_to_ui()
        # Refresh title whenever chat list / unread counts change.
        # Tray tooltip is only refreshed while the window is hidden — when
        # visible the title already shows unread counts, and RemoveIcon/SetIcon
        # disrupts NVDA focus (see tray_manager.py update_tooltip docstring).
        self._update_title()
        if getattr(self, "tray_icon", None) is not None and self._window_hidden:
            self.tray_icon.update_tooltip()

    def set_chats(self):
        self._build_lid_to_phone_cache()
        self._apply_chat_lists(*self._compute_chat_lists())

    def _schedule_set_chats(self):
        """Debounce set_chats() so rapid message bursts trigger only one rebuild.
        Safe to call from any thread; scheduling happens on the wx main thread."""
        if getattr(self, "_set_chats_pending", False):
            return
        self._set_chats_pending = True
        wx.CallLater(300, self._do_scheduled_set_chats)

    def _do_scheduled_set_chats(self):
        """Run heavy computation in background; apply UI changes on main thread."""
        self._set_chats_pending = False
        def _bg():
            try:
                self._build_lid_to_phone_cache()
                result = self._compute_chat_lists()
                wx.CallAfter(self._apply_chat_lists, *result)
            except Exception as e:
                print(f"[_do_scheduled_set_chats] error: {e}")
        threading.Thread(target=_bg, daemon=True).start()

    def _build_lid_to_phone_cache(self):
        """
        Build self._lid_to_phone: a dict mapping @lid JIDs to @s.whatsapp.net
        JIDs by scanning remoteJidAlt fields across all loaded chat messages.

        Evolution API v2 normalises the key before emitting the WebSocket event:
          OLD format: remoteJid=@lid,          remoteJidAlt=@s.whatsapp.net
          NEW format: remoteJid=@s.whatsapp.net, remoteJidAlt=@lid  (after swap)
        Both formats are handled here so the cache is populated regardless of
        which version of the API produced the stored messages.
        """
        cache = {}
        for chat in self.chats.values():
            for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
                key    = msg.get("key", {})
                remote = key.get("remoteJid", "")
                alt    = key.get("remoteJidAlt", "")

                # Normalise @c.us → @s.whatsapp.net so the cache is always keyed
                # under the modern format regardless of which API version wrote
                # the message.
                if alt and alt.endswith("@c.us"):
                    alt = alt[:-5] + "@s.whatsapp.net"
                if remote and remote.endswith("@c.us"):
                    remote = remote[:-5] + "@s.whatsapp.net"

                if alt and alt.endswith("@s.whatsapp.net"):
                    # OLD format: remoteJid=@lid, remoteJidAlt=phone
                    if remote.endswith("@lid"):
                        cache[remote] = alt
                    participant = key.get("participant", "")
                    if participant.endswith("@lid"):
                        cache[participant] = alt

                elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                    # NEW format (post-swap): remoteJid=phone, remoteJidAlt=lid
                    cache[alt] = remote

        self._lid_to_phone  = cache
        self._phone_to_lid  = {v: k for k, v in cache.items()}
        # Presence cache: maps JID → {lastKnownPresence, lastSeen}
        # Populated by WebSocketClient.on_presence_update via wx.CallAfter.
        if not hasattr(self, "_presence_cache"):
            self._presence_cache = {}
        # Maps chat JID → {participant_jid: "composing"|"recording"}
        if not hasattr(self, "_composing_chats"):
            self._composing_chats = {}
        # Maps (chat_jid, participant_jid) → wx.CallLater for 10-second auto-clear
        if not hasattr(self, "_presence_timers"):
            self._presence_timers = {}
        # Persistent pushName map: phone@s.whatsapp.net → real pushName, learned from
        # presence.update events.  Keyed by phone JID so @lid chats can resolve via
        # _lid_to_phone lookup.  Loaded from settings and saved whenever updated.
        if not hasattr(self, "_presence_pushname_map"):
            self._presence_pushname_map = dict(
                self.settings.get("presence_pushname_map", {})
            )

    def _find_alt_jid_from_messages(self, chat):
        """
        Find the canonical @s.whatsapp.net phone JID for a chat by scanning its
        message keys.  Handles both Evolution API v2 key formats and normalises
        any @c.us JIDs encountered to @s.whatsapp.net on the fly:

          OLD: remoteJid=@lid,   remoteJidAlt=@s.whatsapp.net|@c.us → return alt (normalised)
          NEW: remoteJid=phone,  remoteJidAlt=@lid                  → return remoteJid
        Returns the phone JID (@s.whatsapp.net) string, or None if not found.
        """
        def _norm(j: str) -> str:
            return j[:-5] + "@s.whatsapp.net" if j.endswith("@c.us") else j

        for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
            key    = msg.get("key", {})
            remote = _norm(key.get("remoteJid", ""))
            alt    = _norm(key.get("remoteJidAlt", ""))
            # alt is the phone JID, remote is @lid (OLD format)
            if alt and alt.endswith("@s.whatsapp.net"):
                return alt
            # remote is the phone JID, alt is @lid (NEW post-swap format)
            if remote and remote.endswith("@s.whatsapp.net") and alt and alt.endswith("@lid"):
                return remote
        return None

    def _resolve_contact_name(self, chat):
        """
        Return the saved contact name (contact.pushName) for a private chat, or None.

        Tries all three JID formats (@s.whatsapp.net, @c.us, @lid) and returns
        the first valid pushName found.  Groups are skipped (always return None).
        Falls back to the presence-learned pushName map for @lid contacts.
        """
        remoteJid = chat.get("remoteJid", "")
        if not remoteJid or remoteJid.endswith("@g.us"):
            return None

        ppm = getattr(self, "_presence_pushname_map", {})

        def _name_from_contact(c) -> str:
            val = (c.get("pushName") or "").strip()
            return val if val and not val.isdigit() and not is_phone_like(val) else ""

        def _try(jid: str) -> str:
            if not jid:
                return ""
            c = self.contacts.get(jid)
            return _name_from_contact(c) if c else ""

        def _ppm(jid: str) -> str:
            val = (ppm.get(jid) or "").strip()
            return val if val and not val.isdigit() and not is_phone_like(val) else ""

        local = remoteJid.rsplit("@", 1)[0]
        if remoteJid.endswith("@s.whatsapp.net"):
            return (
                _try(remoteJid)
                or _try(local + "@c.us")
                or _try(getattr(self, "_phone_to_lid", {}).get(remoteJid, ""))
                or _ppm(remoteJid)
                or ""
            ) or None
        elif remoteJid.endswith("@c.us"):
            phone_net = local + "@s.whatsapp.net"
            return (
                _try(remoteJid)
                or _try(phone_net)
                or _try(getattr(self, "_phone_to_lid", {}).get(phone_net, ""))
                or _ppm(remoteJid)
                or _ppm(phone_net)
                or ""
            ) or None
        elif remoteJid.endswith("@lid"):
            phone = (
                getattr(self, "_lid_to_phone", {}).get(remoteJid, "")
                or self._find_alt_jid_from_messages(chat)
                or ""
            )
            return (
                _try(remoteJid)
                or (phone and (_try(phone) or _try(phone.rsplit("@", 1)[0] + "@c.us")))
                or _ppm(remoteJid)
                or (phone and _ppm(phone))
                or ""
            ) or None
        return _try(remoteJid) or None

    def find_name_through_messages(self, chat):
        if chat.get("remoteJid", "").endswith("@g.us"):
            return None
        for message in chat["messages"].get("messages", {}).get("records", []):
            if message.get("key", {}).get("fromMe"):
                continue
            push = message.get("pushName", "")
            if push and not is_phone_like(push):
                return push
        return None

    def find_jid_through_messages(self, chat):
        for message in chat["messages"].get("messages", {}).get("records", []):
            if not message.get("key", {}).get("fromMe"):
                key = message.get("key", {})
                alt = key.get("remoteJidAlt", "")
                if alt and alt.endswith("@s.whatsapp.net"):
                    return format_number(alt)
                jid = key.get("remoteJid", "")
                if jid and not jid.endswith("@lid"):
                    return format_number(jid)
        return None

    def preselect_conversations(self):
        #Checks if window is still open
        if self.IsShown():
            lst = self.conversations_panel.conversations_list
            if lst.GetItemCount() > 0:
                lst.Focus(0)
                lst.Select(0)
                lst.EnsureVisible(0)

    def sync_remote_chats(self):
        for chat in self.chats.values():
            try:
                self.sync_chat_messages(chat.copy())
            except Exception:
                # Log but continue — one failed chat must not abort the others
                jid = chat.get("remoteJid", "?")
                print(f"[sync_remote_chats] failed to sync {jid}, continuing")

    def sync_media_for_all_chats(self):
        _MEDIA_TYPES = {"audioMessage", "documentMessage", "imageMessage",
                        "stickerMessage", "videoMessage"}
        tasks = [
            msg
            for chat in self.chats.values()
            for msg in chat.get("messages", {}).get("messages", {}).get("records", [])
            if msg.get("messageType") in _MEDIA_TYPES
        ]
        if not tasks:
            return

        timeout = self._MEDIA_SYNC_TIMEOUT
        with ThreadPoolExecutor(max_workers=self._MEDIA_SYNC_WORKERS) as pool:
            futs = {pool.submit(self.sync_if_media, msg, timeout): msg for msg in tasks}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    pass

        # Persist the set of expired IDs accumulated during this sync run.
        self._save_media_failed_ids()

    def sync_chat_media(self, chat):
        records = chat.get("messages", {}).get("messages", {}).get("records", [])
        for message in records:
            try:
                self.sync_if_media(message)
            except Exception:
                pass

    def sync_chat_messages(self, chat):
        url = f"{self.evolution_server}:{self.evolution_port}/chat/findMessages/{self.token}"

        headers = {
            "apikey": self.token,
            "Content-Type": "application/json"
        }

        remote_jid = self._normalize_jid(chat.get("remoteJid", ""))
        chat["remoteJid"] = remote_jid

        all_messages = []
        current_page = 1
        total_pages = 1

        # Loop through all pages; a single failed page is skipped so the rest
        # of the pages (and the rest of the chats) are still processed.
        consecutive_failures = 0
        while current_page <= total_pages:
            payload = {
                "where": { "key": { "remoteJid": remote_jid} },
                "page": current_page
            }

            try:
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                response_data = response.json()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    break  # give up on this chat after 3 consecutive failures
                current_page += 1
                continue

            # Update total_pages based on response
            if response_data.get("messages", {}):
                total_pages = response_data.get("messages", {}).get("pages", 1)
                records = response_data.get("messages", {}).get("records", [])
                all_messages.extend(records)

            current_page += 1

        # After fetching all pages, update chat messages
        if all_messages:
            # Preserve any messages received via WebSocket during this sync that
            # the API hasn't indexed yet (they arrived after the API snapshot).
            local_chat    = self.chats.get(remote_jid, {})
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
                "pages": total_pages,
                "currentPage": total_pages,
                "records": all_messages
            }

        if chat.get("messages", {}) and chat["messages"] != self.chats.get(remote_jid, {}).get("messages", {}): #update only if necessary
            self.chats[remote_jid] = chat
            wx.CallAfter(self._schedule_set_chats)
            self.save_data(self.chats, self.contacts)

    # WhatsApp CDN URLs (mmg.whatsapp.net) expire after ~90 days.  Attempting
    # to download older media causes the Evolution API to enter a 5-second retry
    # loop for every expired URL, which starves the API thread pool and eventually
    # breaks sends.  Never request media older than this threshold.
    _MEDIA_MAX_AGE_SECONDS = 14 * 24 * 3600  # 14 days — WhatsApp CDN typical TTL
    _MEDIA_SYNC_WORKERS    = 6               # parallel workers during bulk sync
    _MEDIA_SYNC_TIMEOUT    = 20              # seconds per request during bulk sync

    def _load_media_failed_ids(self) -> set:
        """Load the set of message IDs whose media CDN URL has previously expired."""
        try:
            with open(data_path("media_failed.json"), "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

    def _save_media_failed_ids(self):
        """Persist the failed-media set so expired IDs are skipped on future launches."""
        with self._media_failed_lock:
            try:
                with open(data_path("media_failed.json"), "w", encoding="utf-8") as f:
                    json.dump(list(self._media_failed_ids), f)
            except Exception:
                pass

    def sync_if_media(self, msg, timeout=60):
        """Download media for a single message during the background sync phase."""
        message_type = msg.get("messageType", "")
        _MEDIA_TYPES = {"documentMessage", "imageMessage", "stickerMessage", "videoMessage"}
        if message_type not in _MEDIA_TYPES and message_type != "audioMessage":
            return

        # Skip messages older than the CDN TTL — URLs have certainly expired.
        ts = int(msg.get("messageTimestamp", 0) or 0)
        if ts and (time.time() - ts) > self._MEDIA_MAX_AGE_SECONDS:
            return

        msg_id = msg.get("key", {}).get("id", "")

        # Skip IDs that previously returned 403/410 (expired CDN URL).
        if msg_id and msg_id in self._media_failed_ids:
            return

        try:
            if message_type == "audioMessage":
                self.handle_audio_message(msg, timeout=timeout)
            else:
                conv = self.conversations_panel
                def _prog(p, mid=msg_id):
                    wx.CallAfter(conv.update_message_download_progress, mid, p)
                self.handle_media_message(msg, progress_callback=_prog, timeout=timeout)
                if msg_id:
                    wx.CallAfter(conv.update_message_download_progress, msg_id, 1.0)
        except MediaExpiredError:
            if msg_id:
                self._media_failed_ids.add(msg_id)
        except Exception:
            pass

    def handle_media_message(self, msg, progress_callback=None, timeout=60):
        """Download and encrypt a document/image/sticker/video to data/media/."""
        msg_id = msg.get("key", {}).get("id", "")
        if not msg_id:
            return
        media_path = data_path("media", f"{msg_id}.wzmedia")
        if os.path.isfile(media_path):
            return
        b64 = self.get_base64_from_media(msg, progress_callback=progress_callback,
                                         timeout=timeout)
        if not b64:
            return
        content = base64.b64decode(b64)
        encrypted = encrypt(content, self.key)
        with open(media_path, "wb") as f:
            f.write(encrypted)

    def _clean_quoted(self, quoted: dict) -> dict:
        """Return a minimal quoted dict the Evolution API DTO accepts.

        Only ``key`` is sent.  The Evolution API will fetch the full message
        content from its internal Baileys message store using
        ``getMessage(key, true)``.  This avoids serialising binary fields
        (``jpegThumbnail``, ``mediaKey``, ``fileEncSha256``, …) that arrive
        from Socket.IO as Python ``bytes`` objects and cannot be JSON-encoded.

        JIDs are normalised before sending:
          - @c.us  → @s.whatsapp.net  (legacy format)
          - @lid   → @s.whatsapp.net  when the reverse cache knows the mapping
        """
        if not quoted or not isinstance(quoted, dict):
            return None
        key_raw = quoted.get("key")
        if not key_raw or not isinstance(key_raw, dict):
            return None
        _ALLOWED = {"id", "remoteJid", "fromMe", "participant"}
        clean_key = {k: v for k, v in key_raw.items() if k in _ALLOWED}
        if not clean_key.get("id"):
            return None

        # Normalise JIDs so the API always receives @s.whatsapp.net format.
        lid_to_phone = getattr(self, "_lid_to_phone", {})
        for field in ("remoteJid", "participant"):
            jid = clean_key.get(field, "")
            if not jid:
                continue
            jid = self._normalize_jid(jid)          # @c.us → @s.whatsapp.net
            if jid.endswith("@lid"):
                phone = lid_to_phone.get(jid, "")
                if phone:
                    jid = phone
            clean_key[field] = jid

        return {"key": clean_key}

    def _check_wa_connection_closed(self, response):
        """If the Evolution API returned a 'Connection Closed' error, mark the
        WhatsApp connection as down so the MessageQueue pauses retrying until
        Baileys reconnects and fires connection.update with state='open'."""
        try:
            body = response.json()
            messages = body.get("response", {}).get("message", [])
            if any("Connection Closed" in str(m) for m in messages):
                print("[send] WhatsApp Connection Closed — pausing queue until reconnect")
                self._wa_connected = False
        except Exception:
            pass

    def _canonical_mention_jids(self, mentioned_jids):
        """Return mention JIDs in the phone-number format Baileys can tag."""
        out = []
        seen = set()
        lid_to_phone = getattr(self, "_lid_to_phone", {})
        for raw_jid in mentioned_jids or []:
            jid = self._normalize_jid(str(raw_jid or ""))
            if not jid:
                continue
            if jid.endswith("@lid"):
                jid = lid_to_phone.get(jid, jid)
            if jid not in seen:
                seen.add(jid)
                out.append(jid)
        return out

    def send_text_message(self, remote_jid, text, quoted=None, mentioned_jids=None):
        """Send a plain-text message via the Evolution API."""
        url = f"{self.evolution_server}:{self.evolution_port}/message/sendText/{self.token}"
        payload = {"number": remote_jid, "text": text}
        if quoted:
            _cq = self._clean_quoted(quoted)
            if _cq:
                payload["quoted"] = _cq
        if mentioned_jids:
            payload["mentioned"] = self._canonical_mention_jids(mentioned_jids)
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        if "quoted" in payload:
            print(f"[send_text_message] sending quoted reply to {remote_jid}, quoted key.id={payload['quoted'].get('key', {}).get('id')}")
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                print(f"[send_text_message] HTTP {response.status_code}: {response.text[:500]}")
                self._check_wa_connection_closed(response)
                return False
            self._wa_connected = True
            try:
                body = response.json()
                if isinstance(body, dict) and "key" not in body:
                    print(f"[send_text_message] no 'key' in response body: {body}")
                return body.get("key", {}).get("id") or True
            except Exception:
                return True
        except Exception as exc:
            print(f"[send_text_message] exception: {exc}")
            return None

    def send_audio_message(self, remote_jid: str, wav_path: str, quoted=None) -> bool:
        """
        Base64-encode a WAV/audio file and send it as a PTT voice message via the
        Evolution API.  Uses /message/sendWhatsAppAudio which handles OGG conversion
        server-side.  Returns True on HTTP 200/201, False on any failure.
        """
        try:
            with open(wav_path, "rb") as fh:
                audio_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception:
            return False
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendWhatsAppAudio/{self.token}"
        )
        payload = {
            "number":   remote_jid,
            "audio":    audio_b64,
            "encoding": True,
            "ptt":      True,
        }
        if quoted:
            _cq = self._clean_quoted(quoted)
            if _cq:
                payload["quoted"] = _cq
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code in (200, 201):
                self._wa_connected = True
                try:
                    return response.json().get("key", {}).get("id") or True
                except Exception:
                    return True
            self._check_wa_connection_closed(response)
            return None
        except Exception:
            return None

    def send_reaction(self, remote_jid: str, msg_key: dict, emoji: str) -> bool:
        """Send a reaction to a message via the Evolution API."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendReaction/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        # Send only the standard WhatsApp key fields so no extra fields from
        # prepareMessage (e.g. remoteJidAlt, addressingMode) confuse the API.
        clean_key: dict = {
            "id":        msg_key.get("id", ""),
            "remoteJid": msg_key.get("remoteJid", ""),
            "fromMe":    bool(msg_key.get("fromMe", False)),
        }
        participant = msg_key.get("participant")
        if participant:
            clean_key["participant"] = participant
        payload = {"key": clean_key, "reaction": emoji}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                print(f"[send_reaction] HTTP {response.status_code}: {response.text[:500]}")
                return False
            return True
        except Exception as exc:
            print(f"[send_reaction] exception: {exc}")
            return False

    def _on_message_sent(self, local_id: str, audio_path: str = None, real_id: str = None):
        """
        Called on the main thread after a queued message is successfully sent.
        Updates the UI status label and cleans up any temporary audio file.
        real_id is the WhatsApp message ID returned by the API; it replaces the
        local UUID in the virtual message so playback can find the message in the DB.
        """
        if hasattr(self, "conversations_panel"):
            self.conversations_panel._mark_message_sent(local_id, real_id=real_id)
        # Clean up temp WAV for voice messages (media attachments keep their file).
        if audio_path and os.path.isfile(audio_path):
            try:
                os.unlink(audio_path)
            except Exception:
                pass

    def _on_message_failed(self, local_id: str, error: str = "", show_dialog: bool = False):
        """
        Called on the main thread after a queued message exhausts all retries.
        Marks the virtual message as failed in the UI and, for media attachments,
        shows an error dialog so the user knows the file was not delivered.
        """
        if hasattr(self, "conversations_panel"):
            self.conversations_panel._mark_message_failed(local_id)
        if show_dialog:
            self.error_sound.play()
            detail = error[:300] if error else self.i18n.t("error").format(app_name=self.app_name)
            wx.MessageBox(
                self.i18n.t("media_send_failed").format(error=detail),
                self.i18n.t("error").format(app_name=self.app_name),
                wx.OK | wx.ICON_ERROR,
            )

    def on_message_status_update(self, update: dict):
        """
        Handle a messages.update WebSocket event on the main thread.
        Updates MessageUpdate list on the cached message record and refreshes
        the status icon shown in the active conversation.
        """
        key       = update.get("key", {})
        msg_id    = key.get("id", "")
        status    = update.get("status", "") or str(update.get("update", {}).get("status", ""))
        if not msg_id or not status:
            return
        remote_jid = self._normalize_jid(key.get("remoteJid", ""))
        if remote_jid not in self.chats:
            return
        records = (
            self.chats[remote_jid]
                .get("messages", {})
                .get("messages", {})
                .get("records", [])
        )
        for msg in records:
            if msg.get("key", {}).get("id") == msg_id:
                msg.setdefault("MessageUpdate", []).append({"status": status})
                break
        if hasattr(self, "conversations_panel"):
            self.conversations_panel.refresh_message_status(msg_id, status)

    def _resolve_jid_name(self, jid_norm: str) -> str:
        """Return the best display name for a participant JID (contact lookup + fallback)."""
        ppm = getattr(self, "_presence_pushname_map", {})

        # Build candidate list covering all three JID formats for the same person.
        candidates = [jid_norm]
        local = jid_norm.rsplit("@", 1)[0]
        if jid_norm.endswith("@s.whatsapp.net"):
            candidates.append(local + "@c.us")
            lid = getattr(self, "_phone_to_lid", {}).get(jid_norm, "")
            if lid:
                candidates.append(lid)
        elif jid_norm.endswith("@c.us"):
            candidates.append(local + "@s.whatsapp.net")
        elif jid_norm.endswith("@lid"):
            phone = getattr(self, "_lid_to_phone", {}).get(jid_norm, "")
            if phone:
                candidates.append(phone)
                candidates.append(phone.rsplit("@", 1)[0] + "@c.us")

        for cjid in candidates:
            contact = self.contacts.get(cjid)
            if contact:
                name = (contact.get("pushName") or "").strip()
                if name and not name.isdigit():
                    return name
            chat = self.chats.get(cjid)
            if chat:
                name = (chat.get("name") or chat.get("pushName") or "").strip()
                if name and not name.isdigit():
                    return name

        # Fallback: check the presence-learned pushName map
        for cjid in candidates:
            pname = (ppm.get(cjid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname

        if not jid_norm.endswith(("@g.us", "@lid")):
            return format_number(jid_norm)
        return local

    def _presence_label_for_chat(self, chat_jid_norm: str, is_group: bool) -> str:
        """Return the typing/recording label to append to a chat-list row, or ''."""
        active = getattr(self, "_composing_chats", {}).get(chat_jid_norm, {})
        if not active:
            return ""
        participant_jid, action = next(iter(active.items()))
        if action == "composing":
            action_label = self.i18n.t("typing_indicator")
        elif action == "recording":
            action_label = self.i18n.t("recording_indicator")
        else:
            return ""
        if is_group:
            name = self._resolve_jid_name(participant_jid)
            if name:
                return self.i18n.t("group_presence_indicator").format(
                    name=name, action=action_label
                )
        return action_label

    def _refresh_presence_label_in_list(self, chat_jid_norm: str):
        """Update only the chat-list row for chat_jid_norm via SetItem().

        Replaces the full _schedule_set_chats() rebuild for presence-only changes.
        Using SetItem() on a single row prevents NVDA from re-reading the entire
        list and stuttering in TTS echo while the user is typing a message.
        """
        panel = getattr(self, "conversations_panel", None)
        if panel is None:
            return
        lst       = getattr(panel, "conversations_list", None)
        displayed = getattr(panel, "chats_list", [])
        names     = getattr(panel, "chat_names", [])
        if lst is None:
            return
        for idx, chat in enumerate(displayed):
            if self._normalize_jid(chat.get("remoteJid", "")) != chat_jid_norm:
                continue
            name   = names[idx] if idx < len(names) else ""
            unread = int(chat.get("unreadCount") or 0)
            unread_str = (
                f" {unread} " + (
                    self.i18n.t("unread_messages") if unread > 1
                    else self.i18n.t("unread_message")
                )
                if unread > 0 else ""
            )
            preview   = self._last_msg_preview(chat)
            item_text = name + unread_str
            if preview:
                item_text += f" {preview}"
            is_group = chat_jid_norm.endswith("@g.us")
            label = self._presence_label_for_chat(chat_jid_norm, is_group)
            if label:
                item_text += f" {label}"
            lst.SetItem(idx, 0, item_text)
            break

    def on_presence_update(self, jid: str, presences: dict):
        """
        Handle a presence.update WebSocket event (main thread).

        Stores the latest presence data for the JID in _presence_cache, updates
        the composing-chats index for the typing indicator in the chat list, speaks
        via AO2 when the active conversation has a new composing event, and refreshes
        the data-button note for the open conversation.

        presences: {jid_str: {"lastKnownPresence": str, "lastSeen": int|None}, ...}
        """
        if not jid or not isinstance(presences, dict):
            return

        chat_jid_norm = self._normalize_jid(jid)

        composing_chats = getattr(self, "_composing_chats", None)
        if composing_chats is None:
            self._composing_chats = {}
            composing_chats = self._composing_chats

        # Determine the open conversation JID (may be None)
        panel     = getattr(self, "conversations_panel", None)
        conv      = getattr(panel, "conversation", None) if panel else None
        conv_jid  = ""
        if conv is not None:
            conv_jid = self._normalize_jid(conv.get("remoteJid", ""))
            if conv_jid.endswith("@lid"):
                conv_jid = self._lid_to_phone.get(conv_jid, conv_jid)

        presence_changed = False

        _ppm_updated = False
        for participant_jid, data in presences.items():
            if not isinstance(data, dict):
                continue
            canonical = self._normalize_jid(participant_jid)
            if canonical.endswith("@lid"):
                canonical = self._lid_to_phone.get(canonical, canonical)

            # ── Persist pushName learned from presence so @lid contacts show
            # the correct name even before they appear in _lid_to_phone. ──────
            if canonical.endswith("@s.whatsapp.net"):
                contact_entry = self.contacts.get(canonical)
                if contact_entry:
                    push = (contact_entry.get("pushName") or "").strip()
                    if push and not push.isdigit() and not is_phone_like(push):
                        if self._presence_pushname_map.get(canonical) != push:
                            self._presence_pushname_map[canonical] = push
                            _ppm_updated = True
                        # Also index the corresponding @lid if known, so callers
                        # can look up by lid_jid directly without bridging.
                        lid = getattr(self, "_phone_to_lid", {}).get(canonical, "")
                        if lid and self._presence_pushname_map.get(lid) != push:
                            self._presence_pushname_map[lid] = push
                            _ppm_updated = True

            old_lkp = self._presence_cache.get(canonical, {}).get("lastKnownPresence", "")
            new_lkp = data.get("lastKnownPresence", "unavailable")

            self._presence_cache[canonical] = {
                "lastKnownPresence": new_lkp,
                "lastSeen": data.get("lastSeen"),
            }

            if new_lkp != old_lkp:
                presence_changed = True

            # Update composing/recording index for this chat
            if chat_jid_norm not in composing_chats:
                composing_chats[chat_jid_norm] = {}
            timer_key = (chat_jid_norm, canonical)
            if new_lkp in ("composing", "recording"):
                composing_chats[chat_jid_norm][canonical] = new_lkp
                # Reset the 10-second auto-clear timer on every new event
                old_timer = self._presence_timers.pop(timer_key, None)
                if old_timer is not None:
                    try:
                        old_timer.Stop()
                    except Exception:
                        pass
                def _make_clear(cjid, part):
                    def _clear():
                        self._composing_chats.get(cjid, {}).pop(part, None)
                        self._presence_timers.pop((cjid, part), None)
                        self._refresh_presence_label_in_list(cjid)
                    return _clear
                self._presence_timers[timer_key] = wx.CallLater(
                    10_000, _make_clear(chat_jid_norm, canonical)
                )
            else:
                composing_chats[chat_jid_norm].pop(canonical, None)
                old_timer = self._presence_timers.pop(timer_key, None)
                if old_timer is not None:
                    try:
                        old_timer.Stop()
                    except Exception:
                        pass

            # Speak via AO2 when a new composing/recording event starts in the open conversation
            if chat_jid_norm == conv_jid and new_lkp != old_lkp:
                name = self._resolve_jid_name(canonical)
                if name:
                    try:
                        if new_lkp == "composing":
                            self.speak_output.output(
                                self.i18n.t("typing_text").format(name=name)
                            )
                        elif new_lkp == "recording":
                            self.speak_output.output(
                                self.i18n.t("recording_text").format(name=name)
                            )
                    except Exception:
                        pass

        # Persist the updated pushName map to settings (debounced via _schedule_save).
        if _ppm_updated:
            self.settings["presence_pushname_map"] = dict(self._presence_pushname_map)
            self._schedule_save_settings()

        # Update only the affected row — avoids DeleteAllItems()+Append() rebuild
        # that causes NVDA to re-read the full list and stutter during TTS echo.
        if presence_changed:
            self._refresh_presence_label_in_list(chat_jid_norm)

        # Refresh the data-button note for the open conversation
        if panel is None or conv is None:
            return
        if conv_jid in self._presence_cache:
            panel._refresh_presence_note(conv_jid)

    def on_chat_unread_update(self, jid: str, unread_count: int):
        """Handle unread-count change from chats.update (e.g. read on another device)."""
        normalized = self._normalize_jid(jid)
        chat = self.chats.get(normalized)
        if chat is None:
            return
        old_count = int(chat.get("unreadCount") or 0)
        if old_count == unread_count:
            return
        chat["unreadCount"] = unread_count
        # Persist — debounced so rapid chats.update bursts produce one write.
        self._schedule_save()
        self._schedule_set_chats()

    def handle_audio_message(self, msg, timeout=60):
        voice_messages_dir = data_path("voice_messages")
        audio_file_path = os.path.join(voice_messages_dir, f"{msg.get('key', {}).get('id', '')}.msv")
        if os.path.isfile(audio_file_path):
            return
        base64_audio = self.get_base64_from_media(msg, timeout=timeout)
        if not base64_audio:
            return
        audio_content = base64.b64decode(base64_audio)
        self.save_audio_locally(msg, audio_content)

    def get_base64_from_media(self, media, progress_callback=None, timeout=60):
        """
        Fetch encrypted media from Evolution API and return its base64 string.

        Raises MediaExpiredError when the WhatsApp CDN URL has expired (HTTP 403/410).
        When *progress_callback* is provided the request is streamed and the
        callback is called with a float in [0, 1] as each chunk arrives.
        """
        url = f"{self.evolution_server}:{self.evolution_port}/chat/getBase64FromMediaMessage/{self.token}"
        _key = media.get("key", {})
        payload = {
            "message": {
                "key": {
                    "id":        _key.get("id", ""),
                    "fromMe":    _key.get("fromMe", False),
                    "remoteJid": _key.get("remoteJid", ""),
                }
            },
            "convertToMp4": False,
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}

        if progress_callback is None:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if response.status_code in (403, 410):
                raise MediaExpiredError(response.status_code)
            if response.status_code in (200, 201):
                return response.json().get("base64", "")
            return ""

        # Streaming mode so we can report per-chunk progress
        try:
            response = requests.post(url, json=payload, headers=headers,
                                     stream=True, timeout=timeout)
            if response.status_code in (403, 410):
                raise MediaExpiredError(response.status_code)
            if response.status_code not in (200, 201):
                return ""
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunks: list = []
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress_callback(downloaded / total)
            body = b"".join(chunks).decode("utf-8", errors="replace")
            return json.loads(body).get("base64", "")
        except MediaExpiredError:
            raise
        except Exception:
            return ""

    def save_audio_locally(self, msg, audio_content):
        voice_messages_dir = data_path("voice_messages")
        audio_file_path = os.path.join(voice_messages_dir, f"{msg.get('key', {}).get('id', '')}.msv")
        try:
            with open(audio_file_path, "wb") as audio_file:
                encrypted_audio = encrypt(audio_content, self.key)
                audio_file.write(encrypted_audio)
        except Exception as e:
            #Ignore audios that couldn't be saved for now
            pass

    def mark_conversation_as_read(self, remote_jid: str):
        """Mark conversation as read locally and notify the API.

        Evolution API v2 expects POST /chat/markMessageAsRead with
        {"readMessages": [{"remoteJid", "fromMe", "id"}]} where "id" must be
        a real message ID; we send the key of the newest incoming message.
        The Evolution API then calls both Baileys readMessages (sends individual
        read receipts) and chatModify(markRead=true) for proper multi-device sync.
        """
        chat = self.chats.get(remote_jid)
        if chat is None:
            return

        unread = int(chat.get("unreadCount") or 0)
        chat["unreadCount"] = 0
        self._schedule_save()
        wx.CallAfter(self.set_chats)

        if unread == 0:
            return  # nothing to mark as read on the server

        records = chat.get("messages", {}).get("messages", {}).get("records", [])
        latest = max(
            (m for m in records
             if not m.get("key", {}).get("fromMe") and m.get("key", {}).get("id")),
            key=lambda m: int(m.get("messageTimestamp", 0) or 0),
            default=None,
        )
        if latest is None:
            # Fallback: use the chat-level lastMessage stored by findChats
            lm = chat.get("lastMessage", {})
            if (lm and isinstance(lm, dict)
                    and lm.get("key", {}).get("id")
                    and not lm.get("key", {}).get("fromMe")):
                latest = lm

        if latest is None:
            print(f"[mark_as_read] No incoming message found for {remote_jid}, skipping API call")
            return

        key = latest.get("key", {})
        msg_key = {
            "remoteJid": remote_jid,
            "fromMe":    False,
            "id":        key.get("id", ""),
        }
        # Include participant for group chats so Evolution API can forward it
        # to Baileys readMessages/chatModify with the correct sender context.
        if key.get("participant"):
            msg_key["participant"] = key["participant"]

        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/markMessageAsRead/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            resp = requests.post(
                url,
                json={"readMessages": [msg_key]},
                headers=headers,
                timeout=10,
            )
            if not resp.ok:
                print(f"[mark_as_read] API error {resp.status_code} for {remote_jid}: {resp.text[:200]}")
        except Exception as exc:
            print(f"[mark_as_read] Request failed for {remote_jid}: {exc}")

    def mark_conversation_as_unread(self, remote_jid: str):
        chat = self.chats.get(remote_jid)
        if chat is not None:
            chat["unreadCount"] = 1
            self._schedule_save()
            wx.CallAfter(self.set_chats)

    # ── Evolution API — profile / group info ─────────────────────────────────

    def get_contact_profile(self, jid: str) -> dict:
        """Fetch contact profile from Evolution API (runs on background thread)."""
        # The API only accepts phone-number JIDs; resolve @lid first.
        if jid.endswith("@lid"):
            resolved = getattr(self, "_lid_to_phone", {}).get(jid, "")
            if not resolved:
                return {}
            jid = resolved
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/fetchProfile/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json={"number": jid}, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                return r.json() or {}
        except Exception:
            pass
        return {}

    def get_group_info(self, jid: str) -> dict:
        """Fetch group metadata via GET /group/findGroupInfos?groupJid=...
        (runs on background thread)."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/group/findGroupInfos/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.get(url, params={"groupJid": jid}, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                return r.json() or {}
        except Exception:
            pass
        return {}

    # ── Block ─────────────────────────────────────────────────────────────────

    def block_contact(self, jid: str, action: str = "block"):
        """action: 'block' or 'unblock'"""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/updateBlockStatus/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.post(
                url, json={"number": jid, "status": action},
                headers=headers, timeout=10,
            )
        except Exception:
            pass

    # ── Mute ──────────────────────────────────────────────────────────────────

    def is_chat_muted(self, jid: str) -> bool:
        muted = self.settings.get("muted_chats", {})
        expiry = muted.get(jid)
        if expiry is None:
            return False
        if expiry == -1:
            return True  # permanent
        return time.time() < expiry

    def mute_chat(self, jid: str, duration_secs: int):
        """duration_secs=-1 means mute permanently."""
        self.settings.setdefault("muted_chats", {})
        if duration_secs == -1:
            self.settings["muted_chats"][jid] = -1
        else:
            self.settings["muted_chats"][jid] = int(time.time()) + duration_secs
        self.save_settings()

    def unmute_chat(self, jid: str):
        self.settings.setdefault("muted_chats", {})
        self.settings["muted_chats"].pop(jid, None)
        self.save_settings()

    # ── Archive ───────────────────────────────────────────────────────────────

    def is_chat_archived(self, jid: str) -> bool:
        return jid in self.settings.get("archived_chats", [])

    def archive_chat(self, jid: str):
        lst = self.settings.setdefault("archived_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.save_settings()
        wx.CallAfter(self.set_chats)
        self._api_archive_chat(jid, archive=True)

    def unarchive_chat(self, jid: str):
        lst = self.settings.setdefault("archived_chats", [])
        if jid in lst:
            lst.remove(jid)
        self.save_settings()
        wx.CallAfter(self.set_chats)
        self._api_archive_chat(jid, archive=False)

    def _api_archive_chat(self, jid: str, archive: bool):
        url = (f"{self.evolution_server}:{self.evolution_port}"
               f"/chat/archiveChat/{self.token}")
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            resp = requests.post(
                url,
                json={"chat": jid, "archive": archive},
                headers=headers,
                timeout=10,
            )
            if not resp.ok:
                print(f"[archive_chat] API error {resp.status_code} for {jid}: {resp.text[:200]}")
        except Exception as exc:
            print(f"[archive_chat] Request failed for {jid}: {exc}")

    # ── Delete / Clear ────────────────────────────────────────────────────────

    def is_chat_deleted(self, jid: str) -> bool:
        return jid in self.settings.get("deleted_chats", [])

    def delete_chat_local(self, jid: str):
        lst = self.settings.setdefault("deleted_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.save_settings()
        self.chats.pop(jid, None)
        self._schedule_save()
        wx.CallAfter(self.set_chats)

    def clear_chat_messages_local(self, jid: str):
        chat = self.chats.get(jid)
        if chat:
            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = []
            self.settings.setdefault("cleared_chats", {})[jid] = int(time.time())
            self._schedule_save()
            self.save_settings()

    # ── Pin ───────────────────────────────────────────────────────────────────

    def is_chat_pinned(self, jid: str) -> bool:
        return jid in self.settings.get("pinned_chats", [])

    def pin_chat(self, jid: str):
        lst = self.settings.setdefault("pinned_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.save_settings()
        wx.CallAfter(self.set_chats)

    def unpin_chat(self, jid: str):
        lst = self.settings.setdefault("pinned_chats", [])
        if jid in lst:
            lst.remove(jid)
        self.save_settings()
        wx.CallAfter(self.set_chats)

    # ── Group ─────────────────────────────────────────────────────────────────

    def leave_group(self, jid: str):
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/group/leaveGroup/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.delete(url, params={"groupJid": jid}, headers=headers, timeout=10)
        except Exception:
            pass
        # Archive instead of delete so the message history is preserved locally.
        self.archive_chat(jid)

    def create_group(self, name: str, participants: list) -> tuple:
        """
        Create a WhatsApp group with the given name and participant numbers.
        participants: list of phone number strings (e.g. ["5511999999999"])
        Returns (True, group_jid) on success, (False, error_message) on failure.
        """
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/group/create/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        payload = {
            "subject":      name,
            "participants": [{"number": p} for p in participants],
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code in (200, 201):
                # v2 returns the Baileys GroupMetadata object; the JID is "id"
                return True, r.json().get("id", "")
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)

    def add_group_members(self, group_jid: str, participant_jids: list) -> tuple:
        """
        Add one or more participants to a group.
        Returns (True, "") on success, (False, error_message) on failure.
        """
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/group/updateParticipant/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        # v2 expects numeric strings (phone numbers), not full JIDs
        payload = {
            "groupJid":    group_jid,
            "action":      "add",
            "participants": [j.split("@")[0] for j in participant_jids],
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)

    # ── Media / contact attachments ───────────────────────────────────────────

    def send_media_attachment(
        self, remote_jid: str, file_path: str,
        media_type: str, caption: str = "", quoted: dict = None
    ) -> bool:
        """
        Base64-encode a file and send it as a media message.
        media_type: 'image' | 'video' | 'audio' | 'document'
        """
        import mimetypes
        try:
            with open(file_path, "rb") as fh:
                media_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception:
            return False
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        filename = os.path.basename(file_path)
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendMedia/{self.token}"
        )
        payload = {
            "number":    remote_jid,
            "mediatype": media_type,
            "media":     media_b64,
            "mimetype":  mime,
            "fileName":  filename,
            "caption":   caption,
        }
        if quoted:
            _cq = self._clean_quoted(quoted)
            if _cq:
                payload["quoted"] = _cq
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            if r.status_code in (200, 201):
                try:
                    return r.json().get("key", {}).get("id") or True
                except Exception:
                    return True
            err = f"HTTP {r.status_code}"
            try:
                body = r.json()
                msg = (body.get("message") or body.get("error") or "")
                if msg:
                    err = f"{err}: {msg}"
            except Exception:
                if r.text:
                    err = f"{err}: {r.text[:200]}"
            return {"ok": False, "error": err, "retry": False}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200], "retry": False}

    def send_contact_attachment(self, remote_jid: str, contact_info: dict,
                                quoted: dict = None) -> bool:
        """Send a contact card as an attachment."""
        name = contact_info.get("pushName") or ""
        jid = contact_info.get("remoteJid", "")
        phone_raw = jid.split("@")[0] if "@" in jid else jid
        phone_fmt  = format_number(jid)
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendContact/{self.token}"
        )
        payload = {
            "number":  remote_jid,
            "contact": [{"fullName": name, "wuid": phone_raw, "phoneNumber": phone_fmt}],
        }
        if quoted:
            _cq = self._clean_quoted(quoted)
            if _cq:
                payload["quoted"] = _cq
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                try:
                    return r.json().get("key", {}).get("id") or True
                except Exception:
                    return True
            return None
        except Exception:
            return None

    # ── Message edit / delete-for-everyone ────────────────────────────────────

    def edit_message(self, remote_jid: str, message_id: str, new_text: str):
        """Send an edited message via POST /chat/updateMessage (Evolution API v2)."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/updateMessage/{self.token}"
        )
        payload = {
            "number": remote_jid,
            "key":    {"remoteJid": remote_jid, "fromMe": True, "id": message_id},
            "text":   new_text,
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.post(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass

    def delete_message_for_everyone(self, remote_jid: str, message_id: str, from_me: bool):
        """Delete a message for everyone via DELETE /chat/deleteMessageForEveryone.

        Evolution API v2 expects a flat body: {"id", "fromMe", "remoteJid"}.
        """
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/deleteMessageForEveryone/{self.token}"
        )
        payload = {
            "id":        message_id,
            "fromMe":    from_me,
            "remoteJid": remote_jid,
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.delete(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass

    def _preview_sender_from_jid(self, jid: str) -> str:
        """
        Resolve a participant JID to a display name for chat list previews.
        Tries contacts dict (with @lid bridging), then falls back to
        format_number on the phone-number JID. Never returns a bare @lid string.
        """
        if not jid:
            return ""
        ppm = getattr(self, "_presence_pushname_map", {})
        phone_jid = ""
        contact = self.contacts.get(jid)
        if not contact and jid.endswith("@lid"):
            phone_jid = getattr(self, "_lid_to_phone", {}).get(jid, "")
            if phone_jid:
                contact = self.contacts.get(phone_jid)
        if contact:
            name = (contact.get("name") or contact.get("pushName") or "").strip()
            if name and not is_phone_like(name):
                return name
        # Fallback: presence-learned pushName map
        for lookup_jid in ([jid, phone_jid] if phone_jid else [jid]):
            pname = (ppm.get(lookup_jid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname
        if jid.endswith("@lid"):
            if not phone_jid:
                phone_jid = getattr(self, "_lid_to_phone", {}).get(jid, "")
            return format_number(phone_jid) if phone_jid else ""
        return format_number(jid)

    def _last_msg_preview(self, chat: dict) -> str:
        """
        Build a compact last-message description for the conversations list.
        Returns "" if no messages are found.
        Format: "[você: ]{content} {timestamp}"
        """
        records = (
            chat.get("messages", {})
                .get("messages", {})
                .get("records", [])
        )
        if not records:
            return ""

        # Find the most recent message (max by timestamp)
        try:
            last = max(
                (m for m in records if isinstance(m, dict)),
                key=lambda m: int(m.get("messageTimestamp", 0) or 0),
                default=None,
            )
        except Exception:
            return ""
        if last is None:
            return ""

        from_me  = last.get("key", {}).get("fromMe", False)
        msg_type = last.get("messageType", "conversation")
        msg_obj  = last.get("message") or {}
        i18n     = self.i18n

        # If latest message is a reaction, show it inline instead of skipping
        if msg_type == "reactionMessage":
            reaction = msg_obj.get("reactionMessage") or {}
            emoji = reaction.get("text", "")
            orig_id = (reaction.get("key") or {}).get("id", "")
            orig_text = ""
            for m in records:
                if isinstance(m, dict) and m.get("key", {}).get("id") == orig_id:
                    orig_type = m.get("messageType", "")
                    orig_obj  = m.get("message") or {}
                    if orig_type == "conversation":
                        orig_text = (orig_obj.get("conversation") or "")
                    elif orig_type == "extendedTextMessage":
                        orig_text = ((orig_obj.get("extendedTextMessage") or {}).get("text") or "")
                    elif orig_type == "audioMessage":
                        orig_text = i18n.t("message_type_audio")
                    elif orig_type == "videoMessage":
                        orig_text = i18n.t("video")
                    elif orig_type == "imageMessage":
                        orig_text = i18n.t("photo")
                    elif orig_type == "documentMessage":
                        orig_text = i18n.t("document")
                    elif orig_type == "stickerMessage":
                        orig_text = i18n.t("sticker")
                    elif orig_type == "contactMessage":
                        orig_text = i18n.t("notif_contact")
                    elif orig_type == "locationMessage":
                        orig_text = i18n.t("notif_location")
                    else:
                        orig_text = i18n.t("notif_unsupported")
                    break
            ts = last.get("messageTimestamp")
            time_str = ""
            if ts:
                try:
                    from datetime import datetime as _dt
                    dt    = _dt.fromtimestamp(int(ts))
                    today = _dt.now().date()
                    if dt.date() == today:
                        time_str = dt.strftime("%H:%M")
                    else:
                        time_str = dt.strftime(i18n.t("datetime_fmt"))
                except Exception:
                    pass
            if from_me:
                label = i18n.t("reaction_preview_you").format(emoji=emoji)
            else:
                p_key      = last.get("key", {})
                sender_jid = p_key.get("participant", "") or p_key.get("remoteJid", "")
                push       = last.get("pushName", "")
                sender_name = (
                    self._resolve_contact_name({"remoteJid": sender_jid})
                    or (push if push and not is_phone_like(push) else "")
                    or self._preview_sender_from_jid(sender_jid)
                )
                label = i18n.t("reaction_preview_them").format(name=sender_name, emoji=emoji)
            parts = [label]
            if orig_text:
                parts.append(orig_text)
            if time_str:
                parts.append(time_str)
            return " ".join(parts)

        # Build compact content
        def _dur(secs):
            try:
                s = int(secs or 0)
            except Exception:
                return "0:00"
            h, m, sec = s // 3600, (s % 3600) // 60, s % 60
            return f"{h}:{m:02d}:{sec:02d}" if h > 0 else f"{m}:{sec:02d}"

        if msg_type == "conversation":
            content = msg_obj.get("conversation") or ""
        elif msg_type == "extendedTextMessage":
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        elif msg_type == "audioMessage":
            dur     = _dur((msg_obj.get("audioMessage") or {}).get("seconds"))
            content = f"{i18n.t('message_type_audio')} {dur}"
        elif msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            dur   = _dur(video.get("seconds"))
            content = f"{i18n.t('video')} {dur}"
        elif msg_type == "imageMessage":
            img     = msg_obj.get("imageMessage") or {}
            caption = (img.get("caption") or "").strip()
            content = i18n.t("photo") + (f" {caption}" if caption else "")
        elif msg_type == "documentMessage":
            content = i18n.t("document")
        elif msg_type == "stickerMessage":
            content = i18n.t("sticker")
        elif msg_type == "contactMessage":
            contact = msg_obj.get("contactMessage") or {}
            content = i18n.t("contact_message").format(
                name=contact.get("displayName") or ""
            )
        elif msg_type == "locationMessage":
            content = i18n.t("notif_location")
        else:
            content = i18n.t("notif_unsupported")

        # Build time string
        ts = last.get("messageTimestamp")
        time_str = ""
        if ts:
            try:
                from datetime import datetime as _dt
                dt    = _dt.fromtimestamp(int(ts))
                today = _dt.now().date()
                if dt.date() == today:
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = dt.strftime(i18n.t("datetime_fmt"))
            except Exception:
                pass

        # For group chats add sender name before content (e.g. "João: vídeo 0:30")
        jid      = chat.get("remoteJid", "")
        is_group = jid.endswith("@g.us")
        if from_me:
            sender_prefix = i18n.t("conv_preview_you") + " "
        elif is_group:
            p_key      = last.get("key", {})
            sender_jid = p_key.get("participant") or p_key.get("remoteJid", "")
            push       = last.get("pushName", "")
            sender_name = (
                self._resolve_contact_name({"remoteJid": sender_jid})
                or (push if push and not is_phone_like(push) else "")
                or self._preview_sender_from_jid(sender_jid)
            )
            sender_prefix = f"{sender_name}: " if sender_name else ""
        else:
            sender_prefix = ""
        parts = [f"{sender_prefix}{content}"]
        if time_str:
            parts.append(time_str)
        return " ".join(parts)

    def add_chats_to_ui(self):
        """Rebuild the conversations list from the current chats data.

        Applies active search and conversation filter to both the wx.ListCtrl
        and the backing chats_list/chat_names arrays so that list indices are
        always consistent.  Without this sync the user would open the wrong
        conversation when a search was active.
        """
        search       = self.conversations_panel.search_field.GetValue().strip().lower()
        conv_filter  = getattr(self.conversations_panel, '_conv_filter', 'all')

        # Always start from the full sorted lists saved by set_chats() so
        # that restoring the window or clearing a search shows all chats.
        full_chats = list(getattr(self.conversations_panel, '_all_chats_list',
                                  self.conversations_panel.chats_list))
        full_names = list(getattr(self.conversations_panel, '_all_chat_names',
                                  self.conversations_panel.chat_names))

        displayed_chats: list = []
        displayed_names: list = []

        lst = self.conversations_panel.conversations_list
        focus_allowed = self._allow_ui_focus_changes()
        _lst_had_focus = (wx.Window.FindFocus() is lst)
        lst.Freeze()
        try:
            lst.DeleteAllItems()
            for i, chat in enumerate(full_chats):
                name     = full_names[i]
                chat_jid = chat.get("remoteJid", "")
                # ── Conversation filter ───────────────────────────────────────
                if conv_filter == 'unread' and int(chat.get("unreadCount") or 0) == 0:
                    continue
                if conv_filter == 'groups' and not chat_jid.endswith("@g.us"):
                    continue
                if conv_filter == 'individual' and chat_jid.endswith("@g.us"):
                    continue
                # ── Search filter ─────────────────────────────────────────────
                if search and search not in name.lower():
                    continue
                unread = int(chat.get("unreadCount") or 0)
                if unread > 0:
                    unread_str = (
                        f" {unread} "
                        + (self.i18n.t("unread_messages") if unread > 1 else self.i18n.t("unread_message"))
                    )
                else:
                    unread_str = ""
                preview = self._last_msg_preview(chat)
                item_text = name + unread_str
                if preview:
                    item_text += f" {preview}"
                # Show typing/recording indicator when any participant is active
                chat_jid_norm = self._normalize_jid(chat_jid) if chat_jid else ""
                if chat_jid_norm:
                    presence_label = self._presence_label_for_chat(
                        chat_jid_norm, chat_jid_norm.endswith("@g.us")
                    )
                    if presence_label:
                        item_text += f" {presence_label}"
                lst.Append((item_text,))
                displayed_chats.append(chat)
                displayed_names.append(name)
        finally:
            lst.Thaw()

        # Keep backing lists in sync with exactly what is displayed so that
        # on_conversation_selected_by_index(idx) always maps correctly.
        self.conversations_panel.chats_list = displayed_chats
        self.conversations_panel.chat_names = displayed_names

        # Restore selection / focus after DeleteAllItems() clears everything.
        # When no conversation is open, prefer the last-opened JID; fall back
        # to item 0 so the list is never left with nothing focused.
        panel = self.conversations_panel
        if focus_allowed and panel.conversation is None and displayed_chats:
            last_jid    = getattr(panel, "_last_open_jid", "")
            target_idx  = 0
            if last_jid:
                for i, chat in enumerate(displayed_chats):
                    if chat.get("remoteJid") == last_jid:
                        target_idx = i
                        break
            lst.Focus(target_idx)
            lst.Select(target_idx)
            lst.EnsureVisible(target_idx)
            # Restore keyboard focus to the list when no conversation is open.
            # DeleteAllItems() can make the list lose focus; also restore if
            # nothing has focus (e.g. right after close_conversation()).
            # Skip if the user is actively typing in the search field.
            search = getattr(panel, "search_field", None)
            focused_now = wx.Window.FindFocus()
            if _lst_had_focus or focused_now is None or focused_now is lst:
                if focused_now is not search:
                    wx.CallAfter(lst.SetFocus)
        elif focus_allowed and panel.conversation is not None:
            # A conversation is already open.  Re-select the corresponding
            # item in the list so it stays visually highlighted after the
            # list is rebuilt.  Do NOT call lst.SetFocus() — keyboard focus
            # must stay on the conversation panel (message field / messages).
            open_jid = panel.conversation.get("remoteJid", "")
            if open_jid and displayed_chats:
                for i, chat in enumerate(displayed_chats):
                    if chat.get("remoteJid") == open_jid:
                        lst.Focus(i)
                        lst.Select(i)
                        lst.EnsureVisible(i)
                        break
            # Re-anchor keyboard focus to the message field only if the app
            # lost focus entirely (FindFocus() returns None) AND is the
            # foreground window.  Skipping IsActive() would steal focus from
            # other apps.
            focus_ctrl = getattr(panel, "message_field", None)
            if focus_ctrl and focus_ctrl.IsShownOnScreen():
                if wx.Window.FindFocus() is None and self.IsActive():
                    wx.CallAfter(focus_ctrl.SetFocus)

        # Also refresh the archived panel if present
        if hasattr(self, "archived_conversations_panel"):
            panel = self.archived_conversations_panel
            arch_full_chats = list(getattr(panel, '_all_chats_list', panel.chats_list))
            arch_full_names = list(getattr(panel, '_all_chat_names', panel.chat_names))
            arch_displayed_chats: list = []
            arch_displayed_names: list = []
            panel.conversations_list.DeleteAllItems()
            for i, chat in enumerate(arch_full_chats):
                name = arch_full_names[i]
                unread = int(chat.get("unreadCount") or 0)
                if unread > 0:
                    unread_str = (
                        f" {unread} "
                        + (self.i18n.t("unread_messages") if unread > 1 else self.i18n.t("unread_message"))
                    )
                else:
                    unread_str = ""
                preview = self._last_msg_preview(chat)
                item_text = name + unread_str
                if preview:
                    item_text += f" {preview}"
                panel.conversations_list.Append((item_text,))
                arch_displayed_chats.append(chat)
                arch_displayed_names.append(name)
            panel.chats_list = arch_displayed_chats
            panel.chat_names = arch_displayed_names
            # Keep focus on archived panel too
            # ArchivedConversationsPanel has no 'conversation' attribute — it never
            # keeps an "open" conversation, so we simply focus item 0 on first load.
            if focus_allowed and arch_displayed_chats:
                last_jid   = getattr(panel, "_last_open_jid", "")
                target_idx = 0
                if last_jid:
                    for i, chat in enumerate(arch_displayed_chats):
                        if chat.get("remoteJid") == last_jid:
                            target_idx = i
                            break
                panel.conversations_list.Focus(target_idx)
                panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)

    def generate_secret_key(self):
        key_file = data_path("secret.key")
        if not os.path.isfile(key_file):
            generate_and_save_key(key_file)

    def retrieve_secret_key(self):
        return retrieve_key(data_path("secret.key"))

    def exception_handler(self, exc_type, exc_value, exc_traceback):
        """Global exception handler for unexpected errors."""
        # Format the full traceback
        error_text = ''.join(format_exception(exc_type, exc_value, exc_traceback))

        #Play error sound
        self.error_sound.play()

        # Create error dialog
        dialog = wx.Dialog(None, title=self.i18n.t("error").format(app_name=self.app_name), size=(600, 400), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Error message
        message_text = wx.StaticText(panel, label=self.i18n.t("unexpected_error_message").format(app_name=self.app_name))
        sizer.Add(message_text, 0, wx.ALL, 10)

        #Error details label
        details_label = wx.StaticText(panel, label=self.i18n.t("error_details"))
        sizer.Add(details_label, 0, wx.LEFT | wx.TOP, 10)

        # Error details text control (read-only, multiline)
        error_ctrl = wx.TextCtrl(panel, value=error_text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        sizer.Add(error_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Copy button
        copy_btn = wx.Button(panel, label=self.i18n.t("copy_error_text"))
        copy_btn.Bind(wx.EVT_BUTTON, lambda evt: self.on_copy_error(error_text))
        button_sizer.Add(copy_btn, 0, wx.ALL, 5)

        # Close button
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=self.i18n.t("close"))
        button_sizer.Add(close_btn, 0, wx.ALL, 5)

        sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(sizer)

        # Show dialog
        dialog.ShowModal()
        dialog.Destroy()

    def on_copy_error(self, error_text):
        """Copy error text to clipboard."""
        try:
            pyperclip.copy(error_text)
            self.output(self.i18n.t("error_copied"), interrupt=True)
        except Exception:
            pass


def _write_crash_log(tb: str) -> str:
    """Write a traceback to crash.log next to the exe and return the path."""
    from app_paths import _outer_exe_dir
    crash_path = os.path.join(_outer_exe_dir(), "crash.log")
    try:
        with open(crash_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(tb)
    except Exception:
        pass
    return crash_path


if __name__ == "__main__":
    try:
        from autostart import acquire_single_instance_mutex, activate_existing_window

        background = "--background" in sys.argv
        first_instance = acquire_single_instance_mutex()

        if not first_instance:
            if not background:
                # A normal launch while WinZapp is already running in the background:
                # bring the existing window to the foreground and exit.
                activate_existing_window()
            # If --background and already running: nothing to do — exit silently.
            sys.exit(0)

        app = wx.App()
        frame = MainWindow()
    except Exception:
        tb = format_exc()
        crash_path = _write_crash_log(tb)
        # Try to show a native Windows error box (works even without wx).
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"O WinZapp encontrou um erro crítico ao iniciar e não pôde continuar.\n\n"
                f"Detalhes foram salvos em:\n{crash_path}\n\n{tb[:800]}",
                "WinZapp — Erro de inicialização",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        sys.exit(1)
