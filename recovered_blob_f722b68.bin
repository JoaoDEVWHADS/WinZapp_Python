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
from core.utils import encrypt, decrypt, encrypt_json, decrypt_json, generate_and_save_key, retrieve_key, format_number, check_internet_connection
from app_paths import resource_path, data_path
from core.message_queue import MessageQueue, PendingMessage
import wx
import wx.adv
from ui.dialogs.connect import Connect
from ui.navigation import NavigationPanel
from ui.conversations import ConversationsPanel, ArchivedConversationsPanel
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

        #Start local Evolution API (if bundled)
        self.evolution_process = None
        self.ensure_evolution_running()

        # First-run dialog: ask about autostart (normal mode only, once ever)
        if not self.background_mode:
            self._check_first_run()

        #Check Internet Connection
        self.offline_mode = not check_internet_connection()

        #Play startup sound (skipped in background mode)
        if not self.background_mode:
            self.startup_sound.play()

        #Check for what window should be shown (skipped in background mode)
        if not self.background_mode:
            if not self.connect.check_connection_status():
                self.connect.show_connection_dial()
                self.ws.sio.disconnect()
        self.retrieve_token()
        #Initialize websocket
        self.ws = WebSocketClient(self, self.connect, self.token)

        self.prepare_sync()
        # Initialise outgoing-message queue (must exist before init_UI so the
        # ConversationsPanel can call self.main_window.message_queue.enqueue).
        self.message_queue = MessageQueue(self)
        #Connect WebSocket if not Offline
        if not self.offline_mode:
            self.connect_websocket()
        self.init_UI()


    def init_UI(self):
        if self.offline_mode:
            self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('offline_mode')}")
        self.SetMinSize((400, 300))
        self.main_panel = wx.Panel(self)

        self.navigation_panel = NavigationPanel(self, self.main_panel)
        self.content_panel = wx.Panel(self.main_panel)
        self.conversations_panel = ConversationsPanel(self, self.content_panel)
        self.archived_conversations_panel = ArchivedConversationsPanel(
            self, self.content_panel
        )
        self.archived_conversations_panel.Hide()

        # Content panel: both panels fill it; only one is shown at a time
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self.conversations_panel, 1, wx.EXPAND)
        content_sizer.Add(self.archived_conversations_panel, 1, wx.EXPAND)
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
        """
        if self.tray_icon is not None:
            self.Hide()
            event.Veto()
        else:
            self.real_exit()

    def restore_window(self):
        """Bring the WinZapp window to the foreground."""
        if not self.IsShown():
            self.Show()
        if self.IsIconized():
            self.Restore()
        self.Raise()
        self.SetFocus()

    def real_exit(self):
        """Completely close WinZapp, removing the tray icon and stopping all threads."""
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

    def on_new_message(self, msg: dict):
        """
        Called on the main thread (via wx.CallAfter) when a new message
        arrives via the messages.upsert WebSocket event.
        Adds the message to local storage, updates the UI, and sends a
        notification if appropriate.
        """
        key        = msg.get("key", {})
        from_me    = key.get("fromMe", False)
        remote_jid = key.get("remoteJid", "")
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
        if not self.settings.get("general", {}).get("show_tray_icon", True):
            return

        from core.notification_manager import (
            format_notification_title, format_notification_body
        )
        title = format_notification_title(msg, self, self.i18n)
        body  = format_notification_body(msg, self.i18n)
        if hasattr(self, "notification_manager"):
            self.notification_manager.send(title, body, remote_jid)

    def connect_websocket(self):
        self.ws.sio.connect(f"{self.evolution_ws_server}:{self.evolution_port}/", socketio_path="socket.io", headers={"apikey": self.token}, namespaces=[f"/{self.token}"])

    # ── First-run module installation ──────────────────────────────────────

    def ensure_api_modules_installed(self):
        """
        If api/start.js is present but api/node_modules is absent, show the
        module-install dialog.  The dialog runs `npm install` + `npm run
        db:generate` in the background.  If the user cancels or an error
        occurs, the application exits immediately.

        In background mode the dialog is never shown; if modules are missing
        the process exits silently (first run always happens in normal mode).
        """
        start_js     = resource_path("api", "start.js")
        node_modules = resource_path("api", "node_modules")
        # Nothing to do: no bundled api/, or modules already installed
        if not os.path.isfile(start_js) or os.path.isdir(node_modules):
            return
        if self.background_mode:
            # Modules must already be installed for background mode to work.
            sys.exit(0)
        from ui.dialogs.module_install import ModuleInstallDialog
        dlg    = ModuleInstallDialog(self)
        result = dlg.ShowModal()
        dlg.Destroy()
        if result != wx.ID_OK:
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

        self._evolution_log_path = None
        self._evolution_log_fh   = None
        self._start_evolution_background()

        if self.background_mode:
            # Silent wait — no dialog, no speech.  Timeout → exit code 1.
            deadline = time.time() + 180
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
        self.ID_ALT_1 = wx.NewIdRef()
        self.ID_CTRL_COMMA = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT,  ord('1'),   self.ID_ALT_1),
            (wx.ACCEL_CTRL, ord(','),   self.ID_CTRL_COMMA),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_alt_1,       id=self.ID_ALT_1)
        self.Bind(wx.EVT_MENU, self.on_ctrl_comma,  id=self.ID_CTRL_COMMA)

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
        self.conversations_panel.Show()
        self.content_panel.Layout()
        self.conversations_panel.conversations_list.SetFocus()
        if (self.conversations_panel.conversations_list.GetFocusedItem() != -1
                and self.conversations_panel.conversations_list.GetItemCount() > 0):
            self.output(
                self.conversations_panel.conversations_list.GetItemText(
                    self.conversations_panel.conversations_list.GetFocusedItem()
                ),
                interrupt=True,
            )

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

    def retrieve_token(self):
        try:
            with open(data_path("token.tk"), "r") as token_file:
                self.token = token_file.read().strip()
        except Exception as e:
            if self.background_mode:
                # No token means WhatsApp has never been paired — nothing to do
                # in background mode; exit silently so Windows doesn't retry.
                sys.exit(0)
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('token_retrieval_failed')} {format_exc()}", self.i18n.t("error").format(app_name=self.app_name), wx.OK | wx.ICON_ERROR)
            sys.exit()

    def prepare_sync(self):
        self.generate_secret_key()
        self.key = self.retrieve_secret_key()
        self.create_basic_files()

        #Get Local Chats
        self.chats = self.get_chats()
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_contacts()
        if not self.offline_mode:
            if not self.background_mode:
                self.connected_sound.play()
            if self.settings.get("status", {}).get("messages_set_completed"):
                self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
                self.sync_thread.start()
            else:
                self.wait_messages_set()
        else:
            if not self.background_mode:
                self.offline_mode_sound.play()
                self.output(self.i18n.t("offline_mode_enabled"))
        self.monitor_thread = threading.Thread(target=self.monitor_internet_connection, daemon=True)
        self.monitor_thread.start()

    def start_sync(self):
        self.chats = self.get_remote_chats(self.chats)
        self.chats = self.normalize_chats(self.chats)
        self.contacts = self.get_remote_contacts()
        if not self.background_mode:
            self.synchronizing_sound.play()
            self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('synchronizing')}")
            self.output(self.i18n.t("synchronization_started"), interrupt=True)
        # Phase 1: sync all messages (no media download)
        self.sync_remote_chats()
        # Phase 2: download media for all chats
        if not self.background_mode:
            self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('downloading_media')}")
        self.sync_media_for_all_chats()
        if not self.background_mode:
            self.sync_complete_sound.play()
            self.SetTitle(f"{self.i18n.t('app_name')}")
            self.output(self.i18n.t("sync_complete"))
        wx.CallAfter(self.preselect_conversations)

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
            wx.MessageBox(f"{self.i18n.t('chat_load_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
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
                #If chat is not present
                if not chat.get("remoteJid", "") in chats:
                    if not "messages" in chat:
                        chat["messages"] = {"messages": {"records": []}}
                    chats[chat.get("remoteJid", "")] = chat
            self.save_data(chats, self.contacts)
            return chats
        except Exception as e:
            self.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('chat_retrieval_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR, self)

    def normalize_chats(self, chats):
        for key, chat in chats.items():
            if chat["unreadCount"] is None:
                chat["unreadCount"] = 0
            chats[key] = chat
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
            wx.MessageBox(f"{self.i18n.t('data_save_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)

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
            wx.MessageBox(f"{self.i18n.t('contact_load_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
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
            wx.MessageBox(f"{self.i18n.t('contact_retrieval_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR, self)

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

        # Pinned chats float to the top of the main list
        def _sort_key(pair):
            chat, name = pair
            return (0 if chat.get("remoteJid", "") in pinned else 1, name.lower())

        pairs = sorted(zip(main_chats, main_names), key=_sort_key)
        main_chats = [c for c, _ in pairs]
        main_names = [n for _, n in pairs]

        self.chat_names = main_names
        self.conversations_panel.chats_list = main_chats
        self.conversations_panel.chat_names = main_names

        if hasattr(self, "archived_conversations_panel"):
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
            self.conversations_panel.conversations_list.Focus(0)
            self.conversations_panel.conversations_list.Select(0)

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

        all_messages = []
        current_page = 1
        total_pages = 1

        # Loop through all pages
        while current_page <= total_pages:
            payload = {
                "where": { "key": { "remoteJid": chat.get("remoteJid", "")} },
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
            if "messages" not in chat:
                chat["messages"] = {}
            chat["messages"]["messages"] = {
                "total": len(all_messages),
                "pages": total_pages,
                "currentPage": total_pages,
                "records": all_messages
            }

        if chat.get("messages", {}) and chat["messages"] != self.chats[chat.get("remoteJid", "")].get("messages", {}): #update only if necessary
            self.chats[chat.get("remoteJid", "")] = chat
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

    def send_text_message(self, remote_jid, text):
        """Send a plain-text message via the Evolution API."""
        url = f"{self.evolution_server}:{self.evolution_port}/message/sendText/{self.token}"
        payload = {"number": remote_jid, "text": text}
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            return response.status_code in (200, 201)
        except Exception:
            return False

    def send_audio_message(self, remote_jid: str, wav_path: str) -> bool:
        """
        Base64-encode a WAV file and send it as an audio media message via the
        Evolution API.  Returns True on HTTP 200/201, False on any failure.
        """
        try:
            with open(wav_path, "rb") as fh:
                audio_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception:
            return False
        url = (
            f"{self.evolution_server}:{self.evolution_port}"
            f"/message/sendMedia/{self.token}"
        )
        payload = {
            "number":    remote_jid,
            "mediatype": "audio",
            "media":     audio_b64,
            "mimetype":  "audio/wav",
            "fileName":  "voice_message.wav",
        }
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
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
            if response.status_code == 201:
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
        self.delete_chat_local(jid)

    # ── Media / contact attachments ───────────────────────────────────────────

    def send_media_attachment(
        self, remote_jid: str, file_path: str,
        media_type: str, caption: str = ""
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
        headers = {"apikey": self.token, "Content-Type": "application/json"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            return r.status_code in (200, 201)
        except Exception:
            return False

    def send_contact_attachment(self, remote_jid: str, contact_info: dict) -> bool:
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

    def add_chats_to_ui(self):
        search = self.conversations_panel.search_field.GetValue().strip().lower()
        self.conversations_panel.conversations_list.DeleteAllItems()
        for i, chat in enumerate(self.conversations_panel.chats_list):
            name = self.conversations_panel.chat_names[i]
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
            self.conversations_panel.conversations_list.Append((f"{name}{unread_str}",))

        # Also refresh the archived panel if present
        if hasattr(self, "archived_conversations_panel"):
            panel = self.archived_conversations_panel
            panel.conversations_list.DeleteAllItems()
            for i, chat in enumerate(panel.chats_list):
                name = panel.chat_names[i]
                unread = int(chat.get("unreadCount") or 0)
                if unread > 0:
                    unread_str = (
                        f" {unread} "
                        + (self.i18n.t("unread_messages") if unread > 1 else self.i18n.t("unread_message"))
                    )
                else:
                    unread_str = ""
                panel.conversations_list.Append((f"{name}{unread_str}",))

    def monitor_internet_connection(self):
        while True:
            is_connected = check_internet_connection()
            if is_connected and self.offline_mode:
                #Went online
                self.offline_mode = False
                wx.CallAfter(self.on_connection_restored)
            elif not is_connected and not self.offline_mode:
                #Went offline
                self.offline_mode = True
                wx.CallAfter(self.on_connection_lost)
            threading.Event().wait(5)  # Check every 5 seconds

    def on_connection_restored(self):
        self.output(self.i18n.t("connection_restored"), interrupt=True)
        self.SetTitle(f"{self.i18n.t('app_name')}")
        self.connected_sound.play()
        # Immediately retry any messages that accumulated while offline.
        if hasattr(self, "message_queue"):
            self.message_queue.flush()
        self.sync_thread = threading.Thread(target=self.start_sync, daemon=True)
        self.sync_thread.start()
        self.connect_websocket()

    def on_connection_lost(self):
        self.output(self.i18n.t("connection_lost"), interrupt=True)
        self.offline_mode_sound.play()
        self.output(self.i18n.t("offline_mode_enabled"))
        self.SetTitle(f"{self.i18n.t('app_name')} - {self.i18n.t('offline_mode')}")

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

