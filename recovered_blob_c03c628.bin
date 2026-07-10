import threading
import requests
import socketio
import logging
import time


class ConnectionManager:
    """WebSocket connection lifecycle, WhatsApp status checks, and online-presence signalling.

    Receives a reference to the MainWindow so it can access settings, the
    WebSocket client, token, and UI helpers without polluting the god class.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── WebSocket lifecycle ─────────────────────────────────────────────────

    def connect_websocket(self):
        """Connect to the WPPConnect Server WebSocket.

        Connects to both the session namespace and root namespace so that
        global events (qrCode, phoneCode, session-logged) are received.
        Retries up to 6 times with a 2-second delay to handle the brief
        window after session creation where the namespace isn't ready yet.
        """
        import time
        max_attempts = 6
        delay = 2
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                logging.info("connect_websocket: Attempting connection %d/%d...", attempt, max_attempts)
                if self.mw.ws.sio.connected:
                    self.mw.ws.sio.disconnect()
                # WPPConnect Server only uses the root Socket.IO namespace.
                # All events (qrCode, phoneCode, received-message, etc.) are
                # emitted via req.io.emit() on root "/".
                self.mw.ws.sio.connect(
                    f"{self.mw.wpp_ws_server}:{self.mw.wpp_port}/",
                    socketio_path="socket.io",
                    headers={"apikey": self.mw.token},
                    namespaces=["/"],
                )
                logging.info("connect_websocket: Connected successfully on attempt %d.", attempt)
                return
            except Exception as exc:
                logging.warning("connect_websocket: Attempt %d failed: %s", attempt, exc)
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(delay)
        raise last_exc

    def _on_disconnect(self, event=None):
        """Disconnect from WhatsApp: wipe credentials, stop WebSocket and show pairing dialog."""
        pi = self.mw.settings.setdefault("privateinfo", {})
        old_token = pi.pop("WA_token", "")
        pi.pop("WA_phone_number", None)
        pi.pop("paired", None)
        self.mw.settings.setdefault("status", {})["messages_set_completed"] = False
        self.mw.token = ""
        self.mw.save_settings()
        self.mw.clear_local_data()
        # Best-effort: close the WPPConnect session so Chrome is released.
        if old_token:
            def _close():
                try:
                    import requests as _req
                    _req.post(
                        f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{old_token}/close-session",
                        headers={"Authorization": f"Bearer {old_token}", "Content-Type": "application/json"},
                        timeout=5,
                    )
                except Exception:
                    pass
            threading.Thread(target=_close, daemon=True).start()
        try:
            if self.mw.ws and self.mw.ws.sio.connected:
                self.mw.ws.sio.disconnect()
        except Exception:
            pass
        self.mw.connect.show_connection_dial()

    # ── WhatsApp connection status ──────────────────────────────────────────

    def check_wa_connection_http(self):
        """Query the WPPConnect API via HTTP to check if the instance is already connected to WhatsApp."""
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/status-session"
        headers = self.mw._api_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                data = response.json()
                # WPPConnect /status-session returns {"status": "CONNECTED"} — the key is
                # "status", not "state".  Reading "state" always yields "" which incorrectly
                # triggers /start-session even when a session is already alive.
                status = (
                    data.get("status")
                    or data.get("state")
                    or data.get("response", {}).get("status")
                    or data.get("response", {}).get("state")
                    or ""
                )

                logging.info("[check_wa_connection_http] Instance status: %s", status)

                if status in ("CONNECTED", "open"):
                    self.mw._wa_connected = True
                    try:
                        dev_url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/host-device"
                        dev_resp = requests.get(dev_url, headers=headers, timeout=5)
                        if dev_resp.status_code in (200, 201):
                            dev_data = dev_resp.json()
                            phoneNumberObj = dev_data.get("response", {}).get("phoneNumber", {})
                            wuid = ""
                            if isinstance(phoneNumberObj, dict):
                                wuid = phoneNumberObj.get("_serialized", "")
                            elif isinstance(phoneNumberObj, str):
                                wuid = phoneNumberObj
                            if wuid:
                                self.mw.my_jid = wuid
                                self.mw.resolve_self_lid()
                                # Mark as paired on successful HTTP host check too
                                pi = self.mw.settings.setdefault("privateinfo", {})
                                if not pi.get("paired"):
                                    pi["paired"] = True
                                    self.mw.save_settings()
                    except Exception as e:
                        logging.error("[check_wa_connection_http] Failed to fetch host device JID: %s", e)
                elif status in ("INITIALIZING", "QRCODE", "PHONECODE"):
                    # Session is already starting up (e.g. fresh after pairing) — do NOT
                    # call /start-session again: a second call attempts to open a second
                    # browser instance, which fails with "browser is already running" and
                    # causes the WPPConnect auto-close timer to fire, disconnecting us.
                    logging.info(
                        "[check_wa_connection_http] Session is %s — skipping /start-session to avoid browser conflict.",
                        status,
                    )
                else:
                    # Status is CLOSED or unknown: safe to start a new session.
                    try:
                        start_url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/start-session"
                        requests.post(start_url, json={"waitQrCode": False}, headers=headers, timeout=10)
                        logging.info("[check_wa_connection_http] Sent auto-start session command")
                    except Exception as e:
                        logging.error("[check_wa_connection_http] Failed to auto-start session: %s", e)
        except Exception as e:
            logging.error("[check_wa_connection_http] Error checking connection state: %s", e)

    def _check_wa_connection_closed(self, response):
        """If the WPPConnect returned a 'Connection Closed' error, mark the
        WhatsApp connection as down so the MessageQueue pauses retrying until
        Baileys reconnects and fires connection.update with state='open'."""
        try:
            body = response.json()
            messages = body.get("response", {}).get("message", [])
            if any("Connection Closed" in str(m) for m in messages):
                print("[send] WhatsApp Connection Closed — pausing queue until reconnect")
                self.mw._wa_connected = False
        except Exception:
            pass

    # ── Offline mode ────────────────────────────────────────────────────────

    def toggle_offline_mode(self):
        """
        Toggle the user-controlled offline mode (tray menu item).
        While offline the outgoing message queue is suspended; disabling it
        wakes the queue so pending messages are sent immediately.
        """
        self.mw.offline_mode = not self.mw.offline_mode
        self.mw.offline_mode_sound.play()
        if self.mw.offline_mode:
            self.mw.output(self.mw.i18n.t("offline_mode_enabled"), interrupt=True)
        else:
            self.mw.output(self.mw.i18n.t("offline_mode_disabled"), interrupt=True)
            if getattr(self.mw, "message_queue", None) is not None:
                self.mw.message_queue.flush()
        self.mw._update_title()
        if getattr(self.mw, "tray_icon", None) is not None and self.mw._window_hidden:
            self.mw.tray_icon.update_tooltip()

    # ── Online presence ─────────────────────────────────────────────────────

    def _on_window_activate(self, event):
        """
        Fired by wxPython when the main window gains or loses OS focus.
        - Gained focus  → send "available" immediately, then every 20 s
        - Lost focus    → stop the timer, send "unavailable" once
        """
        if self.mw.background_mode:
            event.Skip()
            return
        token = getattr(self.mw, "token", None)
        if not token:
            event.Skip()
            return
        if event.GetActive():
            threading.Thread(
                target=self._send_presence, args=("available",), daemon=True
            ).start()
            if not self.mw._presence_timer.IsRunning():
                self.mw._presence_timer.Start(20_000)   # refresh every 20 s
        else:
            self.mw._presence_timer.Stop()
            threading.Thread(
                target=self._send_presence, args=("unavailable",), daemon=True
            ).start()
        event.Skip()

    def _on_presence_timer(self, event):
        """Periodic keep-alive: resend 'available' while window is focused."""
        token = getattr(self.mw, "token", None)
        if token:
            threading.Thread(
                target=self._send_presence, args=("available",), daemon=True
            ).start()

    def _send_presence(self, presence: str):
        """
        POST /api/{session}/set-online-presence
        Body: {"isOnline": true | false}

        Always runs on a background thread — never blocks the UI.
        """
        token = getattr(self.mw, "token", None)
        if not token:
            return
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{token}/set-online-presence"
        is_online = presence == "available"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            requests.post(url, json={"isOnline": is_online}, headers=headers, timeout=5)
        except Exception:
            pass
