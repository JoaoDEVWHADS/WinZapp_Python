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
        self.instance_name = instance_name.split(":")[0]
        #Initialize i18n
        self.i18n = I18n(self.main_window)
        self.i18n.get_language()

        self.sio = socketio.Client(
            reconnection=True, reconnection_attempts=5,
            logger=True, engineio_logger=True,
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

        # WPPConnect Server Events
        self.sio.on("qrCode", self.on_wpp_qrcode)
        self.sio.on("session-logged", self.on_wpp_session_logged)
        self.sio.on("received-message", self.on_wpp_message_received)
        self.sio.on("onack", self.on_wpp_ack)

    def on_connect(self):
        print("WebSocket connected.")
        # Record when we connected so on_messages_upsert can use a stable
        # cutoff time rather than the ever-advancing time.time().
        self._connect_time = time.time()

    def on_disconnect(self):
        print("WebSocket disconnected.")

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
            if hasattr(self.main_window, "message_queue"):
                self.main_window.message_queue.flush()
            self.on_pairing_complete()
        elif connection_state == "close":
            was_connected = self.main_window._wa_connected
            self.main_window._wa_connected = False

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
            elif was_connected:
                # Temporary disconnection (network glitch, API restart, etc.)
                # Must run on the main thread — wx.MessageBox from a Socket.IO
                # I/O thread triggers COM cross-thread errors and can freeze the app.
                def _show_error():
                    parent_dialog = None
                    for name in ('pairing_dial', 'connection_dial'):
                        dial = getattr(self.connect, name, None)
                        if dial:
                            try:
                                if not wx.IsDestroyed(dial):
                                    parent_dialog = dial
                                    break
                            except Exception:
                                pass

                    if parent_dialog:
                        return  # Do not show error popup if connecting/pairing dialog is open

                    self.main_window.error_sound.play()
                    wx.MessageBox(
                        self.i18n.t("instance_state_changed"),
                        self.i18n.t("error").format(app_name=self.main_window.app_name),
                        wx.OK | wx.ICON_ERROR,
                        parent_dialog,
                    )
                wx.CallAfter(_show_error)

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
        pairing_code = qr_data.get("pairingCode")
        base64_img = qr_data.get("base64")

        def _update_ui():
            # Use connection_mode to determine which mode we're in
            if self.connect.connection_mode == "qrcode" and base64_img:
                # QR-CODE mode: update the image
                self.main_window.pairing_code_updated_sound.play()
                self.main_window.speak_output.output(self.i18n.t("qrcode_image_updated"))
                self.connect.display_qrcode_image(base64_img)
            elif self.connect.connection_mode == "phone" and pairing_code:
                # Pairing code mode: update the text field only if it exists and not destroyed
                if hasattr(self.connect, "pairing_code_field") and self.connect.pairing_code_field:
                    try:
                        if not wx.IsDestroyed(self.connect.pairing_code_field):
                            self.main_window.pairing_code_updated_sound.play()
                            self.main_window.speak_output.output(self.i18n.t("qrcode_updated"))
                            self.connect.pairing_code_field.SetValue(pairing_code)
                    except Exception:
                        pass

        wx.CallAfter(_update_ui)

    def on_messages_set(self, info):
        self.main_window.settings.setdefault("status", {})["messages_set_completed"] = True
        self.main_window.save_settings()
        # Guard 1: don't start a second sync while one is already running.
        existing = getattr(self.main_window, "sync_thread", None)
        if existing and existing.is_alive():
            return
        # Guard 2: don't restart sync after it already completed this session.
        # Evolution API sends messages.set in multiple batches during initial
        # WhatsApp sync; without this guard the second batch would trigger a
        # full re-sync immediately after the first one finished.
        if getattr(self.main_window, "_sync_completed", False):
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
            
            # Extract JID mapping from WebSocket message
            self.main_window._extract_lid_mapping(msg)
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
                msg_id    = msg.get("key", {}).get("id", "")
                own_ids   = getattr(self.main_window, "_own_sent_ids", set())
                if msg_id and msg_id in own_ids:
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
                
                archive = chat_update.get("archive") if chat_update.get("archive") is not None else chat_update.get("archived")
                if archive is not None:
                    wx.CallAfter(self.main_window.on_chat_archive_update, jid, bool(archive))
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

    # ── WPPConnect Event Handlers ─────────────────────────────────────────────

    def on_wpp_qrcode(self, data):
        try:
            qrcode_base64 = data.get("qrCode")
            if qrcode_base64:
                self.on_qrcode_update({
                    "data": {
                        "qrcode": {
                            "base64": qrcode_base64
                        }
                    }
                })
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_qrcode error: {e}")

    def on_wpp_session_logged(self, data):
        try:
            status = data.get("status", False)
            if status:
                try:
                    url = f"{self.main_window.evolution_server}:{self.main_window.evolution_port}/api/{self.main_window.token}/host-device"
                    headers = {
                        "Authorization": f"Bearer {self.main_window.token}",
                        "Content-Type": "application/json"
                    }
                    res = requests.get(url, headers=headers, timeout=5)
                    if res.status_code in (200, 201):
                        res_data = res.json()
                        phoneNumberObj = res_data.get("response", {}).get("phoneNumber", {})
                        wuid = ""
                        if isinstance(phoneNumberObj, dict):
                            wuid = phoneNumberObj.get("_serialized", "")
                        elif isinstance(phoneNumberObj, str):
                            wuid = phoneNumberObj
                        if wuid:
                            self.main_window.my_jid = wuid
                except Exception as ex:
                    print(f"[WebSocketClient] Failed to fetch host device JID: {ex}")

            self.on_connection_update({
                "data": {
                    "state": "open" if status else "close"
                }
            })
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_session_logged error: {e}")

    def on_wpp_message_received(self, data):
        try:
            wpp_msg = data.get("response")
            if not wpp_msg:
                return
            # Ignore WPPConnect echo if it's fromMe
            if wpp_msg.get("fromMe"):
                return
            normalized = self._normalize_wpp_message(wpp_msg)
            self.on_messages_upsert({"data": normalized})
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_message_received error: {e}")

    def on_wpp_ack(self, data):
        try:
            status_mapping = {1: 2, 2: 3, 3: 4}
            wpp_ack = data.get("ack")
            msg_id = data.get("id", {}).get("_serialized") if isinstance(data.get("id"), dict) else data.get("id")
            parts = msg_id.split("_") if msg_id else []
            clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)

            self.on_messages_update({
                "data": {
                    "key": {
                        "id": clean_id,
                        "fromMe": True
                    },
                    "update": {
                        "status": status_mapping.get(wpp_ack, 2)
                    }
                }
            })
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_ack error: {e}")

    def _normalize_wpp_message(self, wpp_msg):
        msg_id = wpp_msg.get("id")
        if isinstance(msg_id, dict):
            msg_id = msg_id.get("_serialized", "")
        elif not isinstance(msg_id, str):
            msg_id = ""

        parts = msg_id.split("_") if msg_id else []
        clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)

        from_jid = wpp_msg.get("from", "")
        to_jid = wpp_msg.get("to", "")
        from_me = bool(wpp_msg.get("fromMe", False))

        remote_jid = to_jid if from_me else from_jid
        remote_jid = remote_jid.replace("@c.us", "@s.whatsapp.net")

        ts = wpp_msg.get("timestamp") or wpp_msg.get("t", int(time.time()))

        msg_type = wpp_msg.get("type", "chat")
        conversation = wpp_msg.get("body", "")

        message_content = {}
        if msg_type == "chat":
            message_content = {"conversation": conversation}
        elif msg_type in ("audio", "ptt"):
            message_content = {
                "audioMessage": {
                    "url": wpp_msg.get("clientUrl", ""),
                    "seconds": wpp_msg.get("duration") or wpp_msg.get("seconds") or 0
                }
            }
        elif msg_type == "image":
            message_content = {
                "imageMessage": {
                    "caption": wpp_msg.get("caption", "") or wpp_msg.get("body", ""),
                    "url": wpp_msg.get("clientUrl", ""),
                    "mimetype": wpp_msg.get("mimetype", "image/jpeg")
                }
            }
        elif msg_type == "video":
            message_content = {
                "videoMessage": {
                    "caption": wpp_msg.get("caption", ""),
                    "seconds": wpp_msg.get("duration") or wpp_msg.get("seconds") or 0,
                    "gifPlayback": wpp_msg.get("isGif", False) or wpp_msg.get("gifPlayback", False),
                    "url": wpp_msg.get("clientUrl", ""),
                    "mimetype": wpp_msg.get("mimetype", "video/mp4")
                }
            }
        elif msg_type == "document":
            message_content = {
                "documentMessage": {
                    "fileName": wpp_msg.get("filename") or wpp_msg.get("fileName") or wpp_msg.get("title") or "Document",
                    "fileLength": wpp_msg.get("size") or wpp_msg.get("fileLength") or 0,
                    "url": wpp_msg.get("clientUrl", ""),
                    "mimetype": wpp_msg.get("mimetype", "")
                }
            }
        elif msg_type == "sticker":
            message_content = {
                "stickerMessage": {
                    "url": wpp_msg.get("clientUrl", ""),
                    "mimetype": wpp_msg.get("mimetype", "image/webp")
                }
            }
        elif msg_type == "vcard":
            message_content = {
                "contactMessage": {
                    "displayName": wpp_msg.get("displayName") or wpp_msg.get("body") or "Contato",
                }
            }

        type_mapping = {
            "chat": "conversation",
            "audio": "audioMessage",
            "ptt": "audioMessage",
            "image": "imageMessage",
            "video": "videoMessage",
            "document": "documentMessage",
            "sticker": "stickerMessage",
            "vcard": "contactMessage"
        }
        mapped_type = type_mapping.get(msg_type, msg_type)

        ack = wpp_msg.get("ack")
        message_updates = []
        if ack is not None:
            status_map = {1: 2, 2: 3, 3: 4, 4: 5}
            mapped_status = status_map.get(ack, ack)
            message_updates.append({"status": str(mapped_status)})

        normalized = {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": clean_id
            },
            "pushName": wpp_msg.get("sender", {}).get("pushname") or wpp_msg.get("notifyName") or "",
            "message": message_content,
            "messageTimestamp": ts,
            "messageType": mapped_type,
            "MessageUpdate": message_updates
        }

        if remote_jid.endswith("@g.us"):
            participant = wpp_msg.get("author") or (wpp_msg.get("sender") or {}).get("id") or ""
            if participant:
                normalized["key"]["participant"] = participant.replace("@c.us", "@s.whatsapp.net")

        quoted_msg = wpp_msg.get("quotedMsg")
        if quoted_msg:
            quoted_id = quoted_msg.get("id")
            if isinstance(quoted_id, dict):
                quoted_id = quoted_id.get("_serialized", "")
            parts = quoted_id.split("_") if quoted_id else []
            clean_quoted_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else quoted_id)

            normalized["message"]["extendedTextMessage"] = {
                "text": conversation,
                "contextInfo": {
                    "stanzaId": clean_quoted_id,
                    "participant": quoted_msg.get("author", "").replace("@c.us", "@s.whatsapp.net"),
                    "quotedMessage": {"conversation": quoted_msg.get("body", "")}
                }
            }

        return normalized
