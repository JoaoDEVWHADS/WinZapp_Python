import os
import sys
import time
import shutil
import socket as _socket
import subprocess
import threading
import textwrap

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
from core.jid_mapping_service import JidMappingService
from core.contact_name_resolver import ContactNameResolver
from core.chat_list_builder import ChatListBuilder
from app_paths import resource_path, data_path
from core.message_queue import MessageQueue, PendingMessage
from core.message_send_service import MessageSendService
from core.connection_manager import ConnectionManager
from core.presence_manager import PresenceManager
from core.wpp_process_manager import WppProcessManager
from core.message_processor import MessageProcessor
from core.media_sync_service import MediaSyncService
from core.data_persistence import DataPersistence
from core.audio_service import AudioService
from core.chat_state_service import ChatStateService
from core.sync_service import SyncService
from core.chat_sync_service import ChatSyncService
from core.message_sync_service import MessageSyncService
from core.first_run_wizard import FirstRunWizard
from core.group_service import GroupService
from core.settings_service import SettingsService
from core.media_send_service import MediaSendService
from core.message_edit_service import MessageEditService
from core.update_manager import UpdateManager
from core.contact_service import ContactService
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
import logging

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



def _spawn_delevated(cmd: list, cwd: str, log_fh, main_window) -> bool:
    """
    Launch *cmd* as a restricted (non-admin) process using the Windows Safer API.

    SaferCreateLevel(SAFER_LEVELID_NORMALUSER) produces a token where the
    Administrators SID is marked DENY_ONLY, so PostgreSQL's pgwin32_is_admin()
    / CheckTokenMembership() returns FALSE even when the parent holds an
    elevated token, allowing initdb to proceed.

    Returns True and sets main_window.wpp_process on success (de-elevated launch).
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
        main_window.wpp_process = _Win32Proc(pi.hProcess, int(pi.dwProcessId))
        print("[_spawn_delevated] node.exe launched de-elevated via Safer API")
        return True

    except Exception as e:
        print(f"[_spawn_delevated] failed: {e}")
        return False


class MainWindow(wx.Frame):
    def __init__(self):
        import logging
        logging.info("MainWindow: Initializing MainWindow...")
        super().__init__(None)
        # Locks and saving state (initialized early to prevent AttributeErrors on early saves/migrations)
        self._save_lock = threading.Lock()
        self._save_timer = None
        self._save_timer_lock = threading.Lock()
        self._unresolvable_lids = set()
        self._unresolvable_names = set()
        self._resolving_lids = set()
        self._lid_resolution_lock = threading.Lock()
        self._media_sync_running = False

        self.data_persistence = DataPersistence(self)

        self.app_name = "WinZapp"
        self.SetTitle(self.app_name)

        # Detect no-UI background mode (started via --background flag by Windows
        # autostart).  When True: no dialogs, no sounds, no visible window.
        self.background_mode = "--background" in sys.argv
        logging.info("MainWindow: background_mode=%s", self.background_mode)

        #Initialize screen reader/sapi output
        logging.info("MainWindow: Initializing screen reader output...")
        self.speak_output = outputs.auto.Auto()

        #Initialize sound system
        logging.info("MainWindow: Initializing sound system...")
        self.sound_system = SoundSystem(self, sound_dir=resource_path("sounds"))
        self.sound_system.start()
        self.load_sounds()
        self.settings_service = SettingsService(self)
        self.settings = {}
        logging.info("MainWindow: Loading settings...")
        self.settings_service.load_settings()

        # Synchronize registry key with the autostart setting on Windows
        self.first_run = FirstRunWizard(self)

        self.first_run.sync_autostart_registry()


        # ── Auto-updater ──────────────────────────────────────────────────────
        # Schedule the update checker on the event loop early so it runs even
        # if language selection, terms acceptance, or pairing dialogs are shown (modal).
        if not self.background_mode:
            wx.CallLater(2000, self._start_update_checker)

        # ── Language selection on first launch ─────────────────────────────────
        # Show before everything else so the user can pick their language
        # before any module installation or connection dialogs appear.
        if not self.background_mode:
            logging.info("MainWindow: Ensuring language selected...")
            self.first_run.ensure_language_selected()

        #Initialize helper classes
        logging.info("MainWindow: Initializing Connect/I18n helpers...")
        self.connect = Connect(self)
        self.i18n = I18n(self)
        self.i18n.get_language()
        self.jid_mapping_service    = JidMappingService(self)
        self.contact_name_resolver = ContactNameResolver(self)
        self.media_sync            = MediaSyncService(self)
        self.chat_list_builder     = ChatListBuilder(self)

        # Terms of service – show once before anything else happens
        if not self.background_mode:
            logging.info("MainWindow: Checking terms acceptance...")
            self.first_run.check_terms_acceptance()

        #bind exception global handler for unexpected errors
        sys.excepthook = self.exception_handler

        self.ws = None

        conn = self.settings.get("connection", {})
        self.wpp_server    = conn.get("wpp_server",    "http://127.0.0.1")
        self.wpp_port      = conn.get("wpp_port",      6300)
        if self.wpp_port == 3417:
            self.wpp_port = 6300
        self.wpp_ws_server = conn.get("wpp_ws_server", "ws://127.0.0.1")
        self.wpp_api_key   = conn.get("wpp_api_key",   "wz-local-api-key")
        logging.info("MainWindow: WPPConnect config - server=%s, port=%s", self.wpp_server, self.wpp_port)

        # ── WPPConnect process manager (extracted responsibility) ────────────
        self.wpp_manager = WppProcessManager(self)

        #Set basic variables
        self.chats = {}
        self.chat_names = []
        self.contacts = {}
        # Set by init_UI() when all wx widgets are ready.  start_sync() waits
        # on this before making any wx.CallAfter calls so it never touches
        # widgets that don't exist yet (e.g. when ShowModal() is blocking init_UI).
        self._ui_ready_event = threading.Event()

        # Check and install API modules if needed (first run only)
        logging.info("MainWindow: Checking/installing API modules...")
        self.wpp_manager.ensure_api_modules_installed()

        # Check that the installed WPPConnect Server meets the minimum required version
        logging.info("MainWindow: Checking WPPConnect Server version...")
        self.wpp_manager.ensure_wpp_version()

        # Start local WPPConnect Server (if bundled)
        self.wpp_process = None
        logging.info("MainWindow: Ensuring WPPConnect Server process is running...")
        self.wpp_manager.ensure_wpp_running()

        # First-run dialogs: autostart and global hotkey (normal mode only, once ever)
        if not self.background_mode:
            self.first_run.check_first_run()
            self.first_run.check_hotkey_first_run()

        self.offline_mode = False
        # True while the Baileys/WhatsApp WebSocket is connected; False after a
        # "Connection Closed" error. The MessageQueue checks this before sending.
        self._wa_connected = False
        # IDs of messages sent by WinZapp itself (via MessageQueue).  Used by
        # WebSocketClient.on_messages_upsert to distinguish "echo of our own
        # send" (skip — already in UI) from "sent on another device" (show).
        # Populated from the MessageQueue worker thread immediately after the
        # API returns the real message ID, so it is always populated before the
        # corresponding WebSocket echo event can be processed.
        self._own_sent_ids: set = set()
        self._own_sent_ids_lock = threading.Lock()
        # (Locks initialized early at the top of __init__)
        # Status text shown in the title bar and tray tooltip (e.g. "sincronizando")
        self._tray_status = ""

        #Play startup sound (skipped in background mode)
        if not self.background_mode:
            self.startup_sound.play()

        # Track whether the user went through the pairing flow this session
        self._just_paired = False

        #Check for what window should be shown (skipped in background mode)
        if not self.background_mode:
            logging.info("MainWindow: Checking WhatsApp connection status...")
            if not self.connect.check_connection_status():
                logging.info("MainWindow: WhatsApp connection not paired. Showing connection dialog...")
                self.connect.show_connection_dial()
                if self.ws:
                    self.ws.sio.disconnect()
                self._just_paired = True
        
        logging.info("MainWindow: Retrieving token...")
        self.retrieve_token()
        #Initialize websocket
        logging.info("MainWindow: Initializing WebSocketClient...")
        self.ws = WebSocketClient(self, self.connect, self.token)

        logging.info("MainWindow: Preparing sync...")
        self.sync_service = SyncService(self)
        self.chat_sync = ChatSyncService(self)
        self.prepare_sync()
        # Initialise outgoing-message queue (must exist before init_UI so the
        # ConversationsPanel can call self.main_window.message_queue.enqueue).
        self.message_queue = MessageQueue(self)
        # Service that handles the actual sending of messages via the WPPConnect API.
        self.message_send_service = MessageSendService(self)
        self.connection_manager = ConnectionManager(self)
        self.audio_service = AudioService(self)
        self.message_processor = MessageProcessor(self)
        self.presence_manager = PresenceManager(self)
        self.chat_state = ChatStateService(self)
        self.message_sync = MessageSyncService(self)
        self.group_service = GroupService(self)
        self.media_send_service = MediaSendService(self)
        self.message_edit_service = MessageEditService(self)
        self.update_manager = UpdateManager(self)
        self.contact_service = ContactService(self)
        # Ensure session is active on WPPConnect Server before connecting WebSocket
        self.connection_manager.check_wa_connection_http()
        try:
            logging.info("MainWindow: Connecting WebSocket...")
            self.connection_manager.connect_websocket()
        except Exception as e:
            logging.exception("MainWindow: Exception during websocket connection")
            self.error_sound.play()
            error_str = str(e)
            # If the instance does not exist on the server (e.g. database recreated/wiped),
            # it returns "Invalid namespace". We should fallback to the connection dialog silently.
            if "Invalid namespace" in error_str or "namespaces failed to connect" in error_str:
                logging.info("WebSocket namespace is invalid (instance does not exist). Showing connection dialog silently.")
            else:
                wx.MessageBox(
                    self.i18n.t("websocket_failed_reconnect"),
                    self.i18n.t("connection_error"),
                    wx.OK | wx.ICON_WARNING,
                )
            self.connect.show_connection_dial()
            self._just_paired = True
        
        logging.info("MainWindow: Initializing User Interface...")
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
        self.Bind(wx.EVT_TIMER,    self.connection_manager._on_presence_timer,   self._presence_timer)
        self.Bind(wx.EVT_ACTIVATE, self.connection_manager._on_window_activate)

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
        self.chat_list_builder.set_chats()
        # All widgets exist and the initial chat list is painted — unblock any
        # sync thread that was waiting for the UI to be ready.
        self._ui_ready_event.set()

        # ── Quick tip after first pairing ─────────────────────────────────────
        if not self.background_mode and self._just_paired:
            wx.CallAfter(self.first_run.check_quick_tip)

        # Auto-updater already scheduled early in constructor

        app.MainLoop()

    # ── Menu bar ─────────────────────────────────────────────────────────────

    def _build_menubar(self):
        """Create the menu bar with Arquivo and Ajuda menus."""
        self._ID_MARK_ALL_READ = wx.NewIdRef()
        self._ID_SETTINGS      = wx.NewIdRef()
        self._ID_DISCONNECT    = wx.NewIdRef()
        self._ID_EXIT          = wx.NewIdRef()
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
        file_menu.AppendSeparator()
        file_menu.Append(
            self._ID_SETTINGS,
            f"{self.i18n.t('menu_settings')}\tCtrl+,",
        )
        file_menu.AppendSeparator()
        file_menu.Append(
            self._ID_DISCONNECT,
            f"{self.i18n.t('menu_disconnect')}\tCtrl+Alt+Shift+D",
        )
        file_menu.AppendSeparator()
        file_menu.Append(
            self._ID_EXIT,
            f"{self.i18n.t('menu_exit')}\tCtrl+Alt+Shift+Q",
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
        self.Bind(wx.EVT_MENU, self.on_ctrl_comma,     id=self._ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self.connection_manager._on_disconnect,    id=self._ID_DISCONNECT)
        self.Bind(wx.EVT_MENU, lambda e: self.real_exit(), id=self._ID_EXIT)
        self.Bind(wx.EVT_MENU, self.on_f1,             id=self._ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self._on_force_update,  id=self._ID_FORCE_UPDATE)
        self.Bind(wx.EVT_MENU, self._on_about,         id=self._ID_ABOUT)

    def _refresh_menubar(self):
        """Retranslate the menu bar labels after a language change."""
        mb = self.GetMenuBar()
        if mb is None:
            return
        file_menu = mb.GetMenu(0)
        mb.SetMenuLabel(0, self.i18n.t("menu_file"))
        file_menu.FindItemById(self._ID_MARK_ALL_READ).SetItemLabel(
            f"{self.i18n.t('menu_mark_all_read')}\tCtrl+Shift+Alt+M"
        )
        file_menu.FindItemById(self._ID_SETTINGS).SetItemLabel(
            f"{self.i18n.t('menu_settings')}\tCtrl+,"
        )
        file_menu.FindItemById(self._ID_DISCONNECT).SetItemLabel(
            f"{self.i18n.t('menu_disconnect')}\tCtrl+Alt+Shift+D"
        )
        file_menu.FindItemById(self._ID_EXIT).SetItemLabel(
            f"{self.i18n.t('menu_exit')}\tCtrl+Alt+Shift+Q"
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

    def _api_headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if extra:
            headers.update(extra)
        return {k: v for k, v in headers.items() if v is not None}

    def _on_mark_all_read(self, event=None):
        self.settings_service._on_mark_all_read(event)

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

    def _on_force_update(self, event):
        self.update_manager._on_force_update(event)

    # ── Auto-updater ──────────────────────────────────────────────────────────

    def _start_update_checker(self, force: bool = False):
        self.update_manager._start_update_checker(force)

    # ── Tray / window lifecycle ───────────────────────────────────────────────

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
        # When started via --background the window was never shown; clear the
        # flag so _allow_ui_focus_changes(), _on_window_activate() and the
        # notification window_active check all work correctly from now on.
        self.background_mode = False
        # ShowWindow via Win32 does NOT update wx's internal m_isShown flag, so
        # IsShown() returns False even though the window is physically visible.
        # Calling Show(True) syncs the flag without causing flicker (the window
        # is already visible to Win32 so SW_SHOW is a no-op at the OS level).
        if not self.IsShown():
            self.Show(True)
        if hasattr(self, "conversations_panel"):
            wx.CallAfter(self.chat_list_builder.add_chats_to_ui)

    def real_exit(self):
        """Completely close WinZapp, removing the tray icon and stopping all threads."""
        # Stop the presence keep-alive timer before tearing down
        if hasattr(self, "_presence_timer") and self._presence_timer.IsRunning():
            self._presence_timer.Stop()
        if getattr(self, "tray_icon", None) is not None:
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
        self.wpp_manager._stop_wpp_server()
        try:
            wx.GetApp().ExitMainLoop()
        except Exception:
            pass
        import os
        os._exit(0)

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
        self.jid_mapping_service._merge_lid_into_phone(lid_jid, phone_jid)

    def on_new_message(self, msg: dict):
        self.message_processor.on_new_message(msg)

    # ── WPPConnect lifecycle ─────────────────────────────────────────────────
    # (moved to WppProcessManager in core/wpp_process_manager.py)

    def create_accelerator_table(self):
        #Set IDs
        self.ID_ALT_1      = wx.NewIdRef()
        self.ID_ALT_2      = wx.NewIdRef()
        self.ID_ALT_3      = wx.NewIdRef()
        self.ID_ALT_4      = wx.NewIdRef()
        self.ID_ALT_5      = wx.NewIdRef()
        self.ID_CTRL_COMMA = wx.NewIdRef()
        self.ID_F1         = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT,    ord('1'),    self.ID_ALT_1),
            (wx.ACCEL_ALT,    ord('2'),    self.ID_ALT_2),
            (wx.ACCEL_ALT,    ord('3'),    self.ID_ALT_3),
            (wx.ACCEL_ALT,    ord('4'),    self.ID_ALT_4),
            (wx.ACCEL_ALT,    ord('5'),    self.ID_ALT_5),
            (wx.ACCEL_CTRL,   ord(','),    self.ID_CTRL_COMMA),
            (wx.ACCEL_NORMAL, wx.WXK_F1,  self.ID_F1),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_alt_1,       id=self.ID_ALT_1)
        self.Bind(wx.EVT_MENU, self._on_global_alt2, id=self.ID_ALT_2)
        self.Bind(wx.EVT_MENU, self._on_global_alt3, id=self.ID_ALT_3)
        self.Bind(wx.EVT_MENU, self.on_alt_4,       id=self.ID_ALT_4)
        self.Bind(wx.EVT_MENU, self.on_alt_5,       id=self.ID_ALT_5)
        self.Bind(wx.EVT_MENU, self.on_ctrl_comma,  id=self.ID_CTRL_COMMA)
        self.Bind(wx.EVT_MENU, self.on_f1,          id=self.ID_F1)

    def _on_global_alt2(self, event):
        """Alt+2: jump to last message regardless of which panel has focus."""
        cp = getattr(self, "conversations_panel", None)
        if cp is not None and cp.conversation is not None:
            cp._on_accel_jump_last(event)

    def _on_global_alt3(self, event):
        """Alt+3: jump to unread separator regardless of which panel has focus."""
        cp = getattr(self, "conversations_panel", None)
        if cp is not None and cp.conversation is not None:
            cp._on_accel_jump_unread(event)

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
        # Restore focus AND selection so the list never ends up empty-focused
        # when navigating back from a conversation or another panel.
        self.conversations_panel._restore_conversation_selection()

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
        self.first_run.ensure_language_selected()

    # ── First-run / autostart ─────────────────────────────────────────────────

    def _check_first_run(self):
        self.first_run.check_first_run()

    def _check_hotkey_first_run(self):
        self.first_run.check_hotkey_first_run()

    def _apply_autostart(self, enable: bool):
        self.first_run.apply_autostart(enable)

    def _sync_autostart_registry(self):
        self.first_run.sync_autostart_registry()

    # ── Quick tip ─────────────────────────────────────────────────────────────

    def _check_quick_tip(self):
        self.first_run.check_quick_tip()

    # ── Terms of service ─────────────────────────────────────────────────────

    def _check_terms_acceptance(self):
        self.first_run.check_terms_acceptance()

    def load_settings(self):
        self.settings_service.load_settings()

    def _migrate_settings(self):
        self.settings_service._migrate_settings()

    def save_settings(self):
        self.settings_service.save_settings()

    def _schedule_save_settings(self):
        self.settings_service._schedule_save_settings()

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
        if token and ":" not in token:
            try:
                url = f"{self.wpp_server}:{self.wpp_port}/api/{token}/{self.wpp_api_key}/generate-token"
                import requests
                response = requests.post(url, timeout=10)
                if response.status_code in (200, 201):
                    data = response.json()
                    hash_token = data.get("token")
                    if hash_token:
                        token = f"{token}:{hash_token}"
                        self.settings["privateinfo"]["WA_token"] = token
                        self.save_settings()
            except Exception as e:
                import logging
                logging.error("[retrieve_token] Failed to migrate WPPConnect token: %s", e)
        if not token:
            if self.background_mode:
                # No token means WhatsApp has never been paired — exit silently.
                sys.exit(0)
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('token_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            sys.exit()
        self.token = token

    def prepare_sync(self):
        self.sync_service.prepare_sync()

    def start_sync(self):
        self.sync_service.start_sync()

    def wait_messages_set(self):
        self.sync_service.wait_messages_set()

    def _store_status_update(self, msg: dict):
        self.message_processor._store_status_update(msg)

    def clear_local_data(self):
        self.data_persistence.clear_local_data()

    def create_basic_files(self):
        self.data_persistence.create_basic_files()

    def get_chats(self):
        return self.data_persistence.get_chats()

    def get_remote_chats(self, chats):
        return self.chat_sync.get_remote_chats(chats)

    def normalize_chats(self, chats):
        return self.chat_sync.normalize_chats(chats)

    def deduplicate_chats(self, chats: dict) -> dict:
        return self.chat_sync.deduplicate_chats(chats)

    def save_data(self, chats, contacts):
        self.data_persistence.save_data(chats, contacts)

    def _do_save(self):
        self.data_persistence._do_save()

    def _schedule_save(self):
        self.data_persistence._schedule_save()

    def _load_local_lid_cache(self):
        self.jid_mapping_service._load_local_lid_cache()

    def get_contacts(self):
        return self.data_persistence.get_contacts()

    def get_remote_contacts(self):
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/all-contacts"
        headers = self._api_headers()
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code not in (200, 201):
                logging.error(f"[get_remote_contacts] API error {response.status_code}: {response.text[:200]}")
                response_data = []
            else:
                try:
                    body = response.json()
                except Exception as json_err:
                    logging.error(f"[get_remote_contacts] Failed to parse JSON response: {json_err}. Response body: {response.text[:200]}")
                    body = {}
                response_data = body.get("response", []) if isinstance(body, dict) else []
            if not isinstance(response_data, list):
                response_data = []

            # Traduzir id._serialized para remoteJid e definir type = contact
            for contact in response_data:
                if not isinstance(contact, dict):
                    continue
                wpp_id = contact.get("id")
                jid_str = wpp_id.get("_serialized") if isinstance(wpp_id, dict) else wpp_id
                if jid_str:
                    contact["remoteJid"] = jid_str.replace("@c.us", "@s.whatsapp.net")
                contact["type"] = "contact"
            logging.info(f"[get_remote_contacts] Downloaded {len(response_data)} contacts from WPPConnect API.")
            filtered_contacts = [c for c in response_data if isinstance(c, dict) and c.get("type", "") == "contact"]
            names_with_values = [c.get("name") or c.get("pushName") for c in filtered_contacts if c.get("name") or c.get("pushName")]
            logging.info(f"[get_remote_contacts] Total filtered contacts (type='contact'): {len(filtered_contacts)} (with valid names: {len(names_with_values)})")
            if filtered_contacts:
                logging.info(f"[get_remote_contacts] First contact raw keys: {list(filtered_contacts[0].keys())}")
                logging.info(f"[get_remote_contacts] First contact raw data: {filtered_contacts[0]}")
            if names_with_values:
                logging.info(f"[get_remote_contacts] First 50 named contacts: {', '.join(names_with_values[:50])}")
            else:
                logging.info("[get_remote_contacts] No filtered contacts have a name or pushName field set in the API response.")
            
            contacts = {}
            for contact in filtered_contacts:
                jid = self._normalize_jid(contact.get("remoteJid") or contact.get("id", ""))
                if jid and not jid.endswith("@g.us") and not jid.endswith("@broadcast"):
                    name = contact.get("name") or contact.get("pushName") or "Contato sem nome"
                    contact = dict(contact)
                    contact["remoteJid"] = jid
                    
                    if jid not in self.contacts:
                        logging.info(f"[get_remote_contacts] Adding contact: {name} ({jid})")
                        self.contacts[jid] = contact
                    else:
                        updated_fields = []
                        for k, v in contact.items():
                            if v is not None and v != "":
                                if self.contacts[jid].get(k) != v:
                                    self.contacts[jid][k] = v
                                    updated_fields.append(k)
                        if updated_fields:
                            logging.info(f"[get_remote_contacts] Updated fields {updated_fields} for contact: {name} ({jid})")
                    contacts[jid] = self.contacts[jid]
            self.data_persistence.save_data(self.chats, self.contacts)
            return contacts
        except Exception as e:
            self.error_sound.play()
            logging.exception("Exception in get_remote_contacts")
            wx.MessageBox(f"{self.i18n.t('contact_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR, self)

    def start_periodic_contacts_sync(self):
        if hasattr(self, "_contacts_sync_thread_started") and self._contacts_sync_thread_started:
            return
        self._contacts_sync_thread_started = True

        def _loop():
            while True:
                time.sleep(300)
                try:
                    if getattr(self, "_wa_connected", False):
                        self.get_remote_contacts()
                        wx.CallAfter(self.chat_list_builder._schedule_set_chats)
                except Exception as e:
                    print(f"[periodic_contacts_sync] error: {e}")

        threading.Thread(target=_loop, daemon=True).start()

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
        if _phone_part(compare) == _phone_part(my_jid):
            return True
        my_lid = getattr(self, "my_lid", "")
        if my_lid and _phone_part(compare) == _phone_part(my_lid):
            return True
        return False

    def _build_lid_to_phone_cache(self):
        self.jid_mapping_service._build_lid_to_phone_cache()

    def _extract_lid_mapping(self, msg):
        self.jid_mapping_service._extract_lid_mapping(msg)

    def scan_all_cached_messages_for_mentions(self):
        self.jid_mapping_service.scan_all_cached_messages_for_mentions()

    def _find_alt_jid_from_messages(self, chat):
        return self.jid_mapping_service._find_alt_jid_from_messages(chat)

    def _resolve_contact_name(self, chat):
        return self.contact_name_resolver._resolve_contact_name(chat)

    def find_name_through_messages(self, chat):
        return self.contact_name_resolver.find_name_through_messages(chat)

    def find_jid_through_messages(self, chat):
        return self.contact_name_resolver.find_jid_through_messages(chat)

    def sync_remote_chats(self):
        self.message_sync.sync_remote_chats()

    def sync_chat_messages(self, chat):
        self.message_sync.sync_chat_messages(chat)

    @staticmethod
    def _find_api_ffmpeg() -> str:
        """Locate ffmpeg binary: bundled npm package first, then system PATH."""
        return AudioService.find_api_ffmpeg()

    def _convert_wav_to_ogg(self, wav_path: str) -> str | None:
        """Convert a WAV file to OGG/Opus using the bundled ffmpeg binary."""
        return self.audio_service.convert_wav_to_ogg(wav_path)

    def send_audio_message(self, remote_jid: str, wav_path: str, quoted=None) -> bool:
        """Base64-encode a WAV/audio file and send it as a PTT voice message."""
        return self.audio_service.send_audio_message(remote_jid, wav_path, quoted=quoted)

    def on_message_status_update(self, update: dict):
        self.message_processor.on_message_status_update(update)

    def _resolve_jid_name(self, jid_norm: str) -> str:
        return self.contact_name_resolver._resolve_jid_name(jid_norm)



    def on_chat_unread_update(self, jid: str, unread_count: int):
        self.chat_state.on_chat_unread_update(jid, unread_count)

    def on_chat_archive_update(self, jid: str, archived: bool):
        self.chat_state.on_chat_archive_update(jid, archived)

    def fetch_older_messages(self, remote_jid, oldest_msg):
        return self.message_sync.fetch_older_messages(remote_jid, oldest_msg)

    def save_audio_locally(self, msg, audio_content):
        """Save an incoming audio message to disk (encrypted)."""
        self.audio_service.save_audio_locally(msg, audio_content)

    def mark_conversation_as_read(self, remote_jid: str, force: bool = False):
        """Mark conversation as read locally and notify WPPConnect.

        WPPConnect's sendSeen only needs the chat JID — no message key required.
        The HTTP call runs in a background thread to avoid blocking the UI.
        """
        chat = self.chats.get(remote_jid)
        if chat is None:
            return

        unread = int(chat.get("unreadCount") or 0)
        chat["unreadCount"] = 0
        self.data_persistence._schedule_save()
        wx.CallAfter(self.chat_list_builder._schedule_set_chats)

        if unread == 0 and not force:
            return

        # Resolve LID if available, otherwise format to @c.us for WPPConnect
        target_phone = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
        if not target_phone:
            if remote_jid.endswith("@s.whatsapp.net"):
                target_phone = remote_jid.split("@")[0] + "@c.us"
            else:
                target_phone = remote_jid

        def _do_api():
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-seen"
            headers = self._api_headers()
            try:
                resp = requests.post(
                    url,
                    json={"phone": [target_phone]},
                    headers=headers,
                    timeout=10,
                )
                if not resp.ok:
                    logging.warning("[mark_as_read] API error %s for %s: %s",
                                    resp.status_code, target_phone, resp.text[:200])
            except Exception as exc:
                logging.warning("[mark_as_read] Request failed for %s: %s", target_phone, exc)

        threading.Thread(target=_do_api, daemon=True).start()

    def mark_conversation_as_unread(self, remote_jid: str):
        chat = self.chats.get(remote_jid)
        if chat is not None:
            chat["unreadCount"] = 1
            self.data_persistence._schedule_save()
            wx.CallAfter(self.chat_list_builder.set_chats)

    # ── WPPConnect — profile / group info ─────────────────────────────────
    
    def resolve_self_lid(self):
        self.jid_mapping_service.resolve_self_lid()

    def register_jid_mapping(self, lid_jid, phone_jid):
        self.jid_mapping_service.register_jid_mapping(lid_jid, phone_jid)

    def resolve_lid_jids_via_api(self, jids):
        self.jid_mapping_service.resolve_lid_jids_via_api(jids)

    def get_contact_profile(self, jid: str) -> dict:
        return self.contact_service.get_contact_profile(jid)

    def start_background_lid_resolution(self):
        self.jid_mapping_service.start_background_lid_resolution()

    def get_group_info(self, jid: str) -> dict:
        return self.group_service.get_group_info(jid)

    # ── Block ─────────────────────────────────────────────────────────────────

    def block_contact(self, jid: str, action: str = "block"):
        self.contact_service.block_contact(jid, action)

    # ── Mute ──────────────────────────────────────────────────────────────────

    # ── Chat state (delegated to ChatStateService) ──────────────────────────

    def is_chat_muted(self, jid: str) -> bool:
        return self.chat_state.is_chat_muted(jid)

    def mute_chat(self, jid: str, duration_secs: int):
        self.chat_state.mute_chat(jid, duration_secs)

    def unmute_chat(self, jid: str):
        self.chat_state.unmute_chat(jid)

    def is_chat_archived(self, jid: str) -> bool:
        return self.chat_state.is_chat_archived(jid)

    def archive_chat(self, jid: str):
        self.chat_state.archive_chat(jid)

    def unarchive_chat(self, jid: str):
        self.chat_state.unarchive_chat(jid)

    def is_chat_deleted(self, jid: str) -> bool:
        return self.chat_state.is_chat_deleted(jid)

    def delete_chat_local(self, jid: str):
        self.chat_state.delete_chat_local(jid)

    def clear_chat_messages_local(self, jid: str):
        self.chat_state.clear_chat_messages_local(jid)

    def is_chat_pinned(self, jid: str) -> bool:
        return self.chat_state.is_chat_pinned(jid)

    def pin_chat(self, jid: str):
        self.chat_state.pin_chat(jid)

    def unpin_chat(self, jid: str):
        self.chat_state.unpin_chat(jid)

    # ── Group ─────────────────────────────────────────────────────────────────

    def leave_group(self, jid: str):
        self.group_service.leave_group(jid)

    def create_group(self, name: str, participants: list) -> tuple:
        return self.group_service.create_group(name, participants)

    def add_group_members(self, group_jid: str, participant_jids: list) -> tuple:
        return self.group_service.add_group_members(group_jid, participant_jids)

    # ── Media / contact attachments ───────────────────────────────────────────

    def send_media_attachment(
        self, remote_jid: str, file_path: str,
        media_type: str, caption: str = "", quoted: dict = None
    ) -> bool:
        return self.media_send_service.send_media_attachment(
            remote_jid, file_path, media_type, caption, quoted)

    # ── Message edit / delete-for-everyone ────────────────────────────────────

    def edit_message(self, remote_jid: str, message_id: str, new_text: str):
        self.message_edit_service.edit_message(remote_jid, message_id, new_text)

    def delete_message_for_everyone(self, remote_jid: str, message_id: str, from_me: bool):
        self.message_edit_service.delete_message_for_everyone(remote_jid, message_id, from_me)

    def _preview_sender_from_jid(self, jid: str) -> str:
        return self.contact_name_resolver._preview_sender_from_jid(jid)



    def generate_secret_key(self):
        key_file = data_path("secret.key")
        if not os.path.isfile(key_file):
            generate_and_save_key(key_file)

    def retrieve_secret_key(self):
        self.generate_secret_key()
        return retrieve_key(data_path("secret.key"))

    def exception_handler(self, exc_type, exc_value, exc_traceback):
        """Global exception handler for unexpected errors."""
        # Format the full traceback
        error_text = ''.join(format_exception(exc_type, exc_value, exc_traceback))
        try:
            import logging
            logging.error("Unhandled global exception:\n%s", error_text)
        except Exception:
            pass

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


class LoggerWriter:
    def __init__(self, original_stream, level):
        self.original_stream = original_stream
        self.level = level

    def write(self, message):
        if self.original_stream:
            self.original_stream.write(message)
        msg = message.rstrip()
        if msg:
            import logging
            logging.log(self.level, msg)

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()


def setup_logging():
    import logging
    import logging.handlers
    from app_paths import log_path
    try:
        os.makedirs(log_path(), exist_ok=True)
        log_file = log_path("log.log")

        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] (%(filename)s:%(lineno)d) - %(message)s"
        ))

        root = logging.getLogger()
        # Remove any handler added by a prior basicConfig call
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        root.addHandler(handler)
        root.setLevel(logging.WARNING)

        # Silence very noisy third-party libraries
        for _lib in ("urllib3", "requests", "socketio", "engineio",
                     "charset_normalizer", "websocket", "PIL"):
            logging.getLogger(_lib).setLevel(logging.ERROR)

        logging.warning("WinZapp client starting up...")

        # Only redirect stderr (uncaught exceptions / tracebacks) to the log.
        # Redirecting stdout would write every print() call to the file.
        sys.stderr = LoggerWriter(sys.stderr, logging.ERROR)
    except Exception as e:
        sys.stderr.write(f"Failed to setup logging: {e}\n")


if __name__ == "__main__":
    setup_logging()
    try:
        import logging
        logging.info("Checking instance lock...")
        from autostart import acquire_single_instance_mutex, activate_existing_window

        background = "--background" in sys.argv
        first_instance = acquire_single_instance_mutex()

        if not first_instance:
            logging.info("Another instance is already running.")
            if not background:
                # A normal launch while WinZapp is already running in the background:
                # bring the existing window to the foreground and exit.
                activate_existing_window()
            # If --background and already running: nothing to do — exit silently.
            sys.exit(0)

        logging.info("Creating wx.App...")
        app = wx.App()
        frame = MainWindow()
    except Exception:
        tb = format_exc()
        try:
            import logging
            logging.error("Critical initialization error:\n%s", tb)
        except Exception:
            pass
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
