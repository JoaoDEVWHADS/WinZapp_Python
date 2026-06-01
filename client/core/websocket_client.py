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
            logger=True
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
            self.on_pairing_complete()
        elif connection_state == "close":
            self.main_window.error_sound.play()
            # Show error in the appropriate dialog
            parent_dialog = self.connect.pairing_dial if hasattr(self.connect, 'pairing_dial') else self.connect.connection_dial
            wx.MessageBox(self.i18n.t("instance_state_changed"), self.i18n.t("error").format(app_name=self.main_window.app_name), wx.OK | wx.ICON_ERROR, parent_dialog)

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

        The event payload can arrive in several forms:
          • {"data": {"messages": [...], "type": "notify"}}   (most common)
          • {"data": [message_object, ...], "type": "notify"} (some versions)
          • {"data": {<message fields>, "type": "notify"}}    (single message in data)
          • {"messages": [...], "type": "notify"}             (no data wrapper)
        We only process new messages and skip type=="append" (history replay).
        """
        try:
            data = info.get("data", {})

            # Normalise: data may be a dict, list, or the message itself
            if isinstance(data, dict):
                event_type = data.get("type", "")
                messages   = data.get("messages", [])
                # Some versions embed the single message directly in "data"
                if not messages and data.get("key"):
                    messages = [data]
            elif isinstance(data, list):
                # Some Evolution versions send the messages array directly
                event_type = info.get("type", "notify")
                messages   = data
            else:
                event_type = ""
                messages   = []

            # Fallback: messages may be at the root of the info dict
            if not messages:
                messages = info.get("messages", [])
                if not messages and info.get("key"):
                    messages = [info]

            # Skip historical sync replays; allow "notify" and unknown types
            if event_type == "append":
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

    def on_contacts_update(self, info):
        """
        Handle contacts.update for real-time 1:1 message notifications.

        In Evolution API, when a direct-message arrives the contact record is
        updated (unread count, lastMessage) and contacts.update fires.  Group
        messages continue to arrive via messages.upsert.

        Payload expected:
          {"data": [{"id": "<jid>", ..., "lastMessage": {...}}]}

        on_new_message performs duplicate-ID detection, so even if
        messages.upsert also fires for the same message it will be silently
        skipped the second time.
        """
        try:
            data = info.get("data", [])
            if not isinstance(data, list):
                return
            for contact in data:
                if not isinstance(contact, dict):
                    continue
                jid = contact.get("id", "") or contact.get("remoteJid", "")
                # Group chats are handled by messages.upsert
                if not jid or jid.endswith("@g.us") or jid.endswith("@broadcast"):
                    continue
                last_msg = contact.get("lastMessage") or contact.get("msgs")
                if isinstance(last_msg, list):
                    last_msg = last_msg[-1] if last_msg else None
                if not last_msg or not isinstance(last_msg, dict):
                    continue
                key = last_msg.get("key", {})
                if key.get("fromMe", False):
                    continue
                # Ensure remoteJid is present — some payloads omit it from lastMessage
                if not key.get("remoteJid"):
                    last_msg = dict(last_msg)
                    last_msg["key"] = dict(key)
                    last_msg["key"]["remoteJid"] = jid
                wx.CallAfter(self.main_window.on_new_message, last_msg)
        except Exception as e:
            print(f"[WebSocketClient] on_contacts_update error: {e}")
