import os
import sys
import time
import threading
import wx
import requests
from core.i18n import I18n
from core.websocket_client import WebSocketClient
from app_paths import data_path, resource_path
from traceback import format_exc
import base64
from io import BytesIO
from countries import COUNTRIES
import logging


# Events forwarded to the WinZapp client via Socket.IO
_WEBSOCKET_EVENTS = [
    "CALL", "APPLICATION_STARTUP", "QRCODE_UPDATED",
    "MESSAGES_SET", "MESSAGES_UPSERT", "MESSAGES_UPDATE", "MESSAGES_DELETE",
    "SEND_MESSAGE", "CONTACTS_SET", "CONTACTS_UPSERT", "CONTACTS_UPDATE",
    "PRESENCE_UPDATE", "CHATS_SET", "CHATS_UPSERT", "CHATS_UPDATE", "CHATS_DELETE",
    "CONNECTION_UPDATE", "GROUPS_UPSERT", "GROUP_UPDATE", "GROUP_PARTICIPANTS_UPDATE",
]


class Connect:
    def __init__(self, main_window):
        self.main_window = main_window
        #initialize i18n
        self.i18n = I18n(self.main_window)
        self.i18n.get_language()
        self.connection_mode = "phone"  # Default mode: qrcode or phone

        # Phone-field state (formatter + country selector)
        self._current_dial_code: str = "55"   # Brazil default
        self._phone_updating:    bool = False  # reentrancy guard for EVT_TEXT

    # ── Helpers ────────────────────────────────────────────────────────────

    def _wpp_headers(self, use_global_key=False):
        """Return headers for WPPConnect Server API requests."""
        apikey = (
            self.main_window.wpp_api_key
            if use_global_key
            else self.main_window.token
        )
        return {"Authorization": f"Bearer {apikey}", "Content-Type": "application/json"}

    def _create_instance(self, token):
        """
        Start/Create a WhatsApp session in the local WPPConnect Server.
        """
        url = (
            f"{self.main_window.wpp_server}"
            f":{self.main_window.wpp_port}/api/{token}/start-session"
        )
        payload = {
            "waitQrCode": False
        }
        headers = self._wpp_headers(use_global_key=True)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            # 200, 201 are success. 400 might mean session already active which is fine.
            if response.status_code in (200, 201, 400):
                return token
            
            # Any other status is a real failure
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")
        except Exception as exc:
            if "already" in str(exc).lower() or "active" in str(exc).lower():
                return token
            raise exc

    def _setup_websocket_for_instance(self, token):
        """
        No-op for WPPConnect Server as Socket.io events are active by default.
        """
        return True

    def _cleanup_orphan_sessions(self, keep_token: str = "") -> None:
        """Close all WPPConnect browser sessions except *keep_token*.

        Each failed / abandoned pairing attempt leaves a headless Chromium
        process running (visible in wppconnect.log as
        '[session:client] Auto close remain: Xs').  Having two or more
        browsers initialising simultaneously eats CPU/RAM and causes the
        new session to miss the 60 s Auto Close window → ReadTimeout.

        We enumerate the userDataDir sub-folders (one per session) and
        call /close-session for every entry that is NOT keep_token.
        Errors are silently swallowed — this is best-effort cleanup.
        """
        import os
        api_dir = resource_path("api")
        udd = os.path.join(api_dir, "userDataDir")
        if not os.path.isdir(udd):
            return

        # Keep only the first component of the token (before the colon).
        keep_raw = keep_token.split(":")[0] if keep_token else ""

        for entry in os.listdir(udd):
            if entry == keep_raw:
                continue
            session_id = entry
            
            # Spawn a daemon thread to clean up this session in parallel
            def _clean_single(sid):
                try:
                    gen_url = (
                        f"{self.main_window.wpp_server}"
                        f":{self.main_window.wpp_port}/api/{sid}"
                        f"/{self.main_window.wpp_api_key}/generate-token"
                    )
                    res = requests.post(gen_url, timeout=5)
                    if res.status_code in (200, 201):
                        hash_token = res.json().get("token")
                        token = f"{sid}:{hash_token}"
                        url = (
                            f"{self.main_window.wpp_server}"
                            f":{self.main_window.wpp_port}/api/{token}/close-session"
                        )
                        requests.post(
                            url,
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                            timeout=5,
                        )
                        logging.info("[cleanup_orphan_sessions] Closed orphan session: %s", sid)
                except Exception:
                    pass

            threading.Thread(target=_clean_single, args=(session_id,), daemon=True).start()



    # ── Connection status ──────────────────────────────────────────────────

    def check_connection_status(self):
        """Return True only if there is a saved token AND the API confirms the session is connected.

        A token is written to settings as soon as the user clicks "Connect" — before
        pairing is actually completed.  If the app is closed mid-pairing or an error
        occurs, the stale token remains in settings.  On the next launch we must
        validate with the server that the session is genuinely connected; otherwise
        the connection dialog is never shown and the user is stuck with a broken state.
        """
        private_info = self.main_window.settings.get("privateinfo", {})
        token = private_info.get("WA_token", "").strip()

        # Legacy fallback: token.tk file means old-format paired session.
        if not token:
            return os.path.exists(data_path("token.tk"))

        # Validate with the API that this token's session is actually connected.
        # We query the specific check-connection-session endpoint which tells us if the WhatsApp
        # account is genuinely authenticated/linked.
        try:
            check_url = (
                f"{self.main_window.wpp_server}"
                f":{self.main_window.wpp_port}/api/{token}/check-connection-session"
            )
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            check_resp = requests.get(check_url, headers=headers, timeout=5)
            is_paired = private_info.get("paired", False)
            if check_resp.status_code in (200, 201):
                check_data = check_resp.json()
                # Only trust check-connection-session if the user actually completed pairing.
                # The WPPConnect browser can stay alive for a while after the app closes
                # mid-pairing, causing this endpoint to return status:true even though the
                # WhatsApp account was never linked. Requiring paired=True prevents that false positive.
                if check_data.get("status") is True:
                    if not is_paired:
                        logging.info(
                            "[check_connection_status] check-connection-session returned true and paired=False. "
                            "Marking session as paired locally."
                        )
                        self.main_window.settings.setdefault("privateinfo", {})["paired"] = True
                        self.main_window.save_settings()
                    return True

                # status:false — session offline but may have valid token in store.
                # If paired=True, trust the local flag and let the app reconnect.
                if is_paired:
                    logging.info("[check_connection_status] Session offline but paired=True. Retaining token.")
                    return True

                logging.warning(
                    "[check_connection_status] check-connection-session returned false and paired=False. "
                    "Session is unlinked or incomplete. Clearing WA_token and wiping local data."
                )
                self.main_window.settings.setdefault("privateinfo", {})["WA_token"] = ""
                self.main_window.settings.setdefault("privateinfo", {}).pop("paired", None)
                self.main_window.save_settings()
                # Clear all cached chats/contacts/media to avoid cross-account data leakage
                self.main_window.clear_local_data()
                # Best-effort delete of orphaned instance
                if token:
                    def _close(t=token):
                        try:
                            requests.post(
                                f"{self.main_window.wpp_server}:{self.main_window.wpp_port}/api/{t}/close-session",
                                headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                                timeout=5,
                            )
                        except Exception:
                            pass
                    threading.Thread(target=_close, daemon=True).start()
                return False

            # Fallback/Safety Check: also check general status-session
            url = (
                f"{self.main_window.wpp_server}"
                f":{self.main_window.wpp_port}/api/{token}/status-session"
            )
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code in (200, 201):
                data = resp.json()
                status = (
                    data.get("status")
                    or data.get("state")
                    or data.get("response", {}).get("status")
                    or ""
                )
                if status == "CONNECTED":
                    if not is_paired:
                        logging.info(
                            "[check_connection_status] status-session returned CONNECTED and paired=False. "
                            "Marking session as paired locally."
                        )
                        self.main_window.settings.setdefault("privateinfo", {})["paired"] = True
                        self.main_window.save_settings()
                    return True
                _INCOMPLETE = {"INITIALIZING", "QRCODE", "PHONECODE", ""}
                if status not in _INCOMPLETE and is_paired:
                    # Session is connected or closed (but closed is allowed if still paired)
                    return True
                # Stale token — pairing was never finished. Clear it so the
                # connection dialog is shown on this and future launches.
                logging.warning(
                    "[check_connection_status] Token exists but session status is '%s' "
                    "and paired=%s (pairing incomplete). Clearing stale WA_token and wiping local data.",
                    status,
                    is_paired,
                )
                self.main_window.settings.setdefault("privateinfo", {})["WA_token"] = ""
                self.main_window.settings.setdefault("privateinfo", {}).pop("paired", None)
                self.main_window.save_settings()
                if is_paired:
                    # Clear local cached data if it was previously paired
                    self.main_window.clear_local_data()
                # Best-effort delete of orphaned instance
                if token:
                    def _close(t=token):
                        try:
                            requests.post(
                                f"{self.main_window.wpp_server}:{self.main_window.wpp_port}/api/{t}/close-session",
                                headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                                timeout=5,
                            )
                        except Exception:
                            pass
                    threading.Thread(target=_close, daemon=True).start()
                return False
        except Exception as exc:
            # If the API is unreachable (still starting up), only assume the token is valid
            # when the user has previously completed pairing. If paired=False, the connection
            # dialog must be shown — the exception could have been an AttributeError or timeout
            # that masked a stale/mid-pairing token.
            logging.warning("[check_connection_status] Could not reach API to validate token: %s", exc)
            is_paired = self.main_window.settings.get("privateinfo", {}).get("paired", False)
            if is_paired:
                return True
            logging.warning(
                "[check_connection_status] API unreachable and paired=False — clearing stale token and showing connection dialog."
            )
            self.main_window.settings.setdefault("privateinfo", {})["WA_token"] = ""
            self.main_window.save_settings()
            return False

        return False

    # ── Connection dialog ──────────────────────────────────────────────────

    def show_connection_dial(self):
        self.connection_dial = wx.Dialog(None, title=self.i18n.t("connect_phone").format(app_name=self.main_window.app_name), size=(400, 500))

        # QR-CODE Panel
        self.qrcode_panel = wx.Panel(self.connection_dial)
        self.qrcode_instructions = wx.StaticText(self.qrcode_panel, label=self.i18n.t("qrcode_instructions"))
        self.qrcode_image = wx.StaticBitmap(self.qrcode_panel, size=(300, 300))
        self.switch_to_phone_btn = wx.Button(self.qrcode_panel, label=self.i18n.t("connect_with_phone"))
        self.switch_to_phone_btn.Bind(wx.EVT_BUTTON, self.on_switch_to_phone)

        qrcode_sizer = wx.BoxSizer(wx.VERTICAL)
        qrcode_sizer.Add(self.qrcode_instructions, 0, wx.ALL | wx.CENTER, 10)
        qrcode_sizer.Add(self.qrcode_image, 0, wx.ALL | wx.CENTER, 10)
        qrcode_sizer.Add(self.switch_to_phone_btn, 0, wx.ALL | wx.CENTER, 10)
        self.qrcode_panel.SetSizer(qrcode_sizer)

        # Hide QR-CODE panel by default
        self.qrcode_panel.Hide()

        # Phone Number Panel
        self.phone_panel = wx.Panel(self.connection_dial)

        # ── Country selector ──────────────────────────────────────────────
        self.country_label_ctrl = wx.StaticText(
            self.phone_panel, label=self.i18n.t("country_label")
        )
        self.country_combo = wx.ComboBox(
            self.phone_panel,
            style=wx.CB_READONLY,
            choices=[c[0] for c in COUNTRIES],
        )
        self.country_combo.SetSelection(0)   # Brazil
        self.country_combo.Bind(wx.EVT_COMBOBOX, self.on_country_changed)

        # ── Phone number field ────────────────────────────────────────────
        self.phone_number_label = wx.StaticText(
            self.phone_panel, label=self.i18n.t("enter_phone")
        )
        self.phone_field = wx.TextCtrl(
            self.phone_panel,
            value=f"+{self._current_dial_code} ",
            style=wx.TE_CENTER | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP,
        )
        self.phone_field.Bind(wx.EVT_CHAR,       self.on_phone_char)
        self.phone_field.Bind(wx.EVT_TEXT,       self.on_phone_text_changed)
        self.phone_field.Bind(wx.EVT_TEXT_ENTER, self.on_continue)
        self.phone_field.SetInsertionPointEnd()

        self.continue_btn = wx.Button(self.phone_panel, label=self.i18n.t("continue"))
        self.continue_btn.Bind(wx.EVT_BUTTON, self.on_continue)
        self.switch_to_qrcode_btn = wx.Button(
            self.phone_panel, label=self.i18n.t("connect_with_qrcode")
        )
        self.switch_to_qrcode_btn.Bind(wx.EVT_BUTTON, self.on_switch_to_qrcode)

        phone_sizer = wx.BoxSizer(wx.VERTICAL)
        phone_sizer.Add(self.country_label_ctrl,  0, wx.LEFT | wx.TOP,        10)
        phone_sizer.Add(self.country_combo,        0, wx.ALL | wx.EXPAND,     10)
        phone_sizer.Add(self.phone_number_label,   0, wx.LEFT | wx.TOP,       10)
        phone_sizer.Add(self.phone_field,          0, wx.ALL | wx.EXPAND,     10)
        phone_sizer.Add(self.continue_btn,         0, wx.ALL | wx.CENTER,     10)
        phone_sizer.Add(self.switch_to_qrcode_btn, 0, wx.ALL | wx.CENTER,     10)
        self.phone_panel.SetSizer(phone_sizer)

        # Quit button
        self.quit_btn = wx.Button(self.connection_dial, wx.ID_CANCEL, "&Sair")
        self.quit_btn.Bind(wx.EVT_BUTTON, self.on_quit_from_connect)

        # Bind close event
        self.connection_dial.Bind(wx.EVT_CLOSE, self.on_dialog_close)

        # Main sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.qrcode_panel, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(self.phone_panel, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(self.quit_btn, 0, wx.ALL | wx.CENTER, 5)
        self.connection_dial.SetSizer(main_sizer)

        # Guard: catch wxAssertionError if the event loop has already exited
        # during shutdown. wx.GetApp() still exists — only the loop is gone.
        try:
            self.connection_dial.ShowModal()
        except Exception:
            logging.exception("show_connection_dial: could not show dialog (shutting down?)")
        finally:
            self.connection_dial.Destroy()
            self.connection_dial = None

    def on_switch_to_phone(self, event):
        # Set connection mode to phone
        self.connection_mode = "phone"

        # Disconnect WebSocket when switching to phone mode
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()

        self.qrcode_panel.Hide()
        self.phone_panel.Show()
        self.connection_dial.Layout()
        self.phone_field.SetFocus()
        self.phone_field.SetInsertionPointEnd()


    def on_switch_to_qrcode(self, event):
        # Set connection mode to qrcode
        self.connection_mode = "qrcode"

        self.phone_panel.Hide()
        self.qrcode_panel.Show()
        self.connection_dial.Layout()

        if not hasattr(self, 'qrcode_connection_started'):
            # First time: start full QR-CODE connection
            self.start_qrcode_connection()
        else:
            # Already tried QR-CODE before: just reconnect WebSocket
            self.reconnect_websocket()

        self.main_window.qrcode_loaded_sound.play()
        self.main_window.output(self.i18n.t("qrcode_instructions"))

    def start_qrcode_connection(self):
        """Initiates QR-CODE connection without user interaction."""
        self.qrcode_connection_started = True
        try:
            # Determine whether a token has been saved from a previous session.
            # We still always call _create_instance to (re)start the WPPConnect
            # session in case the API was restarted since the last connection.
            existing_token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            _instance_exists = bool(existing_token)

            server_base = f"{self.main_window.wpp_server}:{self.main_window.wpp_port}"
            api_key = self.main_window.wpp_api_key

            def _generate_hash(raw: str) -> str:
                """Call generate-token and return 'raw:hash'. Raises on failure."""
                url = f"{server_base}/api/{raw}/{api_key}/generate-token"
                res = requests.post(url, timeout=10)
                if res.status_code in (200, 201):
                    hash_token = res.json().get("token") or ""
                    if hash_token:
                        return f"{raw}:{hash_token}"
                    raise RuntimeError(
                        f"generate-token returned empty hash (HTTP {res.status_code})"
                    )
                raise RuntimeError(
                    f"generate-token failed: HTTP {res.status_code} — {res.text[:200]}"
                )

            if _instance_exists:
                # Re-generate hash if the stored token has no colon (legacy or corrupt).
                # Without a hash the auth middleware returns 401 on every API call.
                if ":" not in existing_token:
                    try:
                        existing_token = _generate_hash(existing_token)
                    except Exception as exc:
                        logging.warning(
                            "[start_qrcode_connection] Could not refresh token hash: %s", exc
                        )
                self.main_window.token = existing_token
            else:
                # New pairing: reset sync flag so we wait for messages.set
                self.main_window.settings["status"]["messages_set_completed"] = False
                self.main_window.save_settings()
                self.main_window.clear_local_data()
                raw_token = self.generate_random_token()
                # Raise on failure so the outer except shows a meaningful message
                # instead of an opaque 401 from _create_instance.
                self.main_window.token = _generate_hash(raw_token)
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token

            # Always (re)start the session so WPPConnect launches Chrome and
            # emits qrCode. WPPConnect tolerates a start-session when a session
            # already exists — it will simply resume it (or show a new QR if
            # the session was invalidated).
            self._create_instance(self.main_window.token)

            # Save settings
            self.main_window.save_settings()

            # Set websocket client and connect BEFORE querying status so we
            # don't miss the qrCode Socket.IO event that comes asynchronously.
            self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)

            try:
                self.main_window.connect_websocket()
            except Exception:
                self.main_window.error_sound.play()
                wx.MessageBox(self.i18n.t("websocket_failed_reconnect"), self.i18n.t("connection_error"), wx.OK | wx.ICON_WARNING)
                self.show_connection_dial()
                return

            # Poll status-session to pick up a QR code that may already be ready.
            url = (
                f"{self.main_window.wpp_server}"
                f":{self.main_window.wpp_port}/api/{self.main_window.token}/status-session"
            )
            try:
                response = requests.get(url, headers=self._wpp_headers())
                response_data = response.json()
                qrcode_base64 = (
                    response_data.get("qrcode")
                    or response_data.get("urlcode")
                    or (response_data.get("response") or {}).get("qrcode")
                )
                if qrcode_base64:
                    wx.CallAfter(self.display_qrcode_image, qrcode_base64)
            except Exception:
                pass

        except Exception:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('connection_failed').format(app_name=self.main_window.app_name)} {format_exc()}", self.i18n.t("connection_error").format(app_name=self.main_window.app_name), wx.OK | wx.ICON_ERROR)

    def display_qrcode_image(self, base64_string):
        """Decodes and displays the base64 QR-CODE image."""
        try:
            # Remove data URI prefix if present
            if "," in base64_string:
                base64_string = base64_string.split(",")[1]

            # Decode base64 to image
            image_data = base64.b64decode(base64_string)
            image = wx.Image(BytesIO(image_data))

            # Scale image if needed
            width, height = 300, 300
            image = image.Scale(width, height, wx.IMAGE_QUALITY_HIGH)

            # Convert to bitmap and display
            bitmap = wx.Bitmap(image)
            self.qrcode_image.SetBitmap(bitmap)

            # Play sound notification
            self.main_window.pairing_code_updated_sound.play()

        except Exception:
            pass

    def reconnect_websocket(self):
        """Reconnects WebSocket for QR-CODE mode (instance already created)."""
        try:
            self.main_window.connect_websocket()
        except Exception:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('websocket_init_failed')} {format_exc()}", self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)

    def on_continue(self, event):
        """Phone-number pairing flow (asynchronous to prevent GUI freeze)."""
        self.phone_number = "".join(
            c for c in self.phone_field.GetValue() if c.isdigit()
        )
        if not self.phone_number:
            return

        # Disable continue button and show connecting status to user
        self.continue_btn.Disable()
        self.continue_btn.SetLabel(self.i18n.t("connecting") or "Conectando...")
        self.main_window.output(self.i18n.t("connecting") or "Conectando...")

        # Monkey-patch wx.GetApp to ensure background threads can access the app instance
        # even before the MainLoop is entered (which is blocked by ShowModal).
        app = wx.GetApp()
        if app:
            wx.GetApp = lambda: app

        def _bg_pairing_flow():
            try:
                # Normalise stored number to digits-only for comparison
                stored_raw = "".join(
                    c for c in self.main_window.settings.get("privateinfo", {}).get(
                        "WA_phone_number", ""
                    )
                    if c.isdigit()
                )
                # Check if the user has already paired with this number.
                existing_token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
                _instance_exists = bool(stored_raw == self.phone_number and existing_token)
                if not _instance_exists:
                    # New pairing: reset sync flag so we wait for messages.set
                    self.main_window.settings["status"]["messages_set_completed"] = False
                    self.main_window.clear_local_data()

                if _instance_exists:
                    self.main_window.token = existing_token
                else:
                    # Kill any leftover Chromium sessions from previous failed attempts
                    # so only ONE browser runs at a time (prevents Auto Close race).
                    self._cleanup_orphan_sessions(keep_token="")
                    raw_token = self.generate_random_token()
                    url = f"{self.main_window.wpp_server}:{self.main_window.wpp_port}/api/{raw_token}/{self.main_window.wpp_api_key}/generate-token"
                    try:
                        res = requests.post(url, timeout=10)
                        if res.status_code in (200, 201):
                            hash_token = res.json().get("token")
                            self.main_window.token = f"{raw_token}:{hash_token}"
                        else:
                            self.main_window.token = raw_token
                    except Exception:
                        self.main_window.token = raw_token

                # Terminate any existing session running on the server. If a session is already
                # active/initializing in QR code mode (e.g. from the startup check), WPPConnect
                # will ignore new start-session requests, and the pairing code will never generate.
                # We fire close-session and immediately set up the WebSocket in parallel to avoid
                # the 2s blocking wait — the Node side handles the close asynchronously.
                headers = self._wpp_headers(use_global_key=True)
                close_done = threading.Event()

                def _close_and_signal():
                    try:
                        close_url = (
                            f"{self.main_window.wpp_server}"
                            f":{self.main_window.wpp_port}/api/{self.main_window.token}/close-session"
                        )
                        requests.post(close_url, headers=headers, timeout=10)
                        logging.info("[_bg_pairing_flow] Closed existing session to prepare for pairing code")
                    except Exception as e:
                        logging.warning("[_bg_pairing_flow] Failed to close existing session: %s", e)
                    finally:
                        close_done.set()

                threading.Thread(target=_close_and_signal, daemon=True).start()

                # Wait for close to finish (max 3s) so Node has time to release the session
                # and unlock userDataDir before we call /start-session.
                close_done.wait(timeout=3)

                # Set up the websocket client (but do not connect yet)
                self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)
                if self.main_window.ws:
                    self.main_window.ws._phone_code_event.clear()
                    with self.main_window.ws._phone_code_lock:
                        self.main_window.ws._phone_code_value = ""

                # Call /start-session in a background thread. This immediately registers the namespace on Node side.
                url = (
                    f"{self.main_window.wpp_server}"
                    f":{self.main_window.wpp_port}/api/{self.main_window.token}/start-session"
                )
                payload = {"phone": self.phone_number, "waitQrCode": True}
                ws_ref = self.main_window.ws  # capture before thread starts

                def _call_start_session():
                    try:
                        resp = requests.post(url, json=payload, headers=headers, timeout=120)
                        # If the code came back inline (rare), unblock the wait loop.
                        inline_code = resp.json().get("phoneCode", "")
                        if inline_code and not ws_ref._phone_code_event.is_set():
                            with ws_ref._phone_code_lock:
                                ws_ref._phone_code_value = str(inline_code)
                            ws_ref._phone_code_event.set()
                    except Exception:
                        # Signal the event so the main thread doesn't wait forever.
                        ws_ref._phone_code_event.set()

                threading.Thread(target=_call_start_session, daemon=True).start()

                # Connect the WebSocket
                try:
                    self.main_window.connect_websocket()
                except Exception:
                    pass

                # Wait up to 90 s for WPPConnect to emit the phoneCode via Socket.IO.
                got_code = self.main_window.ws._phone_code_event.wait(timeout=90)
                with self.main_window.ws._phone_code_lock:
                    pairing_code = self.main_window.ws._phone_code_value if got_code else ""

                if pairing_code:
                    # Only now persist the token — pairing has actually started.
                    if "privateinfo" not in self.main_window.settings:
                        self.main_window.settings["privateinfo"] = {}
                    self.main_window.settings["privateinfo"]["WA_phone_number"] = self.phone_number
                    self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token
                    self.main_window.save_settings()
                    wx.CallAfter(self._on_pairing_code_success, pairing_code)
                else:
                    # No code received — clear any partially-saved token so next
                    # launch shows the connection dialog instead of acting connected.
                    self.main_window.settings.setdefault("privateinfo", {})["WA_token"] = ""
                    self.main_window.save_settings()
                    wx.CallAfter(self._on_pairing_code_error)

            except Exception as exc:
                # On any unexpected error, clear the token so next launch works correctly.
                self.main_window.settings.setdefault("privateinfo", {})["WA_token"] = ""
                self.main_window.save_settings()
                wx.CallAfter(self._on_pairing_code_exception, str(exc))

        threading.Thread(target=_bg_pairing_flow, daemon=True).start()

    def _on_pairing_code_success(self, pairing_code):
        self.continue_btn.Enable()
        self.continue_btn.SetLabel(self.i18n.t("continue"))
        self.show_pairing_dial(pairing_code)

    def _on_pairing_code_error(self):
        self.continue_btn.Enable()
        self.continue_btn.SetLabel(self.i18n.t("continue"))
        wx.MessageBox(
            self.i18n.t("no_pairing_code_received").format(app_name=self.main_window.app_name),
            self.i18n.t("connection_error"),
            wx.OK | wx.ICON_ERROR,
        )

    def _on_pairing_code_exception(self, err_msg):
        self.continue_btn.Enable()
        self.continue_btn.SetLabel(self.i18n.t("continue"))
        self.main_window.error_sound.play()
        wx.MessageBox(
            f"{self.i18n.t('connection_failed').format(app_name=self.main_window.app_name)} {err_msg}",
            self.i18n.t('connection_error').format(app_name=self.main_window.app_name),
            wx.OK | wx.ICON_ERROR,
        )


    # ── Phone formatter ────────────────────────────────────────────────────

    def on_country_changed(self, event):
        """Update the dial code and reformat the phone field."""
        idx = self.country_combo.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        _, new_code = COUNTRIES[idx]

        # Preserve the local digits already typed (strip old country code prefix)
        text       = self.phone_field.GetValue()
        all_digits = "".join(c for c in text if c.isdigit())
        old_cc     = self._current_dial_code
        local_digits = (
            all_digits[len(old_cc):]
            if all_digits.startswith(old_cc)
            else all_digits
        )

        self._current_dial_code = new_code

        self._phone_updating = True
        try:
            self.phone_field.ChangeValue(
                self._format_phone_display(new_code + local_digits)
            )
            self.phone_field.SetInsertionPointEnd()
        finally:
            self._phone_updating = False

    def on_phone_char(self, event):
        """
        Filter individual keystrokes in the phone field.

        Digits (0-9 and numpad), navigation keys and Ctrl+key combinations
        pass through.  Everything else (letters, punctuation, @, _, …) is
        consumed and the screen reader announces "Caractere inválido".
        """
        key = event.GetKeyCode()

        # Navigation / editing keys always pass through
        _NAV = {
            wx.WXK_BACK, wx.WXK_DELETE,
            wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END,
            wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER,
            wx.WXK_TAB, wx.WXK_ESCAPE,
        }
        if key in _NAV:
            event.Skip()
            return

        # Any Ctrl+key combo (clipboard shortcuts, select-all, …)
        if event.ControlDown():
            event.Skip()
            return

        # Main keyboard digits
        if ord("0") <= key <= ord("9"):
            event.Skip()
            return

        # Numpad digits
        if wx.WXK_NUMPAD0 <= key <= wx.WXK_NUMPAD9:
            event.Skip()
            return

        # Anything else → reject and announce
        self.main_window.speak_output.output(
            self.main_window.i18n.t("invalid_char")
        )
        # Do NOT call event.Skip() — the character is swallowed

    def on_phone_text_changed(self, event):
        """
        Reformat the phone field after every text change (including paste).

        If the new text contains characters that are not digits and not our
        formatting symbols (+, -, space), the screen reader announces
        "Caractere inválido" and those characters are silently stripped.
        """
        if self._phone_updating:
            return
        self._phone_updating = True
        try:
            text = self.phone_field.GetValue()

            # Detect truly invalid chars coming from paste
            _fmt = set("+- ")
            if any(c not in _fmt and not c.isdigit() for c in text):
                self.main_window.speak_output.output(
                    self.main_window.i18n.t("invalid_char")
                )

            digits    = "".join(c for c in text if c.isdigit())
            formatted = self._format_phone_display(digits)
            if formatted != text:
                self.phone_field.ChangeValue(formatted)
                self.phone_field.SetInsertionPointEnd()
        finally:
            self._phone_updating = False

    def _format_phone_display(self, digits: str) -> str:
        """Convert a raw digit string (including country code) to display format.

        Brazil (CC=55): +55 DD XXXXX-XXXX or +55 DD XXXX-XXXX
        All other countries: +CC local  (no area-code split, no hyphen)
        """
        cc    = self._current_dial_code
        local = digits[len(cc):] if digits.startswith(cc) else digits

        result = f"+{cc}"
        if not local:
            return result

        if cc == "55":
            # Brazil: 2-digit DDD + body with hyphen
            area = local[:2]
            rest = local[2:]
            result += f" {area}"
            if not rest:
                return result
            if len(rest) < 7:
                result += f" {rest}"
            elif len(rest) == 9:
                result += f" {rest[:5]}-{rest[5:]}"
            else:
                split = len(rest) - 4
                result += f" {rest[:split]}-{rest[split:]}"
        else:
            # Generic international: just append local digits with a space
            result += f" {local}"

        return result

    def generate_random_token(self):
        return os.urandom(16).hex()

    def show_pairing_dial(self, pairing_code):
        self.pairing_dial = wx.Dialog(self.connection_dial, title=self.i18n.t("pairing_dial_intro"), size=(300, 150))
        self.pairing_instructions = wx.StaticText(self.pairing_dial, label=self.i18n.t("pairing_instructions"))
        self.pairing_code_label = wx.StaticText(self.pairing_dial, label=self.i18n.t("pairing_code_label"))
        self.pairing_code_field = wx.TextCtrl(self.pairing_dial, style=wx.TE_CENTER | wx.TE_READONLY | wx.TE_DONTWRAP, value=pairing_code)
        self.cancel_btn = wx.Button(self.pairing_dial, label=self.i18n.t("cancel_pairing"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel_pairing)

        self.main_window.waiting_pairing_sound.play()
        self.pairing_dial.ShowModal()

    def on_cancel_pairing(self, event):
        self.pairing_dial.Destroy()
        
        # Disconnect WebSocket
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()

        # Call close-session API endpoint to terminate the headless browser and clear state
        token = getattr(self.main_window, 'token', '')
        if token:
            def _close_api_session():
                try:
                    close_url = (
                        f"{self.main_window.wpp_server}"
                        f":{self.main_window.wpp_port}/api/{token}/close-session"
                    )
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    requests.post(close_url, headers=headers, timeout=5)
                except Exception:
                    pass
            threading.Thread(target=_close_api_session, daemon=True).start()

    def on_dialog_close(self, event):
        # Disconnect WebSocket if connected
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()
        
        # Call close-session API endpoint to terminate the headless browser
        token = getattr(self.main_window, 'token', '')
        if token:
            def _close_api_session():
                try:
                    close_url = (
                        f"{self.main_window.wpp_server}"
                        f":{self.main_window.wpp_port}/api/{token}/close-session"
                    )
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    requests.post(close_url, headers=headers, timeout=5)
                except Exception:
                    pass
            threading.Thread(target=_close_api_session, daemon=True).start()
        event.Skip()

    def on_quit_from_connect(self, event):
        sys.exit()
