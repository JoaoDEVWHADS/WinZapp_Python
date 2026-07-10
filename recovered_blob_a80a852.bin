import os
import sys
import threading
import socketio
import wx
import json
from core.i18n import I18n
from app_paths import data_path
from traceback import format_exc

class WebSocketClient:
    def __init__(self, main_window, connect, instance_name):
        self.main_window = main_window
        self.connect = connect
        self.instance_name = instance_name
        #Initialize i18n
        self.i18n = I18n(self.main_window)
        self.i18n.get_language()

        self.sio = socketio.Client(
            reconnection=True, reconnection_attempts=5,
            logger=True
        )
        #Bind events
        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on("connection.update", self.on_connection_update, namespace=f"/{self.instance_name}")
        self.sio.on("qrcode.updated", self.on_qrcode_update, namespace=f"/{self.instance_name}")
        self.sio.on("messages.set", self.on_messages_set, namespace=f"/{self.instance_name}")
        self.sio.on("messages.upsert", self.on_messages_upsert, namespace=f"/{self.instance_name}")

    def on_connect(self):
        print("WebSocket connected.")

    def on_disconnect(self):
        print("WebSocket disconnected.")

    def on_connection_update(self, info):
        print(info)
        #Checks the new connection state
        connection_state = info.get("data", {}).get("state", "")
        if connection_state == "open":
            self.on_pairing_complete()
        elif connection_state == "close":
            self.main_window.error_sound.play()
            # Show error in the appropriate dialog
            parent_dialog = self.connect.pairing_dial if hasattr(self.connect, 'pairing_dial') else self.connect.connection_dial
            wx.MessageBox(self.i18n.t("instance_state_changed"), self.i18n.t("error"), wx.OK | wx.ICON_ERROR, parent_dialog)

    def on_pairing_complete(self):
        #Saves the new user token in the data  directory
        try:
            self.save_token(self.instance_name)
        except Exception as e:
            self.main_window.error_sound.play()
            wx.MessageBox(f"{self.i18n.t('token_save_failed')} {format_exc()}", self.i18n.t("error"), wx.OK | wx.ICON_ERROR)
            sys.exit()

        # Close pairing dialog if it exists (phone mode)
        if hasattr(self.connect, 'pairing_dial'):
            self.connect.pairing_dial.Destroy()

        # Close connection dialog
        self.connect.connection_dial.Destroy()

    def save_token(self, token):
        with open(data_path("token.tk"), "w") as token_file:
            token_file.write(token)


    def on_qrcode_update(self, info):
        print(info)
        # Check if this is QR-CODE mode (base64) or pairing code mode
        qr_data = info.get("data", {}).get("qrcode", {})

        # Use connection_mode to determine which mode we're in
        if self.connect.connection_mode == "qrcode" and qr_data.get("base64"):
            # QR-CODE mode: update the image
            self.main_window.pairing_code_updated_sound.play()
            self.main_window.speak_output.output(self.i18n.t("qrcode_image_updated"))
            self.connect.display_qrcode_image(qr_data.get("base64"))
        elif self.connect.connection_mode == "phone" and qr_data.get("pairingCode"):
            # Pairing code mode: update the text field
            self.main_window.pairing_code_updated_sound.play()
            self.main_window.speak_output.output(self.i18n.t("qrcode_updated"))
            self.connect.pairing_code_field.SetValue(qr_data.get("pairingCode", ""))

    def on_messages_set(self, info):
        #Only consider if messages_set for the first time is false
        if self.main_window.settings["status"].get("messages_set_completed", False):
            return
        self.main_window.settings["status"]["messages_set_completed"] = True
        self.main_window.save_settings()
        self.main_window.sync_thread = threading.Thread(target=self.main_window.start_sync, daemon=True)
        self.main_window.sync_thread.start()

    def on_messages_upsert(self, info):
        """
        Handle real-time incoming messages from the Evolution API.

        The event payload can arrive in two forms:
          • {"data": {"messages": [...], "type": "notify"}}   (most common)
          • {"data": [message_object, ...], "type": "notify"} (some versions)
        We only process type=="notify" (new messages) and skip
        type=="append" (history) or missing type (echo/status updates).
        """
        try:
            data = info.get("data", {})

            # Normalise: data may be a dict or a list
            if isinstance(data, dict):
                event_type = data.get("type", "")
                messages   = data.get("messages", [])
            elif isinstance(data, list):
                # Some Evolution versions send the messages array directly
                event_type = info.get("type", "notify")
                messages   = data
            else:
                return

            if event_type not in ("notify", ""):
                return

            if not isinstance(messages, list):
                messages = [messages]

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                # Skip reactions — they update an existing message, not a new one
                if msg.get("messageType") == "reactionMessage":
                    continue
                # Skip messages sent by ourselves (fromMe=True means we sent it;
                # the MessageQueue already handles those in the UI)
                if msg.get("key", {}).get("fromMe", False):
                    continue
                wx.CallAfter(self.main_window.on_new_message, msg)

        except Exception as e:
            print(f"[WebSocketClient] on_messages_upsert error: {e}")
