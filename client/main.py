import os
import sys
import time

# Add lib/ directory to Windows DLL search path so BASS plugins can find their dependencies (e.g. libopus-0.dll)
if sys.platform == 'win32':
    _lib_path = ""
    if getattr(sys, 'frozen', False):
        _lib_path = os.path.join(os.path.dirname(sys.executable), 'lib')
    else:
        _lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
    if os.path.isdir(_lib_path):
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(_lib_path)
            except Exception:
                pass
        # Fallback: add to PATH environment variable
        os.environ['PATH'] = _lib_path + os.pathsep + os.environ.get('PATH', '')

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
from core.sound_system import SoundSystem, Sound, load_sound
from core.i18n import I18n
from core.websocket_client import WebSocketClient
from core.utils import encrypt, decrypt, encrypt_json, decrypt_json, generate_and_save_key, retrieve_key, format_number, is_phone_like, looks_like_binary_blob, prune_message_record, prune_chats_messages, effective_unread_count
from core.database_bridge import DatabaseBridge
from app_paths import resource_path, data_path
from core.message_queue import MessageQueue, PendingMessage
import wx
import wx.adv
if sys.platform == "win32":
    from core.tray_manager import TrayIcon
from core.notification_manager import NotificationManager
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

        # MOD_NOREPEAT (0x4000) suppresses the flood of WM_HOTKEY messages that
        # holding the key down would otherwise generate.
        _MOD_NOREPEAT = 0x4000
        if not user32.RegisterHotKey(None, self._HOTKEY_ID, self._mod | _MOD_NOREPEAT, self._vk):
            # Some keyboard layouts / older Windows builds reject MOD_NOREPEAT;
            # fall back to a plain registration so the hotkey still works.
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


class MediaExpiredError(Exception):
    """CDN URL for this media has expired (HTTP 403 or 410 from WhatsApp)."""


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
        self.settings = {}
        logging.info("MainWindow: Loading settings...")
        self.load_settings()

        # Synchronize registry key with the autostart setting on Windows
        self._sync_autostart_registry()




        # ── Language selection on first launch ─────────────────────────────────
        # Show before everything else so the user can pick their language
        # before any module installation or connection dialogs appear.
        if not self.background_mode:
            logging.info("MainWindow: Ensuring language selected...")
            self._ensure_language_selected()

        #Initialize helper classes
        logging.info("MainWindow: Initializing Connect/I18n helpers...")
        self.token = ""
        self.connect = Connect(self)
        self.i18n = I18n(self)
        self.i18n.get_language()

        # ── Auto-updater ──────────────────────────────────────────────────────
        # Schedule the update checker on the event loop early (but after i18n
        # is initialized) so it can run even if modal dialogs block __init__.
        if not self.background_mode:
            wx.CallLater(2000, self._start_update_checker)

        # Terms of service – show once before anything else happens
        if not self.background_mode:
            logging.info("MainWindow: Checking terms acceptance...")
            self._check_terms_acceptance()

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
        self.wpp_custom_api = conn.get("wpp_custom_api", False)
        logging.info("MainWindow: WPPConnect config - server=%s, port=%s, custom_api=%s", self.wpp_server, self.wpp_port, self.wpp_custom_api)

        #Set basic variables
        self.chats = {}
        self.chat_names = []
        self.contacts = {}
        # Presence cache: maps JID → {lastKnownPresence, lastSeen}. Must be
        # initialized here (not lazily in _build_lid_to_phone_cache, which only
        # runs after the initial chat sync) because a presence.update WebSocket
        # event can arrive and call on_presence_update() before that sync
        # completes, depending on how fast WPPConnect emits it.
        self._presence_cache = {}
        # Maps chat JID → {participant_jid: "composing"|"recording"}
        self._composing_chats = {}
        # Maps (chat_jid, participant_jid) → wx.CallLater for 10-second auto-clear
        self._presence_timers = {}
        # Persistent pushName map: phone@s.whatsapp.net → real pushName, learned
        # from presence.update events. Loaded from DB on prepare_sync() and saved whenever updated.
        self._presence_pushname_map = {}
        # List of deleted, archived, pinned, and muted chats, loaded from DB on prepare_sync()
        self._deleted_chats = set()
        self._archived_chats = set()
        self._pinned_chats = set()
        self._muted_chats = {}
        # Set by init_UI() when all wx widgets are ready.  start_sync() waits
        # on this before making any wx.CallAfter calls so it never touches
        # widgets that don't exist yet (e.g. when ShowModal() is blocking init_UI).
        self._ui_ready_event = threading.Event()

        # Check if we should ask the user to choose between local and custom/remote API (first run)
        self._check_api_type_first_run()

        # First-run dialogs: autostart and global hotkey (normal mode only, once ever).
        # These must run BEFORE the WPPConnect API is started so the user never
        # sees a "starting WPPConnect" dialog stacked on top of setup prompts —
        # the API only starts once all setup steps are confirmed.
        self.wpp_process = None
        if not self.background_mode:
            self._check_first_run()
            self._check_hotkey_first_run()

        # Handle API execution configuration
        if self.wpp_custom_api:
            # Delete local node_modules and Puppeteer cache (Chrome) to free space
            node_modules_path = resource_path("api", "node_modules")
            if os.path.isdir(node_modules_path):
                logging.info("MainWindow: Custom API enabled. Cleaning local node_modules...")
                try:
                    import shutil
                    shutil.rmtree(node_modules_path, ignore_errors=True)
                except Exception as e:
                    logging.error("MainWindow: Failed to clean local node_modules: %s", e)

            puppeteer_cache_path = resource_path("api", ".cache")
            if os.path.isdir(puppeteer_cache_path):
                logging.info("MainWindow: Custom API enabled. Cleaning local Puppeteer cache...")
                try:
                    import shutil
                    shutil.rmtree(puppeteer_cache_path, ignore_errors=True)
                except Exception as e:
                    logging.error("MainWindow: Failed to clean local Puppeteer cache: %s", e)
        else:
            # Check and install API modules if needed (first run only)
            logging.info("MainWindow: Checking/installing API modules...")
            self.ensure_api_modules_installed()

            # Check that the installed WPPConnect Server meets the minimum required version
            logging.info("MainWindow: Checking WPPConnect Server version...")
            self.ensure_wpp_version()

            # Start local WPPConnect Server (if bundled)
            logging.info("MainWindow: Ensuring WPPConnect Server process is running...")
            self.ensure_wpp_running()

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
                if not self.connect.check_connection_status():
                    logging.info("Connection dialog closed without pairing. Exiting application.")
                    sys.exit()
                if self.ws:
                    self.ws.sio.disconnect()
                self._just_paired = True
        
        logging.info("MainWindow: Retrieving token...")
        self.retrieve_token()
        if not self.token:
            logging.error("No token retrieved. Exiting application.")
            sys.exit()
        #Initialize websocket
        logging.info("MainWindow: Initializing WebSocketClient...")
        if hasattr(self, 'ws') and self.ws:
            try:
                self.ws.sio.disconnect()
            except Exception:
                pass
            self.ws = None
        self.ws = WebSocketClient(self, self.connect, self.token)

        logging.info("MainWindow: Preparing sync...")
        self.prepare_sync()
        # Initialise outgoing-message queue (must exist before init_UI so the
        # ConversationsPanel can call self.main_window.message_queue.enqueue).
        self.message_queue = MessageQueue(self)
        # Ensure session is active on WPPConnect Server before connecting WebSocket
        self.check_wa_connection_http()
        try:
            logging.info("MainWindow: Connecting WebSocket...")
            self.connect_websocket()
        except Exception as e:
            logging.exception("MainWindow: Exception during websocket connection")
            self.error_sound.play()
            error_str = str(e)
            # If the instance does not exist on the server (e.g. database recreated/wiped),
            # it returns "Invalid namespace". We should fallback to the connection dialog silently.
            if "Invalid namespace" in error_str or "namespaces failed to connect" in error_str:
                logging.info("WebSocket namespace is invalid (instance does not exist). Triggering logout.")
                wx.MessageBox(
                    self.i18n.t("device_logged_out"),
                    self.i18n.t("error").format(app_name=self.app_name),
                    wx.OK | wx.ICON_ERROR,
                )
                self._on_disconnect()
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

        # Auto-updater already scheduled early in constructor

        app.MainLoop()

    # ── Menu bar ─────────────────────────────────────────────────────────────

    def _build_menubar(self):
        """Create the menu bar with Arquivo, Sincronização and Ajuda menus."""
        self._ID_MARK_ALL_READ = wx.NewIdRef()
        self._ID_SETTINGS      = wx.NewIdRef()
        self._ID_DISCONNECT    = wx.NewIdRef()
        self._ID_EXIT          = wx.NewIdRef()
        self._ID_RESYNC_ALL    = wx.NewIdRef()
        self._ID_OFFLINE_MENU  = wx.NewIdRef()
        self._ID_SHORTCUTS     = wx.NewIdRef()
        self._ID_FORCE_UPDATE  = wx.NewIdRef()
        self._ID_FORCE_REINSTALL_ZIP = wx.NewIdRef()
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

        # ── Sincronização ─────────────────────────────────────────────────────
        sync_menu = wx.Menu()
        sync_menu.Append(
            self._ID_RESYNC_ALL,
            f"{self.i18n.t('menu_resync_all')}\tF5",
        )
        self._sync_offline_menu_item = sync_menu.AppendCheckItem(
            self._ID_OFFLINE_MENU,
            f"{self.i18n.t('tray_offline_mode')}\tCtrl+Alt+Shift+O",
        )
        self._sync_offline_menu_item.Check(bool(self.offline_mode))
        menubar.Append(sync_menu, self.i18n.t("menu_sync"))

        # ── Ajuda ─────────────────────────────────────────────────────────────
        help_menu = wx.Menu()
        help_menu.Append(
            self._ID_SHORTCUTS,
            f"{self.i18n.t('menu_shortcuts')}\tF1",
        )
        help_menu.AppendSeparator()
        help_menu.Append(self._ID_FORCE_UPDATE, self.i18n.t("menu_force_update"))
        help_menu.Append(self._ID_FORCE_REINSTALL_ZIP, self.i18n.t("menu_force_reinstall_zip"))
        help_menu.AppendSeparator()
        help_menu.Append(self._ID_ABOUT, self.i18n.t("menu_about"))
        menubar.Append(help_menu, self.i18n.t("menu_help"))

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self._on_mark_all_read, id=self._ID_MARK_ALL_READ)
        self.Bind(wx.EVT_MENU, self.on_ctrl_comma,     id=self._ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self._on_disconnect,    id=self._ID_DISCONNECT)
        self.Bind(wx.EVT_MENU, lambda e: self.real_exit(), id=self._ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_menu_resync_all, id=self._ID_RESYNC_ALL)
        self.Bind(wx.EVT_MENU, self._on_menu_toggle_offline, id=self._ID_OFFLINE_MENU)
        self.Bind(wx.EVT_MENU, self.on_f1,             id=self._ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self._on_force_update,  id=self._ID_FORCE_UPDATE)
        self.Bind(wx.EVT_MENU, self._on_force_reinstall_zip, id=self._ID_FORCE_REINSTALL_ZIP)
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
        mb.SetMenuLabel(1, self.i18n.t("menu_sync"))
        mb.GetMenu(1).FindItemById(self._ID_RESYNC_ALL).SetItemLabel(
            f"{self.i18n.t('menu_resync_all')}\tF5"
        )
        mb.GetMenu(1).FindItemById(self._ID_OFFLINE_MENU).SetItemLabel(
            f"{self.i18n.t('tray_offline_mode')}\tCtrl+Alt+Shift+O"
        )
        mb.SetMenuLabel(2, self.i18n.t("menu_help"))
        mb.GetMenu(2).FindItemById(self._ID_SHORTCUTS).SetItemLabel(
            f"{self.i18n.t('menu_shortcuts')}\tF1"
        )
        mb.GetMenu(2).FindItemById(self._ID_FORCE_UPDATE).SetItemLabel(
            self.i18n.t("menu_force_update")
        )
        mb.GetMenu(2).FindItemById(self._ID_FORCE_REINSTALL_ZIP).SetItemLabel(
            self.i18n.t("menu_force_reinstall_zip")
        )
        mb.GetMenu(2).FindItemById(self._ID_ABOUT).SetItemLabel(
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
                "Juan Mathews Rebelo Santos, João Jorge e Gustavo Barrios: principais colaboradores."
                "Fabiano Ferreira, Tadeu Junior, Wagner Soares da Silva, Eduardo Ferreira, Elias Junior e todos da comunidade que ajudaram, seja testando, implementando melhorias ou dando sugestões / relatórios de bugs.",
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

    def _on_disconnect(self, event=None):
        """Disconnect from WhatsApp: wipe credentials, stop WebSocket and show pairing dialog."""
        pi = self.settings.setdefault("privateinfo", {})
        old_token = pi.pop("WA_token", "")
        pi.pop("WA_phone_number", None)
        pi.pop("paired", None)
        self.messages_set_completed = False
        self.token = ""
        self.save_settings()
        self.clear_local_data()
        # Best-effort: close the WPPConnect session so Chrome is released.
        if old_token:
            def _close():
                try:
                    import requests as _req
                    _req.post(
                        f"{self.wpp_server}:{self.wpp_port}/api/{old_token}/close-session",
                        headers={"Authorization": f"Bearer {old_token}", "Content-Type": "application/json"},
                        timeout=5,
                    )
                except Exception:
                    pass
            threading.Thread(target=_close, daemon=True).start()
        try:
            if self.ws and self.ws.sio.connected:
                self.ws.sio.disconnect()
        except Exception:
            pass
        self.connect.show_connection_dial()

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
        if not hasattr(self, "_hotkey_manager"):
            return
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
        if not getattr(self, "_initial_sync_running", False):
            deleted = set(self.settings.get("deleted_chats", []))
            unread_chats = sum(
                1 for jid, chat in list(self.chats.items())
                if jid not in deleted and effective_unread_count(chat) > 0
            )
            if unread_chats:
                title += f" ({unread_chats})"
        if self.offline_mode:
            title += f" | {self.i18n.t('tray_offline_mode')}"
        if self._tray_status:
            title += f" | {self._tray_status}"
        self.SetTitle(title)
        if getattr(self, "tray_icon", None) is not None:
            self.tray_icon.update_tooltip()

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
        Toggle the user-controlled offline mode (tray menu item / Sincronização menu).
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
        if getattr(self, "_sync_offline_menu_item", None) is not None:
            self._sync_offline_menu_item.Check(bool(self.offline_mode))

    def _on_menu_toggle_offline(self, event=None):
        """Sincronização menu / Ctrl+Alt+Shift+O: toggle offline mode."""
        self.toggle_offline_mode()

    def _on_menu_resync_all(self, event=None):
        """Sincronização menu / F5: wipe all local chat/message state and
        force a full resync, exactly as if pairing for the first time."""
        if getattr(self, "_initial_sync_running", False):
            # Avoid corrupting state with two syncs writing to self.chats/db
            # at the same time.
            return
        # Ensure we are connected before wiping local data
        self.check_wa_connection_http()
        if not getattr(self, "_wa_connected", False):
            self.error_sound.play()
            wx.MessageBox(
                self.i18n.t("resync_failed_offline"),
                self.i18n.t("app_name"),
                wx.OK | wx.ICON_WARNING,
                self
            )
            return

        self.output(self.i18n.t("resyncing_all_announcement"), interrupt=True)
        threading.Thread(target=self._resync_all_worker, daemon=True).start()

    def _resync_all_worker(self):
        """Background worker for _on_menu_resync_all(). See that method."""
        ui_ready = threading.Event()

        def _prepare_ui():
            try:
                panel = self.conversations_panel
                panel._stop_audio()
                panel.close_conversation()
                panel.chats_list = []
                panel.chat_names = []
                panel._all_chats_list = []
                panel._all_chat_names = []
                panel._displayed_jids = None
                panel.conversations_list.DeleteAllItems()
                if hasattr(self, "archived_conversations_panel"):
                    ap = self.archived_conversations_panel
                    ap.chats_list = []
                    ap.chat_names = []
                    ap._all_chats_list = []
                    ap._all_chat_names = []
                    ap._displayed_jids = None
                    ap.conversations_list.DeleteAllItems()
            finally:
                ui_ready.set()

        wx.CallAfter(_prepare_ui)
        ui_ready.wait(timeout=5)

        # Wipe the local database and downloaded media/voice-message caches.
        self._sync_completed = False
        self.clear_local_data()
        try:
            media_failed_path = data_path("media_failed.json")
            if os.path.isfile(media_failed_path):
                os.remove(media_failed_path)
        except Exception as exc:
            logging.warning("[resync_all] failed to remove media_failed.json: %s", exc)
        self._media_failed_ids = set()

        # Resync from scratch, exactly like a fresh pairing.
        self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
        self.sync_thread.start()

    def _on_force_update(self, event):
        if self._update_checker is None:
            self._start_update_checker(force=True)
        else:
            self._update_checker.force_check()

    def _on_force_reinstall_zip(self, event):
        """
        Help > Force Reinstall from ZIP: always downloads and reinstalls the
        latest GitHub release's ZIP, regardless of whether it's actually
        newer than the running version — unlike _on_force_update(), which
        only checks and installs when a newer version exists.
        """
        if self._update_checker is None:
            from updater import UpdateChecker
            self._update_checker = UpdateChecker(self)
        self._update_checker.force_reinstall()

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
            self._last_activation_time = time.time()
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
        POST /api/{session}/set-online-presence
        Body: {"isOnline": true | false}

        Always runs on a background thread — never blocks the UI.
        """
        token = getattr(self, "token", None)
        if not token:
            return
        url = f"{self.wpp_server}:{self.wpp_port}/api/{token}/set-online-presence"
        is_online = presence == "available"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            requests.post(url, json={"isOnline": is_online}, headers=headers, timeout=5)
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
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, SW_RESTORE)
        # SetForegroundWindow() alone silently fails when another application
        # holds the foreground lock (Win32 foreground-stealing prevention). When
        # that happened the window stayed hidden/behind and the global hotkey
        # appeared "dead" until the app was restarted. Briefly attaching our
        # input queue to the current foreground thread lifts the lock so the
        # restore is reliable.
        try:
            kernel32 = ctypes.windll.kernel32
            fg_hwnd = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            cur_thread = kernel32.GetCurrentThreadId()
            attached = False
            if fg_thread and fg_thread != cur_thread:
                attached = bool(user32.AttachThreadInput(fg_thread, cur_thread, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            if attached:
                user32.AttachThreadInput(fg_thread, cur_thread, False)
        except Exception:
            user32.SetForegroundWindow(hwnd)
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
            wx.CallAfter(self.add_chats_to_ui)

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
        self._stop_wpp_server()
        if hasattr(self, "db") and self.db is not None:
            try:
                self.db.close()
            except Exception:
                pass
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
        """Normalize WhatsApp JID: strip device suffix (e.g. :1, :60) and replace legacy @c.us with @s.whatsapp.net.
        @g.us (groups) and @lid (linked-device IDs) are left unchanged."""
        if not jid:
            return jid
        # Strip companion device suffix if present (e.g. "5511919177719:60@c.us" -> "5511919177719@c.us")
        if ":" in jid and "@" in jid:
            parts = jid.split("@", 1)
            base = parts[0].split(":", 1)[0]
            jid = f"{base}@{parts[1]}"
        if jid.endswith("@c.us"):
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
        
        def _bg_delete_chat():
            try:
                self.db.delete_chat(lid_jid)
            except Exception as e:
                logging.error(f"[merge_lid] Failed to delete merged LID chat {lid_jid}: {e}")
        threading.Thread(target=_bg_delete_chat, daemon=True).start()

        
        # Redirect active conversation if it was the merged LID chat, or refresh if it is the destination phone chat
        if hasattr(self, "conversations_panel") and self.conversations_panel.conversation:
            active_jid = self.conversations_panel.conversation.get("remoteJid", "")
            if active_jid == lid_jid:
                self.conversations_panel.conversation = self.chats[phone_jid]
                wx.CallAfter(self.conversations_panel.populate_messages, preserve_focus=True)
            elif active_jid == phone_jid:
                wx.CallAfter(self.conversations_panel.populate_messages, preserve_focus=True)

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

        # If the message is from ourselves, ensure from_me is True
        sender = key.get("participant") or key.get("remoteJid") or ""
        if sender and self._is_self_jid(sender):
            from_me = True

        if not remote_jid:
            return

        # ── Guard against self-chat multi-device-sync artifacts ─────────────
        # WPPConnect/Baileys occasionally reports one of our own sends (seen
        # with self-chat text, audio and documents) tagged with an identity
        # that isn't our real phone JID, in one of two shapes:
        #
        #  (a) "participant" (the actual sender/author, per wa-js semantics)
        #      has the same digits as "remoteJid" (the chat). For a real
        #      GROUP, remoteJid is the group's own independently-allocated
        #      ID, never equal to any participant's JID — so this overlap
        #      alone proves it's not a real group, regardless of whatever
        #      fromMe flag WPPConnect attached to the sync echo (observed:
        #      it can arrive as fromMe=False, producing a bogus "new message
        #      from an unnamed participant" notification). For a bare,
        #      not-yet-resolved @lid or @s.whatsapp.net remoteJid, the same
        #      overlap is only unambiguous when fromMe is already True —
        #      for a real 1:1 chat, an incoming (fromMe=False) message's
        #      participant legitimately mirrors remoteJid (the sender IS
        #      the chat), so that combination must NOT be redirected.
        #
        #  (b) remoteJid is suffixed "@g.us" but its digits are simply our
        #      own phone number (with the Brazilian 9th-digit variant) — no
        #      real group JID is ever shaped like a plain phone number.
        #
        # Either shape otherwise spawns an unnamed phantom "group"/duplicate
        # chat that (1) duplicates a message already stored under "Eu" and
        # (2) can't be cleanly identified/deleted afterwards. Redirect to
        # the real self-chat, and opportunistically learn my_lid from case
        # (a) so later messages resolve immediately via _is_self_jid()
        # without waiting on resolve_self_lid()'s async API round-trip.
        participant_raw = key.get("participant") or ""
        remote_digits = remote_jid.split("@", 1)[0]
        part_digits = participant_raw.split("@", 1)[0] if participant_raw else ""
        # Normalize before using as a redirect target below — my_jid can be
        # in raw "@c.us" form early in a session (set directly from the
        # host-device API response, before resolve_self_lid() gets a chance
        # to normalize it), and redirecting to it as-is created yet another
        # duplicate "Eu" chat under @c.us instead of the canonical @s.whatsapp.net one.
        my_jid = self._normalize_jid(getattr(self, "my_jid", ""))
        my_lid = getattr(self, "my_lid", "")
        is_group_jid = remote_jid.endswith("@g.us")

        # A fromMe message's own "participant" field always identifies us —
        # wa-js only populates it to tag the sender within a group, and the
        # sender of our own outgoing message is always us. Learn my_lid from
        # this far more common signal (any ordinary group message we send),
        # not just the rarer self-referential artifacts checked below, so
        # _is_self_jid()/self_reference_label() resolve correctly (e.g. for
        # quoted-reply headers) from the first group message sent this
        # session — without waiting on resolve_self_lid()'s async API call,
        # which otherwise left _get_participant_name() falling through to a
        # saved contact name (e.g. a self-addressed contact literally named
        # "Eu") instead of honouring the "Como se referir a mim?" setting.
        if from_me and participant_raw.endswith("@lid") and not getattr(self, "my_lid", "") and my_lid != participant_raw:
            self.my_lid = my_lid = participant_raw
            if my_jid:
                self.register_jid_mapping(participant_raw, my_jid)

        digits_self_referential = bool(part_digits and remote_digits == part_digits)
        is_self_referential = digits_self_referential and (
            is_group_jid or (from_me and my_jid and self._phone_digits_equivalent(remote_digits, my_jid.split("@", 1)[0]))
        )
        is_self_phone_group = bool(
            is_group_jid and my_jid
            and self._phone_digits_equivalent(remote_digits, my_jid.split("@", 1)[0])
        )

        if is_self_referential or is_self_phone_group:
            from_me = True
            if my_jid:
                remote_jid = my_jid
            elif my_lid:
                remote_jid = my_lid
            else:
                remote_jid = participant_raw or remote_jid
        elif (
            my_jid and remote_jid != my_jid
            and remote_jid.endswith("@s.whatsapp.net")
            and self._is_self_jid(remote_jid)
        ):
            # Plain self-chat message, no group/participant artifact involved
            # — just WhatsApp reporting our own number in the "other" digit
            # variant for this particular event (with vs. without the
            # Brazilian 9th digit). _is_self_jid() already tolerates that
            # when deciding it's self, but without canonicalizing remote_jid
            # here too, each variant kept its own separate chat entry —
            # e.g. sending a photo to yourself as a document created one
            # "Eu" chat for the (9-digit) document echo and a second "Eu"
            # chat for the (8-digit) sync-artifact echo of the same send.
            remote_jid = my_jid

        # Learn/update presence pushName map from incoming message
        if not from_me:
            sender_jid = key.get("participant") or key.get("remoteJid", "")
            push = msg.get("pushName", "")
            if sender_jid and push and not is_phone_like(push):
                sender_jid = self._normalize_jid(sender_jid)
                ppm = getattr(self, "_presence_pushname_map", {})
                if ppm.get(sender_jid) != push:
                    ppm[sender_jid] = push
                    self._schedule_save(contacts_dirty=True)

        # Extract mapping and mentions from incoming messages
        self._extract_lid_mapping(msg)

        # Statuses (stories) arrive as messages on status@broadcast; they are
        # stored in _status_updates for the Status tab, not in a conversation.
        # Newsletter (channels) are read-only and also ignored.
        if remote_jid.endswith("@broadcast"):
            self._store_status_update(msg)
            return
        if remote_jid.endswith("@newsletter"):
            return
            return

        # Reaction messages only update the live display of an existing message;
        # they must not be added to records or unread counts. They DO, however,
        # trigger a notification when someone reacts to one of *your* messages.
        if msg.get("messageType") == "reactionMessage":
            if hasattr(self, "conversations_panel"):
                self.conversations_panel.on_incoming_message(remote_jid, msg)
            self._maybe_notify_reaction(remote_jid, msg)
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
            else:
                # We don't have the mapping for this new @lid JID!
                # Start a background thread to resolve it, merge it, and update the UI
                def _bg_resolve_new_lid(lid_jid, message_obj):
                    try:
                        pn_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact/pn-lid/{lid_jid}"
                        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
                        pn_resp = requests.get(pn_url, headers=headers, timeout=5)
                        if pn_resp.ok:
                            pn_data = pn_resp.json()
                            phone_obj = pn_data.get("phoneNumber") or {}
                            phone_val = phone_obj.get("_serialized") or phone_obj.get("id") or ""
                            if phone_val:
                                if not phone_val.endswith("@s.whatsapp.net") and not phone_val.endswith("@c.us"):
                                    phone_val = f"{phone_val}@s.whatsapp.net"
                                phone_val = self._normalize_jid(phone_val)
                                
                                # Register mapping and merge on the main thread
                                def _main_thread_merge():
                                    self.register_jid_mapping(lid_jid, phone_val)
                                    self._merge_lid_into_phone(lid_jid, phone_val)
                                    self._schedule_set_chats()
                                wx.CallAfter(_main_thread_merge)
                    except Exception as e:
                        logging.warning("[on_new_message] Failed to resolve new LID %s in background: %s", lid_jid, e)
                threading.Thread(target=_bg_resolve_new_lid, args=(remote_jid, msg), daemon=True).start()
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
            push_name = "" if remote_jid.endswith("@g.us") else msg.get("pushName", "")
            self.chats[remote_jid] = {
                "remoteJid":   remote_jid,
                "unreadCount": 0,
                "pushName":    push_name,
                "messages":    {"messages": {
                    "records":     [],
                    "total":       0,
                    "pages":       1,
                    "currentPage": 1,
                }},
            }
            if remote_jid.endswith("@g.us"):
                # Unlike chats created by get_remote_chats() at sync time, a
                # group first seen via a live socket event has no name yet —
                # without this it stays "unnamed" until the next full sync.
                self._resolve_group_name_async(remote_jid)

        chat = self.chats[remote_jid]
        
        msg_ts = int(msg.get("messageTimestamp", 0) or msg.get("t", 0) or time.time())
        if msg_ts > 1_000_000_000_000:
            msg_ts //= 1000
        if msg_ts > int(chat.get("t", 0) or 0):
            chat["t"] = msg_ts

        # ── Avoid duplicate insertions or resolve pending ones ────────────────
        records = (
            chat.setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
        )
        if from_me:
            # Match the echo to the pending virtual message it actually
            # confirms, not just "whichever pending message we saw first".
            # When two sends are in flight at once (e.g. a text message
            # still awaiting its HTTP response while a voice message is
            # fired off right after), the previous "first pending" pick
            # would happily hand a text message the real ID of an unrelated
            # audio message (and vice versa) — corrupting both: the text
            # message freezes with no status updates (WhatsApp's status
            # events for its real ID never find a matching record), the
            # audio message's real ID collides with another entry's, its
            # sent sound fires for the wrong message, and the recording
            # file gets renamed onto the wrong ID so playback later loads
            # someone else's audio. Restrict candidates to pending messages
            # of the same type so unrelated messages can no longer swap IDs.
            incoming_type = msg.get("messageType", "")
            _text_types = ("conversation", "extendedTextMessage")
            pending_msg = None
            for r in records:
                if not r.get("_local_pending"):
                    continue
                r_type = r.get("messageType", "")
                if incoming_type in _text_types:
                    if r_type not in _text_types:
                        continue
                elif r_type != incoming_type:
                    continue
                pending_msg = r
                break
            if pending_msg:
                # Found the corresponding pending message: update it and skip appending a duplicate
                pending_msg["_local_pending"] = False
                local_id = pending_msg.get("_local_id")
                pending_msg["key"]["id"] = msg_id
                pending_msg["messageTimestamp"] = msg.get("messageTimestamp", pending_msg["messageTimestamp"])
                # The virtual message built before sending never carries a
                # "participant" (it doesn't know its own WhatsApp identity),
                # but our own group messages are indexed in WPPConnect's
                # store under participant=our own JID (see _serialize_msg_id).
                # Without backfilling it from the real echo here, replying-
                # to/quoting a message sent seconds ago falls back to a
                # guessed participant (my_jid) that doesn't match what the
                # live store actually indexed it under whenever the account
                # is on @lid — "Message ... not found" — until a later full
                # resync overwrites this record with the API's copy anyway.
                if key.get("participant"):
                    pending_msg["key"]["participant"] = key.get("participant")
                
                # Remove any existing record with the same real ID (e.g. from API
                # sync) *including* pending_msg itself (its key was just updated
                # to msg_id), then re-append it at the end.  The old filter kept
                # pending_msg via `r is pending_msg`, which left it in the list
                # AND then appended it again — creating a duplicate entry.
                if msg_id:
                    records[:] = [r for r in records
                                  if r.get("key", {}).get("id") != msg_id]
                records.append(pending_msg)
                
                def _bg_insert_pending():
                    try:
                        self.db.insert_message(remote_jid, pending_msg)
                    except Exception as e:
                        logging.error(f"[on_new_message] Failed to insert pending message to DB: {e}")
                threading.Thread(target=_bg_insert_pending, daemon=True).start()
                
                with self._own_sent_ids_lock:
                    self._own_sent_ids.add(msg_id)
                    if len(self._own_sent_ids) > 500:
                        self._own_sent_ids.discard(next(iter(self._own_sent_ids)))
                
                if hasattr(self, "conversations_panel"):
                    wx.CallAfter(self.conversations_panel._mark_message_sent, local_id, real_id=msg_id)
                
                self._schedule_save(dirty_jid=remote_jid)
                self._schedule_set_chats()
                return

        if msg_id:
            for existing in records:
                if existing.get("key", {}).get("id") == msg_id:
                    return  # already stored



        # Ignore stale re-deliveries of messages the user already cleared.
        if self._is_cleared_message(remote_jid, msg):
            return

        # Slim any bloated quoted-message payload before persisting.
        prune_message_record(msg)
        records.append(msg)
        
        def _bg_insert_msg():
            try:
                self.db.insert_message(remote_jid, msg)
            except Exception as e:
                logging.error(f"[on_new_message] Failed to insert message to DB: {e}")
        threading.Thread(target=_bg_insert_msg, daemon=True).start()

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
        self._schedule_save(dirty_jid=remote_jid)

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

        # Guard: do not play sound or show notification for messages older than 60 seconds
        ts = msg.get("messageTimestamp")
        if ts:
            try:
                conn_time = getattr(self.ws, "_connect_time", time.time()) if self.ws else time.time()
                cutoff = conn_time - 60
                if int(ts) < cutoff:
                    return
            except (TypeError, ValueError):
                pass

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

        body  = format_notification_body(msg, self, self.i18n)

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
                # Mark the active conversation as read immediately, but only if the
                # window has been focused for at least 5 seconds (to prevent marking
                # startup/offline messages as read automatically).
                last_act = getattr(self, "_last_activation_time", 0)
                if time.time() - last_act >= 5.0:
                    threading.Thread(
                        target=self.mark_conversation_as_read,
                        args=(remote_jid, True),
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

    def on_historical_message(self, msg: dict):
        """
        Processes historical/sync messages (isMdHistoryMsg=True) received via WebSocket.
        Saves them to local storage, sorts records, and updates the lastMessage/t
        of the chat if the incoming message is newer. Does not trigger notifications or sounds.
        """
        key        = msg.get("key", {})
        remote_jid = self._normalize_jid(key.get("remoteJid", ""))
        msg_id     = key.get("id", "")

        if not remote_jid or not msg_id:
            return

        # Statuses (stories) or channels ignored
        if remote_jid.endswith("@broadcast") or remote_jid.endswith("@newsletter"):
            return

        # Normalize Alt JID mapping if present
        self._extract_lid_mapping(msg)
        alt_jid = self._normalize_jid(key.get("remoteJidAlt", ""))
        if alt_jid:
            self._extract_lid_mapping(msg)

        # Retrieve/create local chat object
        chat = self.chats.get(remote_jid)
        if not chat:
            chat = {
                "remoteJid": remote_jid,
                "unreadCount": 0,
                "pushName": msg.get("pushName", "") or "",
                "name": "",
                "messages": {"messages": {"records": []}},
                "lastMessage": None,
                "t": 0,
                "archived": False,
                "archive": False,
                "type": "group" if remote_jid.endswith("@g.us") else "chat",
            }
            if remote_jid.endswith("@g.us"):
                chat["name"] = self._fill_group_name(remote_jid)
            self.chats[remote_jid] = chat

        records_wrapper = chat.setdefault("messages", {})
        if not isinstance(records_wrapper, dict):
            records_wrapper = chat["messages"] = {}
        inner_wrapper = records_wrapper.setdefault("messages", {})
        if not isinstance(inner_wrapper, dict):
            inner_wrapper = records_wrapper["messages"] = {}
        records = inner_wrapper.setdefault("records", [])
        if not isinstance(records, list):
            records = inner_wrapper["records"] = []

        # Check if already present in memory records
        if any(r.get("key", {}).get("id") == msg_id for r in records):
            return

        # Ignore stale re-deliveries of cleared messages
        if self._is_cleared_message(remote_jid, msg):
            return

        # Slim the payload
        prune_message_record(msg)
        records.append(msg)

        # Sort the records chronologically
        try:
            records.sort(key=lambda m: int(m.get("messageTimestamp") or m.get("timestamp") or 0))
        except Exception as sort_err:
            logging.error(f"[on_historical_message] Failed to sort records: {sort_err}")

        # Update lastMessage and 't' (timestamp) if this message is newer
        msg_ts = int(msg.get("messageTimestamp") or msg.get("timestamp") or 0)
        current_lm = chat.get("lastMessage")
        lm_ts = 0
        if isinstance(current_lm, dict):
            lm_ts = int(current_lm.get("messageTimestamp") or current_lm.get("timestamp") or 0)
        if msg_ts >= lm_ts:
            chat["lastMessage"] = msg
            chat["t"] = msg_ts
            # Save updated chat to DB
            def _bg_upsert_chat():
                try:
                    self.db.upsert_chat(remote_jid, chat)
                except Exception as db_err:
                    logging.error(f"[on_historical_message] Failed to upsert chat to DB: {db_err}")
            threading.Thread(target=_bg_upsert_chat, daemon=True).start()

        # Insert message to DB in background
        def _bg_insert_msg():
            try:
                self.db.insert_message(remote_jid, msg)
            except Exception as e:
                logging.error(f"[on_historical_message] Failed to insert message to DB: {e}")
        threading.Thread(target=_bg_insert_msg, daemon=True).start()

        # Debounced UI update
        self._schedule_save(dirty_jid=remote_jid)
        self._schedule_set_chats()

        # Add message to the open conversation panel if it's currently selected
        cp = getattr(self, "conversations_panel", None)
        if cp and cp.conversation and cp.conversation.get("remoteJid") == remote_jid:
            wx.CallAfter(cp.populate_messages, preserve_focus=True)

    def _reacted_message_preview(self, remote_jid: str, orig_id: str) -> str:
        """Return a short text preview of the original message a reaction targets."""
        if not orig_id:
            return ""
        from core.notification_manager import format_notification_body
        candidates = [remote_jid, self._normalize_jid(remote_jid)]
        lid = getattr(self, "_phone_to_lid", {}).get(remote_jid)
        phone = getattr(self, "_lid_to_phone", {}).get(remote_jid)
        if lid:
            candidates.append(lid)
        if phone:
            candidates.append(phone)
        seen = set()
        for cj in candidates:
            if not cj or cj in seen:
                continue
            seen.add(cj)
            chat = self.chats.get(cj)
            if not chat:
                continue
            for r in list(chat.get("messages", {}).get("messages", {}).get("records", [])):
                if r.get("key", {}).get("id") == orig_id:
                    try:
                        return (format_notification_body(r, self, self.i18n) or "")[:120]
                    except Exception:
                        return ""
        return ""

    def _maybe_notify_reaction(self, remote_jid: str, msg: dict):
        """
        Notify when someone reacts to one of *your* messages.

        Only fires for reactions by other people to messages you sent — never for
        your own reactions, nor for reactions to other people's messages. Mirrors
        the guards (age, mute, archive, master toggle) used for normal messages.
        """
        try:
            reaction = (msg.get("message") or {}).get("reactionMessage") or {}
            emoji = (reaction.get("text") or "").strip()
            if not emoji:
                return  # empty emoji = reaction removed
            key = msg.get("key", {})
            if key.get("fromMe"):
                return  # I reacted — don't notify myself
            target_key = reaction.get("key") or {}
            if not target_key.get("fromMe"):
                return  # reaction to someone else's message — ignore

            ts = msg.get("messageTimestamp")
            if ts:
                try:
                    conn_time = getattr(self.ws, "_connect_time", time.time()) if self.ws else time.time()
                    if int(ts) < conn_time - 60:
                        return
                except (TypeError, ValueError):
                    pass

            if self.is_chat_muted(remote_jid) or self.is_chat_archived(remote_jid):
                return
            if not self.settings.get("general", {}).get("notifications_enabled", True):
                return

            from core.notification_manager import format_notification_title

            orig_text = self._reacted_message_preview(remote_jid, target_key.get("id", ""))
            if orig_text:
                body = self.i18n.t("notif_reaction_to_own").format(emoji=emoji, text=orig_text)
            else:
                body = self.i18n.t("notif_reaction").format(emoji=emoji)
            title = format_notification_title(msg, self, self.i18n)

            window_active = (
                not getattr(self, "_window_hidden", False)
                and self.IsShown()
                and not self.IsIconized()
                and self.IsActive()
            )
            if window_active:
                self.message_foreground_sound.play()
                self.output(f"{title}: {body}")
                return
            if not self.settings.get("general", {}).get("show_tray_icon", True):
                return
            if hasattr(self, "notification_manager"):
                self.notification_manager.send(title, body, remote_jid)
        except Exception:
            logging.exception("[_maybe_notify_reaction] failed")

    def connect_websocket(self):
        """Connect to the WPPConnect Server WebSocket.

        Connects to both the session namespace and root namespace so that
        global events (qrCode, phoneCode, session-logged) are received.
        Retries up to 6 times with a 2-second delay to handle the brief
        window after session creation where the namespace isn't ready yet.
        """
        import time
        max_attempts = 6
        delay = 2
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                logging.info("connect_websocket: Attempting connection %d/%d...", attempt, max_attempts)
                if self.ws.sio.connected:
                    self.ws.sio.disconnect()
                # WPPConnect Server only uses the root Socket.IO namespace.
                # All events (qrCode, phoneCode, received-message, etc.) are
                # emitted via req.io.emit() on root "/".
                self.ws.sio.connect(
                    f"{self.wpp_ws_server}:{self.wpp_port}/",
                    socketio_path="socket.io",
                    headers={"apikey": self.token},
                    namespaces=["/"],
                )
                logging.info("connect_websocket: Connected successfully on attempt %d.", attempt)
                return
            except Exception as exc:
                logging.warning("connect_websocket: Attempt %d failed: %s", attempt, exc)
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(delay)
        raise last_exc

    # ── First-run module installation ──────────────────────────────────────

    def ensure_api_modules_installed(self):
        """
        Ensure the WPPConnect is cloned, compiled, and has its node_modules.

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
        import sys
        import shutil
        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        dist_server  = resource_path("api",  "dist", "server.js")
        node_modules = resource_path("api",  "node_modules")

        # Node.js is mandatory — auto-download portable version if missing.
        if not os.path.isfile(node_exe):
            if self.background_mode:
                logging.error("[ensure_api_modules_installed] Node.js not found and cannot show download dialog in background mode")
                sys.exit(0)
            logging.info("[ensure_api_modules_installed] Node.js not found — downloading portable version...")
            from ui.dialogs.node_download import NodeDownloadDialog
            dlg = NodeDownloadDialog(self)
            result = dlg.ShowModal()
            dlg.Destroy()
            if result != wx.ID_OK:
                sys.exit(1)
            # Re-resolve path after download
            if sys.platform == "win32":
                node_exe = resource_path("node", "node.exe")
            # If still missing after download, abort
            if not os.path.isfile(node_exe):
                logging.error("[ensure_api_modules_installed] Node.js download failed — node.exe still missing")
                sys.exit(1)

        # Detect and clean legacy node_modules from WPPConnect to force a clean install of WPPConnect
        wpp_marker = os.path.join(node_modules, "@wppconnect-team")
        if os.path.isdir(node_modules) and not os.path.isdir(wpp_marker):
            logging.info("[ensure_api_modules_installed] Legacy node_modules detected. Cleaning for WPPConnect...")
            try:
                import shutil
                shutil.rmtree(node_modules, ignore_errors=True)
            except Exception as e:
                logging.error("[ensure_api_modules_installed] Failed to remove legacy node_modules: %s", e)

        # ── Check for new required packages in an existing node_modules ──────
        # When we add a new npm dependency (e.g. @ffmpeg-installer/ffmpeg) the
        # user's node_modules is already installed from a previous run, so the
        # normal "node_modules absent" gate never fires.  We compare a list of
        # required package markers and run `npm install` silently in the
        # background if any are missing — no dialog needed.
        _REQUIRED_MARKERS = [
            os.path.join(node_modules, "@ffmpeg-installer", "ffmpeg"),
            os.path.join(node_modules, "@babel", "runtime"),
        ]
        if os.path.isfile(dist_server) and os.path.isdir(node_modules):
            missing = [m for m in _REQUIRED_MARKERS if not os.path.isdir(m)]
            if missing:
                logging.info(
                    "[ensure_api_modules_installed] Missing packages detected: %s — running npm install",
                    missing,
                )
                if sys.platform == "win32":
                    node_exe = resource_path("node", "node.exe")
                    npm_cli  = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    npm_cmd  = [node_exe, npm_cli]
                    node_dir = resource_path("node")
                    path_env = node_dir + os.pathsep + os.environ.get("PATH", "")
                else:
                    local_node = resource_path("node", "node")
                    if os.path.isfile(local_node):
                        node_exe = local_node
                    else:
                        node_exe = shutil.which("node") or "node"
                    local_npm = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    if os.path.isfile(local_npm):
                        npm_cmd = [node_exe, local_npm]
                    else:
                        npm_cmd = [shutil.which("npm") or "npm"]
                    node_dir = os.path.dirname(node_exe) if os.path.isabs(node_exe) else ""
                    path_env = (node_dir + os.pathsep + os.environ.get("PATH", "")) if node_dir else os.environ.get("PATH", "")

                npm_env  = {
                    **os.environ,
                    "PATH": path_env,
                    "PUPPETEER_CACHE_DIR": resource_path("api", ".cache", "puppeteer"),
                }
                api_dir  = resource_path("api")
                creation_flags = 0
                if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creation_flags = subprocess.CREATE_NO_WINDOW

                try:
                    proc = subprocess.Popen(
                        npm_cmd + ["install", "--no-audit", "--no-fund", "--include=optional", "--legacy-peer-deps"],
                        cwd=api_dir,
                        env=npm_env,
                        creationflags=creation_flags,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    _, stderr_bytes = proc.communicate()
                    if proc.returncode != 0:
                        logging.error(
                            "[ensure_api_modules_installed] npm install failed: %s",
                            (stderr_bytes or b"").decode("utf-8", errors="replace"),
                        )
                    else:
                        logging.info("[ensure_api_modules_installed] npm install completed OK")
                except Exception as exc:
                    logging.error("[ensure_api_modules_installed] npm install error: %s", exc)
            return

        # Detect and clean legacy node_modules from WPPConnect to force a clean install of WPPConnect
        wpp_marker = os.path.join(node_modules, "@wppconnect-team")
        if os.path.isdir(node_modules) and not os.path.isdir(wpp_marker):
            logging.info("[ensure_api_modules_installed] Legacy node_modules detected. Cleaning for WPPConnect...")
            try:
                import shutil
                shutil.rmtree(node_modules, ignore_errors=True)
            except Exception as e:
                logging.error("[ensure_api_modules_installed] Failed to remove legacy node_modules: %s", e)

        # ── Check for new required packages in an existing node_modules ──────
        # When we add a new npm dependency (e.g. @ffmpeg-installer/ffmpeg) the
        # user's node_modules is already installed from a previous run, so the
        # normal "node_modules absent" gate never fires.  We compare a list of
        # required package markers and run `npm install` silently in the
        # background if any are missing — no dialog needed.
        _REQUIRED_MARKERS = [
            os.path.join(node_modules, "@ffmpeg-installer", "ffmpeg"),
            os.path.join(node_modules, "@babel", "runtime"),
        ]
        if os.path.isfile(dist_server) and os.path.isdir(node_modules):
            missing = [m for m in _REQUIRED_MARKERS if not os.path.isdir(m)]
            if missing:
                logging.info(
                    "[ensure_api_modules_installed] Missing packages detected: %s — running npm install",
                    missing,
                )
                if sys.platform == "win32":
                    node_exe = resource_path("node", "node.exe")
                    npm_cli  = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    npm_cmd  = [node_exe, npm_cli]
                    node_dir = resource_path("node")
                    path_env = node_dir + os.pathsep + os.environ.get("PATH", "")
                else:
                    local_node = resource_path("node", "node")
                    if os.path.isfile(local_node):
                        node_exe = local_node
                    else:
                        node_exe = shutil.which("node") or "node"
                    local_npm = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    if os.path.isfile(local_npm):
                        npm_cmd = [node_exe, local_npm]
                    else:
                        npm_cmd = [shutil.which("npm") or "npm"]
                    node_dir = os.path.dirname(node_exe) if os.path.isabs(node_exe) else ""
                    path_env = (node_dir + os.pathsep + os.environ.get("PATH", "")) if node_dir else os.environ.get("PATH", "")

                npm_env  = {
                    **os.environ,
                    "PATH": path_env,
                    "PUPPETEER_CACHE_DIR": resource_path("api", ".cache", "puppeteer"),
                }
                api_dir  = resource_path("api")
                creation_flags = 0
                if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creation_flags = subprocess.CREATE_NO_WINDOW

                try:
                    proc = subprocess.Popen(
                        npm_cmd + ["install", "--no-audit", "--no-fund", "--include=optional", "--legacy-peer-deps"],
                        cwd=api_dir,
                        env=npm_env,
                        creationflags=creation_flags,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    _, stderr_bytes = proc.communicate()
                    if proc.returncode != 0:
                        logging.error(
                            "[ensure_api_modules_installed] npm install failed: %s",
                            (stderr_bytes or b"").decode("utf-8", errors="replace"),
                        )
                    else:
                        logging.info("[ensure_api_modules_installed] npm install completed OK")
                except Exception as exc:
                    logging.error("[ensure_api_modules_installed] npm install error: %s", exc)
            return

        # Everything already set up — nothing to do.
        if os.path.isfile(dist_server) and os.path.isdir(node_modules):
            return

        if self.background_mode:
            sys.exit(0)

        if not os.path.isfile(dist_server):
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

    # ── WPPConnect version gate ───────────────────────────────────────────────

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

    def _get_installed_wpp_version(self) -> str:
        """Read the WPPConnect Server version from api/package.json."""
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

    def ensure_wpp_version(self):
        """
        Compare the installed WPPConnect version against the minimum required
        by this WinZapp build (WPP_MINIMUM_VERSION in client/.env).

        If the installed version is older the user is prompted to:
          • Update now   — re-download + rebuild via ApiSetupDialog, then continue
          • Exit         — terminate WinZapp
          • Continue     — proceed without updating (not recommended)

        The check is skipped when:
          - Running in background mode (no UI)
          - api/package.json is absent (setup not done yet)
          - WPP_MINIMUM_VERSION is not defined in the .env
        """
        if self.background_mode:
            return

        dist_main = resource_path("api", "dist", "main.js")
        if not os.path.isfile(dist_main):
            return  # API not installed yet — setup dialog will handle it

        minimum  = self._read_env_value("WPP_MINIMUM_VERSION")
        if not minimum:
            return  # No minimum defined — nothing to check

        installed = self._get_installed_wpp_version()
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

    # ── WPPConnect lifecycle ─────────────────────────────────────────────────

    def _is_wpp_running(self):
        """Return True if the WPPConnect is already listening on the configured server/port."""
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(self.wpp_server)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or self.wpp_port
            with _socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            return False

    def _start_wpp_background(self):
        """
        Launch the bundled WPPConnect Server node process in the background.
        stdout and stderr are redirected to api/wppconnect.log so that startup
        errors can be shown to the user if the port never opens.
        Does nothing if the node or start.js files are not present (dev mode).

        When the current process is elevated (run as Administrator) the child
        is spawned using the non-elevated linked token via CreateProcessWithTokenW
        so that PostgreSQL's initdb can start (it refuses to run as root/admin).
        """
        import sys
        import shutil

        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        start_js  = resource_path("api",  "start.js")
        if not os.path.isfile(node_exe) or not os.path.isfile(start_js):
            return  # Not bundled — developer runs WPPConnect separately
        try:
            from app_paths import log_path
            self._wpp_log_path = log_path("wppconnect.log")
            log_fh = open(self._wpp_log_path, "w",
                          encoding="utf-8", errors="replace")
            # Use the short (8.3) path so PostgreSQL's initdb doesn't choke on
            # accented characters in the install path (e.g. "Área de Trabalho").
            cwd = _get_short_path_name(resource_path("api"))
            self.wpp_process = None

            # Guarantee that the child Node process inherits the correct API key
            # regardless of whether the local start.js or .env has been preserved.
            os.environ["AUTHENTICATION_API_KEY"] = self.wpp_api_key
            os.environ["WPP_LID_MODE"] = "false"
            os.environ["PORT"] = str(self.wpp_port)
            os.environ["PUPPETEER_CACHE_DIR"] = resource_path("api", ".cache", "puppeteer")

            # Ensure dist/config.js has useChrome:false so WPPConnect always uses
            # Puppeteer's own bundled Chrome/Chromium instead of searching for a
            # system Chrome installation. Patched here at runtime so existing users
            # with a pre-built dist/ benefit immediately without a full rebuild.
            try:
                _dist_cfg = resource_path("api", "dist", "config.js")
                if os.path.isfile(_dist_cfg):
                    with open(_dist_cfg, "r", encoding="utf-8") as _f:
                        _cfg_src = _f.read()
                    if "useChrome" not in _cfg_src:
                        _cfg_src = _cfg_src.replace(
                            "createOptions: {",
                            "createOptions: { useChrome: false,",
                            1,
                        )
                        with open(_dist_cfg, "w", encoding="utf-8") as _f:
                            _f.write(_cfg_src)
                        logging.info("[startup] Patched dist/config.js: useChrome → false")
            except Exception as _e:
                logging.warning("[startup] Could not patch dist/config.js: %s", _e)

            # WPPConnect uses Puppeteer/Chrome which already includes --no-sandbox
            # in its config (see api/src/config.ts), so Chrome runs correctly even
            # when the parent process is elevated.  De-elevation via the Safer API
            # is therefore not needed and would prevent Node.js from writing session
            # tokens/cache to the installation directory, breaking admin users.
            creation_flags = 0
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creation_flags = subprocess.CREATE_NO_WINDOW

            self.wpp_process = subprocess.Popen(
                [node_exe, start_js],
                cwd=cwd,
                creationflags=creation_flags,
                stdout=log_fh,
                stderr=log_fh,
            )
            # Release Python's file handle now that node.exe has inherited it.
            # This avoids a double-lock on wppconnect.log so an update extraction
            # can overwrite the file once WinZapp exits (only node.exe holds a
            # lock while it is running — we don't need it on the Python side).
            log_fh.close()
            self._wpp_log_fh = None
            atexit.register(self._stop_wpp_server)
        except Exception:
            pass

    def _stop_wpp_server(self):
        """Terminate the WPPConnect Server process and all its children.

        Calls /close-session first so WPPConnect asks Puppeteer to
        browser.close() Chrome gracefully, preventing stale Chrome windows.
        """
        token = getattr(self, "token", "")
        if token:
            try:
                url = (
                    f"{self.wpp_server}:{self.wpp_port}"
                    f"/api/{token}/close-session"
                )
                requests.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5,
                )
                time.sleep(2)
            except Exception:
                pass

        proc = getattr(self, "wpp_process", None)
        pid = None
        if proc and proc.poll() is None:
            pid = proc.pid
        elif proc is None:
            # This session never spawned WPPConnect itself — it found the port
            # already open (e.g. a previous session was force-quit and its
            # node.exe never got killed). Locate the orphaned process by the
            # port it's listening on so it doesn't leak across restarts.
            pid = self._find_pid_listening_on_port(self.wpp_port)

        if pid:
            try:
                import sys
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                    )
                elif proc is not None:
                    proc.terminate()
            except Exception:
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

    def _find_pid_listening_on_port(self, port):
        """Return the PID of the node.exe process listening on *port* (Windows only).

        Used when this session reused an already-running WPPConnect Server
        left behind by a previous session that was force-quit, so we still
        have a way to terminate it instead of leaving it running forever.
        """
        import sys
        if sys.platform != "win32":
            return None
        no_window = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                creationflags=no_window,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return None

        port_suffix = f":{port}"
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0] != "TCP" or parts[3] != "LISTENING":
                continue
            if not parts[1].endswith(port_suffix):
                continue
            try:
                candidate_pid = int(parts[-1])
            except ValueError:
                continue
            try:
                tasklist_out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {candidate_pid}", "/FO", "CSV", "/NH"],
                    creationflags=no_window,
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue
            if "node.exe" in tasklist_out.lower():
                return candidate_pid
        return None

    def ensure_wpp_running(self):
        """
        Start the local WPPConnect Server if it is not already listening.

        Normal mode   — shows a progress dialog while waiting (up to 5 min).
        Background mode — polls silently; exits with code 1 on timeout.

        On first launch the database initialisation and migrations can take
        60-90 s; subsequent starts are much faster.  On slower machines (HDD,
        antivirus scanning, or a first-run Puppeteer/Chrome download in
        start.js) startup can take well over 2 minutes, hence the 5-minute
        budget below.
        """
        if self._is_wpp_running():
            return  # Already up (e.g. left running from a previous session)

        import sys
        import shutil

        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        start_js  = resource_path("api",  "start.js")
        dist_server = resource_path("api",  "dist", "server.js")

        # All three files are required to start the bundled API.
        # If any is missing (setup incomplete or not yet run), skip silently —
        # ensure_api_modules_installed() already handled the missing node.exe
        # case; dist/server.js absence means setup was cancelled or not done yet.
        if not (os.path.isfile(node_exe)
                and os.path.isfile(start_js)
                and os.path.isfile(dist_server)):
            return

        self._wpp_log_path = None
        self._wpp_log_fh   = None
        self._start_wpp_background()

        if self.background_mode:
            # Silent wait — no dialog, no speech.  Timeout → exit code 1.
            deadline = time.time() + 300
            while time.time() < deadline:
                if self._is_wpp_running():
                    return
                time.sleep(2)
            sys.exit(1)

        from ui.dialogs.api_startup import ApiStartupDialog
        dlg    = ApiStartupDialog(self, self.wpp_port)
        result = dlg.ShowModal()
        if dlg:
            dlg.Destroy()

        if result != wx.ID_OK:
            # Collect the last 40 lines of the WPPConnect log for diagnosis
            details = ""
            log_path = getattr(self, "_wpp_log_path", None)
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
        if not hasattr(self, "navigation_panel"):
            return
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

    def _check_api_type_first_run(self):
        """
        Check if we need to ask the user to choose between local and custom/remote API on first launch.
        """
        if self.background_mode:
            return

        gen = self.settings.get("general", {})
        if gen.get("api_type_first_run_asked", False):
            return

        msg = self.i18n.t("api_type_ask_message")
        title = self.i18n.t("api_type_ask_title")

        result = wx.MessageBox(
            msg,
            title,
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
        )

        if result == wx.YES:
            # User wants local API (default)
            self.settings.setdefault("connection", {})["wpp_custom_api"] = False
            self.wpp_custom_api = False
            self.settings.setdefault("general", {})["api_type_first_run_asked"] = True
            self.save_settings()
        elif result == wx.NO:
            # User wants to specify a custom/remote API
            self.settings.setdefault("connection", {})["wpp_custom_api"] = True
            self.wpp_custom_api = True
            self.save_settings()

            # Open settings dialog on the Connection tab (index 3)
            from ui.dialogs.settings_dialog import SettingsDialog
            dlg = SettingsDialog(self)
            dlg._notebook.SetSelection(3)
            settings_res = dlg.ShowModal()
            dlg.Destroy()

            if settings_res == wx.ID_OK:
                # Successfully configured! Mark as asked.
                self.settings.setdefault("general", {})["api_type_first_run_asked"] = True
                self.save_settings()
            else:
                # User cancelled or closed settings dialog. Roll back and exit.
                self.settings.setdefault("connection", {})["wpp_custom_api"] = False
                self.wpp_custom_api = False
                self.save_settings()
                sys.exit(0)
        else:
            # User cancelled or closed the question box. Exit.
            sys.exit(0)

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

    def _sync_autostart_registry(self):
        """
        Synchronize the Windows Run registry key with the current settings.
        Only runs on Windows. If autostart setting is True, ensures the registry key exists.
        If autostart setting is False (and it's not the first run), ensures the key is removed.
        """
        import sys
        if sys.platform != "win32":
            return

        if self.settings.get("general", {}).get("first_run", True):
            return

        try:
            from autostart import is_autostart_enabled, enable_autostart, disable_autostart
            setting_enabled = self.settings.get("general", {}).get("autostart", False)
            registry_enabled = is_autostart_enabled()

            if setting_enabled and not registry_enabled:
                logging.info("Startup: Autostart is enabled in settings but missing in registry. Enabling...")
                enable_autostart()
            elif not setting_enabled and registry_enabled:
                logging.info("Startup: Autostart is disabled in settings but present in registry. Disabling...")
                disable_autostart()
        except Exception as e:
            logging.error("Startup: Failed to sync autostart registry key: %s", e)

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

    @property
    def messages_set_completed(self) -> bool:
        """Get the messages synchronization status from SQLite metadata."""
        if not hasattr(self, "db") or self.db is None:
            return False
        return self.db.get_metadata_json("messages_set_completed", False)

    @messages_set_completed.setter
    def messages_set_completed(self, val: bool):
        """Set the messages synchronization status in SQLite metadata."""
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("messages_set_completed", val)

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
        self.startup_sound = load_sound(self.sound_system, "startup.ogg")
        self.error_sound = load_sound(self.sound_system, "error.ogg")
        self.qrcode_loaded_sound = load_sound(self.sound_system, "qrcode_loaded.ogg")
        self.waiting_pairing_sound = load_sound(self.sound_system, "waiting_pairing.ogg")
        self.pairing_code_updated_sound = load_sound(self.sound_system, "pairing_code_updated.ogg")
        self.connected_sound = load_sound(self.sound_system, "connected.ogg")
        self.synchronizing_sound = load_sound(self.sound_system, "synchronizing.ogg")
        self.sync_complete_sound = load_sound(self.sound_system, "sync_complete.ogg")
        self.offline_mode_sound = load_sound(self.sound_system, "offline_mode.ogg")
        # Voice recording sounds
        self.voicemsg_startrecording_sound  = load_sound(self.sound_system, "voicemsg_startrecording.ogg")
        self.voicemsg_pauserecording_sound  = load_sound(self.sound_system, "voicemsg_pauserecording.ogg")
        self.voicemsg_discard_sound         = load_sound(self.sound_system, "voicemsg_discard.ogg")
        self.voicemsg_send_sound            = load_sound(self.sound_system, "voicemsg_send.ogg")
        # Background notification sound
        self.message_background_sound       = load_sound(self.sound_system, "message_background.ogg")
        # Foreground notification sounds
        self.message_current_sound          = load_sound(self.sound_system, "message_current.ogg")
        self.message_foreground_sound       = load_sound(self.sound_system, "message_foreground.ogg")
        # Message sent confirmation sound
        self.message_sent_sound             = load_sound(self.sound_system, "message_sent.ogg")

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
                        hash_token = hash_token.replace("/", "_").replace("+", "-")
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
        self.token = token.replace("/", "_").replace("+", "-")

    def prepare_sync(self):
        os.makedirs(data_path(), exist_ok=True)
        self._media_failed_lock = threading.Lock()
        self._media_failed_ids  = self._load_media_failed_ids()
        self.generate_secret_key()
        self.key = self.retrieve_secret_key()
        self.create_basic_files()

        # Initialise DatabaseBridge (async→sync bridge)
        self.db = DatabaseBridge(data_path("messages.db"), self.key)
        # Load persistent metadata from database with fallback/bootstrap from settings.json
        settings_dirty = False
        
        # 1. presence_pushname_map
        if self.db.get_metadata("presence_pushname_map") is None and "presence_pushname_map" in self.settings:
            self._presence_pushname_map = dict(self.settings.pop("presence_pushname_map", {}))
            self.db.set_metadata_json("presence_pushname_map", self._presence_pushname_map)
            settings_dirty = True
        else:
            self._presence_pushname_map = dict(self.db.get_metadata_json("presence_pushname_map", {}))
            
        # 2. deleted_chats
        if self.db.get_metadata("deleted_chats") is None and "deleted_chats" in self.settings:
            self._deleted_chats = set(self.settings.pop("deleted_chats", []))
            self.db.set_metadata_json("deleted_chats", list(self._deleted_chats))
            settings_dirty = True
        else:
            self._deleted_chats = set(self.db.get_metadata_json("deleted_chats", []))
            
        # 3. archived_chats
        if self.db.get_metadata("archived_chats") is None and "archived_chats" in self.settings:
            self._archived_chats = set(self.settings.pop("archived_chats", []))
            self.db.set_metadata_json("archived_chats", list(self._archived_chats))
            settings_dirty = True
        else:
            self._archived_chats = set(self.db.get_metadata_json("archived_chats", []))
            
        # 4. pinned_chats
        if self.db.get_metadata("pinned_chats") is None and "pinned_chats" in self.settings:
            self._pinned_chats = set(self.settings.pop("pinned_chats", []))
            self.db.set_metadata_json("pinned_chats", list(self._pinned_chats))
            settings_dirty = True
        else:
            self._pinned_chats = set(self.db.get_metadata_json("pinned_chats", []))
            
        # 5. muted_chats
        if self.db.get_metadata("muted_chats") is None and "muted_chats" in self.settings:
            self._muted_chats = dict(self.settings.pop("muted_chats", {}))
            self.db.set_metadata_json("muted_chats", self._muted_chats)
            settings_dirty = True
        else:
            self._muted_chats = dict(self.db.get_metadata_json("muted_chats", {}))
            
        if settings_dirty:
            self.save_settings()
        # Run migration from messages.dat → SQLite if needed
        try:
            if self.db.run_migration():
                logging.info("[startup] Migration from messages.dat to SQLite completed")
        except Exception as exc:
            logging.error("[startup] Migration failed: %s", exc)

        #Get Local Chats
        self.chats = self.get_chats()
        self._load_local_lid_cache()
        # Build cache first so deduplicate_chats() can use it as a fallback
        # for @lid chats whose messages carry no remoteJidAlt bridge field.
        self._build_lid_to_phone_cache()
        self.chats = self.deduplicate_chats(self.chats)
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_contacts()
        self._clean_contacts_cached()
        # One-time migration: slim bloated quoted-message payloads already stored
        # in messages.dat by older versions (full thumbnails / mediaKeys / URLs),
        # which made conversations with many replies slow to open. Runs now that
        # chats, contacts and the LID caches are all loaded, so the debounced
        # save persists the complete record set.
        if prune_chats_messages(self.chats):
            logging.info("[startup] pruned bloated quoted-message data from messages.dat")
            self._schedule_save()
        self.scan_all_cached_messages_for_mentions()
        self.connected_sound.play()
        # Reset per-session sync guard so on_messages_set() can start a fresh
        # sync.  Without this, _sync_completed stays True from the previous
        # session and messages.set never triggers start_sync() again.
        self._sync_completed = False
        # In-memory store for status/story updates received via WebSocket.
        # Keys are sender JIDs; values are lists of normalized message dicts.
        self._status_updates: dict = {}
        # Reset so the 60-s fallback and on_messages_set() can fire.
        # The flag persisted as True across restarts, blocking re-sync on
        # reconnection when the WPPConnect doesn't re-send messages.set.
        self.messages_set_completed = False
        self.wait_messages_set()
        self.start_connection_health_checker()

    def start_connection_health_checker(self):
        """Periodically verify session health and auto-restart Puppeteer if closed."""
        def _loop():
            # Wait a bit after startup before starting checks
            time.sleep(30)
            while True:
                try:
                    if not getattr(self, "_wa_connected", False) and not getattr(self, "offline_mode", False):
                        logging.info("[health_checker] Connection down. Checking session status on API server...")
                        self.check_wa_connection_http()
                except Exception as e:
                    logging.warning(f"[health_checker] Error checking connection in background: {e}")
                time.sleep(30)

        threading.Thread(target=_loop, daemon=True).start()

    def check_wa_connection_http(self):
        """Query the WPPConnect API via HTTP to check if the instance is already connected to WhatsApp."""
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/status-session"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code in (401, 403):
                logging.warning("[check_wa_connection_http] Token is unauthorized (HTTP %s). Triggering logout.", response.status_code)
                self.error_sound.play()
                wx.MessageBox(
                    self.i18n.t("device_logged_out"),
                    self.i18n.t("error").format(app_name=self.app_name),
                    wx.OK | wx.ICON_ERROR,
                )
                self._on_disconnect()
                return

            if response.status_code in (200, 201):
                data = response.json()
                # WPPConnect /status-session returns {"status": "CONNECTED"} — the key is
                # "status", not "state".  Reading "state" always yields "" which incorrectly
                # triggers /start-session even when a session is already alive.
                status = (
                    data.get("status")
                    or data.get("state")
                    or data.get("response", {}).get("status")
                    or data.get("response", {}).get("state")
                    or ""
                )

                logging.info("[check_wa_connection_http] Instance status: %s", status)

                # Robust check: Only call start-session if the instance is explicitly CLOSED, DESTROYED, or completely inactive.
                # WPPConnect status values include: CONNECTED, open, INITIALIZING, QRCODE, PHONECODE, notLogged, inChat, PAIRED, etc.
                if status in ("CONNECTED", "open"):
                    self._wa_connected = True
                    try:
                        dev_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/host-device"
                        dev_resp = requests.get(dev_url, headers=headers, timeout=5)
                        if dev_resp.status_code in (200, 201):
                            dev_data = dev_resp.json()
                            phoneNumberObj = dev_data.get("response", {}).get("phoneNumber", {})
                            wuid = ""
                            if isinstance(phoneNumberObj, dict):
                                wuid = phoneNumberObj.get("_serialized", "")
                            elif isinstance(phoneNumberObj, str):
                                wuid = phoneNumberObj
                            if wuid:
                                self.my_jid = wuid
                                self.resolve_self_lid()
                                # Mark as paired on successful HTTP host check too
                                pi = self.settings.setdefault("privateinfo", {})
                                if not pi.get("paired"):
                                    pi["paired"] = True
                                    self.save_settings()
                    except Exception as e:
                        logging.error("[check_wa_connection_http] Failed to fetch host device JID: %s", e)
                elif status in ("CLOSED", "DESTROYED", ""):
                    # Status is CLOSED or unknown: safe to start a new session.
                    # But skip if the connection dialog is currently open (pairing in progress)
                    # to avoid spawning a duplicate Chrome alongside the one the pairing flow manages.
                    if getattr(self.connect, 'connection_dial', None) and self.connect.connection_dial.IsShown() if hasattr(self.connect, 'connection_dial') and self.connect.connection_dial else False:
                        logging.info("[check_wa_connection_http] Skipping auto-start — pairing dialog is active.")
                    else:
                        try:
                            start_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/start-session"
                            requests.post(start_url, json={"waitQrCode": False}, headers=headers, timeout=10)
                            logging.info("[check_wa_connection_http] Sent auto-start session command")
                        except Exception as e:
                            logging.error("[check_wa_connection_http] Failed to auto-start session: %s", e)
                else:
                    # Instance is in some active state (e.g. notLogged, inChat, QRCODE, INITIALIZING, etc.)
                    # We should NOT call start-session to avoid launching duplicate Puppeteer tabs.
                    logging.info(
                        "[check_wa_connection_http] Session is in active state '%s' — skipping /start-session to avoid browser conflict.",
                        status,
                    )
        except Exception as e:
            logging.error("[check_wa_connection_http] Error checking connection state: %s", e)

    def trigger_sync_if_needed(self):
        # Trigger sync only if it hasn't completed, isn't already running, and we are connected.
        if getattr(self, "_wa_connected", False) and not getattr(self, "_sync_completed", False) and not getattr(self, "_initial_sync_running", False):
            logging.info("[trigger_sync_if_needed] WhatsApp connected and sync is incomplete. Triggering sync thread...")
            self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
            self.sync_thread.start()

    def start_sync(self):
        # Block until init_UI() completes.  This prevents wx.CallAfter calls
        # below from referencing panels that don't exist yet (which happens when
        # the websocket failed and ShowModal() is still blocking init_UI()).
        if not self._ui_ready_event.wait(timeout=120):
            return  # UI never initialized; bail out silently

        self._initial_sync_running = True
        try:
            self._run_sync()
        except Exception:
            logging.exception("[start_sync] Unhandled error during sync")
        finally:
            # Always clear the tray/status text and the running flag, even if
            # something above raised — otherwise an error mid-sync leaves the
            # tray stuck on "preparing to sync" / "synchronizing" forever,
            # since none of those status calls are inside a try/finally and a
            # thread that dies mid-sync never reaches its own clear-status line.
            self._initial_sync_running = False
            wx.CallAfter(self._set_status, "")

    def _run_sync(self):
        logging.info("[start_sync] Waiting for WhatsApp connection before syncing...")
        self.check_wa_connection_http()
        waited = 0
        while waited < 30:
            if getattr(self, "_wa_connected", False):
                break
            time.sleep(1)
            waited += 1
        if not getattr(self, "_wa_connected", False):
            logging.warning("[start_sync] Sync starting without active WhatsApp connection (timeout).")

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
            wx.CallAfter(self._set_status, self.i18n.t("preparing_to_sync"))
            time.sleep(_CHAT_DELAY)
        self.chats = self.normalize_chats(self.chats)

        # Quick initial contacts fetch — may be incomplete on first QR pairing
        # because WhatsApp delivers contacts to the WPPConnect concurrently
        # with messages.  We'll do a second, definitive fetch after messages are
        # synced (by then the API has received all contacts from WhatsApp).
        self.get_remote_contacts()

        self.synchronizing_sound.play()
        wx.CallAfter(self._set_status, self.i18n.t("synchronizing"))
        if not self.background_mode:
            self.output(self.i18n.t("synchronization_started"), interrupt=True)

        # ── Start background resolving of unknown LIDs ──────────────────
        self.start_background_lid_resolution()

        # Show the contact list immediately from get_remote_chats() metadata
        # (name, pushName, unreadCount) so the user is not staring at a blank
        # screen while the per-chat message sync runs below.
        # Build the LID cache first (background is fine here — sync thread).
        self._build_lid_to_phone_cache()
        wx.CallAfter(self.set_chats)

        # ── Phase 1: sync all messages ────────────────────────────────────
        self.sync_remote_chats()

        # After messages are loaded, remoteJidAlt bridge fields are available
        # so @lid ↔ @s.whatsapp.net duplicates (introduced because the API
        # returned both JID formats before messages were fetched) can now be
        # fully resolved and merged.
        self.chats = self.deduplicate_chats(self.chats)

        # Re-resolve group names that were still empty right after pairing.
        # WPPConnect doesn't have every group's metadata (subject) cached
        # immediately after a fresh pairing — group-info lookups made during
        # the initial fast chat-list fetch can come back empty. By now the
        # (much slower) per-chat message sync above has given WPPConnect time
        # to receive that metadata from WhatsApp, so retry once here before
        # the chat list is shown, instead of leaving the group stuck on the
        # generic "unknown group" placeholder for the rest of the session.
        self._resolve_missing_group_names()

        # Re-fetch contacts now that sync_remote_chats() has finished.  The
        # message sync takes long enough that by this point the WPPConnect
        # has received all contacts from WhatsApp — solving the first-pairing
        # issue where names were missing because the initial fetch was too early.
        self.get_remote_contacts()

        # Conversations are fully sorted as soon as messages are synced.
        # Sort, display, play sync-complete sound, and announce to the user
        # NOW — before the slower media-download phase begins.
        # Rebuild the LID cache first so the chat list shows correct names.
        self._build_lid_to_phone_cache()
        wx.CallAfter(self.set_chats)
        wx.CallAfter(self.preselect_conversations)
        self.sync_complete_sound.play()
        wx.CallAfter(self._set_status, "")
        if not self.background_mode:
            self.output(self.i18n.t("sync_complete"))

        # ── Phase 2: download media (silent) ──────────────────────────────
        wx.CallAfter(self._set_status, self.i18n.t("downloading_media"))
        self._media_sync_running = True
        try:
            self.sync_media_for_all_chats()
        finally:
            self._media_sync_running = False
        wx.CallAfter(self._set_status, "")
        # Final refresh so any media-resolved previews appear in the list.
        wx.CallAfter(self.set_chats)

        # Start periodic background contacts sync (every 5 minutes)
        self.start_periodic_contacts_sync()

        # Mark sync as done for this session so late-arriving messages.set
        # events (WPPConnect sends them in batches) don't restart the full
        # sync process after it already completed successfully.
        # Mark sync as done for this session ONLY if we actually had an active
        # WhatsApp connection to query new messages. If we synced while disconnected,
        # we only loaded the local cache, so keep _sync_completed = False so we can
        # trigger a real sync once WhatsApp connects.
        if len(self.chats) > 0 and getattr(self, "_wa_connected", False):
            self._sync_completed = True
        else:
            self._sync_completed = False
            # Schedule a retry in 15 seconds to see if history has loaded
            def _retry_sync():
                time.sleep(15)
                # Check if we are still connected and still have 0 chats
                if getattr(self, "_wa_connected", False) and len(self.chats) == 0:
                    logging.info("[start_sync] Retrying empty chats sync...")
                    self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
                    self.sync_thread.start()
            threading.Thread(target=_retry_sync, daemon=True).start()
        # _initial_sync_running is reset by start_sync()'s finally block.

    def wait_messages_set(self):
        self._set_status(self.i18n.t("preparing_to_sync"))
        # Fallback: WPPConnect does not emit a messages.set WebSocket event.
        # Poll the API every 5 s for up to 60 s and start sync as soon as it
        # responds.  If the API never responds within the window, start sync
        # unconditionally so the program never stays stuck on "preparing to sync".
        def _fallback():
            def _already_syncing() -> bool:
                if self.messages_set_completed:
                    return True
                existing = getattr(self, "sync_thread", None)
                if existing and existing.is_alive():
                    return True
                return getattr(self, "_sync_completed", False)

            def _probe_and_start() -> bool:
                """Probe the API for existing chats; start sync and return True if found."""
                if _already_syncing():
                    # Sync is already running or completed — clear "preparing" status
                    # if it was left visible because the sync finished before this
                    # fallback thread checked in.
                    if getattr(self, "_sync_completed", False):
                        wx.CallAfter(self._set_status, "")
                    return True
                try:
                    url = (
                        f"{self.wpp_server}:{self.wpp_port}"
                        f"/api/{self.token}/list-chats"
                    )
                    headers = {
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    }
                    r = requests.post(url, headers=headers, timeout=5)
                    if r.ok and isinstance(r.json(), list):
                        self.messages_set_completed = True
                        self.sync_thread = threading.Thread(
                            target=self.start_sync, daemon=True
                        )
                        self.sync_thread.start()
                        return True
                except Exception:
                    pass
                return False

            # Probe immediately — when the server is already connected (no
            # session-logged event fires), this avoids an unnecessary 5-second wait.
            if _probe_and_start():
                return

            for _ in range(12):   # 12 × 5 s = 60 s maximum
                time.sleep(5)
                if _probe_and_start():
                    return

            # 60 s elapsed and sync still hasn't started — start it unconditionally
            # so the program never stays stuck on "preparando para sincronizar".
            if not _already_syncing():
                self.messages_set_completed = True
                self.sync_thread = threading.Thread(
                    target=self.start_sync, daemon=True
                )
                self.sync_thread.start()
        threading.Thread(target=_fallback, daemon=True).start()

    def _store_status_update(self, msg: dict):
        """Store an incoming status/story message in _status_updates and refresh the Status tab."""
        key = msg.get("key", {})
        participant = (
            key.get("participant")
            or msg.get("participant")
            or (key.get("fromMe") and getattr(self, "my_jid", ""))
            or ""
        )
        if not participant:
            return
        if not hasattr(self, "_status_updates"):
            self._status_updates = {}
        bucket = self._status_updates.setdefault(participant, [])
        msg_id = key.get("id", "")
        if msg_id and any(m.get("key", {}).get("id") == msg_id for m in bucket):
            return  # deduplicate
        bucket.append(msg)
        # Persist the status update directly instead of going through _schedule_save()
        # (which would fall back to writing all chats when no dirty_jid is set).
        def _save_status():
            try:
                self.db.upsert_status_update(participant, msg)
            except Exception as exc:
                logging.warning("[_store_status_update] DB write failed: %s", exc)
        threading.Thread(target=_save_status, daemon=True).start()
        # Refresh the Status tab if it is currently visible
        try:
            if hasattr(self, "navigation_panel"):
                sp = getattr(self.navigation_panel, "status_panel", None)
                if sp and sp.IsShown():
                    wx.CallAfter(lambda: threading.Thread(target=sp._load_statuses, daemon=True).start())
        except Exception:
            pass

    def clear_local_data(self):
        """Wipe all cached chats, contacts, messages, media, and mapping caches to avoid cross-account leakage."""
        logging.info("[clear_local_data] Clearing all local caches, media, and database...")
        self.chats = {}
        self.contacts = {}
        self._status_updates = {}
        if hasattr(self, "_lid_to_phone"):
            self._lid_to_phone.clear()
        else:
            self._lid_to_phone = {}
        if hasattr(self, "_phone_to_lid"):
            self._phone_to_lid.clear()
        else:
            self._phone_to_lid = {}
        if hasattr(self, "_unresolvable_lids"):
            self._unresolvable_lids.clear()
        else:
            self._unresolvable_lids = set()
        if hasattr(self, "_unresolvable_names"):
            self._unresolvable_names.clear()
        else:
            self._unresolvable_names = set()
        if hasattr(self, "_unresolvable_names"):
            self._unresolvable_names.clear()
        else:
            self._unresolvable_names = set()
        if hasattr(self, "_resolving_lids"):
            self._resolving_lids.clear()
        else:
            self._resolving_lids = set()
            
        try:
            if hasattr(self, "db") and self.db is not None:
                self.db.save_full_state({"chats": {}, "contacts": {}})
                logging.info("[clear_local_data] Database cleared successfully.")
        except Exception as e:
            logging.error(f"[clear_local_data] Failed to clear database: {e}")
            
        # Clear local downloaded media files to prevent cross-account leakage
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

    def create_basic_files(self):
        data_dir = data_path("")
        os.makedirs(data_dir, exist_ok=True)

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

    def get_chat(self, jid: str) -> dict | None:
        """Get a chat from self.chats by JID, with fallback to mapped JID (LID/phone)."""
        if not jid:
            return None
        chat = self.chats.get(jid)
        if chat is not None:
            return chat
        # Fallback to mapped JID
        alt_jid = ""
        if jid.endswith("@lid"):
            alt_jid = getattr(self, "_lid_to_phone", {}).get(jid, "")
        else:
            alt_jid = getattr(self, "_phone_to_lid", {}).get(jid, "")
        if alt_jid:
            return self.chats.get(alt_jid)
        return None

    def get_chats(self, limit: int = 5):
        try:
            return self.db.get_chats(limit=limit)
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_load_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            return {}

    def get_remote_chats(self, chats):
        # Use the modern `list-chats` endpoint (WPP.chat.list) instead of the
        # deprecated `all-chats` (legacy WAPI.getAllChats). The legacy call omits
        # some chats — notably muted or pinned groups — so those never got
        # collected on pairing. An empty POST body returns every chat.
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/list-chats"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # Retry up to 3 times with a fixed timeout and a short sleep between
        # attempts so we don't hammer the API server during startup.
        _RETRY_SLEEP = 5   # seconds between retries
        _TIMEOUT     = 120  # seconds per request
        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(url, json={}, headers=headers, timeout=_TIMEOUT)
                if response.status_code not in (200, 201):
                    logging.error(
                        "[get_remote_chats] API error %s (attempt %d/3): %s",
                        response.status_code, attempt + 1, response.text[:200],
                    )
                    last_error = f"HTTP {response.status_code}"
                    if attempt < 2:
                        logging.info("[get_remote_chats] Retrying in %ds...", _RETRY_SLEEP)
                        time.sleep(_RETRY_SLEEP)
                        continue
                    break
                try:
                    resp_text = response.text.strip() if response.text else ""
                    if not resp_text or resp_text == "undefined" or resp_text == "null":
                        logging.warning("[get_remote_chats] Server returned empty or undefined response.")
                        body = []
                    else:
                        body = response.json()
                except Exception as json_err:
                    logging.error(
                        "[get_remote_chats] Failed to parse JSON (attempt %d/3): %s. Body: %s",
                        attempt + 1, json_err, response.text[:200],
                    )
                    last_error = json_err
                    if attempt < 2:
                        logging.info("[get_remote_chats] Retrying in %ds...", _RETRY_SLEEP)
                        time.sleep(_RETRY_SLEEP)
                        continue
                    break

                # list-chats returns the array directly; tolerate the legacy
                # {"response": [...]} envelope too in case of a mixed deployment.
                if isinstance(body, list):
                    response_data = body
                elif isinstance(body, dict):
                    response_data = body.get("response", [])
                else:
                    response_data = []
                if not isinstance(response_data, list):
                    response_data = []

                # Traduzir as chaves do WPPConnect (remoteJid)
                for chat in response_data:
                    if not isinstance(chat, dict):
                        continue
                    wpp_id = chat.get("id")
                    jid_str = wpp_id.get("_serialized") if isinstance(wpp_id, dict) else wpp_id
                    if jid_str:
                        chat["remoteJid"] = jid_str.replace("@c.us", "@s.whatsapp.net")

                # Diagnostic log to inspect chat keys
                lid_chats = [c for c in response_data if isinstance(c, dict) and c.get("remoteJid", "").endswith("@lid")]
                if lid_chats:
                    logging.info(f"[get_remote_chats] RAW LID CHAT KEYS: {list(lid_chats[0].keys())}")
                    logging.info(f"[get_remote_chats] RAW LID CHAT DATA: {lid_chats[0]}")

                deleted = set(self.settings.get("deleted_chats", []))
                cleared = self.settings.get("cleared_chats", {})

                for chat in response_data:
                    if not isinstance(chat, dict):
                        continue
                    jid = self._normalize_jid(chat.get("remoteJid", ""))

                    # Try to extract JID mapping from lastMessage if present
                    last_msg = chat.get("lastMessage")
                    if isinstance(last_msg, dict):
                        key = last_msg.get("key")
                        if isinstance(key, dict):
                            remote = key.get("remoteJid", "")
                            alt = key.get("remoteJidAlt", "")
                            if remote and alt:
                                if remote.endswith("@lid") and alt.endswith("@s.whatsapp.net"):
                                    if not hasattr(self, "_lid_to_phone"):
                                        self._lid_to_phone = {}
                                    if not hasattr(self, "_phone_to_lid"):
                                        self._phone_to_lid = {}
                                    if self._lid_to_phone.get(remote) != alt:
                                        self._lid_to_phone[remote] = alt
                                        self._phone_to_lid[alt] = remote
                                        logging.info(f"[LID Mapping] Extracted mapping from lastMessage in get_remote_chats: {remote} <-> {alt}")
                                elif alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                                    if not hasattr(self, "_lid_to_phone"):
                                        self._lid_to_phone = {}
                                    if not hasattr(self, "_phone_to_lid"):
                                        self._phone_to_lid = {}
                                    if self._lid_to_phone.get(alt) != remote:
                                        self._lid_to_phone[alt] = remote
                                        self._phone_to_lid[remote] = alt
                                        logging.info(f"[LID Mapping] Extracted mapping from lastMessage in get_remote_chats (alt): {alt} <-> {remote}")

                    # Skip status@broadcast — statuses are shown in the Status tab
                    if not jid or jid.endswith("@broadcast"):
                        continue
                    # Populate/update self.contacts from chat name metadata
                    if jid and not jid.endswith("@g.us"):
                        name = chat.get("name")
                        pushName = chat.get("pushName")
                        if looks_like_binary_blob(name):
                            name = None
                        if looks_like_binary_blob(pushName):
                            pushName = None
                        if jid not in self.contacts:
                            self.contacts[jid] = {"id": jid, "remoteJid": jid}
                        if name:
                            self.contacts[jid]["name"] = name
                        if pushName:
                            self.contacts[jid]["pushName"] = pushName

                        phone_jid = getattr(self, "_lid_to_phone", {}).get(jid)
                        if phone_jid:
                            if phone_jid not in self.contacts:
                                self.contacts[phone_jid] = {"id": phone_jid, "remoteJid": phone_jid}
                            if name:
                                self.contacts[phone_jid]["name"] = name
                            if pushName:
                                self.contacts[phone_jid]["pushName"] = pushName

                        lid_jid = getattr(self, "_phone_to_lid", {}).get(jid)
                        if lid_jid:
                            if lid_jid not in self.contacts:
                                self.contacts[lid_jid] = {"id": lid_jid, "remoteJid": lid_jid}
                            if name:
                                self.contacts[lid_jid]["name"] = name
                            if pushName:
                                self.contacts[lid_jid]["pushName"] = pushName

                    if jid.endswith("@lid"):
                        phone_jid = getattr(self, "_lid_to_phone", {}).get(jid)
                        if phone_jid and phone_jid in chats:
                            continue
                    if jid in deleted:
                        continue
                    if jid.endswith("@lid"):
                        phone_jid = getattr(self, "_lid_to_phone", {}).get(jid)
                        if phone_jid and phone_jid in deleted:
                            continue
                    if not jid.endswith("@lid"):
                        lid_jid = getattr(self, "_phone_to_lid", {}).get(jid)
                        if lid_jid and lid_jid in deleted:
                            continue
                    if jid in cleared:
                        continue
                    # WPPConnect's list-chats returns every entry in WhatsApp's
                    # internal ChatStore, which includes 1:1 "phantom" chats the
                    # user never actually messaged (e.g. address-book contacts
                    # WhatsApp matched but no conversation ever started with).
                    # Real chats always carry a last-activity timestamp ("t"),
                    # a last message, or unread messages; entries with none of
                    # these are not real conversations and would otherwise
                    # pollute the chat list and the forward-message picker.
                    # Groups are exempt: a freshly-joined group can legitimately
                    # have none of these yet.
                    if jid not in chats and not jid.endswith("@g.us"):
                        has_activity = (
                            bool(chat.get("t"))
                            or bool(chat.get("lastMessage"))
                            or bool(chat.get("unreadCount"))
                        )
                        if not has_activity:
                            continue
                    if jid not in chats:
                        if "messages" not in chat:
                            chat["messages"] = {"messages": {"records": []}}
                        chat["remoteJid"] = jid
                        if jid.endswith("@g.us"):
                            name = chat.get("name") or chat.get("subject") or ""
                            if not name or name.strip() == "":
                                name = getattr(self, "_group_name_cache", {}).get(jid, "")
                                if not name or name.strip() == "":
                                    name = self._fill_group_name(jid)
                            chat["name"] = name
                        chats[jid] = chat
                    else:
                        for k, v in chat.items():
                            if k in ("messages", "remoteJid"):
                                continue
                            if k == "pushName" and jid.endswith("@g.us"):
                                continue
                            if k == "name" and jid.endswith("@g.us") and not v:
                                v = chat.get("subject", "")
                            # Don't let the server overwrite a positive local
                            # unreadCount with zero — the local counter may have
                            # incremented since the server snapshot was taken.
                            # But always accept a server-reported positive value
                            # so that newly-arrived unread chats show up.
                            if k == "unreadCount":
                                server_val = int(v or 0)
                                local_val = int(chats[jid].get("unreadCount") or 0)
                                # During startup sync (before messages_set_completed is True),
                                # WPPConnect often returns 0 unreadCount because WhatsApp Web has
                                # not fully finished syncing chats from the phone yet.
                                # Keep the local count to prevent startup wipe of unread badges.
                                if server_val == 0 and local_val > 0 and not getattr(self, "messages_set_completed", False):
                                    continue
                            chats[jid][k] = v
                        # WPPConnect may return the group name only in "subject".
                        # If the existing entry still has no name, pull it from subject.
                        if jid.endswith("@g.us") and not chats[jid].get("name"):
                            subj = chats[jid].get("subject", "")
                            if subj:
                                chats[jid]["name"] = subj
                                self._group_name_cache = getattr(self, "_group_name_cache", {})
                                self._group_name_cache[jid] = subj

                # Sync mute and pin state from server into DB metadata
                now = int(time.time())
                db_changed = False
                for chat in response_data:
                    if not isinstance(chat, dict):
                        continue
                    raw_jid = chat.get("remoteJid", "")
                    if not raw_jid:
                        continue
                    jid = self._normalize_jid(raw_jid)
                    if "muteExpiration" in chat:
                        mute_expiry = chat["muteExpiration"]
                        if mute_expiry == -1 or (isinstance(mute_expiry, (int, float)) and mute_expiry > now):
                            if self._muted_chats.get(jid) != int(mute_expiry):
                                self._muted_chats[jid] = int(mute_expiry)
                                db_changed = True
                        elif jid in self._muted_chats:
                            del self._muted_chats[jid]
                            db_changed = True

                    # Check if the JID starts with "0@" (official WhatsApp/system account)
                    is_system = jid.startswith("0@")
                    
                    # Parse and clean pin values to prevent bool() truthiness bug on non-standard fields
                    pin_val = chat.get("pin")
                    if isinstance(pin_val, str):
                        if pin_val.lower() == "true":
                            pin_val = True
                        elif pin_val.lower() == "false":
                            pin_val = False
                        else:
                            try:
                                pin_val = float(pin_val)
                            except ValueError:
                                pin_val = None

                    is_pinned = False
                    if not is_system:
                        if isinstance(pin_val, bool):
                            is_pinned = pin_val
                        elif isinstance(pin_val, (int, float)):
                            is_pinned = pin_val > 1000000
                        


                    if is_pinned:
                        if jid not in self._pinned_chats:
                            self._pinned_chats.add(jid)
                            db_changed = True
                        # Also pin the alternate JID if present
                        if jid.endswith("@lid"):
                            alt = getattr(self, "_lid_to_phone", {}).get(jid, "")
                            if alt:
                                alt_norm = self._normalize_jid(alt)
                                if alt_norm not in self._pinned_chats:
                                    self._pinned_chats.add(alt_norm)
                                    db_changed = True
                        else:
                            alt = getattr(self, "_phone_to_lid", {}).get(jid, "")
                            if alt:
                                if alt not in self._pinned_chats:
                                    self._pinned_chats.add(alt)
                                    db_changed = True
                    elif jid in self._pinned_chats:
                        self._pinned_chats.remove(jid)
                        db_changed = True
                        # Also remove pin from the alternate JID if present
                        if jid.endswith("@lid"):
                            alt = getattr(self, "_lid_to_phone", {}).get(jid, "")
                            if alt:
                                alt_norm = self._normalize_jid(alt)
                                if alt_norm in self._pinned_chats:
                                    self._pinned_chats.remove(alt_norm)
                                    db_changed = True
                        else:
                            alt = getattr(self, "_phone_to_lid", {}).get(jid, "")
                            if alt:
                                if alt in self._pinned_chats:
                                    self._pinned_chats.remove(alt)
                                    db_changed = True

                if db_changed and hasattr(self, "db") and self.db is not None:
                    self.db.set_metadata_json("muted_chats", self._muted_chats)
                    self.db.set_metadata_json("pinned_chats", list(self._pinned_chats))

                # Retroactively prune 1:1 phantom chats that slipped into the
                # local cache before this filter existed: no local messages,
                # no server-reported activity, and not deliberately pinned or
                # muted by the user.
                response_jids = {
                    self._normalize_jid(c.get("remoteJid", ""))
                    for c in response_data if isinstance(c, dict)
                }
                for stale_jid in list(chats.keys()):
                    if stale_jid.endswith("@g.us"):
                        continue
                    if stale_jid not in response_jids:
                        continue
                    if stale_jid in self._pinned_chats or stale_jid in self._muted_chats:
                        continue
                    stale_chat = chats[stale_jid]
                    has_messages = bool(
                        stale_chat.get("messages", {}).get("messages", {}).get("records")
                    )
                    if has_messages:
                        continue
                    has_activity = (
                        bool(stale_chat.get("t"))
                        or bool(stale_chat.get("lastMessage"))
                        or bool(stale_chat.get("unreadCount"))
                    )
                    if not has_activity:
                        del chats[stale_jid]

                self.save_data(chats, self.contacts)
                return chats
            except Exception as e:
                last_error = e
                logging.warning("[get_remote_chats] Attempt %d/3 failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(_RETRY_SLEEP)
                    continue
            else:
                break

        if last_error:
            wx.CallAfter(self.error_sound.play)
            wx.CallAfter(
                wx.MessageBox,
                f"{self.i18n.t('chat_retrieval_failed')} {last_error}",
                self.i18n.t("error").format(app_name=self.app_name),
                wx.OK | wx.ICON_ERROR,
            )

    def normalize_chats(self, chats):
        db_changed = False
        normalized = {}
        for key, chat in chats.items():
            if key.endswith("@newsletter") or chat.get("remoteJid", "").endswith("@newsletter"):
                continue
            if chat.get("unreadCount") is None:
                chat["unreadCount"] = 0
            is_arch = (
                chat.get("archived") is True 
                or chat.get("archive") is True
                or str(chat.get("archived")).lower() == "true"
                or str(chat.get("archive")).lower() == "true"
            )
            if is_arch:
                if key not in self._archived_chats:
                    self._archived_chats.add(key)
                    db_changed = True
            normalized[key] = chat
        if db_changed and hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("archived_chats", list(self._archived_chats))
        return normalized

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

        # ── Pass 0: merge phantom "self-referential" chats ────────────────────
        # WPPConnect/Baileys occasionally reports a self-chat send (seen with
        # text, audio and documents) tagged with an identity that isn't our
        # real phone JID — either a group whose JID is built from a
        # participant's own @lid number with "@g.us" swapped in for "@lid",
        # a group JID that's simply our own phone number, or the bare,
        # not-yet-resolved @lid itself left over from before
        # resolve_self_lid() completed (see on_new_message() for the same
        # detection applied to live traffic). No real WhatsApp group JID is
        # ever numerically identical to one of its own participants' JIDs or
        # to a plain phone number — group IDs come from an entirely
        # different, longer ID space — so either digit overlap alone
        # identifies the artifact. Merge its records into the real
        # self-chat and drop it, instead of leaving an unnamed phantom
        # chat that duplicates messages already stored under "Eu" and
        # can't be reliably deleted (any other chat cleared out by the same
        # buggy delete would be a side effect of this same bogus entry, not
        # a separate bug).
        my_jid = getattr(self, "my_jid", "")
        if my_jid:
            my_jid_digits = my_jid.split("@", 1)[0]
            candidate_jids = [
                j for j in list(chats.keys())
                if j.endswith("@g.us") or j.endswith("@lid")
            ]
            for cand_jid in candidate_jids:
                cand_chat = chats.get(cand_jid)
                if cand_chat is None:
                    continue
                cand_digits = cand_jid.split("@", 1)[0]
                records = cand_chat.get("messages", {}).get("messages", {}).get("records", [])
                is_self_referential = any(
                    r.get("key", {}).get("fromMe")
                    and r.get("key", {}).get("participant", "").split("@", 1)[0] == cand_digits
                    and (cand_jid.endswith("@g.us") or self._phone_digits_equivalent(cand_digits, my_jid_digits))
                    for r in records
                    if r.get("key", {}).get("participant")
                )
                is_self_phone_group = (
                    cand_jid.endswith("@g.us")
                    and self._phone_digits_equivalent(cand_digits, my_jid_digits)
                )
                if not (is_self_referential or is_self_phone_group):
                    continue
                if my_jid in chats:
                    dst_records = (
                        chats[my_jid]
                        .setdefault("messages", {})
                        .setdefault("messages", {})
                        .setdefault("records", [])
                    )
                    _merge_records(dst_records, records)
                else:
                    cand_chat["remoteJid"] = my_jid
                    chats[my_jid] = cand_chat
                del chats[cand_jid]

        # ── Pass 0b: merge duplicate self-chat digit variants ────────────────
        # Even without any group/participant artifact, WhatsApp sometimes
        # reports our own self-chat messages under the "other" Brazilian
        # 9th-digit variant of our number for a given event (the matching
        # normalisation for live traffic is in on_new_message()) — e.g.
        # sending a photo to yourself as a document created one "Eu" chat
        # for the real document echo and a second "Eu" chat, under the
        # other digit variant, for a sync-artifact echo of the same send.
        # Merge any such leftover duplicate into the canonical my_jid entry.
        if my_jid:
            for other_jid in [
                j for j in list(chats.keys())
                if j != my_jid and j.endswith("@s.whatsapp.net") and self._is_self_jid(j)
            ]:
                other_chat = chats.get(other_jid)
                if other_chat is None:
                    continue
                records = other_chat.get("messages", {}).get("messages", {}).get("records", [])
                if my_jid in chats:
                    dst_records = (
                        chats[my_jid]
                        .setdefault("messages", {})
                        .setdefault("messages", {})
                        .setdefault("records", [])
                    )
                    _merge_records(dst_records, records)
                else:
                    other_chat["remoteJid"] = my_jid
                    chats[my_jid] = other_chat
                del chats[other_jid]

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
        temp_cache = {}
        for jid_key, chat_obj in chats.items():
            for msg in chat_obj.get("messages", {}).get("messages", {}).get("records", []):
                key    = msg.get("key", {})
                remote = key.get("remoteJid", "")
                alt    = key.get("remoteJidAlt", "")
                if alt and alt.endswith("@s.whatsapp.net"):
                    if remote.endswith("@lid"):
                        temp_cache[remote] = alt
                    participant = key.get("participant", "")
                    if participant.endswith("@lid"):
                        temp_cache[participant] = alt
                elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                    temp_cache[alt] = remote

        lid_jids = [j for j in list(chats.keys()) if j.endswith("@lid")]
        for lid_jid in lid_jids:
            if lid_jid not in chats:
                continue
            lid_chat = chats[lid_jid]
            alt_jid  = self._find_alt_jid_from_messages(lid_chat) or temp_cache.get(lid_jid)
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
                
                # Merge unread counts
                unread_dst = int(chats[alt_jid].get("unreadCount") or 0)
                unread_src = int(lid_chat.get("unreadCount") or 0)
                chats[alt_jid]["unreadCount"] = unread_dst + unread_src
            else:
                # Only the @lid version exists — rename it to @s.whatsapp.net
                lid_chat["remoteJid"] = alt_jid
                chats[alt_jid] = lid_chat
            del chats[lid_jid]
            
            # Redirect active conversation if it was the merged LID chat
            if hasattr(self, "conversations_panel") and self.conversations_panel.conversation:
                active_jid = self.conversations_panel.conversation.get("remoteJid", "")
                if active_jid == lid_jid:
                    self.conversations_panel.conversation = chats[alt_jid]
                    wx.CallAfter(self.conversations_panel.populate_messages, preserve_focus=True)

        return chats

    def _fill_group_name(self, jid: str) -> str:
        """Fetch group info from API and cache the name.

        Called lazily when a group has no cached name. Returns the group
        name or empty string on failure.
        """
        try:
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/group-info/{jid}"
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.ok:
                body = resp.json()
                info = body.get("response", body) if isinstance(body, dict) else {}
                name = info.get("name") or info.get("subject", "")
                if name:
                    if not hasattr(self, "_group_name_cache"):
                        self._group_name_cache = {}
                    self._group_name_cache[jid] = name
                    return name
        except Exception:
            pass
        return ""

    def _resolve_group_name_async(self, jid: str):
        """Look up a newly-seen group's name in the background.

        _fill_group_name() does a blocking HTTP request, so this must not run
        on the wx main thread (on_new_message is called via wx.CallAfter).
        """
        def _worker():
            name = self._fill_group_name(jid)
            if not name:
                return
            chat = self.chats.get(jid)
            if chat is None or (chat.get("name") or chat.get("subject") or "").strip():
                return
            chat["name"] = name
            self._schedule_save(dirty_jid=jid)
            wx.CallAfter(self._schedule_set_chats)
        threading.Thread(target=_worker, daemon=True).start()

    def _resolve_missing_group_names(self):
        """Retry group-info lookups for groups still unnamed after sync.

        Runs on the background sync thread. Uses a few parallel workers so a
        large number of unresolved groups doesn't add much wall-clock time to
        the sync.
        """
        unresolved = [
            jid for jid, chat in list(self.chats.items())
            if jid.endswith("@g.us") and not (chat.get("name") or chat.get("subject") or "").strip()
        ]
        if not unresolved:
            return
        max_workers = min(6, len(unresolved))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(self._fill_group_name, jid): jid for jid in unresolved}
            for fut in as_completed(futs):
                jid = futs[fut]
                try:
                    name = fut.result()
                except Exception:
                    name = ""
                if name:
                    self.chats[jid]["name"] = name
                    self._schedule_save(dirty_jid=jid)

    def save_data(self, chats, contacts):
        """Write chat+contact data to SQLite via DatabaseBridge.

        Protected by _save_lock so concurrent callers never write at the
        same time.  Replaces the old messages.dat blob with a transactional
        full-state import.
        """
        with self._save_lock:
            try:
                lid_to_phone = getattr(self, "_lid_to_phone", {})
                unresolvable_lids = list(getattr(self, "_unresolvable_lids", set()))
                unresolvable_names = list(getattr(self, "_unresolvable_names", set()))
                # Incremental upsert — never clear the DB during normal saves.
                # Full-clear is only used by clear_local_data() for account reset.
                self.db.save_full_state({
                    "chats": dict(chats),
                    "contacts": dict(contacts),
                    "lid_to_phone": dict(lid_to_phone),
                    "unresolvable_lids": unresolvable_lids,
                    "unresolvable_names": unresolvable_names,
                    "status_updates": {
                        k: list(v) for k, v in
                        getattr(self, "_status_updates", {}).items()
                    }
                }, clear_first=False)
            except Exception:
                self.error_sound.play()
                wx.CallAfter(
                    wx.MessageBox,
                    f"{self.i18n.t('data_save_failed')} {format_exc()}",
                    self.i18n.t("error").format(app_name=self.app_name),
                    wx.OK | wx.ICON_ERROR,
                )

    def _do_save(self):
        """Timer callback: incrementally persist dirty chats and contacts.

        Uses targeted upsert_chat() / upsert_contacts_batch() instead of the
        old save_data() full dump.  This avoids re-encrypting every message
        blob on every save — the dominant source of idle CPU usage.
        """
        # ── 1. Dirty chats ────────────────────────────────────────────────────
        dirty_chats: set[str] = set(getattr(self, "_dirty_jids_for_save", None) or set())
        self._dirty_jids_for_save = set()

        # Only save explicitly dirty chats.  The old "save all as fallback"
        # behaviour wrote every chat on every unrelated event (e.g. mark-as-read,
        # status updates), causing 1-second DB writes even during idle operation.
        for jid in dirty_chats:
            chat = self.chats.get(jid)
            if not chat:
                continue
            try:
                self.db.upsert_chat(jid, chat)
            except Exception as exc:
                logging.warning("[_do_save] upsert_chat %s: %s", jid, exc)

        # ── 2. Contacts (only when explicitly marked dirty) ───────────────────
        if getattr(self, "_contacts_dirty_for_save", False):
            self._contacts_dirty_for_save = False
            try:
                self.db.upsert_contacts_batch(dict(self.contacts))
            except Exception as exc:
                logging.warning("[_do_save] upsert_contacts_batch: %s", exc)

    def _schedule_save(
        self,
        dirty_jid: "str | None" = None,
        contacts_dirty: bool = False,
    ) -> None:
        """Debounce DB saves into one write per burst.

        Parameters
        ----------
        dirty_jid :
            JID of the specific chat that changed.  When supplied, only that
            chat is written to the DB (fast).  When omitted, all chat metadata
            is saved (slower but still far cheaper than a full import_from_dict).
        contacts_dirty :
            Set to True to also flush self.contacts to the contacts table.
        """
        if not hasattr(self, "_dirty_jids_for_save"):
            self._dirty_jids_for_save = set()
        if dirty_jid:
            self._dirty_jids_for_save.add(dirty_jid)
        else:
            # No specific JID given — the caller wants the full chat set
            # persisted (see docstring). _do_save() only writes JIDs found
            # in _dirty_jids_for_save, so without this the "save everything"
            # call was silently a no-op (e.g. resolved group names and
            # mark-as-unread never reached disk).
            self._dirty_jids_for_save.update(self.chats.keys())
        if contacts_dirty:
            self._contacts_dirty_for_save = True
        with self._save_timer_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            t = threading.Timer(0.15, self._do_save)
            t.daemon = True
            self._save_timer = t
            t.start()

    def _load_local_lid_cache(self):
        try:
            self._lid_to_phone = self.db.get_lid_mappings()
            self._phone_to_lid = {v: k for k, v in self._lid_to_phone.items()}
            lids, names = self.db.get_unresolvable_lids()
            self._unresolvable_lids = lids
            self._unresolvable_names = names
            self._status_updates = self.db.get_status_updates()
            logging.info(f"[LID Cache] Loaded {len(self._lid_to_phone)} JID mappings, {len(self._unresolvable_lids)} LIDs, {len(self._unresolvable_names)} names, and status updates for {len(self._status_updates)} participants.")
            return
        except Exception as e:
            logging.error(f"[LID Cache] Error loading JID mappings from database: {e}")
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self._unresolvable_lids = set()
        self._unresolvable_names = set()

    def get_contacts(self):
        try:
            return self.db.get_contacts()
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_load_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            return {}

    @staticmethod
    def _is_bad_contact_name(name: str) -> bool:
        if not name or not isinstance(name, str):
            return True
        name = name.strip()
        if not name or name.isdigit() or is_phone_like(name) or looks_like_binary_blob(name):
            return True
        val_lower = name.lower()
        return "sem nome" in val_lower or "unnamed" in val_lower or val_lower in ("no name", "unknown", "desconhecido")

    def _clean_contacts_cached(self):
        changed = False
        for jid, contact in list(self.contacts.items()):
            for field in ("name", "pushName"):
                val = contact.get(field)
                if self._is_bad_contact_name(val):
                    if field in contact:
                        del contact[field]
                        changed = True
            if not contact.get("name") and not contact.get("pushName"):
                contact["name"] = ""
        if changed and hasattr(self, "db"):
            self.db.upsert_contacts_batch(self.contacts)

    def get_remote_contacts(self):
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/all-contacts"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
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
                    name = contact.get("name") or contact.get("pushName") or ""
                    if not name or name == "Contato sem nome" or is_phone_like(name):
                        name = ""
                    contact = dict(contact)
                    contact["remoteJid"] = jid
                    contact["name"] = name
                    contact["pushName"] = name
                    
                    if jid not in self.contacts:
                        logging.debug(f"[get_remote_contacts] Adding contact: {name} ({jid})")
                        self.contacts[jid] = contact
                    else:
                        updated_fields = []
                        for k, v in contact.items():
                            if v is not None and v != "":
                                if self.contacts[jid].get(k) != v:
                                    self.contacts[jid][k] = v
                                    updated_fields.append(k)
                        if updated_fields:
                            logging.debug(f"[get_remote_contacts] Updated fields {updated_fields} for contact: {name} ({jid})")
                    contacts[jid] = self.contacts[jid]
            self._schedule_save(contacts_dirty=True)
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
                        wx.CallAfter(self._schedule_set_chats)
                except Exception as e:
                    print(f"[periodic_contacts_sync] error: {e}")

        threading.Thread(target=_loop, daemon=True).start()

    @staticmethod
    def _phone_digits_equivalent(a: str, b: str) -> bool:
        """Compare two bare digit strings, tolerating the Brazilian 9th-digit
        variant (55DDD9XXXXXXXX vs 55DDDXXXXXXXX) so a self/contact match
        isn't missed just because one side carries the extra digit.
        """
        if a == b:
            return True
        if a.startswith("55") and b.startswith("55"):
            if len(a) == 13 and len(b) == 12 and a[4] == "9":
                return a[:4] + a[5:] == b
            if len(b) == 13 and len(a) == 12 and b[4] == "9":
                return b[:4] + b[5:] == a
        return False

    def self_reference_label(self) -> str:
        """Return the word used for the user's own messages/replies in the
        messages list ("Eu"/"Você"/a custom word), per the "Como se referir
        a mim?" setting. Does not affect the self-chat's own name (still
        always self_chat_name, "Eu (mensagens para mim)") — only the sender
        label shown next to your own messages and quoted-reply headers.
        """
        ui = self.settings.get("user_interface", {})
        mode = ui.get("self_reference_mode", "eu")
        if mode == "voce":
            return self.i18n.t("ui_self_reference_voce")
        if mode == "custom":
            word = (ui.get("self_reference_custom_word") or "").strip()
            if word:
                return word
        return self.i18n.t("sender_you")

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
        if self._phone_digits_equivalent(_phone_part(compare), _phone_part(my_jid)):
            return True
        my_lid = getattr(self, "my_lid", "")
        if my_lid and _phone_part(compare) == _phone_part(my_lid):
            return True
        return False

    def _compute_chat_lists(self):
        """Compute sorted/filtered chat lists. Safe to run on a background thread."""
        deleted  = self._deleted_chats
        archived = self._archived_chats
        pinned   = self._pinned_chats
        my_jid   = getattr(self, "my_jid", "")

        # Dedup: if both a @lid JID and its corresponding phone JID exist as
        # separate keys in self.chats, only render the one with more content
        # (prefer @lid since that's the active WPPConnect chat). Build a set of
        # phone JIDs that are already covered by a @lid entry so we can skip them.
        lid_to_phone = getattr(self, "_lid_to_phone", {})
        phone_to_lid = getattr(self, "_phone_to_lid", {})
        _covered_by_lid: set[str] = set()
        for lid_jid, phone_jid in lid_to_phone.items():
            if lid_jid in self.chats and phone_jid in self.chats:
                # Both exist — keep the one with more messages (usually lid).
                lid_msgs = len(self.chats[lid_jid].get("messages", {}).get("messages", {}).get("records", []))
                phone_msgs = len(self.chats[phone_jid].get("messages", {}).get("messages", {}).get("records", []))
                if lid_msgs >= phone_msgs:
                    _covered_by_lid.add(phone_jid)
                else:
                    _covered_by_lid.add(lid_jid)

        main_chats, main_names = [], []
        arch_chats, arch_names = [], []

        for jid, chat in list(self.chats.items()):
            if jid in deleted:
                continue
            if jid in _covered_by_lid:
                continue  # duplicate – already shown via the other JID

    
            records_wrapper = chat.get("messages") or {}
            records = []
            if isinstance(records_wrapper, dict):
                inner_wrapper = records_wrapper.get("messages") or {}
                if isinstance(inner_wrapper, dict):
                    records = inner_wrapper.get("records") or []
            last_msg  = chat.get("lastMessage")
            unread    = int(chat.get("unreadCount", 0) or 0)
            is_pinned = jid in pinned
            # Skip chats with absolutely no content AND no identity.
            # We do NOT skip based on missing messages alone: during and just
            # after sync many valid chats have empty records but still carry a
            # name/pushName from the WPPConnect list-chats response.
            has_content  = bool(records or last_msg or unread > 0 or is_pinned)
            name_hint    = (chat.get("name") or chat.get("pushName") or
                            chat.get("subject") or "").strip()
            has_identity = bool(name_hint and not name_hint.isdigit() and len(name_hint) > 1)
            if not has_content and not has_identity:
                continue
                
            def get_valid_name(val):
                if not val or not isinstance(val, str):
                    return ""
                val = val.strip()
                if not val or val.isdigit() or is_phone_like(val):
                    return ""
                if looks_like_binary_blob(val):
                    return ""
                val_lower = val.lower()
                if "sem nome" in val_lower or "unnamed" in val_lower or val_lower in ("no name", "unknown", "desconhecido"):
                    return ""
                return val

            if jid.endswith("@lid"):
                phone_jid = getattr(self, "_lid_to_phone", {}).get(jid) or self._find_alt_jid_from_messages(chat)
            else:
                phone_jid = jid
            
            is_group = jid.endswith("@g.us")
            resolved_name = ""
            msg_push = ""
        
            if is_group:
                # Check both "name" and "subject" — WPPConnect uses either field
                # depending on API version; prefer "name", fall back to "subject".
                name = get_valid_name(chat.get("name", "") or chat.get("subject", ""))
                if not name:
                    cached = getattr(self, "_group_name_cache", {}).get(jid, "")
                    if cached:
                        name = cached
                    else:
                        fetched = self._fill_group_name(jid)
                        if fetched:
                            chat["name"] = fetched
                            name = fetched
            else:
                # Chat individual: usar a lógica existente
                resolved_name = self._resolve_contact_name(chat)
                chat_push = get_valid_name(chat.get("pushName", ""))
                name = resolved_name or chat_push
                if not name:
                    msg_push = self.find_name_through_messages(chat)
                    name = msg_push or get_valid_name(chat.get("name", ""))
            
            if not name or not name.strip():
                if jid.endswith("@g.us"):
                    name = self.i18n.t("unknown_group")
                else:
                    if phone_jid and not phone_jid.endswith("@lid"):
                        name = format_number(phone_jid)
                    else:
                        msg_jid_num = self.find_jid_through_messages(chat)
                        if msg_jid_num:
                            name = msg_jid_num
                        elif self._format_jid_for_display(jid):
                            name = self._format_jid_for_display(jid)
                        elif jid.endswith("@lid"):
                            # Unresolved @lid: show placeholder, never format as phone
                            name = self.i18n.t("unknown_contact")
                        else:
                            numeric = jid.split("@")[0].split(":")[0]
                            if numeric.isdigit():
                                name = format_number(numeric)
                            else:
                                name = self.i18n.t("unknown_contact")
            
            # Detailed logging for name resolution debugging
            if jid.endswith("@lid") or name == self.i18n.t("unknown_contact"):
                logging.debug(
                    f"[Name Resolution] jid={jid} phone_jid={phone_jid} "
                    f"resolved_name={resolved_name} "
                    f"msg_name={msg_push} "
                    f"chat_name={chat.get('name')} push_name={chat.get('pushName')} -> final_name='{name}'"
                )
            if my_jid and not jid.endswith("@g.us") and self._is_self_jid(jid):
                name = self.i18n.t("self_chat_name")
            is_archived = (
                jid in archived 
                or chat.get("archived") is True 
                or chat.get("archive") is True
                or str(chat.get("archived")).lower() == "true"
                or str(chat.get("archive")).lower() == "true"
            )
            if is_archived:
                arch_chats.append(chat)
                arch_names.append(name)
            else:
                main_chats.append(chat)
                main_names.append(name)

        # Pinned chats float to the top; within each group sort by most-recent
        # message timestamp descending (newest first), then alphabetically.
        def _chat_last_ts(c):
            lm = c.get("lastMessage")
            has_messages = False
            ts = 0
            
            if isinstance(lm, dict):
                lm_ts = int(lm.get("timestamp", 0) or lm.get("messageTimestamp", 0) or lm.get("t", 0) or 0)
                if lm_ts > 1_000_000_000_000:
                    lm_ts //= 1000
                ts = lm_ts
                has_messages = True
                
            records_wrapper = c.get("messages") or {}
            if isinstance(records_wrapper, dict):
                inner_wrapper = records_wrapper.get("messages") or {}
                if isinstance(inner_wrapper, dict):
                    records_copy = list(inner_wrapper.get("records") or [])
                    if records_copy:
                        has_messages = True
                        for m in records_copy:
                            if isinstance(m, dict):
                                t = int(m.get("timestamp", 0) or m.get("messageTimestamp", 0) or m.get("t", 0) or 0)
                                if t > 1_000_000_000_000:
                                    t //= 1000
                                if t > ts:
                                    ts = t
                                    
            if not has_messages:
                return 1
            return ts if ts else 1

        def _sort_key(pair):
            c, n = pair
            j   = c.get("remoteJid", "")
            pin = 0 if j in pinned else 1
            return (pin, -_chat_last_ts(c), n.lower())

        pairs = sorted(zip(main_chats, main_names), key=_sort_key)
        main_chats = [c for c, _ in pairs]
        main_names = [n for _, n in pairs]

        arch_pairs = sorted(zip(arch_chats, arch_names), key=_sort_key)
        arch_chats = [c for c, _ in arch_pairs]
        arch_names = [n for _, n in arch_pairs]

        return main_chats, main_names, arch_chats, arch_names

    def _apply_chat_lists(self, main_chats, main_names, arch_chats, arch_names):
        """Apply sorted chat lists to panels and refresh UI. Must run on main thread."""
        if not hasattr(self, "conversations_panel"):
            return  # UI not yet initialized; skip silently
        self.chat_names = main_names

        # Save focused JIDs from the CURRENT (old) displayed lists BEFORE
        # overwriting chats_list.  add_chats_to_ui() maps focused_idx (from
        # the live ListCtrl) against chats_list to recover the JID — but
        # chats_list is about to be replaced with a reordered copy, so
        # focused_idx would point to the wrong chat after the assignment.
        _panel = self.conversations_panel
        _fi = _panel.conversations_list.GetFocusedItem()
        _panel._preserved_focused_jid = (
            _panel.chats_list[_fi].get("remoteJid")
            if 0 <= _fi < len(_panel.chats_list) else None
        )
        if hasattr(self, "archived_conversations_panel"):
            _ap = self.archived_conversations_panel
            _afi = _ap.conversations_list.GetFocusedItem()
            _ap._preserved_focused_jid = (
                _ap.chats_list[_afi].get("remoteJid")
                if 0 <= _afi < len(_ap.chats_list) else None
            )

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

    def set_chats(self):
        # NOTE: _build_lid_to_phone_cache() is intentionally NOT called here.
        # It scans every message in every chat (O(chats × messages)) and is
        # too expensive to run on the wx main thread. The cache is built once
        # at startup (in init_chats) and then maintained incrementally by
        # _extract_lid_mapping() on each new message.
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
                # _build_lid_to_phone_cache() is intentionally NOT called here.
                # It scans every message in every chat (O(total_messages)) and is
                # too expensive to run on every WebSocket event.  The cache is
                # maintained incrementally by _extract_lid_mapping() on each new
                # message, and rebuilt in full only at startup (set_chats calls).
                result = self._compute_chat_lists()
                wx.CallAfter(self._apply_chat_lists, *result)
            except Exception:
                logging.exception("[_do_scheduled_set_chats] Unhandled error during scheduled set_chats")
        threading.Thread(target=_bg, daemon=True).start()

    def _build_lid_to_phone_cache(self):
        """
        Build self._lid_to_phone: a dict mapping @lid JIDs to @s.whatsapp.net
        JIDs by scanning remoteJidAlt fields across all loaded chat messages.

        WPPConnect v2 normalises the key before emitting the WebSocket event:
          OLD format: remoteJid=@lid,          remoteJidAlt=@s.whatsapp.net
          NEW format: remoteJid=@s.whatsapp.net, remoteJidAlt=@lid  (after swap)
        Both formats are handled here so the cache is populated regardless of
        which version of the API produced the stored messages.
        """
        cache = getattr(self, "_lid_to_phone", {}).copy()
        for chat in list(self.chats.values()):
            for msg in list(chat.get("messages", {}).get("messages", {}).get("records", [])):
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

    def _extract_lid_mapping(self, msg):
        """Extract JID mapping from a message object and update cache & persist if new."""
        if not isinstance(msg, dict):
            return
        key = msg.get("key")
        if not isinstance(key, dict):
            return
        remote = self._normalize_jid(key.get("remoteJid", ""))
        alt = self._normalize_jid(key.get("remoteJidAlt", ""))
        participant = self._normalize_jid(key.get("participant", ""))

        # Invalidate the negative cache since a new message is added to this chat
        if remote and hasattr(self, "_chats_without_alt_jid"):
            self._chats_without_alt_jid.discard(remote)

        # Cache pushName if present in the message
        push_name = msg.get("pushName")
        if push_name and remote and not remote.endswith("@g.us") and not is_phone_like(push_name):
            if not hasattr(self, "_message_pushname_cache"):
                self._message_pushname_cache = {}
            self._message_pushname_cache[remote] = push_name

        # Guard against corrupt self-mappings: if any JID is ours, block cross-mapping with others
        if self._is_self_jid(remote) or self._is_self_jid(alt) or self._is_self_jid(participant):
            if alt and (self._is_self_jid(remote) != self._is_self_jid(alt)):
                alt = ""
            if participant and (self._is_self_jid(remote) != self._is_self_jid(participant)):
                participant = ""

        updated = False
        # Initialize dictionary if not present
        if not hasattr(self, "_lid_to_phone"):
            self._lid_to_phone = {}
        if not hasattr(self, "_phone_to_lid"):
            self._phone_to_lid = {}

        if alt and alt.endswith("@s.whatsapp.net"):
            if remote.endswith("@lid") and self._lid_to_phone.get(remote) != alt:
                self._lid_to_phone[remote] = alt
                self._phone_to_lid[alt] = remote
                updated = True
                logging.info(f"[LID Mapping] Extracted mapping from message key: {remote} <-> {alt}")
        elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
            if self._lid_to_phone.get(alt) != remote:
                self._lid_to_phone[alt] = remote
                self._phone_to_lid[remote] = alt
                updated = True
                logging.info(f"[LID Mapping] Extracted mapping from message key (alt): {alt} <-> {remote}")
                
        # Direct mapping between remote (LID) and participant (phone) for 1:1 chats
        # ONLY if the message is NOT fromMe (if fromMe is True, participant is the user, and remote is the contact!)
        if not key.get("fromMe", False):
            if remote.endswith("@lid") and participant.endswith("@s.whatsapp.net"):
                if self._lid_to_phone.get(remote) != participant:
                    self._lid_to_phone[remote] = participant
                    self._phone_to_lid[participant] = remote
                    updated = True
                    logging.info(f"[LID Mapping] Extracted mapping from 1:1 chat key: {remote} <-> {participant}")
            elif remote.endswith("@s.whatsapp.net") and participant.endswith("@lid"):
                if self._lid_to_phone.get(participant) != remote:
                    self._lid_to_phone[participant] = remote
                    self._phone_to_lid[remote] = participant
                    updated = True
                    logging.info(f"[LID Mapping] Extracted mapping from 1:1 chat key (reversed): {participant} <-> {remote}")

        if updated:
            # Propagate contact details from phone contact to LID contact to make it immediately available
            contacts_to_update = {}
            for lid, phone in list(self._lid_to_phone.items()):
                if phone in self.contacts and self.contacts[phone]:
                    if lid not in self.contacts or self.contacts[lid].get("name") in (None, "", "Contato sem nome"):
                        self.contacts[lid] = self.contacts[phone].copy()
                        self.contacts[lid]["id"] = lid
                        self.contacts[lid]["remoteJid"] = lid
                        contacts_to_update[lid] = self.contacts[lid]

            # Save mapping and updated contacts incrementally
            try:
                for lid, phone in list(self._lid_to_phone.items()):
                    self.db.set_lid_mapping(lid, phone)
                if contacts_to_update:
                    self.db.upsert_contacts_batch(contacts_to_update)
            except Exception as e:
                logging.error(f"[LID Mapping] Incremental save in _extract_lid_mapping failed: {e}")
                self.save_data(self.chats, self.contacts)

            wx.CallAfter(self._schedule_set_chats)

        # Extract mentions and resolve in background if they are not in mapping/contacts
        msg_obj = msg.get("message") or {}
        ext = msg_obj.get("extendedTextMessage") or {}
        mentioned = (
            (msg.get("contextInfo") or {}).get("mentionedJid")
            or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
            or ext.get("contextInfo", {}).get("mentionedJid")
            or []
        )
        if isinstance(mentioned, list):
            lids_to_resolve = []
            phone_jids_to_resolve = []
            for jid in mentioned:
                if not isinstance(jid, str):
                    continue
                if jid.endswith("@lid"):
                    if jid not in getattr(self, "_lid_to_phone", {}):
                        lids_to_resolve.append(jid)
                elif jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us"):
                    normalized = self._normalize_jid(jid)
                    contact = self.contacts.get(normalized)
                    name = ""
                    if contact:
                        name = (contact.get("name") or contact.get("pushName") or "").strip()
                    if not name or name == "Contato sem nome" or is_phone_like(name):
                        phone_jids_to_resolve.append(jid)

            if lids_to_resolve:
                logging.info(f"[LID Mapping] Found unresolved mentioned LIDs in message: {lids_to_resolve}")
                def resolve_in_bg():
                    self.resolve_lid_jids_via_api(lids_to_resolve)
                threading.Thread(target=resolve_in_bg, daemon=True).start()

            if phone_jids_to_resolve:
                logging.info(f"[Contact Resolution] Found unresolved mentioned phone JIDs in message: {phone_jids_to_resolve}")
                def resolve_phones_in_bg():
                    updated_contacts = {}
                    for p_jid in phone_jids_to_resolve:
                        try:
                            res = self.get_contact_profile(p_jid)
                            if res:
                                res_data = res.get("response", {})
                                if isinstance(res_data, dict):
                                    name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                                    if name and name != "Contato sem nome" and not is_phone_like(name):
                                        normalized = self._normalize_jid(p_jid)
                                        if normalized not in self.contacts:
                                            self.contacts[normalized] = {}
                                        self.contacts[normalized]["name"] = name
                                        self.contacts[normalized]["pushName"] = name
 
                                        if not hasattr(self, "_presence_pushname_map"):
                                            self._presence_pushname_map = {}
                                        self._presence_pushname_map[normalized] = name
                                        updated_contacts[normalized] = self.contacts[normalized]
                        except Exception as e:
                            logging.error(f"[Contact Resolution] Error resolving {p_jid}: {e}")
                    if updated_contacts:
                        try:
                            self.db.upsert_contacts_batch(updated_contacts)
                        except Exception as e:
                            logging.error(f"[Contact Resolution] Error saving contacts incrementally: {e}")
                            self.save_data(self.chats, self.contacts)
                        wx.CallAfter(self._schedule_set_chats)
                        if hasattr(self, "conversations_panel"):
                            wx.CallAfter(self.conversations_panel.refresh_active_conversation_messages)
                threading.Thread(target=resolve_phones_in_bg, daemon=True).start()

    def scan_all_cached_messages_for_mentions(self):
        """Scan all cached messages in self.chats, find all unresolved LIDs/phones, and resolve them."""
        def _scan():
            time.sleep(3)  # Wait for startup to stabilize
            logging.info("[Mentions Scan] Starting scan of all cached messages...")
            
            lids_to_resolve = set()
            phones_to_resolve = set()
            
            # 1. Collect JID mappings and mentions
            chats_snapshot = list(self.chats.values())
            for chat in chats_snapshot:
                records = chat.get("messages", {}).get("messages", {}).get("records", [])
                for msg in list(records):
                    if not isinstance(msg, dict):
                        continue
                    # First, see if we can extract immediate JID mappings from key/alt
                    key = msg.get("key") or {}
                    remote = key.get("remoteJid", "")
                    alt = key.get("remoteJidAlt", "")
                    participant = key.get("participant", "")
                    
                    if alt and alt.endswith("@s.whatsapp.net"):
                        if remote.endswith("@lid") and self._lid_to_phone.get(remote) != alt:
                            self.register_jid_mapping(remote, alt)
                    elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                        if self._lid_to_phone.get(alt) != remote:
                            self.register_jid_mapping(alt, remote)

                    # Now collect mentions
                    msg_obj = msg.get("message") or {}
                    ext = msg_obj.get("extendedTextMessage") or {}
                    mentioned = (
                        (msg.get("contextInfo") or {}).get("mentionedJid")
                        or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
                        or ext.get("contextInfo", {}).get("mentionedJid")
                        or []
                    )
                    if isinstance(mentioned, list):
                        for jid in mentioned:
                            if not isinstance(jid, str):
                                continue
                            if jid.endswith("@lid"):
                                if jid not in getattr(self, "_lid_to_phone", {}):
                                    lids_to_resolve.add(jid)
                            elif jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us"):
                                normalized = self._normalize_jid(jid)
                                contact = self.contacts.get(normalized)
                                name = ""
                                if contact:
                                    name = (contact.get("name") or contact.get("pushName") or "").strip()
                                if not name or name == "Contato sem nome" or is_phone_like(name):
                                    phones_to_resolve.add(jid)
                                    
            # 2. Resolve in controlled batches
            if lids_to_resolve:
                logging.info(f"[Mentions Scan] Found {len(lids_to_resolve)} unresolved mentioned LIDs.")
                self.resolve_lid_jids_via_api(list(lids_to_resolve))
                
            if phones_to_resolve:
                logging.info(f"[Mentions Scan] Found {len(phones_to_resolve)} unresolved mentioned phone JIDs.")
                updated_contacts = {}
                for p_jid in list(phones_to_resolve):
                    try:
                         res = self.get_contact_profile(p_jid)
                         if res:
                             res_data = res.get("response", {})
                             if isinstance(res_data, dict):
                                 name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                                 if name and name != "Contato sem nome" and not is_phone_like(name):
                                     normalized = self._normalize_jid(p_jid)
                                     if normalized not in self.contacts:
                                         self.contacts[normalized] = {}
                                     self.contacts[normalized]["name"] = name
                                     self.contacts[normalized]["pushName"] = name
                                     if not hasattr(self, "_presence_pushname_map"):
                                         self._presence_pushname_map = {}
                                     self._presence_pushname_map[normalized] = name
                                     updated_contacts[normalized] = self.contacts[normalized]
                         time.sleep(0.1)  # Rate limiting
                    except Exception as e:
                         logging.error(f"[Mentions Scan] Error resolving phone {p_jid}: {e}")
                if updated_contacts:
                     try:
                         self.db.upsert_contacts_batch(updated_contacts)
                     except Exception as e:
                         logging.error(f"[Mentions Scan] Error saving contacts incrementally: {e}")
                         self.save_data(self.chats, self.contacts)
                     wx.CallAfter(self._schedule_set_chats)
                     if hasattr(self, "conversations_panel"):
                         wx.CallAfter(self.conversations_panel.refresh_active_conversation_messages)
            
            logging.info("[Mentions Scan] Scan and resolution of cached messages completed.")

        threading.Thread(target=_scan, daemon=True).start()

    def _find_alt_jid_from_messages(self, chat):
        """
        Find the canonical @s.whatsapp.net phone JID for a chat by scanning its
        message keys.  Handles both WPPConnect v2 key formats and normalises
        any @c.us JIDs encountered to @s.whatsapp.net on the fly:

          OLD: remoteJid=@lid,   remoteJidAlt=@s.whatsapp.net|@c.us → return alt (normalised)
          NEW: remoteJid=phone,  remoteJidAlt=@lid                  → return remoteJid
        Returns the phone JID (@s.whatsapp.net) string, or None if not found.
        """
        jid = chat.get("remoteJid", "")
        if not jid:
            return None

        if not hasattr(self, "_chats_without_alt_jid"):
            self._chats_without_alt_jid = set()

        if jid in self._chats_without_alt_jid:
            return None

        def _norm(j: str) -> str:
            if not j:
                return j
            if j.endswith("@c.us"):
                j = j[:-5] + "@s.whatsapp.net"
            if ":" in j:
                parts = j.split("@")
                if len(parts) == 2:
                    j = parts[0].split(":")[0] + "@" + parts[1]
            return j

        # Copy records list to avoid RuntimeError due to concurrent modifications
        records_copy = list(chat.get("messages", {}).get("messages", {}).get("records", []))
        for msg in records_copy:
            key    = msg.get("key", {})
            remote = _norm(key.get("remoteJid", ""))
            alt    = _norm(key.get("remoteJidAlt", ""))
            # alt is the phone JID, remote is @lid (OLD format)
            if alt and alt.endswith("@s.whatsapp.net"):
                self.register_jid_mapping(jid, alt)
                return alt
            # remote is the phone JID, alt is @lid (NEW post-swap format)
            if remote and remote.endswith("@s.whatsapp.net") and alt and alt.endswith("@lid"):
                self.register_jid_mapping(alt, remote)
                return remote

        self._chats_without_alt_jid.add(jid)
        return None

    def _format_jid_for_display(self, jid: str) -> str:
        """
        Format a JID as a phone number for display, resolving @lid to its mapped
        phone number when known. A raw @lid (an internal 15+ digit identifier)
        must NEVER be shown as a phone number, so when no mapping exists this
        returns "" and the caller falls back to a generic placeholder.
        """
        if not jid:
            return ""
        if jid.endswith("@lid"):
            phone = getattr(self, "_lid_to_phone", {}).get(jid, "")
            return format_number(phone) if phone else ""
        if jid.endswith("@g.us"):
            return ""
        return format_number(jid)

    def _resolve_contact_name(self, chat):
        """
        Return the saved contact name (contact.pushName) for a private chat, or None.

        Tries all three JID formats (@s.whatsapp.net, @c.us, @lid) and returns
        the first valid pushName found.  Groups are skipped (always return None).
        Falls back to the presence-learned pushName map for @lid contacts.
        """
        remoteJid = chat.get("remoteJid", "")
        if not remoteJid or remoteJid.endswith("@g.us"):
            return None  # groups don't have address-book entries

        def _name_from_contact(c):
            # Prefer the address-book name ('name') over the WhatsApp profile
            # name ('pushName').  Both fields may be absent or a bare phone
            # number — reject those in either case.
            for field in ("name", "pushName"):
                val = c.get(field)
                if val and isinstance(val, str):
                    val = val.strip()
                    if val and not val.isdigit() and not is_phone_like(val) and not looks_like_binary_blob(val):
                        # Reject placeholder names (e.g. "Contato sem nome")
                        val_lower = val.lower()
                        if "sem nome" in val_lower or "unnamed" in val_lower or val_lower in ("no name", "unknown", "desconhecido"):
                            logging.info(f"[LID Mapping] Rejecting placeholder name '{val}' for contact JID '{c.get('id') or c.get('remoteJid')}'")
                            continue
                        return val
            return None

        ppm = getattr(self, "_presence_pushname_map", {})

        def _get_contact_tolerant(jid):
            if not jid:
                return None
            if ":" in jid:
                parts = jid.split("@")
                if len(parts) == 2:
                    jid = parts[0].split(":")[0] + "@" + parts[1]
            c = self.contacts.get(jid)
            if c:
                return c
            # Brazilian number 9-digit tolerance fallback
            if jid.endswith("@s.whatsapp.net"):
                phone = jid.split("@")[0]
                if phone.startswith("55"):
                    if len(phone) == 13 and phone[4] == "9":
                        # e.g., 5511999999999 -> try 551199999999
                        alt = phone[:4] + phone[5:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
                    elif len(phone) == 12:
                        # e.g., 551199999999 -> try 5511999999999
                        alt = phone[:4] + "9" + phone[4:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
            return None

        def _try(jid: str) -> str:
            if not jid:
                return ""
            c = _get_contact_tolerant(jid)
            if c:
                return _name_from_contact(c) or ""
            return ""

        def _ppm(jid: str) -> str:
            val = (ppm.get(jid) or "").strip()
            return val if val and not val.isdigit() and not is_phone_like(val) else ""

        local = remoteJid.rsplit("@", 1)[0]
        resolved = ""
        if remoteJid.endswith("@s.whatsapp.net"):
            resolved = (
                _try(remoteJid)
                or _try(local + "@c.us")
                or _try(getattr(self, "_phone_to_lid", {}).get(remoteJid, ""))
                or _ppm(remoteJid)
            )
        elif remoteJid.endswith("@c.us"):
            phone_net = local + "@s.whatsapp.net"
            resolved = (
                _try(remoteJid)
                or _try(phone_net)
                or _try(getattr(self, "_phone_to_lid", {}).get(phone_net, ""))
                or _ppm(remoteJid)
                or _ppm(phone_net)
            )
        elif remoteJid.endswith("@lid"):
            phone = (
                getattr(self, "_lid_to_phone", {}).get(remoteJid, "")
                or self._find_alt_jid_from_messages(chat)
                or ""
            )
            resolved = (
                _try(remoteJid)
                or (phone and (_try(phone) or _try(phone.rsplit("@", 1)[0] + "@c.us")))
                or _ppm(remoteJid)
                or (phone and _ppm(phone))
            )
        else:
            resolved = _try(remoteJid)

        if resolved:
            return resolved

        # Fall back to the chat's own 'name' field
        chat_name = chat.get("name", "")
        if chat_name and isinstance(chat_name, str):
            chat_name = chat_name.strip()
            if chat_name and not chat_name.isdigit() and not is_phone_like(chat_name):
                chat_name_lower = chat_name.lower()
                if "sem nome" in chat_name_lower or "unnamed" in chat_name_lower or chat_name_lower in ("no name", "unknown", "desconhecido"):
                    pass
                else:
                    return chat_name

        return None

    def find_name_through_messages(self, chat):
        jid = chat.get("remoteJid", "")
        if not jid or jid.endswith("@g.us"):
            return None

        if not hasattr(self, "_message_pushname_cache"):
            self._message_pushname_cache = {}

        if jid in self._message_pushname_cache:
            return self._message_pushname_cache[jid]

        messages_obj = chat.get("messages") or {}
        for message in messages_obj.get("messages", {}).get("records", []):
            if message.get("key", {}).get("fromMe"):
                continue
            push = message.get("pushName", "")
            if push and not is_phone_like(push):
                self._message_pushname_cache[jid] = push
                return push
        return None

    def find_jid_through_messages(self, chat):
        messages_obj = chat.get("messages") or {}
        for message in messages_obj.get("messages", {}).get("records", []):
            if not message.get("key", {}).get("fromMe"):
                key = message.get("key", {})
                alt = key.get("remoteJidAlt", "")
                if alt and alt.endswith("@s.whatsapp.net"):
                    return format_number(alt)
                jid = key.get("remoteJid", "")
                if jid and not jid.endswith("@lid") and not jid.endswith("@g.us"):
                    return format_number(jid)
        return None

    def preselect_conversations(self):
        #Checks if window is still open
        if self.IsShown():
            lst = self.conversations_panel.conversations_list
            if lst.GetItemCount() > 0:
                # Only preselect if there is no current selection/focus
                if lst.GetFocusedItem() == -1:
                    lst.Focus(0)
                    lst.Select(0)
                    lst.EnsureVisible(0)

    def sync_remote_chats(self):
        chats = list(self.chats.values())
        if not chats:
            return
        # Parallel HTTP calls dramatically reduce sync time.  WPPConnect handles
        # concurrent requests fine; cap at 6 workers to avoid overloading it.
        max_workers = min(4, len(chats))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(self.sync_chat_messages, c.copy()): c for c in chats}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as exc:
                    jid = futs[fut].get("remoteJid", "?")
                    logging.warning("[sync_remote_chats] failed for %s: %s", jid, exc)

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
        remote_jid = self._normalize_jid(chat.get("remoteJid", ""))
        chat["remoteJid"] = remote_jid
        # Formata o JID corretamente para o WPPConnect
        # Se houver mapeamento phone -> LID, usamos o LID.
        lid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
        if lid:
            phone = lid
        elif remote_jid.endswith("@s.whatsapp.net"):
            phone = remote_jid.split("@")[0] + "@c.us"
        else:
            phone = remote_jid

        limit = int(self.settings.get("user_interface", {}).get("messages_page_size", 200))
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/get-messages/{phone}?count={limit}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # Always sync with WPPConnect API to ensure no messages are lost or missed due to stale lastMessage cache.

        all_messages = []
        api_ok = False
        # Skip API call entirely if session is known disconnected
        if getattr(self, "_wa_connected", False):
            max_retries = 12
            for attempt in range(max_retries):
                if not getattr(self, "_wa_connected", False):
                    logging.info(f"[sync_chat_messages] Connection lost during sync retry loop for {remote_jid}, aborting sync.")
                    break
                try:
                    logging.info(f"[sync_chat_messages] Querying URL: {url} for chat: {remote_jid} (attempt {attempt+1}/{max_retries})")
                    response = requests.get(url, headers=headers, timeout=30)
                    logging.info(f"[sync_chat_messages] URL: {url} returned status: {response.status_code}")
                    
                    # Alternate JID query fallback (resolves 401/TypeError or Chat not found errors)
                    if response.status_code not in (200, 201):
                        alternate_jid = ""
                        if remote_jid.endswith("@lid"):
                            resolved = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
                            if resolved:
                                alternate_jid = resolved.replace("@s.whatsapp.net", "@c.us")
                        else:
                            alt_lid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
                            if alt_lid:
                                alternate_jid = alt_lid

                        if alternate_jid and alternate_jid != phone:
                            alt_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/get-messages/{alternate_jid}?count={limit}"
                            logging.info(f"[sync_chat_messages] Primary query failed. Retrying with alternate JID {alternate_jid}...")
                            try:
                                alt_response = requests.get(alt_url, headers=headers, timeout=30)
                                if alt_response.status_code in (200, 201):
                                    response = alt_response
                                    logging.info("[sync_chat_messages] Fallback alternate JID query succeeded!")
                            except Exception as alt_e:
                                logging.warning(f"[sync_chat_messages] Fallback alternate JID query failed: {alt_e}")

                    if response.status_code in (200, 201):
                        body = response.json()
                        wpp_messages = body.get("response", []) if isinstance(body, dict) else []
                        logging.info(f"[sync_chat_messages] Fetched {len(wpp_messages)} messages from API for {remote_jid}")
                        if not isinstance(wpp_messages, list):
                            wpp_messages = []
                        for wm in wpp_messages:
                            if isinstance(wm, dict) and self.ws:
                                try:
                                    normalized = self.ws._normalize_wpp_message(wm)
                                    prune_message_record(normalized)
                                    all_messages.append(normalized)
                                except Exception as e:
                                    logging.error(f"[sync_chat_messages] Failed to normalize message in {remote_jid}: {e}")
                        api_ok = True
                        break
                    elif response.status_code in (401, 404, 500):
                        # 401 = "Error on open list" (Baileys not ready yet)
                        # 404 = session not active
                        # 500 = transient WPPConnect internal error
                        # All are retryable — wait briefly and try again.
                        logging.warning(f"[sync_chat_messages] Retryable error {response.status_code} for {remote_jid} (attempt {attempt+1}/{max_retries}): {response.text[:120]}")
                        if attempt < max_retries - 1:
                            sleep_time = min(5 * (attempt + 1), 30)
                            logging.info(f"[sync_chat_messages] Sleeping {sleep_time} seconds before attempt {attempt+2} for {remote_jid}...")
                            # Check connection repeatedly while sleeping
                            for _ in range(sleep_time):
                                if not getattr(self, "_wa_connected", False):
                                    break
                                time.sleep(1)
                        continue
                    else:
                        logging.error(f"[sync_chat_messages] API returned error status {response.status_code} for {remote_jid}: {response.text}")
                        break
                except Exception as e:
                    logging.error(f"[sync_chat_messages] failed to get messages for {remote_jid}: {e}")
                    break
        else:
            logging.info(f"[sync_chat_messages] Session disconnected, using cached messages for {remote_jid}")

        # Drop messages the user cleared (older than the clear-chat cutoff) so a
        # cleared conversation does not silently repopulate on the next sync.
        if all_messages:
            all_messages = [m for m in all_messages
                            if not self._is_cleared_message(remote_jid, m)]

        # After fetching, update chat messages
        for msg in all_messages:
            self._extract_lid_mapping(msg)
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
                          r.get("key", {}).get("id") not in api_ids
                          # Also apply the clear-chat cutoff here: local_records
                          # comes from the on-disk cache, which can still hold
                          # pre-clear messages if the app was closed before the
                          # debounced save after clear_chat_messages_local() ran.
                          # Without this check those stale records get merged
                          # right back in, making "clear chat" undone by the
                          # next sync / app restart.
                          and not self._is_cleared_message(remote_jid, r)]
            if extra:
                all_messages = all_messages + extra

        # Deduplicate: when the same message exists as both an API copy (real
        # WhatsApp ID) and a pending virtual copy (local UUID), keep the API
        # version and drop the pending one.  The hash-set approach below ensures
        # the first occurrence (API) survives, removing the pending dup.
        seen = set()
        deduped = []
        for m in all_messages:
            mid = m.get("key", {}).get("id", "")
            if mid and mid in seen:
                continue
            if mid:
                seen.add(mid)
            deduped.append(m)
        all_messages = deduped

        # Sort by timestamp so the conversation always shows the most recent
        # messages at the bottom. The user scrolls up to see older history.
        all_messages.sort(
            key=lambda m: int(
                m.get("messageTimestamp") or m.get("timestamp") or m.get("t") or 0
            )
        )

        # ── Late-arriving race-condition fix ─────────────────────────────────
        # on_historical_message() and on_new_message() run on the wx main thread
        # and may have inserted messages into self.chats[remote_jid] AFTER we
        # took the local_records snapshot above but BEFORE we write back below.
        # Do a second merge against the live chat to ensure none of those
        # messages are silently discarded by our final self.chats assignment.
        live_chat    = self.chats.get(remote_jid, {})
        live_records = (live_chat.get("messages", {})
                        .get("messages", {})
                        .get("records", []))
        if live_records:
            current_ids = {r.get("key", {}).get("id") for r in all_messages}
            late_extra  = [r for r in live_records
                           if r.get("key", {}).get("id") and
                              r.get("key", {}).get("id") not in current_ids
                              and not self._is_cleared_message(remote_jid, r)]
            if late_extra:
                all_messages = all_messages + late_extra
                # Re-sort to keep chronological order
                all_messages.sort(
                    key=lambda m: int(
                        m.get("messageTimestamp") or m.get("timestamp") or m.get("t") or 0
                    )
                )

        # Update records: accept API data only when it actually returned some
        # messages, or fall back to preserving whatever we have in memory.
        # An empty API response (200 OK with no messages) must NOT wipe the
        # cached records, otherwise conversations appear empty after sync.
        has_records = bool(chat.get("messages", {}).get("messages", {}).get("records"))
        if api_ok and all_messages:
            if "messages" not in chat:
                chat["messages"] = {}
            chat["messages"]["messages"] = {
                "total": len(all_messages),
                "pages": 1,
                "currentPage": 1,
                "records": all_messages
            }
        elif not has_records:
            if "messages" not in chat:
                chat["messages"] = {}

        self.chats[remote_jid] = chat

        if not getattr(self, "_initial_sync_running", False):
            wx.CallAfter(self._schedule_set_chats)

        # Incremental DB save: write only this chat + its messages.
        # This replaces the old save_data(self.chats, ...) call which dumped the
        # ENTIRE state (O(N) writes per chat → O(N²) total during bulk sync).
        try:
            # Don't persist a chat whose message fetch failed and which has
            # no prior local records — that would write the chat-list summary
            # (including a nonzero unreadCount) with zero messages attached,
            # permanently showing "N unread" with an empty conversation on
            # every future restart. Leave it unsaved so the next full sync
            # retries it from scratch instead.
            if api_ok or has_records:
                self.db.upsert_chat(remote_jid, chat)
            if all_messages:
                self.db.insert_messages_batch(remote_jid, all_messages)
        except Exception as exc:
            logging.warning("[sync_chat_messages] incremental DB save failed for %s: %s",
                            remote_jid, exc)

    # WhatsApp CDN URLs (mmg.whatsapp.net) expire after ~90 days.  Attempting
    # to download older media causes the WPPConnect to enter a 5-second retry
    # loop for every expired URL, which starves the API thread pool and eventually
    # breaks sends.  Never request media older than this threshold.
    _MEDIA_MAX_AGE_SECONDS = 14 * 24 * 3600  # 14 days — WhatsApp CDN typical TTL
    _MEDIA_SYNC_WORKERS    = 2               # parallel workers during bulk sync — kept
                                              # low because WPPConnect proxies every
                                              # request through a single Puppeteer/Chrome
                                              # automation session; too many concurrent
                                              # downloads were starving unrelated requests
                                              # (send-seen, contact lookups) into sporadic
                                              # "session is not active" / "chat not found"
                                              # failures even though the session was fine.
    _MEDIA_SYNC_TIMEOUT    = 60              # seconds per request during bulk sync

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

    def _is_conversation_open_for(self, msg) -> bool:
        """True if msg belongs to the conversation currently shown on screen."""
        cp = getattr(self, "conversations_panel", None)
        if cp is None or getattr(cp, "conversation", None) is None:
            return False
        open_jid = cp.conversation.get("remoteJid", "")
        if not open_jid:
            return False
        key = msg.get("key", {})
        msg_jid = self._normalize_jid(key.get("remoteJid", ""))
        return msg_jid == self._normalize_jid(open_jid)

    def sync_if_media(self, msg, timeout=60):
        """Download media for a single message during the background sync phase."""
        if not getattr(self, "_wa_connected", False) or getattr(self, "offline_mode", False):
            return
        message_type = msg.get("messageType", "")
        _MEDIA_TYPES = {"documentMessage", "imageMessage", "stickerMessage", "videoMessage"}
        if message_type not in _MEDIA_TYPES and message_type != "audioMessage":
            return

        # Skip messages older than the CDN TTL — URLs have certainly expired.
        ts = int(msg.get("messageTimestamp", 0) or 0)
        if ts and (time.time() - ts) > self._MEDIA_MAX_AGE_SECONDS:
            return

        msg_id = msg.get("key", {}).get("id", "")
        if not msg_id or "-" in msg_id or msg.get("_local_pending"):
            return

        # Skip IDs that previously returned 403/410 (expired CDN URL).
        if msg_id and msg_id in self._media_failed_ids:
            return

        try:
            if message_type == "audioMessage":
                self.handle_audio_message(msg, timeout=timeout)
            else:
                # Bulk background sync: download WITHOUT per-chunk progress
                # callbacks. Streaming 64 KB chunks across 6 workers used to fire
                # a wx.CallAfter per chunk per file — tens of thousands of UI
                # events, each doing an O(n) scan of the open conversation —
                # which froze the app while media downloaded. Only refresh the
                # row once, and only when its chat is the conversation currently
                # on screen.
                self.handle_media_message(msg, progress_callback=None, timeout=timeout)
                if msg_id and self._is_conversation_open_for(msg):
                    conv = self.conversations_panel
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
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
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

    def _check_wa_connection_closed(self, response):
        """If the WPPConnect returned a 'Connection Closed' error, mark the
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

    def _serialize_quoted_id(self, quoted: dict, fallback_jid: str = None) -> str:
        """Serialize a quoted message key into the format expected by WPPConnect.

        Delegates to _serialize_msg_id, which keeps whatever JID variant
        (@lid or phone) the message was actually keyed under in WPPConnect's
        internal store — rewriting @lid to phone here makes the lookup miss
        and the reply fail (same root cause as the media-download bug).
        """
        if not quoted or not isinstance(quoted, dict):
            return None
        raw_key = quoted.get("key", {})
        if not isinstance(raw_key, dict) or not raw_key.get("id"):
            return None
        # key.remoteJid can be empty for own messages in local cache, fallback to current conversation JID
        remote_jid = raw_key.get("remoteJid") or fallback_jid or ""
        # Swap self-JID with fallback_jid (the other person in the 1-on-1 chat) to prevent WPPConnect lookup fail
        if self._is_self_jid(remote_jid) and fallback_jid:
            remote_jid = fallback_jid
        return self._serialize_msg_id(remote_jid, raw_key)

    def _canonical_mention_jids(self, mentioned_jids):
        """Return mention JIDs in the phone-number format Baileys/WPPConnect can tag."""
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

    def _resolve_jid_for_send(self, jid: str) -> str:
        """
        Format the JID for WPPConnect API, keeping it as-is or converting to @c.us format,
        bypassing forced LID conversion to avoid HTTP 500/400 retry latencies or crashes in private chats.
        If a @lid JID is passed, translate it back to the phone JID using the cache.
        """
        if not jid:
            return jid
        jid = self._normalize_jid(jid)
        if jid.endswith(("@g.us", "@broadcast")):
            return jid
        if jid.endswith("@lid"):
            phone_net = getattr(self, "_lid_to_phone", {}).get(jid, jid)
            if phone_net:
                return phone_net.replace("@s.whatsapp.net", "@c.us")
            return jid
        if jid.endswith("@s.whatsapp.net"):
            return jid.replace("@s.whatsapp.net", "@c.us")
        return jid



    def _bg_resolve_lid_for_send(self, jid: str):
        """Background helper: resolve a single @lid and log the result."""
        try:
            self.resolve_lid_jids_via_api([jid])
        except Exception as exc:
            logging.warning("[_resolve_jid_for_send] background resolve failed for %s: %s", jid, exc)
        phone_jid = getattr(self, "_lid_to_phone", {}).get(jid, "")
        if phone_jid:
            logging.info("[_resolve_jid_for_send] Background resolved %s → %s", jid, phone_jid)
        else:
            if hasattr(self, "_unresolvable_lids"):
                self._unresolvable_lids.add(jid)
            logging.warning("[_resolve_jid_for_send] Background resolve failed for %s — marked unresolvable", jid)

    def send_text_message(self, remote_jid, text, quoted=None, mentioned_jids=None):
        """Send a plain-text message via the WPPConnect Server API."""
        # Always resolve phone JID to @lid JID if available so WPPConnect finds the open chat.
        remote_jid = self._resolve_jid_for_send(remote_jid)

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        quoted_id = None

        if mentioned_jids:
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-mentioned"
            phone_net = remote_jid
            if phone_net.endswith("@s.whatsapp.net"):
                phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
            
            mentioned = self._canonical_mention_jids(mentioned_jids)
            mentioned_clean = [m.replace("@s.whatsapp.net", "@c.us") if m.endswith("@s.whatsapp.net") else m for m in mentioned]
            
            payload = {
                "phone": [phone_net],
                "message": text,
                "mentioned": mentioned_clean,
                "isGroup": phone_net.endswith("@g.us"),
                "options": {
                    "linkPreview": False
                }
            }
        else:
            quoted_id = self._serialize_quoted_id(quoted, fallback_jid=remote_jid) if quoted else None
            if quoted_id:
                url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-reply"
                phone_net = remote_jid
                if phone_net.endswith("@s.whatsapp.net"):
                    phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
                payload = {
                    "phone": [phone_net],
                    "message": text,
                    "messageId": quoted_id,
                    "isGroup": phone_net.endswith("@g.us"),
                    "options": {
                        "linkPreview": False
                    }
                }
                logging.debug("[send_text_message] sending quoted reply via send-reply to %s, quoted key.id=%s", phone_net, quoted_id)
            else:
                phone_net = remote_jid
                if phone_net.endswith("@s.whatsapp.net"):
                    phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
                url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-message"
                payload = {
                    "phone": [phone_net],
                    "message": text,
                    "isGroup": phone_net.endswith("@g.us"),
                    "options": {
                        "linkPreview": False
                    }
                }
        try:
            # 25s (not 15s): WPPConnect can take longer to ack under load (e.g.
            # concurrent media sync). A client-side timeout here is indistinguishable
            # from a real failure to MessageQueue, which then retries — if the
            # original request actually went through server-side, that retry sends
            # a genuine duplicate message to the recipient. A more generous timeout
            # reduces how often that false-timeout/duplicate-send scenario happens.
            response = requests.post(url, json=payload, headers=headers, timeout=25)
            if response.status_code not in (200, 201):
                # 1. If it's a @lid "number not exists" error, try to resolve to phone JID first (preserving the quote)
                if response.status_code == 400 and "não existe" in response.text and remote_jid.endswith("@lid"):
                    orig_jid = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
                    if orig_jid:
                        fb_phone = orig_jid.replace("@s.whatsapp.net", "@c.us")
                        logging.warning("[send_text_message] @lid %s not loaded in browser yet — retrying with %s (cache preserved)", remote_jid, fb_phone)
                        retry_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-message"
                        if quoted_id:
                            retry_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-reply"
                            retry_payload = {
                                "phone": [fb_phone], "message": text,
                                "messageId": quoted_id, "isGroup": fb_phone.endswith("@g.us"),
                                "options": {"linkPreview": False}
                            }
                        else:
                            retry_payload = {
                                "phone": [fb_phone], "message": text,
                                "isGroup": fb_phone.endswith("@g.us"),
                                "options": {"linkPreview": False}
                            }
                        response = requests.post(retry_url, json=retry_payload, headers=headers, timeout=25)
                        if response.status_code in (200, 201):
                            logging.info("[send_text_message] Retry with %s succeeded", fb_phone)

                # 2. If it's still failing and we had a quote, strip the quote and try plain send
                if response.status_code not in (200, 201) and quoted_id:
                    logging.warning("[send_text_message] Quoted send failed (HTTP %s). Retrying without quote...", response.status_code)
                    wx.CallAfter(self.output, self.i18n.t("reply_quote_lost"))
                    url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-message"
                    fb_phone = remote_jid
                    if fb_phone.endswith("@s.whatsapp.net"):
                        fb_phone = fb_phone.replace("@s.whatsapp.net", "@c.us")
                    payload = {
                        "phone": [fb_phone],
                        "message": text,
                        "isGroup": fb_phone.endswith("@g.us"),
                        "options": {
                            "linkPreview": False
                        }
                    }
                    response = requests.post(url, json=payload, headers=headers, timeout=25)
                    # If the plain send also failed because @lid is not loaded, retry it with phone JID
                    if response.status_code == 400 and "não existe" in response.text and remote_jid.endswith("@lid"):
                        orig_jid = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
                        if orig_jid:
                            fb_phone = orig_jid.replace("@s.whatsapp.net", "@c.us")
                            logging.warning("[send_text_message] @lid %s not loaded in browser yet (plain fallback) — retrying with %s (cache preserved)", remote_jid, fb_phone)
                            retry_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-message"
                            retry_payload = {
                                "phone": [fb_phone], "message": text,
                                "isGroup": fb_phone.endswith("@g.us"),
                                "options": {"linkPreview": False}
                            }
                            response = requests.post(retry_url, json=retry_payload, headers=headers, timeout=25)

                # 3. Final error handling if all retries failed
                if response.status_code not in (200, 201):
                    err = f"HTTP {response.status_code}: {response.text[:300]}"
                    logging.error("[send_text_message] All send attempts failed: %s for %s", err, remote_jid)
                    self._check_wa_connection_closed(response)
                    # If it's a transient error, mark retryable
                    is_retryable = response.status_code in (408, 429, 500, 502, 503, 504)
                    return {"ok": False, "error": err, "retry": is_retryable}


            self._wa_connected = True
            try:
                body = response.json()
                # WPPConnect retorna a resposta dentro de 'response'
                resp = body.get("response", {})
                if isinstance(resp, list) and len(resp) > 0:
                    resp = resp[0]
                if isinstance(resp, dict):
                    msg_id = resp.get("id")
                    if isinstance(msg_id, dict):
                        msg_id = msg_id.get("_serialized", "")
                    parts = msg_id.split("_") if msg_id else []
                    clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)
                    return clean_id or True
                return True
            except Exception:
                return True
        except Exception as exc:
            err = str(exc)[:200]
            logging.error("[send_text_message] exception for %s: %s", remote_jid, err)
            return {"ok": False, "error": err, "retry": True}

    @staticmethod
    def _find_api_ffmpeg() -> str:
        """Locate ffmpeg binary: check bundled lib/ first, then node_modules, then system PATH."""
        import glob as _glob
        import shutil
        # 1. Check bundled lib/ directory first (packaged during build for remote API support)
        bundled_lib = resource_path("lib")
        for name in ["ffmpeg.exe", "ffmpeg"]:
            path = os.path.join(bundled_lib, name)
            if os.path.isfile(path):
                return path

        # 2. Bundled npm package (local API dev/run mode)
        installer_root = resource_path("api", "node_modules", "@ffmpeg-installer")
        hits = _glob.glob(os.path.join(installer_root, "**", "ffmpeg.exe"), recursive=True)
        if not hits:
            hits = _glob.glob(os.path.join(installer_root, "**", "ffmpeg"), recursive=True)
        if hits:
            return hits[0]
        # 3. Fallback: ffmpeg on the system PATH (user-installed)
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        return None

    def _convert_wav_to_ogg(self, wav_path: str) -> str | None:
        """
        Convert a WAV file to OGG/Opus using the bundled ffmpeg binary.
        Returns the path to the new .ogg file, or None on failure.
        """
        ffmpeg = self._find_api_ffmpeg()
        if not ffmpeg or not os.path.isfile(ffmpeg):
            logging.warning("[audio] ffmpeg not found — sending WAV (may fail). Searched: %s",
                            resource_path("api", "node_modules", "@ffmpeg-installer", "ffmpeg", "bin"))
            return None
        ogg_path = wav_path + ".ogg"
        try:
            creationflags = 0
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                [ffmpeg, "-y", "-i", wav_path,
                 "-ac", "1",
                 "-c:a", "libopus", "-b:a", "64k",
                 "-vbr", "on", "-compression_level", "10",
                 ogg_path],
                capture_output=True,
                timeout=60,
                creationflags=creationflags,
            )
            if result.returncode == 0 and os.path.isfile(ogg_path) and os.path.getsize(ogg_path) > 0:
                logging.debug("[audio] WAV→OGG conversion succeeded: %s", ogg_path)
                return ogg_path
            logging.error("[audio] ffmpeg WAV→OGG failed (rc=%s): %s",
                          result.returncode,
                          (result.stderr or b"").decode("utf-8", errors="replace")[-800:])
        except Exception as exc:
            logging.error("[audio] ffmpeg conversion exception: %s", exc)
        return None

    def send_audio_message(self, remote_jid: str, wav_path: str, quoted=None,
                           ogg_bytes: bytes = None) -> bool:
        """
        Encode a recorded WAV file to OGG Opus via FFmpeg (or pre-encoded ogg_bytes)
        and send it as a PTT voice message using /send-voice-base64.

        ogg_bytes: if provided (pre-encoded in background thread), skip the
                   disk read and OGG encoding entirely — just base64 + POST.
                   On retry (ogg_bytes=None) falls back to reading wav_path.
        """
        # Always resolve phone JID to @lid JID if available so WPPConnect finds the open chat.
        import time as _time
        _tsend0 = _time.perf_counter()
        remote_jid = self._resolve_jid_for_send(remote_jid)
        logging.info("[VOICE_TIMING] send_audio_message started for %s (ogg_bytes=%s) — jid resolved in %.3fs",
                     remote_jid, "yes" if ogg_bytes else "NO", _time.perf_counter() - _tsend0)

        if ogg_bytes is None:
            # Fallback path: convert WAV to OGG using ffmpeg and read the bytes
            _t_fallback = _time.perf_counter()
            logging.info("[VOICE_TIMING] ogg_bytes is None — running ffmpeg AGAIN as fallback (this should NOT happen!)")
            ogg_path = self._convert_wav_to_ogg(wav_path)
            if ogg_path and os.path.isfile(ogg_path):
                try:
                    with open(ogg_path, "rb") as fh:
                        ogg_bytes = fh.read()
                except Exception as exc:
                    logging.error("[send_audio_message] cannot read OGG file %s: %s", ogg_path, exc)
                finally:
                    try:
                        os.unlink(ogg_path)
                    except Exception:
                        pass

            if ogg_bytes is None:
                # If conversion failed, try reading WAV directly as a fallback (may fail at API level)
                logging.warning("[send_audio_message] FFmpeg conversion failed or OGG empty, trying raw WAV fallback")
                try:
                    with open(wav_path, "rb") as fh:
                        ogg_bytes = fh.read()
                except Exception as exc:
                    logging.error("[send_audio_message] cannot read WAV %s: %s", wav_path, exc)
                    return {"ok": False, "error": str(exc)[:200], "retry": False}
            logging.info("[VOICE_TIMING] fallback encode+read done in %.3fs",
                         _time.perf_counter() - _t_fallback)

        audio_b64 = base64.b64encode(ogg_bytes).decode("utf-8")

        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-voice-base64"
        phone_net = remote_jid
        if phone_net.endswith("@s.whatsapp.net"):
            phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
        quoted_id = self._serialize_quoted_id(quoted, fallback_jid=phone_net) if quoted else None
        payload = {
            "phone": [phone_net],
            "base64Ptt": f"data:audio/ogg;codecs=opus;base64,{audio_b64}",
            "isGroup": phone_net.endswith("@g.us"),
        }
        if quoted_id:
            payload["quotedMessageId"] = quoted_id
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        _t_post = _time.perf_counter()
        logging.info("[VOICE_TIMING] POSTing to send-voice-base64 (payload size ~%d bytes b64)",
                     len(audio_b64))
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            logging.info("[VOICE_TIMING] POST returned HTTP %s in %.3fs",
                         response.status_code, _time.perf_counter() - _t_post)
            if response.status_code not in (200, 201):
                err = f"HTTP {response.status_code}: {response.text[:300]}"
                logging.error("[send_audio_message] %s for %s", err, remote_jid)

                # Fallback: If the @lid returned "número não existe", the chat is just not loaded
                # in Puppeteer yet. Silently retry with the phone JID.
                if response.status_code == 400 and "não existe" in response.text and remote_jid.endswith("@lid"):
                    orig_jid = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
                    if orig_jid:
                        fb_phone = orig_jid.replace("@s.whatsapp.net", "@c.us")
                        logging.warning("[send_audio_message] @lid %s not loaded in browser yet — retrying with %s (cache preserved)", remote_jid, fb_phone)
                        retry_payload = {
                            "phone": [fb_phone],
                            "base64Ptt": f"data:audio/ogg;codecs=opus;base64,{audio_b64}",
                            "isGroup": fb_phone.endswith("@g.us"),
                        }
                        if quoted_id:
                            retry_payload["quotedMessageId"] = quoted_id
                        response = requests.post(url, json=retry_payload, headers=headers, timeout=30)
                        if response.status_code in (200, 201):
                            logging.info("[send_audio_message] Retry with %s succeeded", fb_phone)
                            # fall through to normal response parsing below
                        else:
                            err = f"HTTP {response.status_code}: {response.text[:300]}"
                            logging.error("[send_audio_message] Retry also failed: %s", err)
                            self._check_wa_connection_closed(response)
                            return {"ok": False, "error": err, "retry": True}
                    else:
                        self._check_wa_connection_closed(response)
                        return {"ok": False, "error": err, "retry": False}
                else:
                    self._check_wa_connection_closed(response)
                    return {"ok": False, "error": err, "retry": False}

            self._wa_connected = True
            try:
                body = response.json()
                resp = body.get("response", {})
                if isinstance(resp, list) and len(resp) > 0:
                    resp = resp[0]
                if isinstance(resp, dict):
                    msg_id = resp.get("id")
                    if isinstance(msg_id, dict):
                        msg_id = msg_id.get("_serialized", "")
                    parts = msg_id.split("_") if msg_id else []
                    clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)
                    return clean_id or True
                return True
            except Exception:
                return True
        except Exception as e:
            err = str(e)[:200]
            logging.error("[send_audio_message] exception for %s: %s", remote_jid, err)
            return {"ok": False, "error": err, "retry": True}


    def _serialize_msg_id(self, remote_jid: str, msg_key: dict) -> str:
        """
        Build the full serialized WhatsApp message ID expected by WPPConnect
        (`WPP.chat.getMessageById`).  The bare key.id is not enough — the library
        needs `<fromMe>_<chatId>_<id>` and, for group messages, a trailing
        `_<participant>` — including for our own group messages (`fromMe=True`).
        """
        def _resolve_to_lid_if_available(jid: str) -> str:
            """Resolve JID to cached @lid if available, keeping @g.us / @broadcast, and formatting to @c.us otherwise."""
            if not jid:
                return jid
            if jid.endswith(("@g.us", "@broadcast")):
                return jid
            if jid.endswith("@lid"):
                return jid
            clean = jid.replace("@c.us", "@s.whatsapp.net")
            lid = getattr(self, "_phone_to_lid", {}).get(clean, "")
            if lid:
                return lid
            return jid.replace("@s.whatsapp.net", "@c.us")

        msg_id = msg_key.get("id", "")
        if not msg_id:
            return ""
        # A serialized id may already have been stored as the key id.
        if msg_id.startswith(("true_", "false_")):
            return msg_id
        from_me = bool(msg_key.get("fromMe", False))
        prefix = "true" if from_me else "false"
        chat = _resolve_to_lid_if_available(remote_jid or "")
        # Group messages always carry the sender's JID in the serialized id,
        # even for our own messages (fromMe=True). 1-on-1 keys have no
        # participant — gate on chat type, since a 1:1 @lid message's key
        # often still carries a (same-JID) remoteJidAlt, which would
        # otherwise get wrongly appended as a 4th segment and break the
        # WPPConnect store lookup (e.g. "false_X@lid_<id>_X@lid").
        participant = ""
        if chat.endswith("@g.us"):
            if from_me:
                # Our own group messages: always use our LID/phone as participant.
                raw = (getattr(self, "my_lid", "") or getattr(self, "my_jid", "") or msg_key.get("participant") or "")
            else:
                # Others' group messages: participant may be in key or a dedicated field.
                raw = (
                    msg_key.get("participant")
                    or msg_key.get("author")
                    or msg_key.get("remoteJidAlt")
                    or ""
                )
            participant = _resolve_to_lid_if_available(raw)
        if participant:
            return f"{prefix}_{chat}_{msg_id}_{participant}"
        return f"{prefix}_{chat}_{msg_id}"

    def send_reaction(self, remote_jid: str, msg_key: dict, emoji: str) -> bool:
        """Send a reaction to a message via the WPPConnect Server API."""
        # Resolve the @lid chat to its phone JID the same way deletes do, so the
        # serialized id matches the chat WPPConnect actually has loaded.
        lid_jid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/react-message"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "msgId": self._serialize_msg_id(remote_jid, msg_key),
            "reaction": emoji
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                logging.error("[send_reaction] HTTP %s: %s",
                              response.status_code, response.text[:500])
                return False
            return True
        except Exception as exc:
            logging.error("[send_reaction] exception: %s", exc)
            return False

    def _on_message_sent(self, local_id: str, audio_path: str = None, real_id: str = None, remote_jid: str = None):
        """
        Called on the main thread after a queued message is successfully sent.
        Updates the UI status label and cleans up any temporary audio file.
        real_id is the WhatsApp message ID returned by the API; it replaces the
        local UUID in the virtual message so playback can find the message in the DB.
        """
        import time as _time
        logging.info("[VOICE_TIMING] _on_message_sent — message LEFT pending state. local_id=%s real_id=%s",
                     local_id, real_id)
        if real_id and remote_jid:
            def _bg_update_db():
                try:
                    self.db.update_message_id(remote_jid, local_id, real_id)
                except Exception as e:
                    logging.error("[_on_message_sent] failed to update database message ID: %s", e)
            threading.Thread(target=_bg_update_db, daemon=True).start()

        # Save or copy the local audio copy under the real ID *before* calling _mark_message_sent
        # to prevent background media sync from downloading a file we already have.
        if audio_path and os.path.isfile(audio_path):
            if real_id and isinstance(real_id, str):
                try:
                    voice_messages_dir = data_path("voice_messages")
                    os.makedirs(voice_messages_dir, exist_ok=True)
                    local_audio_path = os.path.join(voice_messages_dir, f"{local_id}.msv")
                    real_audio_path = os.path.join(voice_messages_dir, f"{real_id}.msv")
                    
                    if os.path.isfile(local_audio_path):
                        import shutil
                        shutil.copy2(local_audio_path, real_audio_path)
                    else:
                        with open(audio_path, "rb") as f:
                            wav_data = f.read()
                        with open(real_audio_path, "wb") as f_out:
                            f_out.write(encrypt(wav_data, self.key))
                except Exception as e:
                    print(f"[_on_message_sent] error saving sent audio locally: {e}")
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        # For audio messages, play the sent sound HERE — not only inside
        # _mark_message_sent — because the upload can take several seconds.
        # If the user navigated to another conversation before the API
        # confirmed the send, local_id is no longer in _sorted_messages and
        # _mark_message_sent would silently skip the sound.  Playing it here
        # guarantees the "tac" always fires the moment the API says "sent".
        if audio_path and hasattr(self, "message_sent_sound"):
            self.message_sent_sound.play()

        if hasattr(self, "conversations_panel"):
            self.conversations_panel._mark_message_sent(local_id, real_id=real_id)

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
        logging.info(f"[on_message_status_update] msg_id={msg_id} status={status} remote_jid={remote_jid}")

        # Try all known JID forms (@lid <-> @s.whatsapp.net) to find the chat
        candidates = [remote_jid]
        if remote_jid.endswith("@lid"):
            phone_jid = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
            if phone_jid:
                candidates.append(phone_jid)
        elif remote_jid.endswith("@s.whatsapp.net"):
            lid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
            if lid:
                candidates.append(lid)

        chat_jid = next((j for j in candidates if j in self.chats), None)
        found_msg = None
        found_chat_jid = None

        if chat_jid:
            records = (
                self.chats[chat_jid]
                    .get("messages", {})
                    .get("messages", {})
                    .get("records", [])
            )
            for msg in records:
                if msg.get("key", {}).get("id") == msg_id:
                    msg.setdefault("MessageUpdate", []).append({"status": status})
                    found_msg = msg
                    found_chat_jid = chat_jid
                    logging.info(f"[on_message_status_update] Updated status to {status} for msg_id={msg_id} in records of chat={chat_jid}")
                    break
            if not found_msg:
                logging.warning(f"[on_message_status_update] Message {msg_id} not found in records of chat {chat_jid}")
        else:
            logging.warning(f"[on_message_status_update] Chat not found in self.chats for candidates: {candidates}")

        # ── Fallback: scan all chats in memory when the initial candidates miss ──
        # This happens when a status event arrives with remote_jid equal to our own
        # LID (the account LID), not the recipient's JID, so none of the candidates
        # matched. The message is actually stored in the recipient's chat.
        if not found_msg:
            for jid, chat_data in self.chats.items():
                if jid in candidates:
                    continue
                recs = (
                    chat_data.get("messages", {})
                             .get("messages", {})
                             .get("records", [])
                )
                for msg in recs:
                    if msg.get("key", {}).get("id") == msg_id:
                        msg.setdefault("MessageUpdate", []).append({"status": status})
                        found_msg = msg
                        found_chat_jid = jid
                        logging.info(
                            f"[on_message_status_update] Fallback: updated status to {status} "
                            f"for msg_id={msg_id} in chat={jid}"
                        )
                        break
                if found_msg:
                    break

        # ── Persist updated message record to DB ─────────────────────────────────
        if found_msg and found_chat_jid:
            try:
                self.db.insert_message(found_chat_jid, found_msg)
            except Exception as e:
                logging.error(f"[on_message_status_update] Failed to persist status update to DB: {e}")

        if hasattr(self, "conversations_panel"):
            self.conversations_panel.refresh_message_status(msg_id, status)


    def _resolve_jid_name(self, jid_norm: str) -> str:
        """Return the best display name for a participant JID (contact lookup + fallback)."""
        def _get_contact_tolerant(jid):
            if not jid:
                return None
            c = self.contacts.get(jid)
            if c:
                return c
            if jid.endswith("@s.whatsapp.net"):
                phone = jid.split("@")[0]
                if phone.startswith("55"):
                    if len(phone) == 13 and phone[4] == "9":
                        alt = phone[:4] + phone[5:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
                    elif len(phone) == 12:
                        alt = phone[:4] + "9" + phone[4:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
            return None

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
            contact = _get_contact_tolerant(cjid)
            if contact:
                name = (contact.get("name") or contact.get("pushName") or "").strip()
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
        if jid_norm.endswith("@lid"):
            phone = getattr(self, "_lid_to_phone", {}).get(jid_norm, "")
            if phone:
                return format_number(phone)
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

    def _refresh_chat_row_in_list(self, chat_jid_norm: str):
        """Update only the chat-list row for chat_jid_norm via SetItem(), in
        whichever panel (main or archived) currently displays it.

        Replaces the full _schedule_set_chats() rebuild for changes that don't
        affect list membership/order (presence, unread count going to 0).
        SetItem() on a single row prevents NVDA from re-reading the entire
        list, and applies immediately instead of waiting out the 300ms
        _schedule_set_chats() debounce.
        """
        # Title/tray tooltip unread count: cheap (one pass over self.chats),
        # so recompute it here directly rather than waiting for the next
        # debounced _apply_chat_lists() rebuild.
        self._update_title()

        is_group = chat_jid_norm.endswith("@g.us")
        for panel in (
            getattr(self, "conversations_panel", None),
            getattr(self, "archived_conversations_panel", None),
        ):
            if panel is None:
                continue
            lst       = getattr(panel, "conversations_list", None)
            displayed = getattr(panel, "chats_list", [])
            names     = getattr(panel, "chat_names", [])
            if lst is None:
                continue
            for idx, chat in enumerate(displayed):
                if self._normalize_jid(chat.get("remoteJid", "")) != chat_jid_norm:
                    continue
                if idx >= lst.GetItemCount():
                    # displayed/chats_list (this panel's backing array) has
                    # drifted ahead of the ListCtrl's actual row count — e.g.
                    # a debounced full rebuild (_apply_chat_lists) is
                    # mid-flight on another callback and hasn't inserted this
                    # many rows yet. There's nothing to patch until that
                    # rebuild finishes and re-syncs both; the next presence/
                    # unread event will retry. Falls through to the crash
                    # this guard exists for otherwise ("invalid item index in
                    # SetItem").
                    break
                unread = effective_unread_count(chat)
                conv_filter = getattr(panel, '_conv_filter', 'all')
                if conv_filter == 'unread' and unread == 0:
                    # No longer belongs in the "unread" filtered view. Remove it
                    # outright (and keep the backing arrays in sync) immediately
                    # instead of waiting for the next debounced full rebuild —
                    # this used to be the only way such a row ever disappeared,
                    # and letting several of these pile up made the backing
                    # arrays' indices drift from the ListCtrl's real item count
                    # (the "Couldn't retrieve information about list control
                    # item N" crashes).
                    try:
                        lst.DeleteItem(idx)
                    except Exception:
                        break
                    del displayed[idx]
                    if idx < len(names):
                        del names[idx]
                    displayed_jids = getattr(panel, '_displayed_jids', None)
                    if displayed_jids is not None and idx < len(displayed_jids):
                        del displayed_jids[idx]
                    break
                name   = names[idx] if idx < len(names) else ""
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
                label = self._presence_label_for_chat(chat_jid_norm, is_group)
                if label:
                    item_text += f" {label}"
                # Only touch the row when the visible text actually changes. Presence
                # bursts (online/offline toggles that don't alter the row) otherwise
                # rewrote the focused item's text repeatedly, making NVDA announce the
                # conversation name over and over while the user sat idle on the list.
                try:
                    if lst.GetItemText(idx, 0) != item_text:
                        lst.SetItem(idx, 0, item_text)
                except Exception:
                    # GetItemText/SetItem failing here almost always means idx
                    # is no longer valid for this ListCtrl (see the item-count
                    # guard above) — unconditionally retrying SetItem with the
                    # same idx just raised the exact same wx assertion again,
                    # uncaught this time, crashing the app instead of no-op'ing.
                    pass
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
        if chat_jid_norm.endswith("@lid"):
            chat_jid_norm = self._lid_to_phone.get(chat_jid_norm, chat_jid_norm)

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
                        self._refresh_chat_row_in_list(cjid)
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

            # Speak via AO2 only when a composing/recording event starts in the ACTIVE conversation.
            # Events from other chats are intentionally silent to avoid interrupting the user.
            if new_lkp != old_lkp and new_lkp in ("composing", "recording"):
                speech = self.settings.get("speech_content", {})
                announce_enabled = (
                    speech.get("announce_typing", True) if new_lkp == "composing"
                    else speech.get("announce_recording", True)
                )
                if announce_enabled and chat_jid_norm == conv_jid:
                    if not self.is_chat_muted(chat_jid_norm) and not self.is_chat_archived(chat_jid_norm):
                        name = self._resolve_jid_name(canonical)
                        if name:
                            try:
                                i18n_key = "typing_text" if new_lkp == "composing" else "recording_text"
                                msg_text = self.i18n.t(i18n_key).format(name=name)
                                self.speak_output.output(msg_text)
                            except Exception:
                                pass

        # Persist the updated pushName map to database metadata.
        if _ppm_updated and hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("presence_pushname_map", dict(self._presence_pushname_map))

        # Update only the affected row — avoids DeleteAllItems()+Append() rebuild
        # that causes NVDA to re-read the full list and stutter during TTS echo.
        if presence_changed:
            self._refresh_chat_row_in_list(chat_jid_norm)

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
            return  # no actual change — skip expensive rebuild + save
        # The server sometimes counts own (fromMe) messages as unread. Correct
        # for that by inspecting the tail of the locally-stored message list.
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
        # Never resurrect unread count for a conversation the user already read
        # locally (mark_conversation_as_read set it to 0). The server may still
        # carry a stale unread count from before the read-ack arrived.
        if normalized == getattr(self, "_last_open_jid", ""):
            unread_count = 0
        chat["unreadCount"] = unread_count
        self._schedule_save(dirty_jid=normalized)
        self._schedule_set_chats()

    def on_chat_archive_update(self, jid: str, archived: bool):
        """Handle archive/unarchive status change from chats.update."""
        normalized = self._normalize_jid(jid)
        chat = self.chats.get(normalized)
        if chat is None:
            return
        chat["archived"] = archived
        chat["archive"] = archived
        
        # Keep local DB synchronized
        if archived:
            self._archived_chats.add(normalized)
        else:
            self._archived_chats.discard(normalized)
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("archived_chats", list(self._archived_chats))
        self._schedule_set_chats()

    def on_chat_pin_update(self, jid: str, is_pinned: bool):
        """Handle pin/unpin status change from chats.update."""
        normalized = self._normalize_jid(jid)
        chat = self.chats.get(normalized)
        if chat is None:
            if normalized.endswith("@lid"):
                alt = getattr(self, "_lid_to_phone", {}).get(normalized, "")
                if alt: chat = self.chats.get(self._normalize_jid(alt))
            else:
                alt = getattr(self, "_phone_to_lid", {}).get(normalized, "")
                if alt: chat = self.chats.get(alt)

        if is_pinned:
            self._pinned_chats.add(normalized)
            if normalized.endswith("@lid"):
                alt_phone = getattr(self, "_lid_to_phone", {}).get(normalized, "")
                if alt_phone:
                    self._pinned_chats.add(self._normalize_jid(alt_phone))
            else:
                alt_lid = getattr(self, "_phone_to_lid", {}).get(normalized, "")
                if alt_lid:
                    self._pinned_chats.add(alt_lid)
        else:
            self._pinned_chats.discard(normalized)
            if normalized.endswith("@lid"):
                alt_phone = getattr(self, "_lid_to_phone", {}).get(normalized, "")
                if alt_phone:
                    self._pinned_chats.discard(self._normalize_jid(alt_phone))
            else:
                alt_lid = getattr(self, "_phone_to_lid", {}).get(normalized, "")
                if alt_lid:
                    self._pinned_chats.discard(alt_lid)

        if chat is not None:
            chat["pin"] = is_pinned

        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("pinned_chats", list(self._pinned_chats))
        self._schedule_set_chats()

    def handle_audio_message(self, msg, timeout=60):
        voice_messages_dir = data_path("voice_messages")
        msg_id = msg.get('key', {}).get('id', '')
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
        audio_file_path = os.path.join(voice_messages_dir, f"{msg_id}.msv")
        if os.path.isfile(audio_file_path):
            return
        base64_audio = self.get_base64_from_media(msg, timeout=timeout)
        if not base64_audio:
            return
        audio_content = base64.b64decode(base64_audio)
        self.save_audio_locally(msg, audio_content)

    def get_base64_from_media(self, media, progress_callback=None, timeout=60):
        """
        Fetch encrypted media from WPPConnect and return its base64 string.

        Raises MediaExpiredError when the WhatsApp CDN URL has expired (HTTP 403/410).
        When *progress_callback* is provided the request is streamed and the
        callback is called with a float in [0, 1] as each chunk arrives.
        """
        _key = media.get("key", {})
        msg_id = self._serialize_msg_id(_key.get("remoteJid", ""), _key)
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/get-media-by-message/{msg_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # Prepare body with media details to bypass Puppeteer cache lookups in WPPConnect Server
        body_data = dict(media)
        msg_type = media.get("messageType")
        if msg_type and "message" in media:
            inner = media["message"].get(msg_type)
            if isinstance(inner, dict):
                if "mediaKey" in inner and inner["mediaKey"]:
                    body_data["mediaKey"] = inner["mediaKey"]
                if "url" in inner and inner["url"]:
                    body_data["clientUrl"] = inner["url"]
                if "mimetype" in inner and inner["mimetype"]:
                    body_data["mimetype"] = inner["mimetype"]
                body_data["type"] = msg_type.replace("Message", "")

        max_attempts = 3
        for attempt in range(max_attempts):
            if progress_callback is None:
                try:
                    response = requests.post(url, headers=headers, json=body_data, timeout=timeout)
                except MediaExpiredError:
                    raise
                except Exception as exc:
                    logging.warning(
                        "[get_base64_from_media] request failed for %s (attempt %d/%d): %s",
                        msg_id, attempt + 1, max_attempts, exc,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(3)
                        continue
                    return ""
                if response.status_code in (403, 410):
                    raise MediaExpiredError(response.status_code)
                if response.status_code in (200, 201):
                    return response.json().get("base64", "")
                
                # Check for transient session not active errors
                resp_text = response.text
                if response.status_code in (400, 500) and any(x in resp_text.lower() for x in ("session is not active", "not active", "disconnected")):
                    logging.warning(
                        "[get_base64_from_media] session not active for %s, retrying in 3s (attempt %d/%d)",
                        msg_id, attempt + 1, max_attempts
                    )
                    self._wa_connected = False
                    if attempt < max_attempts - 1:
                        time.sleep(3)
                        continue
                logging.warning(
                     "[get_base64_from_media] HTTP %s fetching media for %s: %s",
                     response.status_code, msg_id, resp_text[:200],
                )
                return ""
            else:
                # Streaming mode so we can report per-chunk progress
                try:
                    response = requests.post(url, headers=headers, json=body_data, stream=True, timeout=timeout)
                    if response.status_code in (403, 410):
                        raise MediaExpiredError(response.status_code)
                    
                    # Check for transient session not active errors before streaming
                    if response.status_code in (400, 500):
                        # Read small error response
                        resp_text = response.text
                        if any(x in resp_text.lower() for x in ("session is not active", "not active", "disconnected")):
                            logging.warning(
                                "[get_base64_from_media] session not active for %s (stream), retrying in 3s (attempt %d/%d)",
                                msg_id, attempt + 1, max_attempts
                            )
                            self._wa_connected = False
                            if attempt < max_attempts - 1:
                                time.sleep(3)
                                continue
                        logging.warning(
                            "[get_base64_from_media] HTTP %s fetching media for %s: %s",
                            response.status_code, msg_id, resp_text[:200],
                        )
                        return ""

                    if response.status_code not in (200, 201):
                        logging.warning(
                            "[get_base64_from_media] HTTP %s fetching media for %s",
                            response.status_code, msg_id,
                        )
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
                    try:
                        return json.loads(body).get("base64", "")
                    except Exception:
                        # Caso o body retornado seja o base64 bruto ou binário
                        return base64.b64encode(b"".join(chunks)).decode("utf-8")
                except MediaExpiredError:
                    raise
                except Exception as exc:
                    logging.warning(
                        "[get_base64_from_media] request failed for %s (stream) (attempt %d/%d): %s",
                        msg_id, attempt + 1, max_attempts, exc,
                    )
                    if attempt < max_attempts - 1:
                        time.sleep(3)
                        continue
                    return ""
        return ""

    def fetch_older_messages(self, remote_jid, oldest_msg):
        """Fetch older messages from server starting before the oldest_msg."""
        remote_jid = self._normalize_jid(remote_jid)
        
        # Check if history is already marked as exhausted in-memory
        if remote_jid in getattr(self, "_exhausted_chats", set()):
            logging.info(f"[fetch_older_messages] History already marked as exhausted in-memory for {remote_jid}, skipping API query.")
            return []

        # Use remote_jid resolved to @lid (if available) for the URL parameter.
        # WPPConnect has a special evaluate-bypass in /get-messages/:phone for @lid JIDs.
        phone = self._resolve_jid_for_send(remote_jid).replace("@s.whatsapp.net", "@c.us")

        # The message ID key in WPPConnect's browser store also matches the chat JID (LID if available).
        resolved_phone = self._resolve_jid_for_send(remote_jid).replace("@s.whatsapp.net", "@c.us")

        _key = oldest_msg.get("key", {})
        msg_id = _key.get("id", "")
        
        # Get raw message ID from key
        raw_id = msg_id
        if msg_id and "_" in msg_id:
            parts = msg_id.split("_")
            raw_id = parts[2] if len(parts) > 2 else parts[-1]

        # WPPConnect's getMessages ?id= param expects the FULLY serialized message key
        # (e.g. "true_226465287282814@lid_3EB0D3BCB679BFCAFD2D39").
        from_me = bool(_key.get("fromMe", False))
        prefix = "true" if from_me else "false"
        
        participant = ""
        if phone.endswith("@g.us"):
            p_raw = _key.get("participant") or oldest_msg.get("participant") or ""
            if msg_id and msg_id.startswith(("true_", "false_")):
                parts = msg_id.split("_")
                if len(parts) > 3:
                    p_raw = parts[3]
            if p_raw:
                # Group participant JIDs must also be resolved using _resolve_jid_for_send
                participant = self._resolve_jid_for_send(p_raw).replace("@s.whatsapp.net", "@c.us")

        if participant:
            serialized_id = f"{prefix}_{resolved_phone}_{raw_id}_{participant}"
        else:
            serialized_id = f"{prefix}_{resolved_phone}_{raw_id}"

        limit = int(self.settings.get("user_interface", {}).get("messages_page_size", 200))
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/get-messages/{phone}?count={limit}&direction=before&id={serialized_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            logging.info(f"[fetch_older_messages] Querying URL: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            
            # Alternate JID query fallback (resolves 401/TypeError or Chat not found errors)
            if response.status_code not in (200, 201):
                alternate_jid = ""
                if remote_jid.endswith("@lid"):
                    # Fallback to resolved phone JID if LID query failed
                    resolved = getattr(self, "_lid_to_phone", {}).get(remote_jid, "")
                    if resolved:
                        alternate_jid = resolved.replace("@s.whatsapp.net", "@c.us")
                else:
                    alt_lid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
                    if alt_lid:
                        alternate_jid = alt_lid

                if alternate_jid and alternate_jid != phone:
                    alt_serialized_id = f"{prefix}_{alternate_jid}_{raw_id}"
                    if participant and alternate_jid.endswith("@g.us"):
                        alt_serialized_id = f"{prefix}_{alternate_jid}_{raw_id}_{participant}"
                    alt_url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/get-messages/{alternate_jid}?count={limit}&direction=before&id={alt_serialized_id}"
                    logging.info(f"[fetch_older_messages] Primary query failed. Retrying with alternate JID {alternate_jid}...")
                    try:
                        alt_response = requests.get(alt_url, headers=headers, timeout=30)
                        if alt_response.status_code in (200, 201):
                            response = alt_response
                            logging.info("[fetch_older_messages] Fallback alternate JID query succeeded!")
                    except Exception as alt_e:
                        logging.warning(f"[fetch_older_messages] Fallback alternate JID query failed: {alt_e}")

            if response.status_code in (200, 201):
                body = response.json()
                wpp_messages = body.get("response", []) if isinstance(body, dict) else []
                if not isinstance(wpp_messages, list):
                    wpp_messages = []
                
                # If API returned no messages, mark history as exhausted in-memory
                if not wpp_messages:
                    if not hasattr(self, "_exhausted_chats"):
                        self._exhausted_chats = set()
                    self._exhausted_chats.add(remote_jid)
                    logging.info(f"[fetch_older_messages] Marked history as exhausted in-memory for {remote_jid}")
                
                fetched_messages = []
                for wm in wpp_messages:
                    if isinstance(wm, dict) and self.ws:
                        try:
                            normalized = self.ws._normalize_wpp_message(wm)
                            self._extract_lid_mapping(normalized)
                            fetched_messages.append(normalized)
                        except Exception:
                            pass
                
                if fetched_messages:
                    # Update local database/memory
                    chat = self.chats.get(remote_jid, {})
                    if chat:
                        local_records = chat.get("messages", {}).get("messages", {}).get("records", [])
                        existing_ids = {r.get("key", {}).get("id") for r in local_records}
                        new_records = [m for m in fetched_messages if m.get("key", {}).get("id") not in existing_ids]
                        if new_records:
                            all_records = new_records + local_records
                            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = all_records
                            chat["messages"]["messages"]["total"] = len(all_records)
                            try:
                                self.db.upsert_chat(remote_jid, chat)
                                self.db.insert_messages_batch(remote_jid, new_records)
                            except Exception as e:
                                logging.error(f"[fetch_older_messages] Incremental save failed: {e}")
                                self.save_data(self.chats, self.contacts)
                    return fetched_messages
            else:
                logging.warning(
                    f"[fetch_older_messages] API returned status {response.status_code} for {remote_jid}: {response.text[:300]}"
                )
        except Exception as e:
            logging.error(f"[fetch_older_messages] failed to get older messages for {remote_jid}: {e}")
        return []

    def save_audio_locally(self, msg, audio_content):
        voice_messages_dir = data_path("voice_messages")
        msg_id = msg.get('key', {}).get('id', '')
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
        audio_file_path = os.path.join(voice_messages_dir, f"{msg_id}.msv")
        try:
            with open(audio_file_path, "wb") as audio_file:
                encrypted_audio = encrypt(audio_content, self.key)
                audio_file.write(encrypted_audio)
        except Exception as e:
            #Ignore audios that couldn't be saved for now
            pass

    def mark_conversation_as_read(self, remote_jid: str, force: bool = False):
        """Mark conversation as read locally and notify WPPConnect."""
        chat = self.chats.get(remote_jid)
        if chat is None:
            return

        unread = int(chat.get("unreadCount") or 0)
        chat["unreadCount"] = 0
        self._schedule_save(dirty_jid=remote_jid)
        # Immediate single-row update: unlike _schedule_set_chats()/set_chats(),
        # this isn't suppressed while a media sync is running, so the badge
        # clears right away instead of only after the sync eventually finishes
        # (previously observed as a 10-20+ second — or longer — delay).
        wx.CallAfter(self._refresh_chat_row_in_list, self._normalize_jid(remote_jid))
        wx.CallAfter(self._schedule_set_chats)

        if unread == 0 and not force:
            return

        # Prefer @lid JID for WPPConnect if mapped
        target_phone = remote_jid
        if not target_phone.endswith("@lid"):
            alt_lid = getattr(self, "_phone_to_lid", {}).get(self._normalize_jid(remote_jid), "")
            if alt_lid:
                target_phone = alt_lid

        if target_phone.endswith("@s.whatsapp.net"):
            target_phone = target_phone.rsplit("@", 1)[0] + "@c.us"
        
        is_lid_target = target_phone.endswith("@lid")

        def _send_seen(phone: str, is_lid: bool) -> "requests.Response | None":
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-seen"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            payload = {"phone": phone, "isGroup": phone.endswith("@g.us")}
            if is_lid:
                payload["isLid"] = True
            return requests.post(url, json=payload, headers=headers, timeout=10)

        def _do_api():
            try:
                resp = _send_seen(target_phone, is_lid_target)
                if not resp.ok:
                    logging.warning("[mark_as_read] API response %s for %s: %s",
                                     resp.status_code, target_phone, resp.text[:200])
                    # If it failed, try the alternate format (LID <-> phone) as fallback
                    fallback_phone = remote_jid
                    if fallback_phone.endswith("@lid"):
                        phone_jid = getattr(self, "_lid_to_phone", {}).get(fallback_phone, "")
                        if phone_jid: fallback_phone = phone_jid
                    else:
                        alt_lid = getattr(self, "_phone_to_lid", {}).get(self._normalize_jid(fallback_phone), "")
                        if alt_lid: fallback_phone = alt_lid

                    if fallback_phone.endswith("@s.whatsapp.net"):
                        fallback_phone = fallback_phone.rsplit("@", 1)[0] + "@c.us"

                    if fallback_phone != target_phone:
                        logging.info("[mark_as_read] Retrying /send-seen using fallback JID: %s", fallback_phone)
                        resp2 = _send_seen(fallback_phone, fallback_phone.endswith("@lid"))
                        if not resp2.ok:
                            logging.warning("[mark_as_read] Fallback /send-seen also failed %s for %s: %s",
                                             resp2.status_code, fallback_phone, resp2.text[:200])
            except Exception as exc:
                logging.warning("[mark_as_read] Request failed for %s: %s", target_phone, exc)
        threading.Thread(target=_do_api, daemon=True).start()

    def mark_conversation_as_unread(self, remote_jid: str):
        chat = self.chats.get(remote_jid)
        if chat is not None:
            chat["unreadCount"] = 1
            self._schedule_save()
            wx.CallAfter(self.set_chats)

    # ── WPPConnect — profile / group info ─────────────────────────────────
    
    def resolve_self_lid(self):
        """Query WPPConnect API for own PN-LID mapping so self-mentions resolve correctly."""
        my_jid = getattr(self, "my_jid", "")
        if not my_jid:
            return

        # Avoid redundant calls if already resolved and present in cache
        my_lid = getattr(self, "my_lid", "")
        if my_lid and my_lid in getattr(self, "_lid_to_phone", {}):
            return

        def _resolve():
            try:
                url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact/pn-lid/{my_jid}"
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                }
                logging.info(f"[Self LID Resolution] Querying pn-lid mapping for own JID {my_jid}...")
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code in (200, 201):
                    res = response.json() or {}
                    logging.info(f"[Self LID Resolution] Response: {res}")
                    # Parse LID JID
                    lid_obj = res.get("lid") or {}
                    lid_jid = None
                    if isinstance(lid_obj, dict):
                        lid_jid = lid_obj.get("_serialized") or lid_obj.get("id")
                    elif isinstance(lid_obj, str):
                        lid_jid = lid_obj
                    if not lid_jid:
                        lid_jid = res.get("lidJid")

                    # Parse Phone JID
                    phone_obj = res.get("phone") or res.get("phoneJid") or res.get("id") or {}
                    phone_jid = None
                    if isinstance(phone_obj, dict):
                        phone_jid = phone_obj.get("_serialized") or phone_obj.get("id")
                    elif isinstance(phone_obj, str):
                        phone_jid = phone_obj

                    if lid_jid and phone_jid:
                        normalized_phone = self._normalize_jid(phone_jid)
                        normalized_lid = self._normalize_jid(lid_jid)
                        self.my_jid = normalized_phone
                        self.my_lid = normalized_lid
                        
                        # Clean up any bad mappings where normalized_phone or normalized_lid were mapped to other contacts
                        if hasattr(self, "_lid_to_phone"):
                            # 1. If another LID was mapped to our phone, delete it (from memory and DB)
                            bad_lids = [k for k, v in self._lid_to_phone.items() if v == normalized_phone and k != normalized_lid]
                            for bad_lid in bad_lids:
                                self._lid_to_phone.pop(bad_lid, None)
                                self._phone_to_lid.pop(normalized_phone, None)
                                try:
                                    self.db.delete_lid_mapping(bad_lid)
                                except Exception as _e:
                                    pass
                                logging.warning(f"[Self LID Resolution] Deleted corrupt mapping: {bad_lid} was mapped to our phone {normalized_phone}")

                            # 2. If our LID JID was mapped to another phone number, delete it
                            old_phone = self._lid_to_phone.get(normalized_lid)
                            if old_phone and old_phone != normalized_phone:
                                self._lid_to_phone.pop(normalized_lid, None)
                                self._phone_to_lid.pop(old_phone, None)
                                try:
                                    self.db.delete_lid_mapping(normalized_lid)
                                except Exception as _e:
                                    pass
                                logging.warning(f"[Self LID Resolution] Cleaned corrupt mapping: {normalized_lid} was mapped to {old_phone}")
                            
                            # 3. If another phone JID was mapped to our LID, delete it
                            bad_phones = [k for k, v in self._phone_to_lid.items() if v == normalized_lid and k != normalized_phone]
                            for bad_phone in bad_phones:
                                self._phone_to_lid.pop(bad_phone, None)
                                self._lid_to_phone.pop(normalized_lid, None)
                                try:
                                    self.db.delete_lid_mapping(normalized_lid)
                                except Exception as _e:
                                    pass
                                logging.warning(f"[Self LID Resolution] Deleted corrupt mapping: our LID {normalized_lid} was mapped to another phone {bad_phone}")

                            # 4. If our phone JID was mapped to another LID, delete it
                            old_lid = self._phone_to_lid.get(normalized_phone)
                            if old_lid and old_lid != normalized_lid:
                                self._phone_to_lid.pop(old_lid, None)
                                self._lid_to_phone.pop(old_lid, None)
                                try:
                                    self.db.delete_lid_mapping(old_lid)
                                except Exception as _e:
                                    pass
                                logging.warning(f"[Self LID Resolution] Cleaned corrupt mapping: {normalized_phone} was mapped to {old_lid}")

                        self.register_jid_mapping(normalized_lid, normalized_phone)
                        logging.info(f"[Self LID Resolution] Successfully resolved and registered own JID mapping: {normalized_lid} <-> {normalized_phone}")
            except Exception as e:
                logging.error(f"[Self LID Resolution] Error resolving self LID: {e}")

        threading.Thread(target=_resolve, daemon=True).start()

    def register_jid_mapping(self, lid_jid, phone_jid, save=True):
        """Register a bidirectional mapping between @lid and @s.whatsapp.net, and persist it."""
        if not lid_jid or not phone_jid:
            return
        if not lid_jid.endswith("@lid") or not phone_jid.endswith("@s.whatsapp.net"):
            return
            
        # Guard against corrupt self-mappings.
        # Special case: if lid_jid is definitively our own LID (my_lid), we know
        # phone_jid is also ours — phone number format differences can make
        # _is_self_jid() return False for the phone side even when they match.
        _my_lid = getattr(self, "my_lid", "")
        if _my_lid and lid_jid == _my_lid:
            # User's own LID→phone mapping: always valid, update my_jid if format differs.
            if not self._is_self_jid(phone_jid):
                logging.info(f"[LID Mapping] Updating my_jid to {phone_jid} (format differs from {getattr(self, 'my_jid', '')})")
                self.my_jid = phone_jid
        elif self._is_self_jid(lid_jid) or self._is_self_jid(phone_jid):
            if not (self._is_self_jid(lid_jid) and self._is_self_jid(phone_jid)):
                logging.warning(f"[LID Mapping] Blocked corrupt self-mapping attempt: {lid_jid} <-> {phone_jid}")
                return
            
        if not hasattr(self, "_lid_to_phone"):
            self._lid_to_phone = {}
        if not hasattr(self, "_phone_to_lid"):
            self._phone_to_lid = {}
            
        current_phone = self._lid_to_phone.get(lid_jid)
        if current_phone != phone_jid:
            self._lid_to_phone[lid_jid] = phone_jid
            self._phone_to_lid[phone_jid] = lid_jid
            logging.info(f"[LID Mapping] Registered JID mapping: {lid_jid} <-> {phone_jid}")
            
            # If it was in the unresolvable set, remove it
            if hasattr(self, "_unresolvable_lids") and lid_jid in self._unresolvable_lids:
                self._unresolvable_lids.discard(lid_jid)
            
            # Update the contact name display mappings in contacts if possible
            if phone_jid in self.contacts and self.contacts[phone_jid]:
                if lid_jid not in self.contacts or self.contacts[lid_jid].get("name") in (None, "", "Contato sem nome"):
                    self.contacts[lid_jid] = self.contacts[phone_jid].copy()
                    self.contacts[lid_jid]["id"] = lid_jid
                    self.contacts[lid_jid]["remoteJid"] = lid_jid
            
            if save:
                # Save the mapping to SQLite incrementally
                try:
                    self.db.set_lid_mapping(lid_jid, phone_jid)
                    if lid_jid in self.contacts:
                        self.db.upsert_contacts_batch({lid_jid: self.contacts[lid_jid]})
                except Exception as exc:
                    logging.warning("[LID Mapping] Failed to save mapping incrementally: %s", exc)
                    # Fallback to save_data if incremental save fails
                    self.save_data(self.chats, self.contacts)
            wx.CallAfter(self._schedule_set_chats)

    def resolve_lid_jids_via_api(self, jids):
        """Resolve a list of @lid JIDs to phone JIDs using WPPConnect contact endpoint."""
        if not jids:
            return
            
        updated_contacts = {}
        for lid_jid in jids:
            if not lid_jid.endswith("@lid"):
                continue
                
            if not getattr(self, "_wa_connected", False):
                logging.warning("[LID Resolution] WhatsApp is not connected. Aborting loop.")
                break

            # Check caches and active resolving list under lock
            if not hasattr(self, "_lid_resolution_lock"):
                self._lid_resolution_lock = threading.Lock()
            if not hasattr(self, "_unresolvable_lids"):
                self._unresolvable_lids = set()
            if not hasattr(self, "_resolving_lids"):
                self._resolving_lids = set()
                
            if not hasattr(self, "_unresolvable_names"):
                self._unresolvable_names = set()
                
            query_pn = lid_jid not in getattr(self, "_lid_to_phone", {}) and lid_jid not in self._unresolvable_lids
            
            contact = self.contacts.get(lid_jid, {})
            has_name = contact.get("name") or contact.get("pushName")
            query_name = not has_name and lid_jid not in self._unresolvable_names
            
            if not query_pn and not query_name:
                continue
                
            with self._lid_resolution_lock:
                if lid_jid in self._resolving_lids:
                    continue
                self._resolving_lids.add(lid_jid)
                
            try:
                canonical_jid = getattr(self, "_lid_to_phone", {}).get(lid_jid)
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                }
                
                if query_pn:
                    # First, resolve pn-lid mapping
                    url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact/pn-lid/{lid_jid}"
                    logging.info(f"[LID Resolution] Querying WPPConnect pn-lid mapping for {lid_jid}...")
                    response = requests.get(url, headers=headers, timeout=4)
                    if response.status_code in (200, 201):
                        res = response.json() or {}
                        logging.info(f"[LID Resolution] pn-lid response for {lid_jid}: {res}")
                        res_data = res.get("response") if isinstance(res.get("response"), dict) else res
                        pn_obj = res_data.get("phoneNumber") or {}
                        pn_jid = None
                        if isinstance(pn_obj, dict):
                            pn_jid = pn_obj.get("_serialized") or pn_obj.get("id")
                        elif isinstance(pn_obj, str):
                            pn_jid = pn_obj
                        if not pn_jid:
                            pn_jid = res_data.get("pnJid")
                        if pn_jid:
                            canonical_jid = self._normalize_jid(pn_jid)
                            if canonical_jid and canonical_jid.endswith("@s.whatsapp.net"):
                                self.register_jid_mapping(lid_jid, canonical_jid, save=False)
                                try:
                                    self.db.set_lid_mapping(lid_jid, canonical_jid)
                                except Exception as exc:
                                    logging.warning("[LID Resolution] set_lid_mapping failed: %s", exc)
                        
                        # Try to resolve contact name/pushname directly from pn-lid mapping response
                        contact_obj = res_data.get("contact") or {}
                        res_name = contact_obj.get("name") or contact_obj.get("pushname") or contact_obj.get("pushName") or contact_obj.get("displayName")
                        if res_name and res_name != "Contato sem nome" and not is_phone_like(res_name):
                            if lid_jid not in self.contacts:
                                self.contacts[lid_jid] = {}
                            self.contacts[lid_jid]["name"] = res_name
                            self.contacts[lid_jid]["pushName"] = res_name
                            updated_contacts[lid_jid] = self.contacts[lid_jid]
                            
                            if not hasattr(self, "_presence_pushname_map"):
                                self._presence_pushname_map = {}
                            self._presence_pushname_map[lid_jid] = res_name
                            
                            if canonical_jid:
                                if canonical_jid not in self.contacts:
                                    self.contacts[canonical_jid] = {}
                                self.contacts[canonical_jid]["name"] = res_name
                                self.contacts[canonical_jid]["pushName"] = res_name
                                updated_contacts[canonical_jid] = self.contacts[canonical_jid]
                                self._presence_pushname_map[canonical_jid] = res_name
                            
                            # Resolved the name successfully, no need to query profile
                            query_name = False
                
                if query_name:
                    # Fetch profile info for name caching
                    # If we mapped it to a phone JID, fetch that. Otherwise fetch the lid JID directly.
                    target_jid = canonical_jid if canonical_jid else lid_jid
                    url_profile = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact/{target_jid}"
                    logging.info(f"[LID Resolution] Querying profile details for {target_jid}...")
                    resp_profile = requests.get(url_profile, headers=headers, timeout=4)
                    # Check profile response
                    if resp_profile.status_code in (200, 201):
                        res_prof = resp_profile.json() or {}
                        res_data = res_prof.get("response") if isinstance(res_prof.get("response"), dict) else res_prof
                        if not isinstance(res_data, dict):
                            res_data = {}
                            
                        # Resolve JID mapping from contact details
                        profile_pn_jid = None
                        id_obj = res_data.get("id") or {}
                        if isinstance(id_obj, dict):
                            ser_id = id_obj.get("_serialized") or ""
                            if ser_id.endswith(("@c.us", "@s.whatsapp.net")):
                                profile_pn_jid = ser_id
                        if not profile_pn_jid:
                            pn_obj = res_data.get("phoneNumber") or {}
                            if isinstance(pn_obj, dict):
                                profile_pn_jid = pn_obj.get("_serialized") or pn_obj.get("id")
                            elif isinstance(pn_obj, str):
                                profile_pn_jid = pn_obj
                        if not profile_pn_jid:
                            profile_pn_jid = res_data.get("pnJid")
                        if not profile_pn_jid:
                            profile_pn_jid = res_data.get("phone")
                            
                        if profile_pn_jid:
                            profile_canonical = self._normalize_jid(profile_pn_jid)
                            if profile_canonical and profile_canonical.endswith("@s.whatsapp.net"):
                                self.register_jid_mapping(lid_jid, profile_canonical, save=False)
                                try:
                                    self.db.set_lid_mapping(lid_jid, profile_canonical)
                                except Exception as exc:
                                    logging.warning("[LID Resolution] set_lid_mapping (profile) failed: %s", exc)
                                if not canonical_jid:
                                    canonical_jid = profile_canonical
                        name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                        if name and name != "Contato sem nome" and not is_phone_like(name):
                            if lid_jid not in self.contacts:
                                self.contacts[lid_jid] = {}
                            self.contacts[lid_jid]["name"] = name
                            self.contacts[lid_jid]["pushName"] = name
                            updated_contacts[lid_jid] = self.contacts[lid_jid]
                            
                            # Also save to presence pushname map to ensure UI functions find it
                            if not hasattr(self, "_presence_pushname_map"):
                                self._presence_pushname_map = {}
                            self._presence_pushname_map[lid_jid] = name
                            
                            # Also copy to phone contact cache if mapped
                            if canonical_jid:
                                if canonical_jid not in self.contacts:
                                    self.contacts[canonical_jid] = {}
                                self.contacts[canonical_jid]["name"] = name
                                self.contacts[canonical_jid]["pushName"] = name
                                updated_contacts[canonical_jid] = self.contacts[canonical_jid]
                                self._presence_pushname_map[canonical_jid] = name
                        else:
                            logging.info(f"[LID Resolution] Profile name not resolved/accepted for {target_jid}. Original name field: {name}. Response data: {res_data}")
                    else:
                        logging.error(f"[LID Resolution] fetchProfile API error {resp_profile.status_code} for {target_jid}: {resp_profile.text}")
                        # If the API returns 404/500 indicating the session was closed/disconnected, stop making calls immediately
                        if resp_profile.status_code in (404, 500) or "session is not active" in resp_profile.text.lower():
                            logging.warning("[LID Resolution] Session is disconnected/not active. Aborting loop.")
                            break
                # Throttle query loop so Puppeteer isn't overwhelmed and can prioritize message sending
                time.sleep(0.5)
            except requests.exceptions.RequestException as e:
                logging.error(f"[LID Resolution] Network/API error during resolution of {lid_jid} (aborting loop): {e}")
                # Abort the loop because the API is likely down, overloaded, or timing out.
                break
            except Exception as e:
                logging.error(f"[LID Resolution] Exception during resolution of {lid_jid}: {e}")
            finally:
                with self._lid_resolution_lock:
                    self._resolving_lids.discard(lid_jid)
                    if query_pn and lid_jid not in getattr(self, "_lid_to_phone", {}):
                        self._unresolvable_lids.add(lid_jid)
                        try:
                            self.db.add_unresolvable_lid(lid_jid)
                        except Exception as exc:
                            logging.warning("[LID Resolution] add_unresolvable_lid failed: %s", exc)
                    if query_name:
                        contact_now = self.contacts.get(lid_jid, {})
                        has_name_now = contact_now.get("name") or contact_now.get("pushName")
                        if not has_name_now:
                            self._unresolvable_names.add(lid_jid)
                            try:
                                self.db.add_unresolvable_name(lid_jid)
                            except Exception as exc:
                                logging.warning("[LID Resolution] add_unresolvable_name failed: %s", exc)
                time.sleep(0.5)

        if updated_contacts:
            try:
                self.db.upsert_contacts_batch(updated_contacts)
            except Exception as e:
                logging.error(f"[LID Resolution] Error saving contacts incrementally: {e}")
                self.save_data(self.chats, self.contacts)
        wx.CallAfter(self._schedule_set_chats)
        if hasattr(self, "conversations_panel"):
            wx.CallAfter(self.conversations_panel.refresh_active_conversation_messages)

    def get_contact_profile(self, jid: str) -> dict:
        """Fetch contact profile from WPPConnect (runs on background thread)."""
        original_jid = jid
        if jid.endswith("@lid"):
            resolved = getattr(self, "_lid_to_phone", {}).get(jid, "")
            if resolved:
                jid = resolved
            else:
                # Only query if not marked as unresolvable
                if jid not in getattr(self, "_unresolvable_lids", set()):
                    # Resolve mapping via API before querying profile
                    self.resolve_lid_jids_via_api([original_jid])
                    resolved = getattr(self, "_lid_to_phone", {}).get(original_jid, "")
                    if resolved:
                        jid = resolved
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact/{jid}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            logging.info(f"[get_contact_profile] Querying for {original_jid} (using JID: {jid}). Response status: {r.status_code}")
            if r.status_code in (200, 201):
                res = r.json() or {}
                logging.info(f"[get_contact_profile] API Response for {original_jid}: {res}")
                res_data = res.get("response", {})
                if not isinstance(res_data, dict):
                    res_data = {}
                
                # If queried directly with @lid, check if we got back a canonical @s.whatsapp.net JID
                if original_jid.endswith("@lid") and jid.endswith("@lid"):
                    canonical_jid = self._normalize_jid(res_data.get("id", {}).get("_serialized") or res_data.get("id") or "")
                    if canonical_jid and canonical_jid.endswith("@s.whatsapp.net"):
                        logging.info(f"[get_contact_profile] SUCCESS: Mapped {original_jid} to {canonical_jid} via profile query")
                        if not hasattr(self, "_lid_to_phone"):
                            self._lid_to_phone = {}
                        if not hasattr(self, "_phone_to_lid"):
                            self._phone_to_lid = {}
                        self._lid_to_phone[original_jid] = canonical_jid
                        self._phone_to_lid[canonical_jid] = original_jid
                        
                        # Trigger UI refresh and save mapped JIDs
                        wx.CallAfter(self._schedule_set_chats)
                        try:
                            self.db.set_lid_mapping(original_jid, canonical_jid)
                        except Exception as e:
                            logging.error(f"[get_contact_profile] Error saving mapping incrementally: {e}")
                            self.save_data(self.chats, self.contacts)
                # The contact endpoint's top-level "status" is the API result
                # ("success"), NOT the contact's About text. Fetch the real
                # About/bio from the dedicated profile-status endpoint and expose
                # it under a clean key the dialog can read without ambiguity.
                res["aboutText"] = self.get_profile_about(jid)
                res["lastSeenTs"] = self.get_last_seen(jid)
                return res
        except Exception as e:
            logging.exception(f"[get_contact_profile] Error querying for {original_jid}: {e}")
        return {}

    def get_last_seen(self, jid: str):
        """Return a contact's last-seen Unix timestamp via /last-seen, or None.

        More reliable than waiting for a presence.update event, which only fires
        if the contact changes state after we subscribe. Returns None when the
        contact hides last-seen or it is unavailable.
        """
        if not jid or jid.endswith("@lid") or jid.endswith("@g.us"):
            return None
        phone = jid.split("@")[0]
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/last-seen/{phone}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code not in (200, 201):
                return None
            resp = (r.json() or {}).get("response")
            if isinstance(resp, dict):
                resp = resp.get("t") or resp.get("lastSeen")
            if isinstance(resp, bool) or resp in (None, 0):
                return None
            try:
                ts = int(resp)
            except (TypeError, ValueError):
                return None
            # WhatsApp sometimes returns timestamps in ms.
            if ts > 1_000_000_000_000:
                ts //= 1000
            return ts if ts > 0 else None
        except Exception:
            return None

    def get_profile_about(self, jid: str) -> str:
        """Return a contact's WhatsApp About/bio text via /profile-status, or ''."""
        if not jid or jid.endswith("@lid"):
            return ""
        phone = jid.replace("@s.whatsapp.net", "@c.us")
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/profile-status/{phone}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code not in (200, 201):
                return ""
            resp = (r.json() or {}).get("response")
            # getStatus returns either a string or {id, status: "<about>"}.
            if isinstance(resp, dict):
                about = resp.get("status") or resp.get("about") or ""
            else:
                about = resp or ""
            about = str(about).strip()
            # Guard against the endpoint echoing an API status word.
            if about.lower() in ("success", "error", "none", "null"):
                return ""
            return about
        except Exception:
            return ""

    def subscribe_presence(self, jid: str):
        """Subscribe to presence events for a contact via WPPConnect API (non-blocking)."""
        if not jid or jid.endswith("@newsletter"):
            return
        
        # Translate phone JID to LID JID if available to prevent "Chat not found" errors
        # on modern WhatsApp Web clients.
        phone_to_lid = getattr(self, "_phone_to_lid", {})
        target_jid = phone_to_lid.get(jid, jid)
        
        def _api():
            is_group = target_jid.endswith("@g.us")
            is_lid = target_jid.endswith("@lid")
            phone = target_jid.replace("@s.whatsapp.net", "@c.us")
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/subscribe-presence"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            try:
                requests.post(url, json={"phone": phone, "isGroup": is_group, "isLid": is_lid}, headers=headers, timeout=10)
            except Exception:
                pass
        threading.Thread(target=_api, daemon=True).start()

    def start_background_lid_resolution(self):
        def _resolve_lids():
            logging.info("[start_background_lid_resolution] Waiting for WhatsApp connection...")
            waited = 0
            while waited < 30:
                if getattr(self, "_wa_connected", False):
                    break
                time.sleep(1)
                waited += 1
            
            if not getattr(self, "_wa_connected", False):
                logging.info("[start_background_lid_resolution] Aborting: WhatsApp not connected after 30 seconds.")
                return
                
            raw_lids = set()
            # 1. Collect JIDs from chats keys
            for jid in list(self.chats.keys()):
                if jid.endswith("@lid"):
                    raw_lids.add(jid)
            # 2. Collect JIDs from contacts keys
            for jid in list(self.contacts.keys()):
                if jid.endswith("@lid"):
                    raw_lids.add(jid)

            active_chat_lids = set()
            for jid in list(self.chats.keys()):
                if jid.endswith("@lid"):
                    active_chat_lids.add(jid)

            lids_to_resolve = []
            lid_to_phone = getattr(self, "_lid_to_phone", {})
            unresolvable = getattr(self, "_unresolvable_lids", set())
            unresolvable_names = getattr(self, "_unresolvable_names", set())
            
            # Helper to filter whether a LID needs resolution
            def _needs_resolve(jid):
                if jid not in lid_to_phone and jid not in unresolvable:
                    return True
                contact = self.contacts.get(jid, {})
                has_name = contact.get("name") or contact.get("pushName")
                if not has_name and jid not in unresolvable_names:
                    return True
                return False

            # First: Add active chat LIDs that need resolution
            for jid in sorted(active_chat_lids):
                if _needs_resolve(jid):
                    lids_to_resolve.append(jid)
            
            # Second: Add remaining collected LIDs that need resolution
            other_lids = raw_lids - active_chat_lids
            for jid in sorted(other_lids):
                if _needs_resolve(jid):
                    lids_to_resolve.append(jid)
            
            if not lids_to_resolve:
                logging.info("[start_background_lid_resolution] No @lid JIDs to resolve.")
                return
                
            logging.info(f"[start_background_lid_resolution] START: Found {len(lids_to_resolve)} @lid JIDs to resolve in background.")
            batch_size = 25
            for i in range(0, len(lids_to_resolve), batch_size):
                if not getattr(self, "_wa_connected", False):
                    logging.info("[start_background_lid_resolution] Aborting resolution loop (WhatsApp disconnected)")
                    break
                batch = lids_to_resolve[i:i+batch_size]
                try:
                    logging.info(f"[start_background_lid_resolution] Querying batch of {len(batch)} JIDs...")
                    self.resolve_lid_jids_via_api(batch)
                    time.sleep(1.0)
                except Exception as e:
                    logging.error(f"[start_background_lid_resolution] Error JID batch: {e}")
            logging.info("[start_background_lid_resolution] COMPLETED background JID resolution loop.")
        
        threading.Thread(target=_resolve_lids, daemon=True).start()

    def get_group_info(self, jid: str) -> dict:
        """Fetch group metadata via GET /api/{session}/group-info/{groupId}"""
        url = (
            f"{self.wpp_server}:{self.wpp_port}"
            f"/api/{self.token}/group-info/{jid}"
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            logging.info(f"[get_group_info] status={r.status_code} for {jid}")
            if r.status_code in (200, 201):
                res_data = r.json() or {}
                response = res_data.get("response") or {}
                logging.info(f"[get_group_info] response type={type(response).__name__} keys={list(response.keys()) if isinstance(response, dict) else response}")
                return response if isinstance(response, dict) else {}
        except Exception as e:
            logging.error(f"[get_group_info] error: {e}")
        return {}

    # ── Block ─────────────────────────────────────────────────────────────────

    def block_contact(self, jid: str, action: str = "block"):
        """action: 'block' or 'unblock'"""
        endpoint = "block-contact" if action == "block" else "unblock-contact"
        url = (
            f"{self.wpp_server}:{self.wpp_port}"
            f"/api/{self.token}/{endpoint}"
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            requests.post(
                url, json={"phone": jid},
                headers=headers, timeout=10,
            )
        except Exception:
            pass

    # ── Mute ──────────────────────────────────────────────────────────────────

    def is_chat_muted(self, jid: str) -> bool:
        expiry = self._muted_chats.get(jid)
        if expiry is None:
            return False
        if expiry == -1:
            return True  # permanent
        return time.time() < expiry

    def mute_chat(self, jid: str, duration_secs: int):
        """duration_secs=-1 means mute permanently."""
        if duration_secs == -1:
            self._muted_chats[jid] = -1
        else:
            self._muted_chats[jid] = int(time.time()) + duration_secs
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("muted_chats", self._muted_chats)
        self._sync_mute_to_server(jid, duration_secs)

    def unmute_chat(self, jid: str):
        self._muted_chats.pop(jid, None)
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("muted_chats", self._muted_chats)
        self._sync_mute_to_server(jid, 0)

    def _sync_mute_to_server(self, jid: str, duration_secs: int):
        """Send mute/unmute to WPPConnect in a background thread. duration_secs=0 = unmute."""
        def _do():
            try:
                if duration_secs == 0:
                    wpp_time, wpp_type = 0, "hours"
                elif duration_secs == -1:
                    wpp_time, wpp_type = 8766, "hours"  # ~1 year (closest to permanent)
                else:
                    wpp_time = max(1, duration_secs // 3600)
                    wpp_type = "hours"
                url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-mute"
                payload = {
                    "phone": jid,
                    "time": wpp_time,
                    "type": wpp_type,
                    "isGroup": jid.endswith("@g.us"),
                }
                requests.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=10,
                )
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Archive ───────────────────────────────────────────────────────────────

    def is_chat_archived(self, jid: str) -> bool:
        chat = self.chats.get(jid, {})
        return (jid in self._archived_chats 
                or chat.get("archived") is True 
                or chat.get("archive") is True
                or str(chat.get("archived")).lower() == "true"
                or str(chat.get("archive")).lower() == "true")


    def archive_chat(self, jid: str):
        if jid not in self._archived_chats:
            self._archived_chats.add(jid)
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("archived_chats", list(self._archived_chats))
        self._schedule_set_chats()
        self._api_archive_chat(jid, archive=True)

    def unarchive_chat(self, jid: str):
        if jid in self._archived_chats:
            self._archived_chats.remove(jid)
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("archived_chats", list(self._archived_chats))
        self._schedule_set_chats()
        self._api_archive_chat(jid, archive=False)

    def _api_archive_chat(self, jid: str, archive: bool):
        url = (f"{self.wpp_server}:{self.wpp_port}"
               f"/api/{self.token}/archive-chat")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        # Prefer `@lid` for API operations if mapped, as WPPConnect expects it
        api_jid = jid
        if not api_jid.endswith("@lid"):
            alt_lid = getattr(self, "_phone_to_lid", {}).get(self._normalize_jid(jid), "")
            if alt_lid:
                api_jid = alt_lid

        try:
            resp = requests.post(
                url,
                json={"phone": api_jid, "value": archive, "isGroup": jid.endswith("@g.us")},
                headers=headers,
                timeout=10,
            )
            if not resp.ok:
                print(f"[archive_chat] API error {resp.status_code} for {jid} (api_jid: {api_jid}): {resp.text[:200]}")
        except Exception as exc:
            print(f"[archive_chat] Request failed for {jid}: {exc}")

    # ── Delete / Clear ────────────────────────────────────────────────────────

    def is_chat_deleted(self, jid: str) -> bool:
        return jid in self._deleted_chats

    def delete_chat_local(self, jid: str):
        if jid not in self._deleted_chats:
            self._deleted_chats.add(jid)
        if jid.endswith("@s.whatsapp.net"):
            lid_jid = getattr(self, "_phone_to_lid", {}).get(jid)
            if lid_jid and lid_jid not in self._deleted_chats:
                self._deleted_chats.add(lid_jid)
        elif jid.endswith("@lid"):
            phone_jid = getattr(self, "_lid_to_phone", {}).get(jid)
            if phone_jid and phone_jid not in self._deleted_chats:
                self._deleted_chats.add(phone_jid)
        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("deleted_chats", list(self._deleted_chats))
        self.chats.pop(jid, None)
        self._schedule_save()
        self._schedule_set_chats()

    def clear_chat_messages_local(self, jid: str):
        chat = self.chats.get(jid)
        if chat:
            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = []
            # Also drop the last-message preview and unread badge so the now-empty
            # conversation is filtered out of the list immediately (otherwise a
            # stale lastMessage kept it visible).
            chat["lastMessage"] = None
            chat["unreadCount"] = 0
            self.settings.setdefault("cleared_chats", {})[jid] = int(time.time())
            self._schedule_save(dirty_jid=jid)
            self.save_settings()

    def delete_chat(self, jid: str):
        """Delete chat locally and sync to WPPConnect API."""
        self.delete_chat_local(jid)
        def _api():
            phone = jid.replace("@s.whatsapp.net", "@c.us")
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/delete-chat"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            try:
                r = requests.post(
                    url, json={"phone": [phone], "isGroup": phone.endswith("@g.us")},
                    headers=headers, timeout=10,
                )
                if not r.ok:
                    logging.warning("[delete_chat] API error %s for %s: %s", r.status_code, jid, r.text[:200])
            except Exception as exc:
                logging.warning("[delete_chat] Request failed for %s: %s", jid, exc)
        threading.Thread(target=_api, daemon=True).start()

    def clear_chat(self, jid: str):
        """Clear chat messages locally and sync to WPPConnect API."""
        self.clear_chat_messages_local(jid)
        def _api():
            phone = jid.replace("@s.whatsapp.net", "@c.us")
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/clear-chat"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            try:
                r = requests.post(
                    url, json={"phone": [phone], "isGroup": phone.endswith("@g.us")},
                    headers=headers, timeout=10,
                )
                if not r.ok:
                    logging.warning("[clear_chat] API error %s for %s: %s", r.status_code, jid, r.text[:200])
            except Exception as exc:
                logging.warning("[clear_chat] Request failed for %s: %s", jid, exc)
        threading.Thread(target=_api, daemon=True).start()

    def _resolve_jid_for_chat_state(self, jid: str) -> str:
        """Resolve to @c.us format without doing LID mapping to avoid inconsistency and potential crashes."""
        if not jid:
            return jid
        if jid.endswith(("@g.us", "@broadcast")):
            return jid.replace("@s.whatsapp.net", "@c.us")
        if jid.endswith("@lid"):
            phone_net = getattr(self, "_lid_to_phone", {}).get(jid, jid)
            if phone_net:
                return phone_net.replace("@s.whatsapp.net", "@c.us")
            return jid
        return jid.replace("@s.whatsapp.net", "@c.us")

    def send_typing_status(self, jid: str, value: bool, is_group: bool = False):
        """Notify WPPConnect that the user started or stopped typing."""
        def _api():
            phone = self._resolve_jid_for_chat_state(jid)
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/typing"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            try:
                requests.post(
                    url,
                    json={"phone": phone, "value": value, "isGroup": is_group},
                    headers=headers,
                    timeout=10,
                )
            except Exception:
                pass
        threading.Thread(target=_api, daemon=True).start()

    def send_recording_status(self, jid: str, value: bool, is_group: bool = False):
        """Notify WPPConnect that the user started or stopped recording audio."""
        def _api():
            phone = self._resolve_jid_for_chat_state(jid)
            url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/recording"
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            try:
                requests.post(
                    url,
                    json={"phone": phone, "duration": 0, "value": value, "isGroup": is_group},
                    headers=headers,
                    timeout=10,
                )
            except Exception:
                pass
        threading.Thread(target=_api, daemon=True).start()

    def _is_cleared_message(self, jid: str, msg: dict) -> bool:
        """
        True if `msg` predates the user's last "clear chat" action for `jid`.

        Clearing a conversation records a cutoff timestamp in
        settings["cleared_chats"]. Without consulting it, the next history sync
        (or a WebSocket re-delivery) would simply repopulate the chat, making the
        clear appear to do nothing. Messages received after the clear have a
        newer timestamp and are kept.
        """
        cutoff = self.settings.get("cleared_chats", {}).get(jid)
        if not cutoff:
            return False
        try:
            ts = int(msg.get("messageTimestamp", 0) or 0)
        except (ValueError, TypeError):
            return False
        return bool(ts) and ts < cutoff

    # ── Pin ───────────────────────────────────────────────────────────────────

    def is_chat_pinned(self, jid: str) -> bool:
        return jid in self._pinned_chats

    def pin_chat(self, jid: str):
        normalized = self._normalize_jid(jid)
        if normalized not in self._pinned_chats:
            self._pinned_chats.add(normalized)
        # Also pin the alternate JID if present
        if normalized.endswith("@lid"):
            alt = getattr(self, "_lid_to_phone", {}).get(normalized, "")
            if alt:
                self._pinned_chats.add(self._normalize_jid(alt))
        else:
            alt = getattr(self, "_phone_to_lid", {}).get(normalized, "")
            if alt:
                self._pinned_chats.add(alt)

        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("pinned_chats", list(self._pinned_chats))
        self._schedule_set_chats()
        self._sync_pin_to_server(jid, pinned=True)

    def unpin_chat(self, jid: str):
        normalized = self._normalize_jid(jid)
        if normalized in self._pinned_chats:
            self._pinned_chats.remove(normalized)
        # Also unpin the alternate JID if present
        if normalized.endswith("@lid"):
            alt = getattr(self, "_lid_to_phone", {}).get(normalized, "")
            if alt:
                self._pinned_chats.discard(self._normalize_jid(alt))
        else:
            alt = getattr(self, "_phone_to_lid", {}).get(normalized, "")
            if alt:
                self._pinned_chats.discard(alt)

        if hasattr(self, "db") and self.db is not None:
            self.db.set_metadata_json("pinned_chats", list(self._pinned_chats))
        self._schedule_set_chats()
        self._sync_pin_to_server(jid, pinned=False)

    def _sync_pin_to_server(self, jid: str, pinned: bool):
        def _do():
            try:
                # Prefer `@lid` for API operations if mapped, as WPPConnect expects it
                api_jid = jid
                if not api_jid.endswith("@lid"):
                    alt_lid = getattr(self, "_phone_to_lid", {}).get(self._normalize_jid(jid), "")
                    if alt_lid:
                        api_jid = alt_lid

                if api_jid.endswith("@s.whatsapp.net"):
                    api_jid = api_jid.rsplit("@", 1)[0] + "@c.us"
                url = (f"{self.wpp_server}:{self.wpp_port}"
                       f"/api/{self.token}/pin-chat")
                payload = {
                    "phone": [api_jid],
                    "state": "true" if pinned else "false",
                    "isGroup": jid.endswith("@g.us"),
                }
                resp = requests.post(
                    url, json=payload,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=10,
                )
                if not resp.ok:
                    logging.warning("[pin_chat] API error %s for %s (api_jid: %s): %s",
                                    resp.status_code, jid, api_jid, resp.text[:200])
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Group ─────────────────────────────────────────────────────────────────

    def leave_group(self, jid: str):
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/leave-group"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            requests.post(url, json={"groupId": jid}, headers=headers, timeout=10)
        except Exception:
            pass
        # Archive instead of delete so the message history is preserved locally.
        self.archive_chat(jid)

    def create_group(self, name: str, participants: list) -> tuple:
        """
        Create a WhatsApp group with the given name and participant numbers.
        participants: list of phone number or JID strings (e.g. ["5511999999999@s.whatsapp.net", "63977983840477@lid"])
        Returns (True, group_jid) on success, (False, error_message) on failure.
        """
        # Normalize participant JIDs for WPPConnect
        normalized_participants = []
        for p in participants:
            if "@" in p:
                p_norm = p.replace("@s.whatsapp.net", "@c.us")
                normalized_participants.append(p_norm)
            else:
                # Default to c.us for raw typed digits (phone numbers)
                normalized_participants.append(f"{p}@c.us")

        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/create-group"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "name":         name,
            "participants": normalized_participants,
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code in (200, 201):
                resp = r.json().get("response", {})
                gid = resp.get("gid", {})
                if isinstance(gid, dict):
                    gid = gid.get("_serialized", "")
                return True, gid or ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)

    def add_group_members(self, group_jid: str, participant_jids: list) -> tuple:
        """
        Add one or more participants to a group.
        Returns (True, "") on success, (False, error_message) on failure.
        """
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/add-participant-group"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "groupId":      group_jid,
            "participantId": [j if "@" in j else f"{j}@c.us" for j in participant_jids],
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
        Upload a file as a media message via multipart/form-data.
        Avoids base64 encoding so payloads stay at true file size
        (no 33 % overhead, no JSON body-size limit).
        media_type: 'image' | 'video' | 'audio' | 'document'
        """
        # Always resolve phone JID to @lid JID if available so WPPConnect finds the open chat.
        remote_jid = self._resolve_jid_for_send(remote_jid)
        import mimetypes
        try:
            file_size = os.path.getsize(file_path)
        except Exception as exc:
            logging.error("[send_media] failed to stat file %s: %s", file_path, exc)
            return False
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        filename = os.path.basename(file_path)
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/send-file"
        # Authorization only — Content-Type is set automatically by requests
        # when using files= (multipart/form-data with correct boundary).
        headers = {"Authorization": f"Bearer {self.token}"}
        phone_val = remote_jid
        if phone_val.endswith("@s.whatsapp.net"):
            phone_val = phone_val.replace("@s.whatsapp.net", "@c.us")
        # Force WPPConnect to send the chosen WhatsApp message type instead of
        # its mimetype-based "auto-detect", which otherwise sends e.g. an .mp3
        # picked from the "Document" menu as a playable audio message, or a
        # .jpg/.png as a photo, regardless of what the user actually selected.
        _wpp_type = {
            "image": "image", "video": "video",
            "audio": "audio", "document": "document",
        }.get(media_type, "document")
        data = {
            "phone":    [phone_val],
            "filename": filename,
            "caption":  caption,
            "isGroup":  phone_val.endswith("@g.us"),
            "type":     _wpp_type,
        }
        if quoted:
            quoted_id = self._serialize_quoted_id(quoted, fallback_jid=remote_jid)
            if quoted_id:
                data["quotedMessageId"] = quoted_id
        # Scale timeout with file size: at least 1 s per 100 KB, min 120 s, max 30 min.
        timeout = max(120, file_size // (100 * 1024))
        timeout = min(timeout, 1800)
        try:
            with open(file_path, "rb") as fh:
                r = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (filename, fh, mime)},
                    timeout=timeout,
                )
            if r.status_code in (200, 201):
                body = r.json()
                resp = body.get("response", body)
                if isinstance(resp, list) and resp:
                    resp = resp[0]
                msg_id = ""
                if isinstance(resp, dict):
                    msg_id = resp.get("id") or resp.get("key", {}).get("id") or ""
                    if isinstance(msg_id, dict):
                        msg_id = msg_id.get("_serialized", "")
                    if msg_id:
                        parts = msg_id.split("_")
                        msg_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)
                if msg_id:
                    return msg_id
                return {"ok": True, "error": "ID not found in response"}
            err = f"HTTP {r.status_code}"
            try:
                body = r.json()
                detail = (body.get("message") or body.get("error") or "")
                if detail:
                    err = f"{err}: {detail}"
            except Exception:
                if r.text:
                    err = f"{err}: {r.text[:200]}"
            logging.error("[send_media] %s for %s (%s, %.1f MB): %s",
                          err, remote_jid, filename, file_size / (1024*1024), r.text[:300])
            # 5xx responses are transient server/puppeteer hiccups — notably the
            # WPPConnect "ProtocolError: Promise was collected" that strikes large
            # uploads under load. Retry those; treat 4xx as permanent.
            retryable = r.status_code >= 500
            return {"ok": False, "error": err, "retry": retryable}
        except Exception as exc:
            # Timeouts and connection errors are transient — let the queue retry.
            logging.error("[send_media] request exception for %s (%s): %s", remote_jid, filename, exc)
            return {"ok": False, "error": str(exc)[:200], "retry": True}

    def save_contact_to_phone(self, phone: str, name: str,
                              surname: str = "", sync: bool = True) -> bool:
        """
        Save a contact to WhatsApp (and, when sync is True, to the device
        address book) via the WPPConnect add-new-contact endpoint, which calls
        WPP.contact.save(..., {syncAddressBook}). Returns True on success.
        """
        digits = "".join(c for c in str(phone) if c.isdigit())
        if not digits or not name:
            return False
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/add-new-contact"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "phone":             digits,
            "name":              name,
            "surname":           surname or "",
            "syncToAddressbook": bool(sync),
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=20)
            if r.status_code in (200, 201):
                return True
            logging.error("[save_contact_to_phone] HTTP %s: %s",
                          r.status_code, r.text[:300])
            return False
        except Exception as exc:
            logging.error("[save_contact_to_phone] exception: %s", exc)
            return False

    def send_contact_attachment(self, remote_jid: str, contact_info: dict,
                                quoted: dict = None) -> bool:
        """Send a contact card as an attachment."""
        # Always resolve phone JID to @lid JID if available so WPPConnect finds the open chat.
        remote_jid = self._resolve_jid_for_send(remote_jid)
        is_group = remote_jid.endswith("@g.us")
        if is_group:
            remote_jid = remote_jid.split("@")[0]
        name = contact_info.get("pushName") or ""
        jid = contact_info.get("remoteJid", "")
        phone_raw = jid.split("@")[0] if "@" in jid else jid
        url = f"{self.wpp_server}:{self.wpp_port}/api/{self.token}/contact-vcard"
        payload = {
            "phone":       [remote_jid],
            "isGroup":     is_group,
            "contactsId":  [f"{phone_raw}@c.us"],
        }
        if quoted:
            quoted_id = self._serialize_quoted_id(quoted, fallback_jid=remote_jid)
            if quoted_id:
                payload["quotedMessageId"] = quoted_id
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                try:
                    resp = r.json().get("response", {})
                    if isinstance(resp, list) and resp:
                        resp = resp[0]
                    return (resp or {}).get("id") or True
                except Exception:
                    return True
            return None
        except Exception:
            return None

    # ── Message edit / delete-for-everyone ────────────────────────────────────

    def edit_message(self, remote_jid: str, message_id: str, new_text: str):
        """Send an edited message via POST /api/session/edit-message."""
        lid_jid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid

        # Find the message key in records (_serialize_msg_id falls back to
        # our own JID as the group participant when it's missing here).
        msg_key = {"id": message_id, "fromMe": True}
        chat = self.chats.get(remote_jid)
        if chat:
            records = chat.get("messages", {}).get("messages", {}).get("records", [])
            for r in records:
                if r.get("key", {}).get("id") == message_id:
                    msg_key = r.get("key", {})
                    break

        full_id = self._serialize_msg_id(remote_jid, msg_key)
        url = (
            f"{self.wpp_server}:{self.wpp_port}"
            f"/api/{self.token}/edit-message"
        )
        payload = {
            "id":      full_id,
            "newText": new_text,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code not in (200, 201):
                logging.error("[edit_message] HTTP %s for %s: %s",
                              r.status_code, full_id, r.text[:300])
        except Exception as exc:
            logging.error("[edit_message] exception for %s: %s", full_id, exc)

    def delete_message_for_everyone(self, remote_jid: str, msg_key: dict) -> bool:
        """Revoke a message for everyone via POST /api/session/delete-message.

        Returns True only when the server confirms the revoke. WPP.chat.delete-
        Message resolves the target through getMessageById, which needs the FULL
        serialized id (`<fromMe>_<chatId>_<id>[_<participant>]`) — a hardcoded
        `true_` prefix made it fail to find (and therefore not revoke) messages
        that weren't your own, and revoke only fires when the message is yours or
        you are a group admin.
        """
        lid_jid = getattr(self, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid
        url = (
            f"{self.wpp_server}:{self.wpp_port}"
            f"/api/{self.token}/delete-message"
        )
        # WhatsApp chat ids use @c.us, not @s.whatsapp.net. Both the chat id
        # embedded in the serialized message id AND the `phone` field must use
        # the same normalized form, otherwise WPP.chat.deleteMessage cannot
        # resolve the chat and the revoke silently no-ops.
        chat_jid = remote_jid.replace("@s.whatsapp.net", "@c.us")
        full_id = self._serialize_msg_id(chat_jid, msg_key)

        payload = {
            "phone":     chat_jid,
            "isGroup":   chat_jid.endswith("@g.us"),
            "messageId": full_id,
            "onlyLocal": False,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                return True
            logging.error("[delete_for_everyone] HTTP %s for %s: %s",
                          r.status_code, full_id, r.text[:300])
            return False
        except Exception as exc:
            logging.error("[delete_for_everyone] exception for %s: %s", full_id, exc)
            return False

    def _preview_sender_from_jid(self, jid: str) -> str:
        """
        Resolve a participant JID to a display name for chat list previews.
        Tries contacts dict (with @lid bridging), then falls back to
        format_number on the phone-number JID. Never returns a bare @lid string.
        """
        if not jid:
            return ""
        def _get_contact_tolerant(j):
            if not j:
                return None
            c = self.contacts.get(j)
            if c:
                return c
            if j.endswith("@s.whatsapp.net"):
                phone = j.split("@")[0]
                if phone.startswith("55"):
                    if len(phone) == 13 and phone[4] == "9":
                        alt = phone[:4] + phone[5:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
                    elif len(phone) == 12:
                        alt = phone[:4] + "9" + phone[4:] + "@s.whatsapp.net"
                        return self.contacts.get(alt)
            return None

        ppm = getattr(self, "_presence_pushname_map", {})
        phone_jid = ""
        contact = _get_contact_tolerant(jid)
        if not contact and jid.endswith("@lid"):
            phone_jid = getattr(self, "_lid_to_phone", {}).get(jid, "")
            if phone_jid:
                contact = _get_contact_tolerant(phone_jid)
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
            return format_number(phone_jid) if phone_jid else self.i18n.t("unnamed_participant")
        if jid.endswith("@g.us"):
            return self.i18n.t("unknown_group")
        return format_number(jid)

    def _last_msg_preview(self, chat: dict) -> str:
        """
        Build a compact last-message description for the conversations list.
        Returns "" if no messages are found.
        Format: "[você: ]{content} {timestamp}"
        """
        records_wrapper = chat.get("messages") or {}
        records = []
        if isinstance(records_wrapper, dict):
            inner_wrapper = records_wrapper.get("messages") or {}
            if isinstance(inner_wrapper, dict):
                records = list(inner_wrapper.get("records") or [])
        if not records:
            return ""

        # Prefer supported user-facing message types for a cleaner preview
        supported_types = {
            "conversation",
            "extendedTextMessage",
            "imageMessage",
            "videoMessage",
            "audioMessage",
            "documentMessage",
            "stickerMessage",
            "contactMessage",
            "locationMessage",
            "liveLocationMessage",
            "pollCreationMessage",
            "buttonsMessage",
            "listMessage",
            "templateMessage",
            "interactiveMessage",
            "buttonsResponseMessage",
            "listResponseMessage",
            "protocolMessage",
            "reactionMessage",
        }
        def is_displayable(m):
            if not isinstance(m, dict):
                return False
            m_type = m.get("messageType", "")
            if m_type not in supported_types:
                return False
            if m_type == "protocolMessage":
                protocol = (m.get("message") or {}).get("protocolMessage") or {}
                p_type = protocol.get("type")
                return p_type in (3, "REVOKE", "revoke")
            return True

        def _get_ts(m):
            if not isinstance(m, dict):
                return 0
            val = int(m.get("timestamp", 0) or m.get("messageTimestamp", 0) or m.get("t", 0) or 0)
            return val // 1000 if val > 1_000_000_000_000 else val

        try:
            last = max(
                (m for m in records if is_displayable(m)),
                key=_get_ts,
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
                    ts_val = int(ts)
                    if ts_val > 1_000_000_000_000:
                        ts_val //= 1000
                    dt    = _dt.fromtimestamp(ts_val)
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
                sender_jid = last.get("participant") or p_key.get("participant", "") or p_key.get("remoteJid", "")
                push       = last.get("pushName", "")
                if sender_jid.endswith("@g.us") and push and push.isdigit():
                    sender_jid = f"{push}@s.whatsapp.net"
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
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "") or ""
            ext = msg_obj.get("extendedTextMessage") or {}
            mentioned = (
                (last.get("contextInfo") or {}).get("mentionedJid")
                or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
                or ext.get("contextInfo", {}).get("mentionedJid")
                or []
            )
            if isinstance(mentioned, list) and mentioned:
                for jid in mentioned:
                    if not isinstance(jid, str):
                        continue
                    if self._is_self_jid(jid):
                        name = "eu"
                    else:
                        if hasattr(self, "conversations_panel"):
                            name = self.conversations_panel._get_participant_name(jid)
                        else:
                            name = ""
                    
                    lid_local = jid.rsplit("@", 1)[0]
                    _lid_map = getattr(self, "_lid_to_phone", {})
                    phone_jid = _lid_map.get(jid, "") if jid.endswith("@lid") else ""
                    phone = phone_jid.split("@")[0] if phone_jid else jid.split("@")[0]
                    
                    placeholder = None
                    if f"@{lid_local}" in content:
                        placeholder = lid_local
                    elif phone and f"@{phone}" in content:
                        placeholder = phone
                        
                    if not placeholder:
                        continue
                        
                    if name and name != placeholder and name != jid:
                        content = content.replace(f"@{placeholder}", f"@{name}")
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
            doc      = msg_obj.get("documentMessage") or {}
            filename = doc.get("fileName") or doc.get("title") or ""
            size_bytes = doc.get("fileLength")
            size_str = ""
            if size_bytes:
                try:
                    sz  = int(size_bytes)
                    sep = i18n.t("decimal_separator")
                    if sz < 1024:
                        size_str = f"{sz} b"
                    elif sz < 1024 ** 2:
                        size_str = f"{sz / 1024:.1f}".replace(".", sep) + " kb"
                    elif sz < 1024 ** 3:
                        size_str = f"{sz / 1024 ** 2:.1f}".replace(".", sep) + " mb"
                    else:
                        size_str = f"{sz / 1024 ** 3:.1f}".replace(".", sep) + " gb"
                except (ValueError, TypeError):
                    pass
            parts = [i18n.t("document")]
            if filename:
                parts.append(filename)
            if size_str:
                parts.append(size_str)
            content = ", ".join(parts)
        elif msg_type == "stickerMessage":
            content = i18n.t("sticker")
        elif msg_type == "contactMessage":
            contact = msg_obj.get("contactMessage") or {}
            content = i18n.t("contact_message").format(
                name=contact.get("displayName") or ""
            )
        elif msg_type == "locationMessage":
            content = i18n.t("notif_location")
        elif msg_type == "pollCreationMessage":
            poll = msg_obj.get("pollCreationMessage") or {}
            name = poll.get("name") or ""
            content = f"📊 Enquete: {name}" if name else "📊 Enquete"
        elif msg_type == "buttonsMessage":
            content = "🔘 Botão"
        elif msg_type == "listMessage":
            content = "📋 Lista"
        elif msg_type == "templateMessage":
            content = "📝 Modelo"
        elif msg_type == "protocolMessage":
            protocol = msg_obj.get("protocolMessage") or {}
            p_type = protocol.get("type")
            if p_type in (3, "REVOKE", "revoke"):
                content = "Mensagem apagada"
            else:
                content = "⚙️ Mensagem do sistema"
        else:
            content = i18n.t("notif_unsupported")

        # Build time string
        ts = last.get("messageTimestamp")
        time_str = ""
        if ts:
            try:
                from datetime import datetime as _dt
                ts_val = int(ts)
                if ts_val > 1_000_000_000_000:
                    ts_val //= 1000
                dt    = _dt.fromtimestamp(ts_val)
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
            sender_prefix = self.self_reference_label() + ": "
        elif is_group:
            p_key      = last.get("key", {})
            sender_jid = last.get("participant") or p_key.get("participant") or p_key.get("remoteJid", "")
            push       = last.get("pushName", "")
            if sender_jid.endswith("@g.us") and push and push.isdigit():
                sender_jid = f"{push}@s.whatsapp.net"
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

    def _refresh_archived_chats_in_ui(self, arch_focused_jid: "str | None" = None):
        """Update the archived conversations list using SetItem when possible.

        Avoids DeleteAllItems() when JID order/count is unchanged so the
        archived panel's scroll position and focus are preserved.
        """
        if not hasattr(self, "archived_conversations_panel"):
            return
        panel = self.archived_conversations_panel
        arch_full_chats = list(getattr(panel, '_all_chats_list', panel.chats_list))
        arch_full_names = list(getattr(panel, '_all_chat_names', panel.chat_names))
        arch_lst = panel.conversations_list
        arch_filter = getattr(panel, '_conv_filter', 'all')

        new_arch_chats: list = []
        new_arch_names: list = []
        new_arch_texts: list = []
        for i, chat in enumerate(arch_full_chats):
            chat_jid = chat.get("remoteJid", "")
            unread_count = effective_unread_count(chat)
            if arch_filter == 'unread' and unread_count == 0:
                continue
            if arch_filter == 'groups' and not chat_jid.endswith("@g.us"):
                continue
            if arch_filter == 'individual' and chat_jid.endswith("@g.us"):
                continue
            name = arch_full_names[i] if i < len(arch_full_names) else ""
            unread = unread_count
            unread_str = (
                f" {unread} " + (self.i18n.t("unread_messages") if unread > 1 else self.i18n.t("unread_message"))
                if unread > 0 else ""
            )
            preview = self._last_msg_preview(chat)
            item_text = name + unread_str
            if item_text and preview:
                item_text += f" {preview}"
            new_arch_chats.append(chat)
            new_arch_names.append(name)
            new_arch_texts.append(item_text)

        new_arch_jids = [c.get("remoteJid", "") for c in new_arch_chats]
        _arch_displayed_jids = getattr(panel, '_displayed_jids', None)

        _arch_fast_path_ok = False
        if (
            _arch_displayed_jids is not None
            and _arch_displayed_jids == new_arch_jids
            and arch_lst.GetItemCount() == len(new_arch_jids)
        ):
            try:
                for idx, new_text in enumerate(new_arch_texts):
                    if arch_lst.GetItemText(idx, 0) != new_text:
                        arch_lst.SetItem(idx, 0, new_text)
                _arch_fast_path_ok = True
            except Exception:
                # See add_chats_to_ui(): don't retry SetItem on a stale index,
                # fall through to the full rebuild below instead.
                pass
        if _arch_fast_path_ok:
            panel.chats_list = new_arch_chats
            panel.chat_names = new_arch_names
            return

        arch_list_has_focus = (wx.Window.FindFocus() == arch_lst)
        arch_fi = arch_lst.GetFocusedItem()
        if arch_fi != -1:
            try:
                arch_lst.SetItemState(arch_fi, 0, wx.LIST_STATE_FOCUSED)
            except Exception:
                pass
        arch_lst.DeleteAllItems()
        for item_text in new_arch_texts:
            arch_lst.Append((item_text,))
        panel.chats_list = new_arch_chats
        panel.chat_names = new_arch_names
        panel._displayed_jids = new_arch_jids

        if new_arch_chats:
            target_idx = -1
            if arch_focused_jid:
                for i, chat in enumerate(new_arch_chats):
                    if chat.get("remoteJid") == arch_focused_jid:
                        target_idx = i
                        break
            if target_idx != -1:
                if arch_list_has_focus and arch_lst.GetFocusedItem() != target_idx:
                    arch_lst.Focus(target_idx)
                if not arch_lst.IsSelected(target_idx):
                    arch_lst.Select(target_idx)
                arch_lst.EnsureVisible(target_idx)
            elif not getattr(self, "_initial_sync_running", False):
                last_jid = getattr(panel, "_last_open_jid", "")
                target_idx = 0
                if last_jid:
                    for i, chat in enumerate(new_arch_chats):
                        if chat.get("remoteJid") == last_jid:
                            target_idx = i
                            break
                if arch_list_has_focus:
                    arch_lst.Focus(target_idx)
                arch_lst.Select(target_idx)
                arch_lst.EnsureVisible(target_idx)

    def add_chats_to_ui(self):
        """Rebuild the conversations list from the current chats data.

        Applies active search and conversation filter to both the wx.ListCtrl
        and the backing chats_list/chat_names arrays so that list indices are
        always consistent.  Without this sync the user would open the wrong
        conversation when a search was active.
        """
        search       = self.conversations_panel.search_field.GetValue().strip().lower()
        conv_filter  = getattr(self.conversations_panel, '_conv_filter', 'all')

        # Used below to tell "the same filtered view just lost an item" (where
        # reusing the old row position to keep focus nearby makes sense) apart
        # from "the active filter/search changed" (where the old row position
        # belongs to a different, unrelated list and must not be reused).
        _filter_or_search_changed = (
            getattr(self, "_last_conv_filter_key", None) != (conv_filter, search)
        )
        self._last_conv_filter_key = (conv_filter, search)

        # Always start from the full sorted lists saved by set_chats() so
        # that restoring the window or clearing a search shows all chats.
        full_chats = list(getattr(self.conversations_panel, '_all_chats_list',
                                  self.conversations_panel.chats_list))
        full_names = list(getattr(self.conversations_panel, '_all_chat_names',
                                  self.conversations_panel.chat_names))

        lst = self.conversations_panel.conversations_list

        # Save focused JID before any potential modification (used by both paths).
        focused_idx = lst.GetFocusedItem()
        focused_jid = getattr(self.conversations_panel, '_preserved_focused_jid', None)
        self.conversations_panel._preserved_focused_jid = None  # consume
        if focused_jid is None and focused_idx != -1 and 0 <= focused_idx < len(self.conversations_panel.chats_list):
            focused_jid = self.conversations_panel.chats_list[focused_idx].get("remoteJid")

        # Save currently focused archived chat JID if archived panel is present
        arch_focused_jid = None
        if hasattr(self, "archived_conversations_panel"):
            arch_lst = self.archived_conversations_panel.conversations_list
            arch_focused_idx = arch_lst.GetFocusedItem()
            arch_focused_jid = getattr(self.archived_conversations_panel, '_preserved_focused_jid', None)
            self.archived_conversations_panel._preserved_focused_jid = None  # consume
            if arch_focused_jid is None and arch_focused_idx != -1 and 0 <= arch_focused_idx < len(self.archived_conversations_panel.chats_list):
                arch_focused_jid = self.archived_conversations_panel.chats_list[arch_focused_idx].get("remoteJid")

        # ── Content fingerprint: skip rebuild when nothing visible changed ──
        _fp_rows: list[tuple] = []
        for _i, _chat in enumerate(full_chats):
            _jid  = _chat.get("remoteJid", "")
            _nm   = full_names[_i] if _i < len(full_names) else ""
            _unrd = effective_unread_count(_chat)
            # NOTE: chat["lastMessage"] is only ever set by get_remote_chats()
            # at sync time — on_new_message() (the WebSocket new-message path)
            # appends to chat["messages"]["messages"]["records"] but never
            # touches "lastMessage". Fingerprinting on "lastMessage" therefore
            # never changes for messages that arrive live, so the row's
            # last-message preview silently stops updating in real time
            # (most visible for the currently-open conversation, where
            # unreadCount also stays 0 and so doesn't bust the fingerprint
            # either). Track the actual records list instead.
            _records = (_chat.get("messages", {}) or {}).get("messages", {}).get("records", [])
            _lid  = (
                len(_records),
                (_records[-1].get("key", {}) or {}).get("id", "") if _records else "",
            )
            if conv_filter == "unread" and _unrd == 0:
                continue
            if conv_filter == "groups" and not _jid.endswith("@g.us"):
                continue
            if conv_filter == "individual" and _jid.endswith("@g.us"):
                continue
            if search and search not in _nm.lower():
                continue
            _fp_rows.append((_jid, _nm, _unrd, _lid))
        _fp = hash((conv_filter, search, tuple(_fp_rows)))
        if _fp == getattr(self, "_chats_ui_fp", None):
            return  # visible list unchanged — skip rebuild entirely
        self._chats_ui_fp = _fp

        # Pre-compute the new display list (filtering + item text) so we can
        # choose between a lightweight SetItem path and a full rebuild.
        def _build_item_text(chat, name):
            chat_jid = chat.get("remoteJid", "")
            unread = effective_unread_count(chat)
            unread_str = (
                f" {unread} " + (self.i18n.t("unread_messages") if unread > 1 else self.i18n.t("unread_message"))
                if unread > 0 else ""
            )
            preview = self._last_msg_preview(chat)
            text = name + unread_str
            if preview:
                text += f" {preview}"
            chat_jid_norm = self._normalize_jid(chat_jid) if chat_jid else ""
            if chat_jid_norm:
                presence_label = self._presence_label_for_chat(chat_jid_norm, chat_jid_norm.endswith("@g.us"))
                if presence_label:
                    text += f" {presence_label}"
            if chat_jid_norm and self.is_chat_muted(chat_jid_norm):
                text += f" ({self.i18n.t('muted')})"
            return text

        displayed_chats: list = []
        displayed_names: list = []
        new_item_texts: list = []
        for i, chat in enumerate(full_chats):
            name     = full_names[i]
            chat_jid = chat.get("remoteJid", "")
            if conv_filter == 'unread' and effective_unread_count(chat) == 0:
                continue
            if conv_filter == 'groups' and not chat_jid.endswith("@g.us"):
                continue
            if conv_filter == 'individual' and chat_jid.endswith("@g.us"):
                continue
            if search and search not in name.lower():
                continue
            displayed_chats.append(chat)
            displayed_names.append(name)
            new_item_texts.append(_build_item_text(chat, name))

        # ── SetItem path: same JIDs in same order — only text may have changed ──
        # Avoids DeleteAllItems() entirely, keeping scroll position and focus intact.
        # NOTE: chats_list was already overwritten by _apply_chat_lists before this
        # function runs, so we track what's truly rendered via _displayed_jids.
        new_jids = [c.get("remoteJid", "") for c in displayed_chats]
        _displayed_jids = getattr(self.conversations_panel, '_displayed_jids', None)
        _fast_path_ok = False
        if (
            _displayed_jids is not None
            and _displayed_jids == new_jids
            and lst.GetItemCount() == len(new_jids)
        ):
            try:
                for idx, new_text in enumerate(new_item_texts):
                    if lst.GetItemText(idx, 0) != new_text:
                        lst.SetItem(idx, 0, new_text)
                _fast_path_ok = True
            except Exception:
                # The underlying Win32 list control rejected an index that
                # GetItemCount() claimed was valid (observed as "Couldn't
                # retrieve information about list control item N"). Don't
                # retry SetItem blindly — fall through to the full rebuild
                # below, which resyncs the control from scratch.
                pass
        if _fast_path_ok:
            self.conversations_panel.chats_list = displayed_chats
            self.conversations_panel.chat_names = displayed_names
            # _displayed_jids stays the same (JIDs didn't change)
            # Refresh archived panel via the same SetItem logic
            if hasattr(self, "archived_conversations_panel"):
                self._refresh_archived_chats_in_ui(arch_focused_jid)
            return

        # ── Full rebuild path: JID order or count changed ────────────────────
        focus_allowed = self._allow_ui_focus_changes()
        _lst_had_focus = (wx.Window.FindFocus() is lst)
        if _lst_had_focus:
            # Set focus to parent panel temporarily to prevent OS from auto-focusing
            # item 0 during DeleteAllItems/Append when the control has focus.
            self.conversations_panel.SetFocus()
        if focused_idx != -1:
            try:
                # Clear focus state before DeleteAllItems to prevent NVDA COMError/freeze
                lst.SetItemState(focused_idx, 0, wx.LIST_STATE_FOCUSED)
            except Exception:
                pass
        if hasattr(self, "archived_conversations_panel"):
            if arch_focused_idx != -1:
                try:
                    self.archived_conversations_panel.conversations_list.SetItemState(
                        arch_focused_idx, 0, wx.LIST_STATE_FOCUSED
                    )
                except Exception:
                    pass
        lst.Freeze()
        try:
            lst.DeleteAllItems()
            for item_text in new_item_texts:
                lst.Append((item_text,))
        finally:
            lst.Thaw()

        # Keep backing lists in sync with exactly what is displayed.
        self.conversations_panel.chats_list = displayed_chats
        self.conversations_panel.chat_names = displayed_names
        self.conversations_panel._displayed_jids = new_jids

        # Restore selection / focus after DeleteAllItems() clears everything.
        # Prefer the previously focused item if it is still in the list to prevent jumping.
        panel = self.conversations_panel
        target_idx = -1
        if focused_jid:
            for i, chat in enumerate(displayed_chats):
                if chat.get("remoteJid") == focused_jid:
                    target_idx = i
                    break

        if target_idx != -1:
            if panel.conversations_list.GetFocusedItem() != target_idx:
                panel.conversations_list.Focus(target_idx)
            if _lst_had_focus:
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)
                panel.conversations_list.SetFocus()
            elif panel.conversation is not None:
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
        elif (_lst_had_focus and focused_jid and displayed_chats
              and focus_allowed):
            # The previously focused chat is gone (e.g. it was just cleared and
            # filtered out). Keep keyboard focus in the list by landing on
            # whatever now occupies its slot instead of dropping focus entirely.
            # But only reuse that raw position when this is still the same
            # filtered/searched view — if the filter or search just changed,
            # the old index refers to an unrelated list and landing on row 0
            # is the only position that means anything in the new one.
            if _filter_or_search_changed:
                neighbor_idx = 0
            else:
                neighbor_idx = min(focused_idx, len(displayed_chats) - 1)
            if neighbor_idx < 0:
                neighbor_idx = 0
            panel.conversations_list.Focus(neighbor_idx)
            panel.conversations_list.Select(neighbor_idx)
            panel.conversations_list.EnsureVisible(neighbor_idx)
            panel.conversations_list.SetFocus()
        elif getattr(self, "_initial_sync_running", False):
            # Skip selection/focus restoration during active initial background sync to prevent screen readers loop
            pass
        elif panel.conversation is None and displayed_chats:
            last_jid    = getattr(panel, "_last_open_jid", "")
            target_idx  = 0
            if last_jid:
                for i, chat in enumerate(displayed_chats):
                    if chat.get("remoteJid") == last_jid:
                        target_idx = i
                        break
            if focus_allowed:
                if panel.conversations_list.GetFocusedItem() != target_idx:
                    panel.conversations_list.Focus(target_idx)
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)
                # Restore keyboard focus to the list when no conversation is open.
                search = getattr(panel, "search_field", None)
                focused_now = wx.Window.FindFocus()
                if _lst_had_focus or focused_now is None or focused_now is lst:
                    if focused_now is not search:
                        wx.CallAfter(lst.SetFocus)
        elif panel.conversation is not None:
            open_jid = panel.conversation.get("remoteJid", "")
            target_idx = -1
            for i, chat in enumerate(displayed_chats):
                if chat.get("remoteJid") == open_jid:
                    target_idx = i
                    break
            if target_idx != -1:
                if _lst_had_focus:
                    if panel.conversations_list.GetFocusedItem() != target_idx:
                        panel.conversations_list.Focus(target_idx)
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)

            if focus_allowed:
                focus_ctrl = getattr(panel, "message_field", None)
                if focus_ctrl and focus_ctrl.IsShownOnScreen():
                    if wx.Window.FindFocus() is None and self.IsActive():
                        wx.CallAfter(focus_ctrl.SetFocus)

        # Also refresh the archived panel if present
        if hasattr(self, "archived_conversations_panel"):
            self._refresh_archived_chats_in_ui(arch_focused_jid)

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
        root.addHandler(handler)
        # Set logging level to INFO to expose auto-updater, settings validation,
        # and startup logs. Noisy dependencies are silenced at ERROR level below.
        root.setLevel(logging.INFO)

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
