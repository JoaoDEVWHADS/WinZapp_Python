import wx
import logging
import requests
from core.utils import is_phone_like


class PresenceManager:
    """Manages online/typing/recording presence state for all chats.

    Receives a reference to the MainWindow so it can access settings,
    contacts, UI panels, and other services.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── Lazy-init helpers for presence data attributes ──────────────────────

    def _ensure_presence_data(self):
        self.mw._presence_cache = getattr(self.mw, "_presence_cache", {})
        self.mw._composing_chats = getattr(self.mw, "_composing_chats", {})
        self.mw._presence_timers = getattr(self.mw, "_presence_timers", {})
        if not hasattr(self.mw, "_presence_pushname_map"):
            self.mw._presence_pushname_map = dict(
                self.mw.settings.get("presence_pushname_map", {})
            )

    # ── Presence label helpers ──────────────────────────────────────────────

    def _presence_label_for_chat(self, chat_jid_norm: str, is_group: bool) -> str:
        """Return the typing/recording label to append to a chat-list row, or ''."""
        active = getattr(self.mw, "_composing_chats", {}).get(chat_jid_norm, {})
        if not active:
            return ""
        participant_jid, action = next(iter(active.items()))
        if action == "composing":
            action_label = self.mw.i18n.t("typing_indicator")
        elif action == "recording":
            action_label = self.mw.i18n.t("recording_indicator")
        else:
            return ""
        if is_group:
            name = self.mw._resolve_jid_name(participant_jid)
            if name:
                return self.mw.i18n.t("group_presence_indicator").format(
                    name=name, action=action_label
                )
        return action_label

    def _refresh_presence_label_in_list(self, chat_jid_norm: str):
        """Update only the chat-list row for chat_jid_norm via SetItem().

        Replaces the full _schedule_set_chats() rebuild for presence-only changes.
        Using SetItem() on a single row prevents NVDA from re-reading the entire
        list and stuttering in TTS echo while the user is typing a message.
        """
        panel = getattr(self.mw, "conversations_panel", None)
        if panel is None:
            return
        lst = getattr(panel, "conversations_list", None)
        displayed = getattr(panel, "chats_list", [])
        names = getattr(panel, "chat_names", [])
        if lst is None:
            return
        for idx, chat in enumerate(displayed):
            if self.mw._normalize_jid(chat.get("remoteJid", "")) != chat_jid_norm:
                continue
            name = names[idx] if idx < len(names) else ""
            unread = int(chat.get("unreadCount") or 0)
            unread_str = (
                f" {unread} " + (
                    self.mw.i18n.t("unread_messages") if unread > 1
                    else self.mw.i18n.t("unread_message")
                )
                if unread > 0 else ""
            )
            preview = self.mw.chat_list_builder._last_msg_preview(chat)
            item_text = name + unread_str
            if preview:
                item_text += f" {preview}"
            is_group = chat_jid_norm.endswith("@g.us")
            label = self._presence_label_for_chat(chat_jid_norm, is_group)
            if label:
                item_text += f" {label}"
            lst.SetItem(idx, 0, item_text)
            break

    # ── WebSocket event handler ─────────────────────────────────────────────

    def on_presence_update(self, jid: str, presences: dict):
        """
        Handle a presence.update WebSocket event (main thread).

        Stores the latest presence data for the JID in _presence_cache, updates
        the composing-chats index for the typing indicator in the chat list, speaks
        via AO2 when the active conversation has a new composing event, and refreshes
        the data-button note for the open conversation.

        presences: {jid_str: {"lastKnownPresence": str, "lastSeen": int|None}, ...}
        """
        if not jid or not isinstance(presences, dict):
            return

        self._ensure_presence_data()
        chat_jid_norm = self.mw._normalize_jid(jid)

        composing_chats = getattr(self.mw, "_composing_chats", None)
        if composing_chats is None:
            self.mw._composing_chats = {}
            composing_chats = self.mw._composing_chats

        # Determine the open conversation JID (may be None)
        panel = getattr(self.mw, "conversations_panel", None)
        conv = getattr(panel, "conversation", None) if panel else None
        conv_jid = ""
        if conv is not None:
            conv_jid = self.mw._normalize_jid(conv.get("remoteJid", ""))
            if conv_jid.endswith("@lid"):
                conv_jid = self.mw._lid_to_phone.get(conv_jid, conv_jid)

        presence_changed = False

        _ppm_updated = False
        for participant_jid, data in presences.items():
            if not isinstance(data, dict):
                continue
            canonical = self.mw._normalize_jid(participant_jid)
            if canonical.endswith("@lid"):
                canonical = self.mw._lid_to_phone.get(canonical, canonical)

            # ── Persist pushName learned from presence so @lid contacts show
            # the correct name even before they appear in _lid_to_phone. ──────
            if canonical.endswith("@s.whatsapp.net"):
                contact_entry = self.mw.contacts.get(canonical)
                if contact_entry:
                    push = (contact_entry.get("pushName") or "").strip()
                    if push and not push.isdigit() and not is_phone_like(push):
                        if self.mw._presence_pushname_map.get(canonical) != push:
                            self.mw._presence_pushname_map[canonical] = push
                            _ppm_updated = True
                        # Also index the corresponding @lid if known, so callers
                        # can look up by lid_jid directly without bridging.
                        lid = getattr(self.mw, "_phone_to_lid", {}).get(canonical, "")
                        if lid and self.mw._presence_pushname_map.get(lid) != push:
                            self.mw._presence_pushname_map[lid] = push
                            _ppm_updated = True

            old_lkp = self.mw._presence_cache.get(canonical, {}).get("lastKnownPresence", "")
            new_lkp = data.get("lastKnownPresence", "unavailable")

            self.mw._presence_cache[canonical] = {
                "lastKnownPresence": new_lkp,
                "lastSeen": data.get("lastSeen"),
            }

            if new_lkp != old_lkp:
                presence_changed = True

            # Update composing/recording index for this chat
            if chat_jid_norm not in composing_chats:
                composing_chats[chat_jid_norm] = {}
            timer_key = (chat_jid_norm, canonical)
            if new_lkp in ("composing", "recording"):
                composing_chats[chat_jid_norm][canonical] = new_lkp
                # Reset the 10-second auto-clear timer on every new event
                old_timer = self.mw._presence_timers.pop(timer_key, None)
                if old_timer is not None:
                    try:
                        old_timer.Stop()
                    except Exception:
                        pass

                def _make_clear(cjid, part):
                    def _clear():
                        self.mw._composing_chats.get(cjid, {}).pop(part, None)
                        self.mw._presence_timers.pop((cjid, part), None)
                        self._refresh_presence_label_in_list(cjid)
                    return _clear

                self.mw._presence_timers[timer_key] = wx.CallLater(
                    10_000, _make_clear(chat_jid_norm, canonical)
                )
            else:
                composing_chats[chat_jid_norm].pop(canonical, None)
                old_timer = self.mw._presence_timers.pop(timer_key, None)
                if old_timer is not None:
                    try:
                        old_timer.Stop()
                    except Exception:
                        pass

            # Speak via AO2 when a new composing/recording event starts in the open conversation
            if new_lkp != old_lkp and new_lkp in ("composing", "recording"):
                if not self.mw.is_chat_muted(chat_jid_norm) and not self.mw.is_chat_archived(chat_jid_norm):
                    name = self.mw._resolve_jid_name(canonical)
                    if name:
                        try:
                            # Check language format key
                            i18n_key = "typing_text" if new_lkp == "composing" else "recording_text"
                            msg_text = self.mw.i18n.t(i18n_key).format(name=name)

                            if chat_jid_norm == conv_jid:
                                self.mw.speak_output.output(msg_text)
                            else:
                                if self.mw.settings.get("general", {}).get("notifications_enabled", True):
                                    window_active = (
                                        not getattr(self.mw, "_window_hidden", False)
                                        and self.mw.IsShown()
                                        and not self.mw.IsIconized()
                                        and self.mw.IsActive()
                                    )
                                    if window_active:
                                        self.mw.message_foreground_sound.play()
                                        self.mw.output(msg_text)
                        except Exception:
                            pass

        # Persist the updated pushName map to settings (debounced via _schedule_save).
        if _ppm_updated:
            self.mw.settings["presence_pushname_map"] = dict(self.mw._presence_pushname_map)
            self.mw._schedule_save_settings()

        # Update only the affected row — avoids DeleteAllItems()+Append() rebuild
        # that causes NVDA to re-read the full list and stutter during TTS echo.
        if presence_changed:
            self._refresh_presence_label_in_list(chat_jid_norm)

        # Refresh the data-button note for the open conversation
        if panel is None or conv is None:
            return
        if conv_jid in self.mw._presence_cache:
            panel._refresh_presence_note(conv_jid)

    # ── Presence subscription ──────────────────────────────────────────────

    def subscribe_presence(self, jid: str):
        """Subscribe to the presence of a contact or group to receive real-time presence updates."""
        if not jid:
            return
        is_group = jid.endswith("@g.us")
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/subscribe-presence"
        headers = self.mw._api_headers()
        payload = {
            "phone": jid,
            "isGroup": is_group
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            logging.info(f"[subscribe_presence] Subscribed to presence for {jid}. Status: {r.status_code}")
        except Exception as e:
            logging.error(f"[subscribe_presence] Error subscribing to presence for {jid}: {e}")
