import threading
import socketio
import wx
from core.i18n import I18n

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
        )
        #Bind events
        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on("connection.update", self.on_connection_update, namespace=f"/{self.instance_name}")
        self.sio.on("qrcode.updated", self.on_qrcode_update, namespace=f"/{self.instance_name}")
        self.sio.on("messages.set", self.on_messages_set, namespace=f"/{self.instance_name}")
        self.sio.on("messages.upsert", self.on_messages_upsert, namespace=f"/{self.instance_name}")
        self.sio.on("contacts.update", self.on_contacts_update, namespace=f"/{self.instance_name}")

    def on_connect(self):
        print("WebSocket connected.")

    def on_disconnect(self):
        print("WebSocket disconnected.")

    def on_connection_update(self, info):
        print(info)
        #Checks the new connection state
        connection_state = info.get("data", {}).get("state", "")
        if connection_state == "open":
            # Mark WhatsApp as connected so the MessageQueue resumes sending.
            self.main_window._wa_connected = True
            if hasattr(self.main_window, "message_queue"):
                self.main_window.message_queue.flush()
            self.on_pairing_complete()
        elif connection_state == "close":
            # Must run on the main thread — wx.MessageBox from a Socket.IO
            # I/O thread triggers COM cross-thread errors and can freeze the app.
            def _show_error():
                self.main_window.error_sound.play()
                parent_dialog = (
                    self.connect.pairing_dial
                    if hasattr(self.connect, 'pairing_dial')
                    else self.connect.connection_dial
                )
                wx.MessageBox(
                    self.i18n.t("instance_state_changed"),
                    self.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    parent_dialog,
                )
            wx.CallAfter(_show_error)

    def on_pairing_complete(self):
        # Destroy dialogs on the main thread to avoid wx thread-safety issues.
        # Guards against the case where the app is already paired (no dialogs open).
        def _close_dialogs():
            if hasattr(self.connect, 'pairing_dial'):
                try:
                    self.connect.pairing_dial.Destroy()
                except Exception:
                    pass
            if hasattr(self.connect, 'connection_dial'):
                try:
                    self.connect.connection_dial.Destroy()
                except Exception:
                    pass

        wx.CallAfter(_close_dialogs)


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

        In Evolution API v2 the websocket envelope is
          {"event": "messages.upsert", "instance": ..., "data": {<message>}, ...}
        where "data" is a single message object (key, pushName, message,
        messageType, messageTimestamp, ...).
        """
        try:
            msg = info.get("data", {})
            if not isinstance(msg, dict) or not msg.get("key"):
                return
            # Skip reactions — they update an existing message, not a new one
            if msg.get("messageType") == "reactionMessage":
                return
            # Skip messages sent by ourselves (fromMe=True means we sent it;
            # the MessageQueue already handles those in the UI)
            if msg.get("key", {}).get("fromMe", False):
                return
            wx.CallAfter(self.main_window.on_new_message, msg)

        except Exception as e:
            print(f"[WebSocketClient] on_messages_upsert error: {e}")

    def on_contacts_update(self, info):
        """
        Handle contacts.update to keep contact names and pictures fresh.

        Evolution API v2 emits this event with "data" being either a single
        contact dict or a list of contact dicts:
          {"remoteJid": ..., "pushName": ..., "profilePicUrl": ..., "instanceId": ...}
        New messages (1:1 and group) arrive via messages.upsert.
        """
        try:
            data = info.get("data", [])
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                return
            updated = False
            for contact in data:
                if not isinstance(contact, dict):
                    continue
                jid = contact.get("remoteJid", "")
                if not jid:
                    continue
                existing = self.main_window.contacts.get(jid)
                if existing is None:
                    continue
                if contact.get("pushName"):
                    existing["pushName"] = contact["pushName"]
                    updated = True
                if contact.get("profilePicUrl"):
                    existing["profilePicUrl"] = contact["profilePicUrl"]
            if updated:
                # Refresh conversation names shown in the UI
                wx.CallAfter(self.main_window.set_chats)
        except Exception as e:
            print(f"[WebSocketClient] on_contacts_update error: {e}")
