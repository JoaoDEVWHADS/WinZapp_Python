import os
import sys
import threading
import socketio
import wx
import requests
from i18n import I18n
from websocket_client import WebSocketClient
from app_paths import data_path
from traceback import format_exc
import json
import base64
from io import BytesIO

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

    # ── Helpers ────────────────────────────────────────────────────────────

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
            "syncFullHistory": False,
        }
        response = requests.post(
            url, json=payload,
            headers=self._evolution_headers(use_global_key=True),
            timeout=15,
        )
        if response.status_code in (200, 201):
            return  # Created successfully
        if response.status_code == 409:
            return  # Already exists — reuse it
        # Any other status is a real failure
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"HTTP {response.status_code}: {detail}"
        )

    def _setup_websocket_for_instance(self, token):
        """
        Enable and configure Socket.IO event delivery for this instance.
        Uses the instance's own token as the API key (not the global key).
        Called once after creating an instance.
        """
        url = (
            f"{self.main_window.evolution_server}"
            f":{self.main_window.evolution_port}/websocket/set/{token}"
        )
        payload = {"enabled": True, "events": _WEBSOCKET_EVENTS}
        try:
            requests.post(
                url, json=payload,
                headers=self._evolution_headers(),  # instance token, not global
                timeout=10,
            )
        except Exception:
            pass  # Non-critical — the app can still function without this

    # ── Connection status ──────────────────────────────────────────────────

    def check_connection_status(self):
        #Check if token file exists and WA_token is available in settings
        token_path = data_path("token.tk")
        private_info = self.main_window.settings.get("privateinfo", {})
        if os.path.exists(token_path) and private_info.get("WA_token"):
            return True
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
        self.phone_number_label = wx.StaticText(self.phone_panel, label=self.i18n.t("enter_phone"))
        self.phone_field = wx.TextCtrl(self.phone_panel, style=wx.TE_CENTER | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP)
        self.continue_btn = wx.Button(self.phone_panel, label=self.i18n.t("continue"))
        self.continue_btn.Bind(wx.EVT_BUTTON, self.on_continue)
        self.phone_field.Bind(wx.EVT_TEXT_ENTER, self.on_continue)
        self.switch_to_qrcode_btn = wx.Button(self.phone_panel, label=self.i18n.t("connect_with_qrcode"))
        self.switch_to_qrcode_btn.Bind(wx.EVT_BUTTON, self.on_switch_to_qrcode)

        phone_sizer = wx.BoxSizer(wx.VERTICAL)
        phone_sizer.Add(self.phone_number_label, 0, wx.ALL | wx.CENTER, 10)
        phone_sizer.Add(self.phone_field, 0, wx.ALL | wx.EXPAND, 10)
        phone_sizer.Add(self.continue_btn, 0, wx.ALL | wx.CENTER, 10)
        phone_sizer.Add(self.switch_to_qrcode_btn, 0, wx.ALL | wx.CENTER, 10)
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

            # Generate token if not already set
            if not self.main_window.settings.get("privateinfo", {}).get("WA_token"):
                self.main_window.token = self.generate_random_token()
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token
            else:
                self.main_window.token = self.main_window.settings.get("privateinfo", {}).get("WA_token")

            # Step 1 – Create Evolution instance
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
            self.phone_number = self.phone_field.GetValue()
            #Ensure messages_set_completed is set to False
            self.main_window.settings["status"]["messages_set_completed"] = False
            self.main_window.save_settings()
            #Check if the user has already tried to connect with this number
            if (
                self.main_window.settings.get("privateinfo", {}).get("WA_phone_number", "") == self.phone_number
                and self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            ):
                #Assume token available
                self.main_window.token = self.main_window.settings.get("privateinfo", {}).get("WA_token", "")
            else:
                self.main_window.token = self.generate_random_token()
                #Set the new token and phone number in settings
                if "privateinfo" not in self.main_window.settings:
                    self.main_window.settings["privateinfo"] = {}
                self.main_window.settings["privateinfo"]["WA_phone_number"] = self.phone_number
                self.main_window.settings["privateinfo"]["WA_token"] = self.main_window.token

            # Step 1 – Create Evolution instance
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
