import threading
import time
import socketio
import wx
import requests
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
            reconnection=True,
            reconnection_attempts=0,      # 0 = unlimited
            reconnection_delay=2,
            reconnection_delay_max=60,
        )
        #Bind events
        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on("connection.update", self.on_connection_update, namespace=f"/{self.instance_name}")
        self.sio.on("qrcode.updated", self.on_qrcode_update, namespace=f"/{self.instance_name}")
        self.sio.on("messages.set", self.on_messages_set, namespace=f"/{self.instance_name}")
        self.sio.on("messages.upsert",  self.on_messages_upsert,  namespace=f"/{self.instance_name}")
        self.sio.on("messages.update",  self.on_messages_update,  namespace=f"/{self.instance_name}")
        self.sio.on("chats.update",     self.on_chats_update,     namespace=f"/{self.instance_name}")
        self.sio.on("contacts.update",  self.on_contacts_update,  namespace=f"/{self.instance_name}")
        self.sio.on("presence.update",  self.on_presence_update,  namespace=f"/{self.instance_name}")

    def on_connect(self):
        print("WebSocket connected.")
        # Record when we first connected so on_messages_upsert can use a stable
        # cutoff time rather than the ever-advancing time.time().
        # NOTE: Only set on first connect; socketio.Client automatic reconnection
        # calls on_connect again on reconnect, but we must keep the original
        # connect time to avoid dropping messages queued during the outage
        # (messages between first_connect and reconnect would appear older than
        # the new cutoff and be incorrectly discarded).
        if not hasattr(self, "_connect_time"):
            self._connect_time = time.time()

    def on_disconnect(self):
        print("WebSocket disconnected.")
        # Pause the message queue until the socket (and WhatsApp) reconnect.
        wx.CallAfter(setattr, self.main_window, "_wa_connected", False)

    def on_connection_update(self, info):
        print(info)
        #Checks the new connection state
        data             = info.get("data", {})
        connection_state = data.get("state", "")
        if connection_state == "open":
            # Store the user's own JID so self-chat detection and group-admin
            # checks have access to it throughout the session.
            wuid = data.get("wuid", "")
            if wuid:
                self.main_window.my_jid = wuid
            # Mark WhatsApp as connected so the MessageQueue resumes sending.
            self.main_window._wa_connected = True
            # Clear any "disconnected" status shown in the title bar / tray.
            if self.main_window._tray_status == self.i18n.t("tray_wa_disconnected"):
                self.main_window._set_status("")
            if hasattr(self.main_window, "message_queue"):
                self.main_window.message_queue.flush()
            self.on_pairing_complete()
        elif connection_state == "close":
            # Detect permanent WhatsApp logout (Baileys DisconnectReason.loggedOut = 401).
            # Evolution API may surface this in different fields depending on the version.
            status_code  = (
                data.get("statusCode")
                or data.get("status")
                or (data.get("lastDisconnect") or {}).get("statusCode")
            )
            is_logout = (
                data.get("loggedOut", False)
                or status_code == 401
            )
            if is_logout:
                # Permanent logout: clear credentials and redirect to pairing.
                wx.CallAfter(self._handle_logout)
            else:
                # Temporary disconnection (network glitch, WhatsApp session interrupted).
                # Mark WA as disconnected so the MessageQueue stops trying to send.
                # Do NOT show a blocking dialog — Baileys reconnects automatically and
                # fires connection.update(state=open) when it succeeds.  A blocking
                # dialog would freeze the UI and prevent that recovery.
                def _notify_disconnection():
                    mw = self.main_window
                    mw._wa_connected = False
                    mw.error_sound.play()
                    mw.output(self.i18n.t("wa_disconnected_temp"), interrupt=False)
                    mw._set_status(self.i18n.t("tray_wa_disconnected"))
                wx.CallAfter(_notify_disconnection)

    def _handle_logout(self):
        """Handle a permanent WhatsApp logout (device removed from account).

        Runs on the wx main thread (via wx.CallAfter).  Shows an informative
        dialog, wipes the now-invalid credentials from settings, disconnects
        the socket, and opens the connection dialog so the user can re-pair.
        """
        mw = self.main_window
        mw._wa_connected = False
        mw.error_sound.play()

        wx.MessageBox(
            self.i18n.t("device_logged_out"),
            self.i18n.t("error").format(app_name=mw.app_name),
            wx.OK | wx.ICON_ERROR,
        )

        # Wipe the invalidated credentials so next startup goes to pairing.
        pi = mw.settings.setdefault("privateinfo", {})
        old_token = pi.pop("WA_token", "")
        pi.pop("WA_phone_number", None)
        mw.settings.setdefault("status", {})["messages_set_completed"] = False
        mw.token = ""
        mw.save_settings()

        # Best-effort: delete the orphaned instance from the local Evolution API.
        if old_token:
            def _delete():
                try:
                    requests.delete(
                        f"{mw.evolution_server}:{mw.evolution_port}/instance/delete/{old_token}",
                        headers={"apikey": mw.evolution_api_key},
                        timeout=5,
                    )
                except Exception:
                    pass
            threading.Thread(target=_delete, daemon=True).start()

        # Disconnect the socket (may already be disconnecting).
        try:
            self.sio.disconnect()
        except Exception:
            pass

        # Redirect to pairing dialog.
        self.connect.show_connection_dial()

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
        self.main_window.settings.setdefault("status", {})["messages_set_completed"] = True
        self.main_window.save_settings()
        # Guard: don't restart sync after it already completed this session.
        # Evolution API sends messages.set in multiple batches during initial
        # WhatsApp sync; without this guard the second batch would trigger a
        # full re-sync immediately after the first one finished.
        if getattr(self.main_window, "_sync_completed", False):
            return
        # TOCTOU-safe: check + create under lock.
        lock = getattr(self.main_window, "_sync_thread_lock", threading.Lock())
        with lock:
            existing = getattr(self.main_window, "sync_thread", None)
            if existing and existing.is_alive():
                return
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
            # Guard: ignore messages older than 60 seconds before the last
            # WebSocket connection.  Using _connect_time as the reference point
            # (rather than the ever-advancing time.time()) means that a message
            # sent 45 s before the app started is still eligible even if the
            # Evolution API burst arrives 30 s after the WebSocket connected —
            # using time.time() in that case would make the message look 75 s
            # old and block it incorrectly.
            ts = msg.get("messageTimestamp")
            if ts:
                try:
                    cutoff = getattr(self, "_connect_time", time.time()) - 60
                    if int(ts) < cutoff:
                        return
                except (TypeError, ValueError):
                    pass
            # fromMe=True can mean two things:
            #   (a) WinZapp sent this message via MessageQueue — already rendered
            #       in the UI; the WebSocket echo must be ignored.
            #   (b) The user sent this message from another device (phone, official
            #       Windows app) — must be added to the conversation like any
            #       incoming message (but without playing a notification sound).
            # We distinguish the two cases via _own_sent_ids, which is populated
            # by MessageQueue immediately after the API returns the real message ID.
            if msg.get("key", {}).get("fromMe", False):
                # Own reactions are applied optimistically in _on_own_reaction_sent;
                # suppress the WebSocket echo so the reaction count isn't doubled.
                if msg.get("messageType") == "reactionMessage":
                    return
                msg_id = msg.get("key", {}).get("id", "")
                with self.main_window._own_sent_ids_lock:
                    _is_own = msg_id and msg_id in self.main_window._own_sent_ids
                if _is_own:
                    return  # echo of our own send — skip
                # Otherwise: sent from another device — fall through to on_new_message
            wx.CallAfter(self.main_window.on_new_message, msg)

        except Exception as e:
            print(f"[WebSocketClient] on_messages_upsert error: {e}")

    def on_messages_update(self, info):
        """
        Handle messages.update — delivery/read status changes for sent messages.

        Evolution API v2 sends:
          {"data": [{"key": {"id": ..., "remoteJid": ..., "fromMe": true},
                     "status": "READ"|"DELIVERY_ACK"|"SERVER_ACK",
                     "update": {"status": 4}}]}
        """
        try:
            data = info.get("data", [])
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                return
            for update in data:
                if not isinstance(update, dict):
                    continue
                if not update.get("key", {}).get("fromMe"):
                    continue
                wx.CallAfter(self.main_window.on_message_status_update, update)
        except Exception as e:
            print(f"[WebSocketClient] on_messages_update error: {e}")

    def on_chats_update(self, info):
        """
        Handle chats.update — partial chat state changes (e.g. unreadCount reset
        when the user reads messages on another device via app-state sync).

        Evolution API emits:
          {"data": [{"remoteJid": ..., "unreadCount": 0, ...}]}
        """
        try:
            data = info.get("data", [])
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                return
            for chat_update in data:
                if not isinstance(chat_update, dict):
                    continue
                jid = chat_update.get("remoteJid") or chat_update.get("id", "")
                if not jid:
                    continue
                unread = chat_update.get("unreadCount")
                if unread is not None:
                    wx.CallAfter(self.main_window.on_chat_unread_update, jid, int(unread))
        except Exception as e:
            print(f"[WebSocketClient] on_chats_update error: {e}")

    def on_presence_update(self, info):
        """
        Handle presence.update — online/typing/last-seen changes for contacts.

        Evolution API wraps the Baileys payload as:
          {"data": {"id": "55XXX@s.whatsapp.net",
                    "presences": {"55XXX@s.whatsapp.net": {
                        "lastKnownPresence": "available"|"unavailable"|"composing"|...,
                        "lastSeen": <unix_ts>|null}}}}
        """
        try:
            data      = info.get("data", {})
            jid       = data.get("id", "")
            presences = data.get("presences", {})
            if not jid or not isinstance(presences, dict):
                return
            wx.CallAfter(self.main_window.on_presence_update, jid, presences)
        except Exception as e:
            print(f"[WebSocketClient] on_presence_update error: {e}")

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
                # Normalise @c.us → @s.whatsapp.net so the lookup matches the
                # contacts dict, which always stores entries under the modern
                # @s.whatsapp.net format.
                jid = self.main_window._normalize_jid(contact.get("remoteJid", ""))
                if not jid:
                    continue
                existing = self.main_window.contacts.get(jid)
                # Bridge @lid JIDs to their canonical phone JID before giving up.
                if existing is None and jid.endswith("@lid"):
                    phone_jid = getattr(self.main_window, "_lid_to_phone", {}).get(jid, "")
                    if phone_jid:
                        existing = self.main_window.contacts.get(phone_jid)
                        if existing is not None:
                            jid = phone_jid
                if existing is None:
                    # Contact was absent from self.contacts (filtered out by
                    # get_remote_contacts because it had no pushName in the DB
                    # at sync time). If this event carries a name, create the
                    # entry now so future lookups can find it.
                    push = contact.get("pushName", "")
                    if push:
                        self.main_window.contacts[jid] = {
                            "remoteJid": jid,
                            "pushName": push,
                            "profilePicUrl": contact.get("profilePicUrl") or "",
                            "type": "contact",
                            "isSaved": True,
                        }
                        updated = True
                    continue
                if contact.get("pushName"):
                    existing["pushName"] = contact["pushName"]
                    updated = True
                if contact.get("profilePicUrl"):
                    existing["profilePicUrl"] = contact["profilePicUrl"]
            if updated:
                # Refresh conversation names shown in the UI (debounced —
                # contacts.update can fire in bursts for many contacts at once)
                wx.CallAfter(self.main_window._schedule_set_chats)
        except Exception as e:
            print(f"[WebSocketClient] on_contacts_update error: {e}")
