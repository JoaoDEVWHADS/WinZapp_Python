import threading
import time
import wx


class MessageProcessor:
    """
    Handles processing of incoming messages, status updates, and
    message status changes received from the WebSocket.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── Public API ──────────────────────────────────────────────────────────

    def on_new_message(self, msg: dict):
        """
        Called on the main thread (via wx.CallAfter) when a new message
        arrives via the messages.upsert WebSocket event.
        Adds the message to local storage, updates the UI, and sends a
        notification if appropriate.
        """
        key        = msg.get("key", {})
        from_me    = key.get("fromMe", False)
        remote_jid = self.mw._normalize_jid(key.get("remoteJid", ""))
        msg_id     = key.get("id", "")

        sender = key.get("participant") or key.get("remoteJid") or ""
        if sender and self.mw._is_self_jid(sender):
            from_me = True

        if not remote_jid:
            return

        if not from_me:
            sender_jid = key.get("participant") or key.get("remoteJid", "")
            push = msg.get("pushName", "")
            if sender_jid and push and not _is_phone_like(push):
                sender_jid = self.mw._normalize_jid(sender_jid)
                ppm = getattr(self.mw, "_presence_pushname_map", {})
                if ppm.get(sender_jid) != push:
                    ppm[sender_jid] = push
                    self.mw._schedule_save()

        self.mw._extract_lid_mapping(msg)

        if remote_jid.endswith("@broadcast"):
            self._store_status_update(msg)
            return
        if remote_jid.endswith("@newsletter"):
            return

        if msg.get("messageType") == "reactionMessage":
            if hasattr(self.mw, "conversations_panel"):
                self.mw.conversations_panel.on_incoming_message(remote_jid, msg)
            return

        # ── Resolve canonical JID, merging @lid duplicates ───────────────────
        alt_jid = self.mw._normalize_jid(key.get("remoteJidAlt", ""))

        if remote_jid.endswith("@lid"):
            phone_jid = (
                alt_jid if alt_jid.endswith("@s.whatsapp.net")
                else getattr(self.mw, "_lid_to_phone", {}).get(remote_jid, "")
            )
            if phone_jid:
                self.mw._merge_lid_into_phone(remote_jid, phone_jid)
                remote_jid = phone_jid
        elif alt_jid.endswith("@lid"):
            self.mw._merge_lid_into_phone(alt_jid, remote_jid)
        elif remote_jid.endswith("@s.whatsapp.net"):
            lid_jid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
            if lid_jid:
                self.mw._merge_lid_into_phone(lid_jid, remote_jid)

        # ── Ensure the chat record exists ─────────────────────────────────────
        if remote_jid not in self.mw.chats:
            self.mw.chats[remote_jid] = {
                "remoteJid":   remote_jid,
                "unreadCount": 0,
                "pushName":    msg.get("pushName", ""),
                "messages":    {"messages": {
                    "records":     [],
                    "total":       0,
                    "pages":       1,
                    "currentPage": 1,
                }},
            }

        chat = self.mw.chats[remote_jid]

        # ── Avoid duplicate insertions or resolve pending ones ────────────────
        records = (
            chat.setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
        )
        if from_me:
            pending_msg = None
            for r in records:
                if r.get("_local_pending"):
                    pending_msg = r
                    break
            if pending_msg:
                pending_msg["_local_pending"] = False
                local_id = pending_msg.get("_local_id")
                pending_msg["key"]["id"] = msg_id
                pending_msg["messageTimestamp"] = msg.get("messageTimestamp", pending_msg["messageTimestamp"])

                with self.mw._own_sent_ids_lock:
                    self.mw._own_sent_ids.add(msg_id)
                    if len(self.mw._own_sent_ids) > 500:
                        self.mw._own_sent_ids.discard(next(iter(self.mw._own_sent_ids)))

                if hasattr(self.mw, "conversations_panel"):
                    wx.CallAfter(self.mw.conversations_panel._mark_message_sent, local_id, real_id=msg_id)

                self.mw._schedule_save()
                self.mw.chat_list_builder._schedule_set_chats()
                return

        if msg_id:
            for existing in records:
                if existing.get("key", {}).get("id") == msg_id:
                    return

        records.append(msg)

        # ── Update unread count (only for messages we received) ───────────────
        if not from_me:
            _cp   = getattr(self.mw, "conversations_panel", None)
            _open = (
                _cp is not None
                and _cp.conversation is not None
                and _cp.conversation.get("remoteJid") == remote_jid
            )
            _visible = (
                not getattr(self.mw, "_window_hidden", False)
                and self.mw.IsShown()
                and not self.mw.IsIconized()
            )
            if not (_open and _visible):
                chat["unreadCount"] = int(chat.get("unreadCount") or 0) + 1

        # ── Persist in background ────────────────────────────────────────────
        self.mw._schedule_save()
        self.mw.chat_list_builder._schedule_set_chats()

        # ── Add message to the open conversation panel (if visible) ──────────
        if hasattr(self.mw, "conversations_panel"):
            self.mw.conversations_panel.on_incoming_message(remote_jid, msg)

        # ── Download media in background ──────────────────────────────────────
        media_types = {"audioMessage", "imageMessage", "videoMessage",
                       "documentMessage", "stickerMessage"}
        if msg.get("messageType") in media_types:
            threading.Thread(
                target=self.mw.sync_if_media, args=(msg,), daemon=True
            ).start()

        # ── Send notification ─────────────────────────────────────────────────
        if from_me:
            return

        ts = msg.get("messageTimestamp")
        if ts:
            try:
                conn_time = getattr(self.mw.ws, "_connect_time", time.time()) if self.mw.ws else time.time()
                cutoff = conn_time - 60
                if int(ts) < cutoff:
                    return
            except (TypeError, ValueError):
                pass

        if self.mw.is_chat_muted(remote_jid):
            return
        if self.mw.is_chat_archived(remote_jid):
            return
        if not self.mw.settings.get("general", {}).get("notifications_enabled", True):
            return

        from core.notification_manager import (
            format_notification_title, format_notification_body,
            format_foreground_sender,
        )

        body  = format_notification_body(msg, self.mw, self.mw.i18n)

        window_active = (
            not getattr(self.mw, "_window_hidden", False)
            and self.mw.IsShown()
            and not self.mw.IsIconized()
            and self.mw.IsActive()
        )

        if window_active:
            cp = getattr(self.mw, "conversations_panel", None)
            current_jid = (
                cp.conversation.get("remoteJid", "")
                if cp is not None and cp.conversation is not None
                else ""
            )
            is_current_conv = (current_jid == remote_jid)

            if is_current_conv:
                self.mw.message_current_sound.play()
                sender = format_foreground_sender(msg, self.mw, self.mw.i18n)
                self.mw.output(f"{sender}: {body}")
                threading.Thread(
                    target=self.mw.mark_conversation_as_read,
                    args=(remote_jid, True),
                    daemon=True,
                ).start()
            else:
                self.mw.message_foreground_sound.play()
                title = format_notification_title(msg, self.mw, self.mw.i18n)
                spoken = self.mw.i18n.t("fg_new_msg").format(name=title) + f": {body}"
                self.mw.output(spoken)
            return

        if not self.mw.settings.get("general", {}).get("show_tray_icon", True):
            return
        title = format_notification_title(msg, self.mw, self.mw.i18n)
        if hasattr(self.mw, "notification_manager"):
            self.mw.notification_manager.send(title, body, remote_jid)

    def on_message_status_update(self, update: dict):
        """
        Handle a messages.update WebSocket event on the main thread.
        Updates MessageUpdate list on the cached message record and refreshes
        the status icon shown in the active conversation.
        """
        key       = update.get("key", {})
        msg_id    = key.get("id", "")
        status    = update.get("status", "") or str(update.get("update", {}).get("status", ""))
        if not msg_id or not status:
            return
        remote_jid = self.mw._normalize_jid(key.get("remoteJid", ""))
        if remote_jid.endswith("@lid"):
            phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(remote_jid, "")
            if phone_jid:
                remote_jid = phone_jid
        if remote_jid not in self.mw.chats:
            return
        records = (
            self.mw.chats[remote_jid]
                .get("messages", {})
                .get("messages", {})
                .get("records", [])
        )
        for msg in records:
            if msg.get("key", {}).get("id") == msg_id:
                msg.setdefault("MessageUpdate", []).append({"status": status})
                break
        if hasattr(self.mw, "conversations_panel"):
            self.mw.conversations_panel.refresh_message_status(msg_id, status)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _store_status_update(self, msg: dict):
        """Store an incoming status/story message in _status_updates and refresh the Status tab."""
        key = msg.get("key", {})
        participant = (
            key.get("participant")
            or msg.get("participant")
            or (key.get("fromMe") and getattr(self.mw, "my_jid", ""))
            or ""
        )
        if not participant:
            return
        if not hasattr(self.mw, "_status_updates"):
            self.mw._status_updates = {}
        bucket = self.mw._status_updates.setdefault(participant, [])
        msg_id = key.get("id", "")
        if msg_id and any(m.get("key", {}).get("id") == msg_id for m in bucket):
            return
        bucket.append(msg)
        self.mw._schedule_save()
        try:
            if hasattr(self.mw, "navigation_panel"):
                sp = getattr(self.mw.navigation_panel, "status_panel", None)
                if sp and sp.IsShown():
                    wx.CallAfter(lambda: threading.Thread(target=sp._load_statuses, daemon=True).start())
        except Exception:
            pass


def _is_phone_like(name: str) -> bool:
    """Return True if name looks like a phone number rather than a display name.

    Also rejects purely-numeric strings of any length (e.g. "0") — those are
    WPPConnect API fallbacks from contact.id.split('@')[0] when no real name is
    available, not actual display names.
    """
    if not name:
        return False
    stripped = name.strip()
    if stripped.isdigit():
        return True
    digit_count = sum(1 for c in stripped if c.isdigit())
    return digit_count >= 7 and digit_count >= len(stripped) * 0.7
