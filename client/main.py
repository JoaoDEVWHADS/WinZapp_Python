import os
import sys
import time
import shutil
import socket as _socket
import subprocess
import threading
import requests
import base64
import socketio
import atexit
import ctypes
from accessible_output2 import outputs
from core.sound_system import SoundSystem, Sound
from core.i18n import I18n
from core.websocket_client import WebSocketClient
from core.utils import encrypt, decrypt, encrypt_json, decrypt_json, generate_and_save_key, retrieve_key, format_number
from app_paths import resource_path, data_path
from core.message_queue import MessageQueue, PendingMessage
import wx
import wx.adv
from ui.dialogs.connect import Connect
from ui.navigation import NavigationPanel
from ui.conversations import ConversationsPanel, ArchivedConversationsPanel
from status_panel import StatusPanel
import json
from traceback import format_exc, format_exception
import pyperclip

# Tell Windows to use "WinZapp" as the App User Model ID so notifications
# show the correct name instead of the executable filename.
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WinZapp")
except Exception:
    pass

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

        # Check and install API modules if needed (first run only)
        self.ensure_api_modules_installed()

        # Check that the installed Evolution API meets the minimum required version
        self.ensure_evolution_version()

        #Start local Evolution API (if bundled)
        self.evolution_process = None
        self.ensure_evolution_running()

        # First-run dialog: ask about autostart (normal mode only, once ever)
        if not self.background_mode:
            self._check_first_run()

        self.offline_mode = False

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
        self.connect_websocket()
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

        # ── Status tracking (shown in title and tray tooltip) ─────────────────
        self._tray_status = ""

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
        self._init_tray()

        # ── Notification manager ──────────────────────────────────────────────
        from core.notification_manager import NotificationManager
        self.notification_manager = NotificationManager(self)

        # Intercept window-close: hide to tray instead of quitting (when tray active)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # In background mode the window is intentionally hidden; it can be
        # restored later by a second instance or a future tray-icon action.
        if not self.background_mode:
            self.Show()
        #Set offline chats for the first time
        self.set_chats()

        # ── Quick tip after first pairing ─────────────────────────────────────
        if not self.background_mode and self._just_paired:
            wx.CallAfter(self._check_quick_tip)

        # ── Auto-updater ──────────────────────────────────────────────────────
        if not self.background_mode:
            wx.CallLater(2000, self._start_update_checker)

        app.MainLoop()

    # ── Menu bar ─────────────────────────────────────────────────────────────

    def _build_menubar(self):
        """Create the Help menu bar with the Force Update item."""
        self._ID_FORCE_UPDATE = wx.NewIdRef()
        menubar    = wx.MenuBar()
        help_menu  = wx.Menu()
        help_menu.Append(self._ID_FORCE_UPDATE, self.i18n.t("menu_force_update"))
        menubar.Append(help_menu, self.i18n.t("menu_help"))
        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self._on_force_update, id=self._ID_FORCE_UPDATE)

    def _refresh_menubar(self):
        """Retranslate the menu bar labels after a language change."""
        mb = self.GetMenuBar()
        if mb is None:
            return
        mb.SetMenuLabel(0, self.i18n.t("menu_help"))
        mb.GetMenu(0).FindItemById(self._ID_FORCE_UPDATE).SetItemLabel(
            self.i18n.t("menu_force_update")
        )

    def _set_status(self, status: str):
        """Update window title and tray tooltip to reflect current status."""
        self._tray_status = status
        app_name = self.i18n.t("app_name")
        if status:
            self.SetTitle(f"{app_name} - {status}")
        else:
            self.SetTitle(app_name)
        if getattr(self, "tray_icon", None) is not None:
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
        if hasattr(self, "conversations_panel"):
            self.add_chats_to_ui()

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
        """Bring the window to front and open the conversation matching jid."""
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
            chat["unreadCount"] = int(chat.get("unreadCount") or 0) + 1

        # ── Persist ───────────────────────────────────────────────────────────
        self.save_data(self.chats, self.contacts)

        # ── Update conversation list UI ───────────────────────────────────────
        self.set_chats()

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
        if not self.settings.get("general", {}).get("notifications_enabled", True):
            return

        from core.notification_manager import (
            format_notification_title, format_notification_body,
            format_foreground_sender,
        )

        body  = format_notification_body(msg, self.i18n)

        # Check if the WinZapp window is currently active/focused
        window_active = self.IsShown() and not self.IsIconized() and self.IsActive()

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
        self.ws.sio.connect(f"{self.evolution_ws_server}:{self.evolution_port}/", socketio_path="socket.io", headers={"apikey": self.token}, namespaces=[f"/{self.token}"])

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
        """
        node_exe = resource_path("node", "node.exe")
        start_js  = resource_path("api",  "start.js")
        if not os.path.isfile(node_exe) or not os.path.isfile(start_js):
            return  # Not bundled — developer runs Evolution separately
        try:
            self._evolution_log_path = resource_path("api", "evolution.log")
            log_fh = open(self._evolution_log_path, "w",
                          encoding="utf-8", errors="replace")
            self._evolution_log_fh = log_fh
            self.evolution_process = subprocess.Popen(
                [node_exe, start_js],
                cwd=resource_path("api"),
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=log_fh,
                stderr=log_fh,
            )
            atexit.register(self._stop_evolution)
        except Exception:
            pass

    def _stop_evolution(self):
        """Terminate the Evolution API process and close the log file."""
        if self.evolution_process and self.evolution_process.poll() is None:
            try:
                self.evolution_process.terminate()
            except Exception:
                pass
        log_fh = getattr(self, "_evolution_log_fh", None)
        if log_fh:
            try:
                log_fh.close()
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
        # Update frame title (keep any suffix that might be present during sync)
        current_title = self.GetTitle()
        if " - " in current_title:
            suffix = current_title.split(" - ", 1)[1]
            self.SetTitle(f"{self.i18n.t('app_name')} - {suffix}")
        else:
            self.SetTitle(self.i18n.t("app_name"))
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
        self.generate_secret_key()
        self.key = self.retrieve_secret_key()
        self.create_basic_files()

        #Get Local Chats
        self.chats = self.get_chats()
        self.chats = self.deduplicate_chats(self.chats)
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_contacts()
        if not self.background_mode:
            self.connected_sound.play()
        if self.settings.get("status", {}).get("messages_set_completed"):
            self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
            self.sync_thread.start()
        else:
            self.wait_messages_set()

    def start_sync(self):
        self.chats = self.get_remote_chats(self.chats)
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_remote_contacts()
        if not self.background_mode:
            self.synchronizing_sound.play()
            wx.CallAfter(self._set_status, self.i18n.t("synchronizing"))
            self.output(self.i18n.t("synchronization_started"), interrupt=True)

        # ── Phase 1: sync all messages ────────────────────────────────────
        self.sync_remote_chats()

        # Conversations are fully sorted as soon as messages are synced.
        # Sort, display, play sync-complete sound, and announce to the user
        # NOW — before the slower media-download phase begins.
        wx.CallAfter(self.set_chats)
        wx.CallAfter(self.preselect_conversations)
        if not self.background_mode:
            self.sync_complete_sound.play()
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

    def wait_messages_set(self):
        if not self.background_mode:
            self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('preparing_to_sync')}")

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
            for chat in response_data:
                jid = self._normalize_jid(chat.get("remoteJid", ""))
                if not jid:
                    continue
                if jid not in chats:
                    if "messages" not in chat:
                        chat["messages"] = {"messages": {"records": []}}
                    chat["remoteJid"] = jid
                    chats[jid] = chat
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
             messages contain a remoteJidAlt / senderPn bridge field that maps
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

        # ── Pass 2: merge @lid into matching @s.whatsapp.net ─────────────────
        lid_jids = [j for j in list(chats.keys()) if j.endswith("@lid")]
        for lid_jid in lid_jids:
            if lid_jid not in chats:
                continue
            lid_chat = chats[lid_jid]
            alt_jid  = self._find_alt_jid_from_messages(lid_chat)
            if not alt_jid or alt_jid not in chats:
                continue  # no matching phone-number chat found — keep @lid as-is

            # Merge @lid messages into the @s.whatsapp.net entry and drop @lid
            dst_records = (
                chats[alt_jid]
                .setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
            )
            src_records = (
                lid_chat.get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            _merge_records(dst_records, src_records)
            del chats[lid_jid]

        return chats

    def save_data(self, chats, contacts):
        #Save back to file
        messages_file = data_path("messages.dat")
        try:
            encrypted_data = encrypt_json({"chats": chats, "contacts": contacts}, self.key)
            with open(messages_file, "wb") as f:
                f.write(encrypted_data)
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('data_save_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)

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
            contacts = {}
            for contact in response_data:
                if contact.get("type", "") == "contact":
                    contacts[contact.get("remoteJid", "")] = contact
            self.save_data(self.chats, contacts)
            return contacts
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('contact_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR, self)

    def set_chats(self):
        deleted  = set(self.settings.get("deleted_chats",  []))
        archived = set(self.settings.get("archived_chats", []))
        pinned   = set(self.settings.get("pinned_chats",   []))

        main_chats, main_names = [], []
        arch_chats, arch_names = [], []

        for jid, chat in self.chats.items():
            if jid in deleted:
                continue
            name = (
                self._resolve_contact_name(chat)
                or self.find_name_through_messages(chat)
                or chat.get("pushName", "")
                or self.find_jid_through_messages(chat)
                or format_number(jid)
            )
            if jid in archived:
                arch_chats.append(chat)
                arch_names.append(name)
            else:
                main_chats.append(chat)
                main_names.append(name)

        # Pinned chats float to the top; within each group sort by most-recent
        # message timestamp descending (newest first), then alphabetically.
        def _chat_last_ts(chat):
            ts = 0
            for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
                t = int(msg.get("messageTimestamp", 0) or 0)
                if t > ts:
                    ts = t
            return ts

        def _sort_key(pair):
            chat, name = pair
            jid = chat.get("remoteJid", "")
            pin = 0 if jid in pinned else 1
            return (pin, -_chat_last_ts(chat), name.lower())

        pairs = sorted(zip(main_chats, main_names), key=_sort_key)
        main_chats = [c for c, _ in pairs]
        main_names = [n for _, n in pairs]

        self.chat_names = main_names
        # _all_chats_list / _all_chat_names always hold the full sorted list.
        # add_chats_to_ui() reads these to apply the search filter, then
        # writes back to chats_list / chat_names so indices stay consistent.
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
        # Refresh tray tooltip whenever chat list / unread counts change
        if getattr(self, "tray_icon", None) is not None:
            self.tray_icon.update_tooltip()

    def _find_alt_jid_from_messages(self, chat):
        """
        When a chat is addressed as @lid, find the corresponding phone-number
        JID by scanning message keys for the bridge fields that Baileys/
        Evolution API sets when addressingMode == "lid":
          - remoteJidAlt  (primary field, e.g. "5511987654321@s.whatsapp.net")
          - senderPn      (fallback field used in some Evolution versions)
        Returns the alt JID string, or None if not found.
        """
        for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
            key = msg.get("key", {})
            if not key.get("fromMe") and key.get("addressingMode") == "lid":
                alt = key.get("remoteJidAlt") or key.get("senderPn", "")
                if alt:
                    return alt
        return None

    def _resolve_contact_name(self, chat):
        """
        Return the address-book contact name (e.g. "mãe") for a private chat,
        or None for groups or when no saved contact name is available.

        WhatsApp uses two JID formats:
          - @s.whatsapp.net  traditional phone-number-based identifier
          - @lid             opaque Linked Device ID (newer accounts)

        The contacts dict is indexed by whichever JID format Evolution API
        stored for each contact.  When a chat's remoteJid is @lid but the
        contact is stored under the phone-number JID (or vice-versa), the
        direct lookup fails.  In that case we scan the chat's message keys
        for the remoteJidAlt / senderPn bridge field that Baileys sets when
        addressingMode == "lid", giving us the alternate JID to try.

        Field priority within a contact object (Baileys / Evolution API):
          name > fullName > verifiedName
          (pushName is the WhatsApp profile name, NOT the address-book name.)
        """
        remoteJid = chat.get("remoteJid", "")
        if not remoteJid or remoteJid.endswith("@g.us"):
            return None  # groups don't have address-book entries

        def _name_from_contact(c):
            # Evolution API v2 stores the address-book name in Contact.pushName
            # (derived from Baileys contact.name || contact.verifiedName).
            # Prefer explicit name fields; fall back to pushName of the contact
            # object (NOT the chat/message pushName, which is the WA profile name).
            return (c.get("name") or c.get("fullName") or
                    c.get("verifiedName") or c.get("pushName") or None)

        # 1. Direct lookup by chat's own remoteJid
        contact = self.contacts.get(remoteJid)
        if contact:
            n = _name_from_contact(contact)
            if n:
                return n

        # 2. @lid chat — bridge to phone-number JID via message keys
        if remoteJid.endswith("@lid"):
            alt_jid = self._find_alt_jid_from_messages(chat)
            if alt_jid:
                contact = self.contacts.get(alt_jid)
                if contact:
                    n = _name_from_contact(contact)
                    if n:
                        return n

        return None

    def find_name_through_messages(self, chat):
        #If it's a chat group, ignore
        if chat.get("remoteJid", "").endswith("@g.us"):
            return None
        #Find a message that is not from you
        for message in chat["messages"].get("messages", {}).get("records", []):
            #If pushName is a phone number, ignore
            if message.get("pushName", "") and message.get("pushName", "").isdigit():
                continue
            if not message.get("key", {}).get("fromMe"):
                #Return the message push name
                return message.get("pushName", "")
        return None

    def find_jid_through_messages(self, chat):
        for message in chat["messages"].get("messages", {}).get("records", []):
            #Find a message that is not from you
            if not message.get("key", {}).get("fromMe"):
                #If addressingMode is lid, return remoteJidAlt, if not return remoteJid
                if message.get("key", {}).get("addressingMode", "") == "lid":
                    return format_number(message.get("key", {}).get("remoteJidAlt", ""))
                return format_number(message.get("key", {}).get("remoteJid", ""))
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
            self.sync_chat_messages(chat.copy())

    def sync_media_for_all_chats(self):
        for chat in self.chats.values():
            self.sync_chat_media(chat)

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

        # Loop through all pages
        while current_page <= total_pages:
            payload = {
                "where": { "key": { "remoteJid": remote_jid} },
                "page": current_page
            }

            response = requests.post(url, json=payload, headers=headers)
            response_data = response.json()

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
            wx.CallAfter(self.set_chats)
            self.save_data(self.chats, self.contacts)

    def sync_if_media(self, msg):
        """Download media for a single message during the background sync phase."""
        message_type = msg.get("messageType", "")
        _MEDIA_TYPES = {"documentMessage", "imageMessage", "stickerMessage", "videoMessage"}
        try:
            if message_type == "audioMessage":
                self.handle_audio_message(msg)
            elif message_type in _MEDIA_TYPES:
                msg_id = msg.get("key", {}).get("id", "")
                conv = self.conversations_panel
                def _prog(p, mid=msg_id):
                    wx.CallAfter(conv.update_message_download_progress, mid, p)
                self.handle_media_message(msg, progress_callback=_prog)
                wx.CallAfter(conv.update_message_download_progress, msg_id, 1.0)
        except Exception:
            pass

    def handle_media_message(self, msg, progress_callback=None):
        """Download and encrypt a document/image/sticker/video to data/media/."""
        msg_id = msg.get("key", {}).get("id", "")
        if not msg_id:
            return
        media_path = data_path("media", f"{msg_id}.wzmedia")
        if os.path.isfile(media_path):
            return
        b64 = self.get_base64_from_media(msg, progress_callback=progress_callback)
        if not b64:
            return
        content = base64.b64decode(b64)
        encrypted = encrypt(content, self.key)
        with open(media_path, "wb") as f:
            f.write(encrypted)

    @staticmethod
    def _clean_quoted(quoted: dict) -> dict:
        """Return a copy of *quoted* with all local-only (``_``-prefixed) keys
        removed so that the Evolution API does not receive internal state fields
        such as ``_local_pending`` or ``_local_id``.
        Only the fields expected by the API (``key``, ``message``, …) are kept.
        """
        if not quoted:
            return quoted
        return {k: v for k, v in quoted.items() if not k.startswith("_")}

    def send_text_message(self, remote_jid, text, quoted=None):
        """Send a plain-text message via the Evolution API."""
        url = f"{self.evolution_server}:{self.evolution_port}/message/sendText/{self.token}"
        payload = {"number": remote_jid, "text": text}
        if quoted:
            payload["quoted"] = self._clean_quoted(quoted)
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                return False
            # Evolution API may return HTTP 200 with an error body (e.g. when the
            # quoted field is malformed).  Treat responses without a "key" as failure
            # so the queue retries.
            try:
                body = response.json()
                if isinstance(body, dict) and "key" not in body:
                    return False
            except Exception:
                pass
            return True
        except Exception:
            return False

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
            payload["quoted"] = self._clean_quoted(quoted)
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            return response.status_code in (200, 201)
        except Exception:
            return False

    def send_reaction(self, remote_jid: str, msg_key: dict, emoji: str) -> bool:
        """Send a reaction to a message via the Evolution API."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendReaction/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        payload = {"key": msg_key, "reaction": emoji}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            return response.status_code in (200, 201)
        except Exception:
            return False

    def _on_message_sent(self, local_id: str, audio_path: str = None):
        """
        Called on the main thread after a queued message is successfully sent.
        Updates the UI status label and cleans up any temporary audio file.
        """
        if hasattr(self, "conversations_panel"):
            self.conversations_panel._mark_message_sent(local_id)
        # Clean up temp WAV for voice messages (media attachments keep their file).
        if audio_path and os.path.isfile(audio_path):
            try:
                os.unlink(audio_path)
            except Exception:
                pass

    def handle_audio_message(self, msg):
        #First, check if the audio is already downloaded
        voice_messages_dir = data_path("voice_messages")
        audio_file_path = os.path.join(voice_messages_dir, f"{msg.get('key', {}).get('id', '')}.msv")
        if os.path.isfile(audio_file_path):
            return

        base64_audio = self.get_base64_from_media(msg)
        audio_content = base64.b64decode(base64_audio)
        self.save_audio_locally(msg, audio_content)

    def get_base64_from_media(self, media, progress_callback=None):
        """
        Fetch encrypted media from Evolution API and return its base64 string.

        When *progress_callback* is provided the request is streamed and the
        callback is called with a float in [0, 1] as each chunk arrives.
        """
        url = f"{self.evolution_server}:{self.evolution_port}/chat/getBase64FromMediaMessage/{self.token}"
        payload = {
            "message": {"key": {"id": media.get("key", {}).get("id", "")}},
            "convertToMp4": False,
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}

        if progress_callback is None:
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code in (200, 201):
                return response.json().get("base64", "")
            return ""

        # Streaming mode so we can report per-chunk progress
        try:
            response = requests.post(url, json=payload, headers=headers, stream=True)
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
        """Mark conversation as read locally and notify the API."""
        chat = self.chats.get(remote_jid)
        if chat is not None:
            chat["unreadCount"] = 0
            wx.CallAfter(self.set_chats)
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/chat/markMessageAsRead/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.post(
                url,
                json={"lastMessages": [{"key": {"remoteJid": remote_jid,
                                                 "fromMe": False, "id": ""}}]},
                headers=headers,
                timeout=10,
            )
        except Exception:
            pass

    def mark_conversation_as_unread(self, remote_jid: str):
        chat = self.chats.get(remote_jid)
        if chat is not None:
            chat["unreadCount"] = 1
            self.save_data(self.chats, self.contacts)
            wx.CallAfter(self.set_chats)

    # ── Evolution API — profile / group info ─────────────────────────────────

    def get_contact_profile(self, jid: str) -> dict:
        """Fetch contact profile from Evolution API (runs on background thread)."""
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
        """Fetch group metadata from Evolution API (runs on background thread)."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/group/findGroupInfos/{self.token}"
        )
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json={"groupJid": jid}, headers=headers, timeout=10)
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

    def unarchive_chat(self, jid: str):
        lst = self.settings.setdefault("archived_chats", [])
        if jid in lst:
            lst.remove(jid)
        self.save_settings()
        wx.CallAfter(self.set_chats)

    # ── Delete / Clear ────────────────────────────────────────────────────────

    def is_chat_deleted(self, jid: str) -> bool:
        return jid in self.settings.get("deleted_chats", [])

    def delete_chat_local(self, jid: str):
        lst = self.settings.setdefault("deleted_chats", [])
        if jid not in lst:
            lst.append(jid)
        self.save_settings()
        self.chats.pop(jid, None)
        self.save_data(self.chats, self.contacts)
        wx.CallAfter(self.set_chats)

    def clear_chat_messages_local(self, jid: str):
        chat = self.chats.get(jid)
        if chat:
            chat.setdefault("messages", {}).setdefault("messages", {})["records"] = []
            self.settings.setdefault("cleared_chats", {})[jid] = int(time.time())
            self.save_data(self.chats, self.contacts)
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
            requests.delete(url, json={"groupJid": jid}, headers=headers, timeout=10)
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
                data = r.json()
                jid = (
                    data.get("id")
                    or data.get("groupJid")
                    or data.get("remoteJid", "")
                )
                return True, jid
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
        payload = {
            "groupJid":    group_jid,
            "action":      "add",
            "participants": participant_jids,
        }
        try:
            r = requests.put(url, json=payload, headers=headers, timeout=15)
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
            payload["quoted"] = self._clean_quoted(quoted)
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            return r.status_code in (200, 201)
        except Exception:
            return False

    def send_contact_attachment(self, remote_jid: str, contact_info: dict,
                                quoted: dict = None) -> bool:
        """Send a contact card as an attachment."""
        name = (
            contact_info.get("name") or contact_info.get("pushName")
            or contact_info.get("verifiedName") or ""
        )
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
            payload["quoted"] = self._clean_quoted(quoted)
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            return r.status_code in (200, 201)
        except Exception:
            return False

    # ── Message edit / delete-for-everyone ────────────────────────────────────

    def edit_message(self, remote_jid: str, message_id: str, new_text: str):
        """Send an edited message to the Evolution API."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/updateMessage/{self.token}"
        )
        payload = {
            "number":    remote_jid,
            "key":       {"remoteJid": remote_jid, "fromMe": True, "id": message_id},
            "text":      new_text,
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.put(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass

    def delete_message_for_everyone(self, remote_jid: str, message_id: str, from_me: bool):
        """Delete a message for everyone via the Evolution API."""
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/deleteMessageForEveryone/{self.token}"
        )
        payload = {
            "number":    remote_jid,
            "key":       {"remoteJid": remote_jid, "fromMe": from_me, "id": message_id},
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            requests.delete(url, json=payload, headers=headers, timeout=15)
        except Exception:
            pass

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
                    if orig_type in ("conversation", "textMessage"):
                        orig_text = (orig_obj.get("conversation") or "")[:40]
                    elif orig_type == "extendedTextMessage":
                        orig_text = ((orig_obj.get("extendedTextMessage") or {}).get("text") or "")[:40]
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
                p_key = last.get("key", {})
                sender_name = (
                    last.get("pushName")
                    or format_number(p_key.get("participant", "") or p_key.get("remoteJid", ""))
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

        if msg_type in ("conversation", "textMessage"):
            content = (
                msg_obj.get("conversation")
                or (msg_obj.get("extendedTextMessage") or {}).get("text")
                or last.get("messageBody")
                or ""
            )
            if len(content) > 60:
                content = content[:57] + "..."
        elif msg_type == "extendedTextMessage":
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
            if len(content) > 60:
                content = content[:57] + "..."
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
            content = i18n.t("photo") + (f" {caption[:40]}" if caption else "")
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
            p_key        = last.get("key", {})
            sender_jid   = p_key.get("participant") or p_key.get("remoteJid", "")
            sender_name  = (
                last.get("pushName")
                or self._resolve_contact_name({"remoteJid": sender_jid})
                or sender_jid.split("@")[0]
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

        Applies the active search filter to both the wx.ListCtrl *and* the
        backing chats_list/chat_names arrays so that list indices are always
        consistent.  Without this sync the user would open the wrong
        conversation when a search was active.
        """
        search = self.conversations_panel.search_field.GetValue().strip().lower()

        # Always start from the full sorted lists saved by set_chats() so
        # that restoring the window or clearing a search shows all chats.
        full_chats = list(getattr(self.conversations_panel, '_all_chats_list',
                                  self.conversations_panel.chats_list))
        full_names = list(getattr(self.conversations_panel, '_all_chat_names',
                                  self.conversations_panel.chat_names))

        displayed_chats: list = []
        displayed_names: list = []

        self.conversations_panel.conversations_list.DeleteAllItems()
        for i, chat in enumerate(full_chats):
            name = full_names[i]
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
            self.conversations_panel.conversations_list.Append((item_text,))
            displayed_chats.append(chat)
            displayed_names.append(name)

        # Keep backing lists in sync with exactly what is displayed so that
        # on_conversation_selected_by_index(idx) always maps correctly.
        self.conversations_panel.chats_list = displayed_chats
        self.conversations_panel.chat_names = displayed_names

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


if __name__ == "__main__":
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

