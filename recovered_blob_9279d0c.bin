import os
import sys
import threading
import socketio
import wx
import requests
from core.i18n import I18n
from core.websocket_client import WebSocketClient
from app_paths import data_path, resource_path
from traceback import format_exc
import json
import base64
from io import BytesIO
from countries import COUNTRIES

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

    def _licensing_email(self) -> str:
        """Return the LICENSING_USER_EMAIL from .env, or the hardcoded default."""
        default = "test@email.com"
        for env_path in [
            resource_path(".env"),
            os.path.join(os.path.dirname(resource_path()), ".env"),
        ]:
            if os.path.isfile(env_path):
                try:
                    with open(env_path, encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            k, _, v = line.partition("=")
                            if k.strip() == "EVOLUTION_LICENSING_USER_EMAIL":
                                val = v.strip()
                                return val if val else default
                except Exception:
                    pass
        return default

    def _evolution_headers(self, use_global_key=False):
        """Return headers for Evolution API requests."""
        apikey = (
            self.main_window.evolution_api_key
            if use_global_key
            else self.main_window.token
        )
        return {"apikey": apikey, "Content-Type": "application/json"}

    def _create_instance(self, token):
        """
        Create a WhatsApp instance in the local Evolution API.

        If the instance already exists (HTTP 409) that is fine — we simply
        reuse it.  Any other non-2xx response is raised as a RuntimeError so
        the caller can surface a meaningful error to the user.

        Special case — HTTP 503 / LICENSE_REQUIRED (Evolution API v2.4+):
        The local Evolution API has not been activated yet.  We call
        ``_activate_instance()`` which posts to the external auto-activation
        endpoint and returns the api_key issued by the licensing server.  That
        key is stored in settings (persisted across restarts) and used as the
        ``apikey`` header for the retry.  If the retry still fails or the
        external call raises, the exception propagates to the caller.

        Note: the phone number for pairing-code flows does NOT belong in the
        create payload; it is passed later to /instance/connect as a query
        parameter.
        """
        url = (
            f"{self.main_window.evolution_server}"
            f":{self.main_window.evolution_port}/instance/create"
        )
        payload = {
            "instanceName": token,
            "token":        token,
            "integration":  "WHATSAPP-BAILEYS",
            "qrcode":       False,
            "syncFullHistory": True,
        }
        headers = self._evolution_headers(use_global_key=True)

        for attempt in range(2):
            response = requests.post(url, json=payload, headers=headers, timeout=15)

            if response.status_code in (200, 201):
                try:
                    data = response.json()
                    instance_id = (
                        data.get("instance", {}).get("instanceId")
                        or data.get("instance", {}).get("id")
                        or data.get("instanceId")
                        or data.get("id")
                    )
                    return instance_id  # May be None if not present in response
                except Exception:
                    return None

            if response.status_code == 409:
                return None  # Already exists — reuse it

            # HTTP 503 + LICENSE_REQUIRED (Evolution API v2.4+):
            # Auto-activate via the licensing server, then retry once.
            # _activate_instance() returns the api_key issued by the licensing
            # server; that key must replace the default global key for all
            # subsequent calls so the local API accepts them.
            if response.status_code == 503 and attempt == 0:
                try:
                    data = response.json()
                except Exception:
                    data = {}
                if data.get("code") == "LICENSE_REQUIRED":
                    instance_id_from_503 = (
                        data.get("instance_id")
                        or data.get("instanceId")
                        or data.get("id")
                    )
                    if instance_id_from_503:
                        # May raise RuntimeError — let it propagate so the
                        # caller shows a meaningful error to the user.
                        new_api_key = self._activate_instance(instance_id_from_503)
                        if new_api_key:
                            # Persist the key: main.py reads evolution_api_key
                            # from settings["connection"]["evolution_api_key"],
                            # so this survives across restarts.
                            self.main_window.evolution_api_key = new_api_key
                            self.main_window.settings.setdefault("connection", {})[
                                "evolution_api_key"
                            ] = new_api_key
                            self.main_window.save_settings()
                            headers = {
                                "apikey": new_api_key,
                                "Content-Type": "application/json",
                            }
                        continue  # retry with updated (or same) headers
                    # 503 LICENSE_REQUIRED but no instance_id in body — fall through

            # Any other status is a real failure
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")

    def _setup_websocket_for_instance(self, token):
        """
        Enable and configure Socket.IO event delivery for this instance.

        The Evolution API expects the payload nested under a "websocket" key:
            {"websocket": {"enabled": true, "events": [...]}}

        Uses the global api_key (works before and after license activation).
        Raises RuntimeError on any non-2xx response so the caller can surface
        the error rather than silently proceeding to a doomed connect_websocket.
        """
        url = (
            f"{self.main_window.evolution_server}"
            f":{self.main_window.evolution_port}/websocket/set/{token}"
        )
        payload = {
            "websocket": {
                "enabled": True,
                "events": _WEBSOCKET_EVENTS,
            }
        }
        response = requests.post(
            url, json=payload,
            headers=self._evolution_headers(use_global_key=True),
            timeout=10,
        )
        if response.status_code not in (200, 201):
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"websocket/set failed — HTTP {response.status_code}: {detail}"
            )

    def _activate_instance(self, instance_id: str) -> str | None:
        """
        Register this Evolution API installation with the licensing server
        (required since v2.4.0) using the auto-activation endpoint.

        Returns the api_key that the licensing server issued, which must be
        used as the ``apikey`` header for all subsequent local Evolution API
        calls in this session.  The caller is responsible for persisting the
        key to settings so future sessions skip this step.

        Raises RuntimeError on any non-2xx response from the licensing server.
        """
        url = "https://license.evolutionfoundation.com.br/v1/register/auto"
        payload = {
            "email":       self._licensing_email(),
            "tier":        "community",
            "version":     "2.4.0",
            "instance_id": instance_id,
        }
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code not in (200, 201):
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"Licensing activation failed — HTTP {response.status_code}: {detail}"
            )
        data = response.json()
        # Extract the api_key returned by the licensing server.
        # Evolution API uses this key as the bearer for all requests once
        # the installation is activated.
        return (
            data.get("api_key")
            or data.get("apikey")
            or data.get("token")
            or (data.get("hash") or {}).get("apikey")
            or (data.get("instance") or {}).get("apikey")
        )

    # ── Connection status ──────────────────────────────────────────────────

    def check_connection_status(self):
        private_info = self.main_window.settings.get("privateinfo", {})
        if private_info.get("WA_token", "").strip():
            return True
        # Legacy fallback: accept token.tk so migrate path in retrieve_token() runs
        return os.path.exists(data_path("token.tk"))

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

        self.connection_dial.ShowModal()

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
            # Ensure messages_set_completed is set to False
            self.main_window.settings["status"]["messages_set_completed"] = False
            self.main_window.save_settings()

            # Determine whether an instance already exists for this token.
            # If WA_token is already saved the Evolution API instance was created
            # in a previous session — skip create + websocket-setup and go
            # straight to /instance/connect.
            existing_token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            _instance_exists = bool(existing_token)

            if _instance_exists:
                self.main_window.token = existing_token
            else:
                self.main_window.token = self.generate_random_token()
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token

            if not _instance_exists:
                # Step 1 – Create Evolution API instance (first time only).
                # Handles 503/LICENSE_REQUIRED via auto-activation internally.
                self._create_instance(self.main_window.token)

                # Step 2 – Configure WebSocket events for this instance
                self._setup_websocket_for_instance(self.main_window.token)

            # Save settings
            self.main_window.save_settings()

            # Set websocket client
            self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)

            # Step 3 – Connect instance (get QR-CODE)
            url = (
                f"{self.main_window.evolution_server}"
                f":{self.main_window.evolution_port}/instance/connect/{self.main_window.token}/"
            )
            response = requests.get(url, headers=self._evolution_headers())
            response_data = response.json()

            if response_data.get("base64"):
                # Connect WebSocket
                self.main_window.connect_websocket()
                # Display QR-CODE image
                self.display_qrcode_image(response_data.get("base64"))
            else:
                wx.MessageBox(self.i18n.t("no_QRcode_received").format(app_name=self.main_window.app_name), self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)

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
        """Phone-number pairing flow."""
        try:
            # Always send raw digits to the API (strip formatting chars)
            self.phone_number = "".join(
                c for c in self.phone_field.GetValue() if c.isdigit()
            )
            if not self.phone_number:
                return
            #Ensure messages_set_completed is set to False
            self.main_window.settings["status"]["messages_set_completed"] = False
            self.main_window.save_settings()
            # Normalise stored number to digits-only for comparison
            stored_raw = "".join(
                c for c in self.main_window.settings.get("privateinfo", {}).get(
                    "WA_phone_number", ""
                )
                if c.isdigit()
            )
            # Check if the user has already paired with this number.
            # If both the phone number and WA_token are already saved, the
            # Evolution API instance was created in a previous session — skip
            # create + websocket-setup and jump straight to /instance/connect.
            existing_token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            _instance_exists = bool(stored_raw == self.phone_number and existing_token)

            if _instance_exists:
                self.main_window.token = existing_token
            else:
                self.main_window.token = self.generate_random_token()
                # Set the new token and phone number in settings
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_phone_number"] = self.phone_number
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token

            if not _instance_exists:
                # Step 1 – Create Evolution API instance (first time only).
                # Handles 503/LICENSE_REQUIRED via auto-activation internally.
                self._create_instance(self.main_window.token)

                # Step 2 – Configure WebSocket events for this instance
                self._setup_websocket_for_instance(self.main_window.token)

            # Save settings
            self.main_window.save_settings()
            # Set websocket client
            self.main_window.ws = WebSocketClient(self.main_window, self, self.main_window.token)

            # Step 3 – Connect instance (get pairing code)
            url = (
                f"{self.main_window.evolution_server}"
                f":{self.main_window.evolution_port}/instance/connect/{self.main_window.token}/"
            )
            response = requests.get(url, params={"number": self.phone_number}, headers=self._evolution_headers())
            response_data = response.json()

            if response_data.get("pairingCode"):
                #Connect WebSocket
                self.main_window.connect_websocket()
                self.show_pairing_dial(response_data.get("pairingCode"))
            else:
                wx.MessageBox(self.i18n.t("no_pairing_code_received").format(app_name=self.main_window.app_name), self.i18n.t("connection_error"), wx.OK | wx.ICON_ERROR)

        except Exception:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('connection_failed').format(app_name=self.main_window.app_name)} {format_exc()}", self.i18n.t('connection_error').format(app_name=self.main_window.app_name), wx.OK | wx.ICON_ERROR)

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
        """
        Convert a raw digit string (including country code) to the display
        format used in the phone field.

        Examples (CC = 55):
          "5551987560609"  →  "+55 51 98756-0609"   (9-digit mobile)
          "5551875606090"  →  "+55 51 8756-0609"    (8-digit landline)

        Rules:
          • Always begin with +CC.
          • Next 2 digits = area code (DDD), separated by a space.
          • Remaining digits: last 4 always appear after a hyphen once there
            are 7+ digits in the body; 9-digit body uses 5-4 split.
          • While the user is still typing (< 7 body digits) no hyphen is
            shown so the field doesn't jump unexpectedly.
        """
        cc = self._current_dial_code
        local = digits[len(cc):] if digits.startswith(cc) else digits

        result = f"+{cc}"
        if not local:
            return result

        # Area code: first 2 digits
        area = local[:2]
        rest = local[2:]
        result += f" {area}"
        if not rest:
            return result

        # Phone body
        if len(rest) < 7:
            # Still typing — no hyphen yet
            result += f" {rest}"
        elif len(rest) == 9:
            # Brazilian 9-digit mobile: 5-4 split
            result += f" {rest[:5]}-{rest[5:]}"
        else:
            # Generic: last 4 after hyphen
            split   = len(rest) - 4
            result += f" {rest[:split]}-{rest[split:]}"

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
        self.main_window.ws.sio.disconnect()

    def on_dialog_close(self, event):
        # Disconnect WebSocket if connected
        if hasattr(self.main_window, 'ws') and self.main_window.ws and self.main_window.ws.sio.connected:
            self.main_window.ws.sio.disconnect()
        event.Skip()

    def on_quit_from_connect(self, event):
        sys.exit()
