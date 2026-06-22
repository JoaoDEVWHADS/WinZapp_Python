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
            reconnection=True,
            reconnection_attempts=0,      # 0 = unlimited
            reconnection_delay=2,
            reconnection_delay_max=60,
            logger=False,
            engineio_logger=False,
        )
        # WPPConnect Server emits all events on root "/" namespace via req.io.emit().
        # Registering handlers without namespace defaults them to "/" (root).
        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on("qrCode", self.on_wpp_qrcode)
        self.sio.on("session-logged", self.on_wpp_session_logged)
        self.sio.on("received-message", self.on_wpp_message_received)
        self.sio.on("onack", self.on_wpp_ack)
        self.sio.on("phoneCode", self.on_wpp_phone_code)
        self.sio.on("status-find", self.on_wpp_status_find)
        self.sio.on("onpresencechanged", self.on_wpp_presence_changed)
        self.sio.on("chats-update", self.on_chats_update)

        # threading.Event used by on_continue() to wait for the phoneCode that
        # WPPConnect emits asynchronously via Socket.IO after /start-session.
        self._phone_code_event = threading.Event()
        self._phone_code_value: str = ""

    def on_connect(self):
        print("WebSocket connected.")
        # Record when we connected so on_messages_upsert can use a stable
        # cutoff time rather than the ever-advancing time.time().
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
                self.main_window.resolve_self_lid()
            # Mark WhatsApp as connected so the MessageQueue resumes sending.
            self.main_window._wa_connected = True
            # Clear any "disconnected" status shown in the title bar / tray.
            if self.main_window._tray_status == self.i18n.t("tray_wa_disconnected"):
                self.main_window._set_status("")
            if hasattr(self.main_window, "message_queue"):
                self.main_window.message_queue.flush()
            
            # Save the paired status so next startup knows pairing was fully completed.
            pi = self.main_window.settings.setdefault("privateinfo", {})
            if not pi.get("paired"):
                pi["paired"] = True
                self.main_window.save_settings()

            self.on_pairing_complete()
        elif connection_state == "close":
            was_connected = self.main_window._wa_connected
            self.main_window._wa_connected = False

            # Detect permanent WhatsApp logout (status 401 = loggedOut).
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
        pi.pop("paired", None)
        mw.settings.setdefault("status", {})["messages_set_completed"] = False
        mw.token = ""
        mw.save_settings()
        
        # Wipe all cached chats/contacts/media to avoid cross-account data leakage
        mw.clear_local_data()

        # Best-effort: close the WPPConnect session so Chrome is released.
        if old_token:
            def _close():
                try:
                    requests.post(
                        f"{mw.wpp_server}:{mw.wpp_port}/api/{old_token}/close-session",
                        headers={"Authorization": f"Bearer {old_token}", "Content-Type": "application/json"},
                        timeout=5,
                    )
                except Exception:
                    pass
            threading.Thread(target=_close, daemon=True).start()

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
        # WPPConnect sends messages.set in multiple batches during initial
        # WhatsApp sync; without this guard the second batch would trigger a
        # full re-sync immediately after the first one finished.
        if getattr(self.main_window, "_sync_completed", False):
            return
        self.main_window.sync_thread = threading.Thread(target=self.main_window.start_sync, daemon=True)
        self.main_window.sync_thread.start()

    def on_messages_upsert(self, info):
        """
        Handle real-time incoming messages from the WPPConnect.

        In WPPConnect v2 the websocket envelope is
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
                _lock = getattr(self.main_window, "_own_sent_ids_lock", None)
                if _lock is not None:
                    with _lock:
                        _is_own = msg_id and msg_id in self.main_window._own_sent_ids
                else:
                    _is_own = msg_id and msg_id in getattr(self.main_window, "_own_sent_ids", set())
                if _is_own:
                    return  # echo of our own send — skip
                # Otherwise: sent from another device — fall through to on_new_message
            wx.CallAfter(self.main_window.on_new_message, msg)

        except Exception as e:
            print(f"[WebSocketClient] on_messages_upsert error: {e}")

    def on_messages_update(self, info):
        """
        Handle messages.update — delivery/read status changes for sent messages.

        WPPConnect v2 sends:
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

        WPPConnect emits:
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

        WPPConnect wraps the Baileys payload as:
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

    def on_wpp_presence_changed(self, info):
        """
        Handle WPPConnect onpresencechanged event.
        Payload format matches PresenceChangeEvent from WPPConnect.
        """
        if not info or not isinstance(info, dict):
            return
        try:
            # The id can be a string or a dict/object (Wid)
            raw_id = info.get("id")
            if isinstance(raw_id, dict):
                chat_jid = raw_id.get("_serialized", "")
            else:
                chat_jid = str(raw_id or "")

            if not chat_jid:
                return

            is_group = bool(info.get("isGroup", False))
            
            # We want to format this into the presences dict that main.py expects:
            # presences: {participant_jid: {"lastKnownPresence": state, "lastSeen": timestamp}}
            presences = {}
            
            # Map state to expected values (available, unavailable, composing, recording)
            def map_state(s):
                if not s:
                    return "unavailable"
                s = s.lower()
                if s == "online":
                    return "available"
                if s == "offline":
                    return "unavailable"
                return s

            timestamp = info.get("t")

            if is_group:
                participants = info.get("participants", [])
                if isinstance(participants, list):
                    for p in participants:
                        if not isinstance(p, dict):
                            continue
                        p_raw_id = p.get("id")
                        if isinstance(p_raw_id, dict):
                            p_jid = p_raw_id.get("_serialized", "")
                        else:
                            p_jid = str(p_raw_id or "")
                        if p_jid:
                            p_state = map_state(p.get("state"))
                            presences[p_jid] = {
                                "lastKnownPresence": p_state,
                                "lastSeen": timestamp
                            }
            else:
                state = map_state(info.get("state"))
                presences[chat_jid] = {
                    "lastKnownPresence": state,
                    "lastSeen": timestamp
                }

            if presences:
                wx.CallAfter(self.main_window.on_presence_update, chat_jid, presences)
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_presence_changed error: {e}")

    def on_contacts_update(self, info):
        """
        Handle contacts.update to keep contact names and pictures fresh.

        WPPConnect v2 emits this event with "data" being either a single
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
            if not isinstance(data, dict):
                return
            # WPPConnect emits: {"data": "data:image/png;base64,...", "session": "..."}
            qrcode_base64 = data.get("data")
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
            if not isinstance(data, dict):
                return
            status = data.get("status", False)
            session = data.get("session", "")

            # Ignore events for other sessions (multi-session server scenario)
            if session and session != self.instance_name:
                return

            # Notify the connection state immediately (non-blocking).
            self.on_connection_update({
                "data": {
                    "state": "open" if status else "close"
                }
            })

            if status:
                # Fetch host-device JID and raise WA file limits on a background
                # thread so we don't block the Socket.IO event loop.
                threading.Thread(target=self._fetch_host_device_jid, daemon=True).start()
                threading.Thread(target=self._set_wpp_limits, daemon=True).start()
                # WPPConnect does not emit messages.set; trigger sync here instead,
                # using the same guards as on_messages_set to prevent double-sync.
                self.on_messages_set({})
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_session_logged error: {e}")

    def _fetch_host_device_jid(self):
        try:
            url = f"{self.main_window.wpp_server}:{self.main_window.wpp_port}/api/{self.main_window.token}/host-device"
            headers = {
                "Authorization": f"Bearer {self.main_window.token}",
                "Content-Type": "application/json",
            }
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code in (200, 201):
                res_data = res.json()
                resp = res_data.get("response", res_data)
                phone_obj = resp.get("phoneNumber", {}) if isinstance(resp, dict) else {}
                wuid = ""
                if isinstance(phone_obj, dict):
                    wuid = phone_obj.get("_serialized", "")
                elif isinstance(phone_obj, str):
                    wuid = phone_obj
                if not wuid and isinstance(resp, dict):
                    wid = resp.get("wid")
                    wuid = wid.get("_serialized", "") if isinstance(wid, dict) else ""
                if wuid:
                    self.main_window.my_jid = wuid
                    wx.CallAfter(self.main_window.resolve_self_lid)
        except Exception as ex:
            print(f"[WebSocketClient] Failed to fetch host device JID: {ex}")

    def _set_wpp_limits(self):
        """Push raised file-size limits into WhatsApp Web via the setLimit API.

        WPPConnect documented maximums:
          maxMediaSize — 70 MB  (images, videos, audio)
          maxFileSize  — 1 GB   (documents)
        """
        mw = self.main_window
        url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/set-limit"
        headers = {
            "Authorization": f"Bearer {mw.token}",
            "Content-Type": "application/json",
        }
        limits = [
            ("maxMediaSize", 70 * 1024 * 1024),    # 70 MB
            ("maxFileSize",  1 * 1024 * 1024 * 1024),  # 1 GB
        ]
        for limit_type, value in limits:
            try:
                requests.post(
                    url,
                    json={"type": limit_type, "value": value},
                    headers=headers,
                    timeout=10,
                )
            except Exception:
                pass

    def on_wpp_status_find(self, data):
        try:
            if not isinstance(data, dict):
                return
            status = data.get("status")
            session = data.get("session")
            print(f"[WebSocketClient] Received status-find: {status}, session: {session}")
            
            # If session is provided in the payload, ignore it if it is not ours
            if session and session != self.instance_name:
                return
                
            if status in ("disconnectedMobile", "notLogged"):
                # Handle permanent WhatsApp logout / disconnection.
                # Only trigger if we were previously fully connected (preventing startup false positives).
                if self.main_window._wa_connected and self.main_window.settings.get("privateinfo", {}).get("paired"):
                    wx.CallAfter(self._handle_logout)
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_status_find error: {e}")

    def on_wpp_phone_code(self, data):
        """Handle the 'phoneCode' Socket.IO event emitted by WPPConnect Server.

        WPPConnect does NOT return the pairing code in the HTTP response of
        /start-session — it emits it asynchronously via Socket.IO.  We store
        the code and set a threading.Event so that on_continue() in connect.py
        can unblock its wait loop and immediately show the pairing dialog.
        """
        try:
            if not isinstance(data, dict):
                return
            code = data.get("data") or data.get("phoneCode") or ""
            if code:
                self._phone_code_value = str(code)
                self._phone_code_event.set()
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_phone_code error: {e}")


    def on_wpp_message_received(self, data):
        try:
            if not isinstance(data, dict):
                return
            wpp_msg = data.get("response")
            if not wpp_msg:
                return
            normalized = self._normalize_wpp_message(wpp_msg)
            self.on_messages_upsert({"data": normalized})
        except Exception as e:
            print(f"[WebSocketClient] on_wpp_message_received error: {e}")

    def on_wpp_ack(self, data):
        try:
            if not isinstance(data, dict):
                return
            status_mapping = {1: 2, 2: 3, 3: 4, 4: 5}
            wpp_ack = data.get("ack")
            msg_id = data.get("id", {}).get("_serialized") if isinstance(data.get("id"), dict) else data.get("id")
            parts = msg_id.split("_") if msg_id else []
            clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)

            remote_jid = data.get("to")
            if not remote_jid and isinstance(data.get("id"), dict):
                remote_jid = data.get("id", {}).get("remote")
            if not remote_jid and len(parts) > 1:
                remote_jid = parts[1]
            if remote_jid:
                remote_jid = remote_jid.replace("@c.us", "@s.whatsapp.net")

            self.on_messages_update({
                "data": {
                    "key": {
                        "id": clean_id,
                        "remoteJid": remote_jid or "",
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

        # Safely parse fromMe supporting boolean, string representation, or ID prefix fallback
        from_me_val = wpp_msg.get("fromMe")
        if from_me_val is not None:
            if isinstance(from_me_val, bool):
                from_me = from_me_val
            else:
                from_me = (str(from_me_val).lower() == "true")
        else:
            from_me = (parts[0] == "true") if parts else False

        # Detect status/story messages: WPPConnect sends them with to="status@broadcast"
        # or sets isStatus=True.  The real sender is in the "from" field.
        is_status = "broadcast" in (to_jid or "") or wpp_msg.get("isStatus", False)

        if is_status:
            remote_jid = "status@broadcast"
            status_participant = from_jid.replace("@c.us", "@s.whatsapp.net") if from_jid else ""
        else:
            remote_jid = to_jid if from_me else from_jid
            remote_jid = remote_jid.replace("@c.us", "@s.whatsapp.net")
            status_participant = ""

        ts = wpp_msg.get("timestamp") or wpp_msg.get("t", int(time.time()))

        msg_type = wpp_msg.get("type", "chat")
        conversation = wpp_msg.get("body", "")

        message_content = {}
        if msg_type == "chat":
            message_content = {"conversation": conversation}
        elif msg_type in ("audio", "ptt"):
            dur = wpp_msg.get("duration") or wpp_msg.get("seconds")
            if not dur and isinstance(wpp_msg.get("mediaData"), dict):
                dur = wpp_msg.get("mediaData", {}).get("duration")
            try:
                seconds_val = int(float(dur)) if dur else 0
            except Exception:
                seconds_val = 0
            message_content = {
                "audioMessage": {
                    "url": wpp_msg.get("clientUrl", ""),
                    "seconds": seconds_val
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
            dur = wpp_msg.get("duration") or wpp_msg.get("seconds")
            if not dur and isinstance(wpp_msg.get("mediaData"), dict):
                dur = wpp_msg.get("mediaData", {}).get("duration")
            try:
                seconds_val = int(float(dur)) if dur else 0
            except Exception:
                seconds_val = 0
            message_content = {
                "videoMessage": {
                    "caption": wpp_msg.get("caption", ""),
                    "seconds": seconds_val,
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
        elif msg_type == "pollCreation":
            message_content = {
                "pollCreationMessage": {
                    "name": wpp_msg.get("pollName") or wpp_msg.get("body") or ""
                }
            }
        elif msg_type == "buttons":
            message_content = {
                "buttonsMessage": {}
            }
        elif msg_type == "list":
            message_content = {
                "listMessage": {}
            }
        elif msg_type == "template":
            message_content = {
                "templateMessage": {}
            }
        elif msg_type == "revoked":
            message_content = {
                "protocolMessage": {
                    "type": 3
                }
            }

        # Fallback to plain text if the message type is unsupported/unmapped but contains body text
        if not message_content and conversation:
            msg_type = "chat"
            message_content = {"conversation": conversation}

        type_mapping = {
            "chat": "conversation",
            "audio": "audioMessage",
            "ptt": "audioMessage",
            "image": "imageMessage",
            "video": "videoMessage",
            "document": "documentMessage",
            "sticker": "stickerMessage",
            "vcard": "contactMessage",
            "pollCreation": "pollCreationMessage",
            "buttons": "buttonsMessage",
            "list": "listMessage",
            "template": "templateMessage",
            "revoked": "protocolMessage"
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

        # Status messages: include the real sender as participant
        if status_participant:
            normalized["key"]["participant"] = status_participant

        participant = (
            wpp_msg.get("author")
            or wpp_msg.get("participant")
            or (wpp_msg.get("key") or {}).get("participant")
            or (wpp_msg.get("sender") or {}).get("id")
            or ""
        )
        if participant:
            normalized["key"]["participant"] = participant.replace("@c.us", "@s.whatsapp.net")

        quoted_msg = wpp_msg.get("quotedMsg")
        quoted_msg_obj = wpp_msg.get("quotedMsgObj")
        quoted_stanza_id = wpp_msg.get("quotedStanzaID") or wpp_msg.get("quotedStanzaId")
        quoted_participant = wpp_msg.get("quotedParticipant")

        # Fallback to WPPConnect/Baileys contextInfo if WPPConnect quote fields are missing
        ctx_info = wpp_msg.get("contextInfo")
        if not ctx_info and isinstance(wpp_msg.get("message"), dict):
            sub_msg = wpp_msg.get("message")
            for sub_key in ("extendedTextMessage", "imageMessage", "videoMessage", "audioMessage", "documentMessage"):
                if isinstance(sub_msg.get(sub_key), dict):
                    ctx_info = sub_msg[sub_key].get("contextInfo")
                    if ctx_info:
                        break
        if isinstance(ctx_info, dict):
            if not quoted_stanza_id:
                quoted_stanza_id = ctx_info.get("stanzaId")
            if not quoted_participant:
                quoted_participant = ctx_info.get("participant")
            if not quoted_msg:
                quoted_msg = ctx_info.get("quotedMessage")

        # Debug quotes
        body_text = str(wpp_msg.get('body') or '').strip().lower()
        if body_text in ('..', 'oi'):
            import logging
            logging.info(f"[Raw Message Debug] Message {wpp_msg.get('id')} body: {body_text}. Full payload: {wpp_msg}")

        # Determine if there is any quoted context
        has_quote = False
        clean_quoted_id = ""
        participant_jid = ""
        quoted_body = ""

        # 1. Start with the top-level keys which are the most reliable in WPPConnect
        if quoted_stanza_id:
            has_quote = True
            clean_quoted_id = quoted_stanza_id
            if isinstance(clean_quoted_id, str) and "_" in clean_quoted_id:
                parts = clean_quoted_id.split("_")
                clean_quoted_id = parts[2] if len(parts) > 2 else parts[-1]

        if quoted_participant:
            has_quote = True
            participant_jid = quoted_participant.replace("@c.us", "@s.whatsapp.net")

        # 2. Extract content from quotedMsg (dictionary or string)
        if isinstance(quoted_msg, dict):
            has_quote = True
            if not quoted_body:
                quoted_body = (
                    quoted_msg.get("body")
                    or quoted_msg.get("caption")
                    or quoted_msg.get("conversation")
                    or (quoted_msg.get("extendedTextMessage") or {}).get("text")
                    or ""
                )
            
            # Fallbacks if top-level fields were missing
            if not clean_quoted_id:
                quoted_id = quoted_msg.get("id")
                if isinstance(quoted_id, dict):
                    quoted_id = quoted_id.get("_serialized", "")
                if quoted_id:
                    parts = quoted_id.split("_")
                    clean_quoted_id = parts[2] if len(parts) > 2 else parts[-1]
            
            if not participant_jid:
                author = quoted_msg.get("author") or quoted_msg.get("sender", {}).get("id") or ""
                if author:
                    participant_jid = author.replace("@c.us", "@s.whatsapp.net")

        elif isinstance(quoted_msg, str) and quoted_msg:
            has_quote = True
            if not clean_quoted_id:
                clean_quoted_id = quoted_msg
                if "_" in clean_quoted_id:
                    parts = clean_quoted_id.split("_")
                    clean_quoted_id = parts[2] if len(parts) > 2 else parts[-1]

        # 3. Extract content from quotedMsgObj (alternative dictionary)
        if isinstance(quoted_msg_obj, dict):
            has_quote = True
            if not quoted_body:
                quoted_body = (
                    quoted_msg_obj.get("body")
                    or quoted_msg_obj.get("caption")
                    or quoted_msg_obj.get("conversation")
                    or (quoted_msg_obj.get("extendedTextMessage") or {}).get("text")
                    or ""
                )
            
            if not clean_quoted_id:
                quoted_id = quoted_msg_obj.get("id")
                if isinstance(quoted_id, dict):
                    quoted_id = quoted_id.get("_serialized", "")
                if quoted_id:
                    parts = quoted_id.split("_")
                    clean_quoted_id = parts[2] if len(parts) > 2 else parts[-1]
            
            if not participant_jid:
                author = quoted_msg_obj.get("author") or quoted_msg_obj.get("sender", {}).get("id") or ""
                if author:
                    participant_jid = author.replace("@c.us", "@s.whatsapp.net")

        wpp_mentioned = wpp_msg.get("mentionedJidList") or []
        mentioned_jids = [
            m.replace("@c.us", "@s.whatsapp.net")
            for m in wpp_mentioned
            if isinstance(m, str)
        ]

        if has_quote or mentioned_jids:
            quoted_msg_payload = quoted_msg if isinstance(quoted_msg, dict) else {"conversation": quoted_body}
            context_info = {}
            if has_quote:
                context_info["stanzaId"] = clean_quoted_id
                context_info["participant"] = participant_jid
                context_info["quotedMessage"] = quoted_msg_payload
            if mentioned_jids:
                context_info["mentionedJid"] = mentioned_jids
            
            # If msg_type is conversation, promote it to extendedTextMessage
            if mapped_type == "conversation":
                mapped_type = "extendedTextMessage"
                normalized["messageType"] = "extendedTextMessage"
                normalized["message"] = {
                    "extendedTextMessage": {
                        "text": conversation,
                        "contextInfo": context_info
                    }
                }
            else:
                # Put under specific sub-keys (e.g. imageMessage, videoMessage) if they exist
                for sub_key in (
                    "extendedTextMessage", "imageMessage", "videoMessage", "audioMessage",
                    "documentMessage", "stickerMessage", "locationMessage", "contactMessage"
                ):
                    if sub_key in normalized["message"] and isinstance(normalized["message"][sub_key], dict):
                        normalized["message"][sub_key]["contextInfo"] = context_info

        return normalized
