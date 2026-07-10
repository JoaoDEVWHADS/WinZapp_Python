import wx
import threading
import logging

from core.utils import format_number, is_phone_like


class ChatListBuilder:
    """Build, sort, filter and apply the conversation list for the main window.

    Extracted from ``MainWindow`` to reduce the size of the god class.  All
    methods that depend on ``MainWindow`` internals receive a ``main_window``
    reference.
    """

    def __init__(self, main_window):
        self.mw = main_window
        self._set_chats_pending = False

    # ── public helpers called from MainWindow ──────────────────────────────

    def set_chats(self):
        if getattr(self.mw, "_media_sync_running", False):
            return
        self.mw._build_lid_to_phone_cache()
        self._apply_chat_lists(*self._compute_chat_lists())

    def _schedule_set_chats(self):
        """Debounce set_chats() so rapid message bursts trigger only one rebuild.
        Safe to call from any thread; scheduling happens on the wx main thread."""
        if getattr(self.mw, "_media_sync_running", False):
            return
        if self._set_chats_pending:
            return
        self._set_chats_pending = True
        wx.CallLater(300, self._do_scheduled_set_chats)

    def _do_scheduled_set_chats(self):
        """Run heavy computation in background; apply UI changes on main thread."""
        self._set_chats_pending = False
        if getattr(self.mw, "_media_sync_running", False):
            return

        def _bg():
            try:
                self.mw._build_lid_to_phone_cache()
                result = self._compute_chat_lists()
                wx.CallAfter(self._apply_chat_lists, *result)
            except Exception as e:
                print(f"[_do_scheduled_set_chats] error: {e}")

        threading.Thread(target=_bg, daemon=True).start()

    def preselect_conversations(self):
        """Select the first conversation if nothing is focused yet."""
        if self.mw.IsShown():
            lst = self.mw.conversations_panel.conversations_list
            if lst.GetItemCount() > 0:
                if lst.GetFocusedItem() == -1:
                    lst.Focus(0)
                    lst.Select(0)
                    lst.EnsureVisible(0)

    # ── chat-list computation (thread-safe helpers) ───────────────────────

    def _compute_chat_lists(self):
        """Compute sorted/filtered chat lists. Safe to run on a background thread."""
        deleted  = set(self.mw.settings.get("deleted_chats", []))
        archived = set(self.mw.settings.get("archived_chats", []))
        pinned   = set(self.mw.settings.get("pinned_chats", []))
        my_jid   = getattr(self.mw, "my_jid", "")

        main_chats, main_names = [], []
        arch_chats, arch_names = [], []

        for jid, chat in list(self.mw.chats.items()):
            if jid in deleted:
                continue

            # Filter out contacts/chats with no messages, no unread messages, and not pinned
            records = chat.get("messages", {}).get("messages", {}).get("records", [])
            last_msg = chat.get("lastMessage")
            unread = int(chat.get("unreadCount", 0) or 0)
            is_pinned = jid in pinned
            if not records and not last_msg and unread == 0 and not is_pinned:
                continue

            def get_valid_name(val):
                if not val or not isinstance(val, str):
                    return ""
                val = val.strip()
                if not val or val.isdigit() or is_phone_like(val):
                    return ""
                val_lower = val.lower()
                if "sem nome" in val_lower or "unnamed" in val_lower or val_lower in ("no name", "unknown", "desconhecido"):
                    return ""
                return val

            phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid) or self.mw._find_alt_jid_from_messages(chat)

            resolved_name = self.mw._resolve_contact_name(chat)
            chat_push = get_valid_name(chat.get("pushName", ""))
            msg_push = self.mw.find_name_through_messages(chat)
            chat_name_field = get_valid_name(chat.get("name", ""))

            if jid.endswith("@g.us"):
                name = chat_name_field
            else:
                name = (
                    resolved_name
                    or chat_push
                    or msg_push
                    or chat_name_field
                )

            if not name or not name.strip():
                if jid.endswith("@g.us"):
                    name = self.mw.i18n.t("unknown_group")
                else:
                    if phone_jid:
                        name = format_number(phone_jid)
                    else:
                        msg_jid_num = self.mw.find_jid_through_messages(chat)
                        if msg_jid_num:
                            name = msg_jid_num
                        else:
                            name = format_number(jid)

            # Detailed logging for name resolution debugging
            if jid.endswith("@lid") or name == self.mw.i18n.t("unknown_contact"):
                logging.info(
                    f"[Name Resolution] jid={jid} phone_jid={phone_jid} "
                    f"resolved_name={self.mw._resolve_contact_name(chat)} "
                    f"msg_name={self.mw.find_name_through_messages(chat)} "
                    f"chat_name={chat.get('name')} push_name={chat.get('pushName')} -> final_name='{name}'"
                )
            if my_jid and not jid.endswith("@g.us") and self.mw._is_self_jid(jid):
                name = self.mw.i18n.t("self_chat_name")
            is_archived = (
                jid in archived
                or chat.get("archived") is True
                or chat.get("archive") is True
                or str(chat.get("archived")).lower() == "true"
                or str(chat.get("archive")).lower() == "true"
            )
            if is_archived:
                arch_chats.append(chat)
                arch_names.append(name)
            else:
                main_chats.append(chat)
                main_names.append(name)

        # Pinned chats float to the top; within each group sort by most-recent
        # message timestamp descending (newest first), then alphabetically.
        def _chat_last_ts(c):
            ts = int(c.get("t", 0) or 0)
            for m in c.get("messages", {}).get("messages", {}).get("records", []):
                t = int(m.get("messageTimestamp", 0) or 0)
                if t > ts:
                    ts = t
            return ts

        def _sort_key(pair):
            c, n = pair
            j   = c.get("remoteJid", "")
            pin = 0 if j in pinned else 1
            return (pin, -_chat_last_ts(c), n.lower())

        pairs = sorted(zip(main_chats, main_names), key=_sort_key)
        main_chats = [c for c, _ in pairs]
        main_names = [n for _, n in pairs]

        arch_pairs = sorted(zip(arch_chats, arch_names), key=_sort_key)
        arch_chats = [c for c, _ in arch_pairs]
        arch_names = [n for _, n in arch_pairs]

        return main_chats, main_names, arch_chats, arch_names

    def _apply_chat_lists(self, main_chats, main_names, arch_chats, arch_names):
        """Apply sorted chat lists to panels and refresh UI. Must run on main thread."""
        self.mw.chat_names = main_names
        self.mw.conversations_panel._all_chats_list = main_chats
        self.mw.conversations_panel._all_chat_names = main_names
        self.mw.conversations_panel.chats_list = main_chats
        self.mw.conversations_panel.chat_names = main_names

        if hasattr(self.mw, "archived_conversations_panel"):
            self.mw.archived_conversations_panel._all_chats_list = arch_chats
            self.mw.archived_conversations_panel._all_chat_names = arch_names
            self.mw.archived_conversations_panel.chats_list = arch_chats
            self.mw.archived_conversations_panel.chat_names = arch_names

        if self.mw.IsShown():
            self.add_chats_to_ui()
        self.mw._update_title()
        if getattr(self.mw, "tray_icon", None) is not None and self.mw._window_hidden:
            self.mw.tray_icon.update_tooltip()

    # ── last-message preview ──────────────────────────────────────────────

    def _last_msg_preview(self, chat: dict) -> str:
        """
        Build a compact last-message description for the conversations list.
        Returns "" if no messages are found.
        Format: "[você: ]{content} {timestamp}"
        """
        records = (
            chat.get("messages", {})
                .get("messages", {})
                .get("records", [])
        )
        if not records:
            return ""

        # Prefer supported user-facing message types for a cleaner preview
        supported_types = {
            "conversation",
            "extendedTextMessage",
            "imageMessage",
            "videoMessage",
            "audioMessage",
            "documentMessage",
            "stickerMessage",
            "contactMessage",
            "locationMessage",
            "liveLocationMessage",
            "pollCreationMessage",
            "buttonsMessage",
            "listMessage",
            "templateMessage",
            "interactiveMessage",
            "buttonsResponseMessage",
            "listResponseMessage",
            "protocolMessage",
            "reactionMessage",
        }

        def is_displayable(m):
            if not isinstance(m, dict):
                return False
            m_type = m.get("messageType", "")
            if m_type not in supported_types:
                return False
            if m_type == "protocolMessage":
                protocol = (m.get("message") or {}).get("protocolMessage") or {}
                p_type = protocol.get("type")
                return p_type in (3, "REVOKE", "revoke")
            return True

        try:
            last = max(
                (m for m in records if is_displayable(m)),
                key=lambda m: int(m.get("messageTimestamp", 0) or 0),
                default=None,
            )
        except Exception:
            return ""
        if last is None:
            return ""

        from_me  = last.get("key", {}).get("fromMe", False)
        msg_type = last.get("messageType", "conversation")
        msg_obj  = last.get("message") or {}
        i18n     = self.mw.i18n

        # If latest message is a reaction, show it inline instead of skipping
        if msg_type == "reactionMessage":
            reaction = msg_obj.get("reactionMessage") or {}
            emoji = reaction.get("text", "")
            orig_id = (reaction.get("key") or {}).get("id", "")
            orig_text = ""
            for m in records:
                if isinstance(m, dict) and m.get("key", {}).get("id") == orig_id:
                    orig_type = m.get("messageType", "")
                    orig_obj  = m.get("message") or {}
                    if orig_type == "conversation":
                        orig_text = (orig_obj.get("conversation") or "")
                    elif orig_type == "extendedTextMessage":
                        orig_text = ((orig_obj.get("extendedTextMessage") or {}).get("text") or "")
                    elif orig_type == "audioMessage":
                        orig_text = i18n.t("message_type_audio")
                    elif orig_type == "videoMessage":
                        orig_text = i18n.t("video")
                    elif orig_type == "imageMessage":
                        orig_text = i18n.t("photo")
                    elif orig_type == "documentMessage":
                        orig_text = i18n.t("document")
                    elif orig_type == "stickerMessage":
                        orig_text = i18n.t("sticker")
                    elif orig_type == "contactMessage":
                        orig_text = i18n.t("notif_contact")
                    elif orig_type == "locationMessage":
                        orig_text = i18n.t("notif_location")
                    else:
                        orig_text = i18n.t("notif_unsupported")
                    break
            ts = last.get("messageTimestamp")
            time_str = ""
            if ts:
                try:
                    from datetime import datetime as _dt
                    dt    = _dt.fromtimestamp(int(ts))
                    today = _dt.now().date()
                    if dt.date() == today:
                        time_str = dt.strftime("%H:%M")
                    else:
                        time_str = dt.strftime(i18n.t("datetime_fmt"))
                except Exception:
                    pass
            if from_me:
                label = i18n.t("reaction_preview_you").format(emoji=emoji)
            else:
                p_key      = last.get("key", {})
                sender_jid = last.get("participant") or p_key.get("participant", "") or p_key.get("remoteJid", "")
                push       = last.get("pushName", "")
                if sender_jid.endswith("@g.us") and push and push.isdigit():
                    sender_jid = f"{push}@s.whatsapp.net"
                sender_name = (
                    self.mw._resolve_contact_name({"remoteJid": sender_jid})
                    or (push if push and not is_phone_like(push) else "")
                    or self.mw._preview_sender_from_jid(sender_jid)
                )
                label = i18n.t("reaction_preview_them").format(name=sender_name, emoji=emoji)
            parts = [label]
            if orig_text:
                parts.append(orig_text)
            if time_str:
                parts.append(time_str)
            return " ".join(parts)

        # Build compact content
        def _dur(secs):
            try:
                s = int(secs or 0)
            except Exception:
                return "0:00"
            h, m, sec = s // 3600, (s % 3600) // 60, s % 60
            return f"{h}:{m:02d}:{sec:02d}" if h > 0 else f"{m}:{sec:02d}"

        if msg_type == "conversation":
            content = msg_obj.get("conversation") or ""
        elif msg_type == "extendedTextMessage":
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "") or ""
            ext = msg_obj.get("extendedTextMessage") or {}
            mentioned = (
                (last.get("contextInfo") or {}).get("mentionedJid")
                or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
                or ext.get("contextInfo", {}).get("mentionedJid")
                or []
            )
            if isinstance(mentioned, list) and mentioned:
                for jid in mentioned:
                    if not isinstance(jid, str):
                        continue
                    if self.mw._is_self_jid(jid):
                        name = "eu"
                    else:
                        if hasattr(self.mw, "conversations_panel"):
                            name = self.mw.conversations_panel._get_participant_name(jid)
                        else:
                            name = ""

                    lid_local = jid.rsplit("@", 1)[0]
                    _lid_map = getattr(self.mw, "_lid_to_phone", {})
                    phone_jid = _lid_map.get(jid, "") if jid.endswith("@lid") else ""
                    phone = phone_jid.split("@")[0] if phone_jid else jid.split("@")[0]

                    placeholder = None
                    if f"@{lid_local}" in content:
                        placeholder = lid_local
                    elif phone and f"@{phone}" in content:
                        placeholder = phone

                    if not placeholder:
                        continue

                    if name and name != placeholder and name != jid:
                        content = content.replace(f"@{placeholder}", f"@{name}")
        elif msg_type == "audioMessage":
            dur     = _dur((msg_obj.get("audioMessage") or {}).get("seconds"))
            content = f"{i18n.t('message_type_audio')} {dur}"
        elif msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            dur   = _dur(video.get("seconds"))
            content = f"{i18n.t('video')} {dur}"
        elif msg_type == "imageMessage":
            img     = msg_obj.get("imageMessage") or {}
            caption = (img.get("caption") or "").strip()
            content = i18n.t("photo") + (f" {caption}" if caption else "")
        elif msg_type == "documentMessage":
            doc      = msg_obj.get("documentMessage") or {}
            filename = doc.get("fileName") or doc.get("title") or ""
            size_bytes = doc.get("fileLength")
            size_str = ""
            if size_bytes:
                try:
                    sz  = int(size_bytes)
                    sep = i18n.t("decimal_separator")
                    if sz < 1024:
                        size_str = f"{sz} b"
                    elif sz < 1024 ** 2:
                        size_str = f"{sz / 1024:.1f}".replace(".", sep) + " kb"
                    elif sz < 1024 ** 3:
                        size_str = f"{sz / 1024 ** 2:.1f}".replace(".", sep) + " mb"
                    else:
                        size_str = f"{sz / 1024 ** 3:.1f}".replace(".", sep) + " gb"
                except (ValueError, TypeError):
                    pass
            parts = [i18n.t("document")]
            if filename:
                parts.append(filename)
            if size_str:
                parts.append(size_str)
            content = ", ".join(parts)
        elif msg_type == "stickerMessage":
            content = i18n.t("sticker")
        elif msg_type == "contactMessage":
            contact = msg_obj.get("contactMessage") or {}
            content = i18n.t("contact_message").format(
                name=contact.get("displayName") or ""
            )
        elif msg_type == "locationMessage":
            content = i18n.t("notif_location")
        elif msg_type == "pollCreationMessage":
            poll = msg_obj.get("pollCreationMessage") or {}
            name = poll.get("name") or ""
            content = f"\U0001f4ca Enquete: {name}" if name else "\U0001f4ca Enquete"
        elif msg_type == "buttonsMessage":
            content = "\U0001f518 Bot\u00e3o"
        elif msg_type == "listMessage":
            content = "\U0001f4cb Lista"
        elif msg_type == "templateMessage":
            content = "\U0001f4dd Modelo"
        elif msg_type == "protocolMessage":
            protocol = msg_obj.get("protocolMessage") or {}
            p_type = protocol.get("type")
            if p_type in (3, "REVOKE", "revoke"):
                content = "\U0001f6ab Mensagem apagada"
            else:
                content = "\u2699\ufe0f Mensagem do sistema"
        else:
            content = i18n.t("notif_unsupported")

        # Build time string
        ts = last.get("messageTimestamp")
        time_str = ""
        if ts:
            try:
                from datetime import datetime as _dt
                dt    = _dt.fromtimestamp(int(ts))
                today = _dt.now().date()
                if dt.date() == today:
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = dt.strftime(i18n.t("datetime_fmt"))
            except Exception:
                pass

        # For group chats add sender name before content (e.g. "João: vídeo 0:30")
        jid      = chat.get("remoteJid", "")
        is_group = jid.endswith("@g.us")
        if from_me:
            sender_prefix = i18n.t("conv_preview_you") + " "
        elif is_group:
            p_key      = last.get("key", {})
            sender_jid = last.get("participant") or p_key.get("participant") or p_key.get("remoteJid", "")
            push       = last.get("pushName", "")
            if sender_jid.endswith("@g.us") and push and push.isdigit():
                sender_jid = f"{push}@s.whatsapp.net"
            sender_name = (
                self.mw._resolve_contact_name({"remoteJid": sender_jid})
                or (push if push and not is_phone_like(push) else "")
                or self.mw._preview_sender_from_jid(sender_jid)
            )
            sender_prefix = f"{sender_name}: " if sender_name else ""
        else:
            sender_prefix = ""
        parts = [f"{sender_prefix}{content}"]
        if time_str:
            parts.append(time_str)
        return " ".join(parts)

    # ── UI rendering ──────────────────────────────────────────────────────

    def add_chats_to_ui(self):
        """Rebuild the conversations list from the current chats data.

        Applies active search and conversation filter to both the wx.ListCtrl
        and the backing chats_list/chat_names arrays so that list indices are
        always consistent.  Without this sync the user would open the wrong
        conversation when a search was active.
        """
        search       = self.mw.conversations_panel.search_field.GetValue().strip().lower()
        conv_filter  = getattr(self.mw.conversations_panel, '_conv_filter', 'all')

        # Always start from the full sorted lists saved by set_chats() so
        # that restoring the window or clearing a search shows all chats.
        full_chats = list(getattr(self.mw.conversations_panel, '_all_chats_list',
                                  self.mw.conversations_panel.chats_list))
        full_names = list(getattr(self.mw.conversations_panel, '_all_chat_names',
                                  self.mw.conversations_panel.chat_names))

        displayed_chats: list = []
        displayed_names: list = []

        lst = self.mw.conversations_panel.conversations_list
        # Save currently focused chat JID before clearing the list to preserve user focus
        focused_idx = lst.GetFocusedItem()
        focused_jid = None
        if focused_idx != -1 and 0 <= focused_idx < len(self.mw.conversations_panel.chats_list):
            focused_jid = self.mw.conversations_panel.chats_list[focused_idx].get("remoteJid")
            try:
                # Clear focus state from this item before deleting to prevent NVDA COMError/freeze
                lst.SetItemState(focused_idx, 0, wx.LIST_STATE_FOCUSED)
            except Exception:
                pass

        # Save currently focused archived chat JID if archived panel is present
        arch_focused_jid = None
        if hasattr(self.mw, "archived_conversations_panel"):
            arch_lst = self.mw.archived_conversations_panel.conversations_list
            arch_focused_idx = arch_lst.GetFocusedItem()
            if arch_focused_idx != -1 and 0 <= arch_focused_idx < len(self.mw.archived_conversations_panel.chats_list):
                arch_focused_jid = self.mw.archived_conversations_panel.chats_list[arch_focused_idx].get("remoteJid")
                try:
                    arch_lst.SetItemState(arch_focused_idx, 0, wx.LIST_STATE_FOCUSED)
                except Exception:
                    pass

        focus_allowed = self.mw._allow_ui_focus_changes()
        _lst_had_focus = (wx.Window.FindFocus() is lst)
        lst.Freeze()
        try:
            lst.DeleteAllItems()
            for i, chat in enumerate(full_chats):
                name     = full_names[i]
                chat_jid = chat.get("remoteJid", "")
                # ── Conversation filter ───────────────────────────────────────
                if conv_filter == 'unread' and int(chat.get("unreadCount") or 0) == 0:
                    continue
                if conv_filter == 'groups' and not chat_jid.endswith("@g.us"):
                    continue
                if conv_filter == 'individual' and chat_jid.endswith("@g.us"):
                    continue
                # ── Search filter ─────────────────────────────────────────────
                if search and search not in name.lower():
                    continue
                unread = int(chat.get("unreadCount") or 0)
                if unread > 0:
                    unread_str = (
                        f" {unread} "
                        + (self.mw.i18n.t("unread_messages") if unread > 1 else self.mw.i18n.t("unread_message"))
                    )
                else:
                    unread_str = ""
                preview = self._last_msg_preview(chat)
                item_text = name + unread_str
                if preview:
                    item_text += f" {preview}"
                # Show typing/recording indicator when any participant is active
                chat_jid_norm = self.mw._normalize_jid(chat_jid) if chat_jid else ""
                if chat_jid_norm:
                    presence_label = self.mw._presence_label_for_chat(
                        chat_jid_norm, chat_jid_norm.endswith("@g.us")
                    )
                    if presence_label:
                        item_text += f" {presence_label}"
                lst.Append((item_text,))
                displayed_chats.append(chat)
                displayed_names.append(name)
        finally:
            lst.Thaw()

        # Keep backing lists in sync with exactly what is displayed so that
        # on_conversation_selected_by_index(idx) always maps correctly.
        self.mw.conversations_panel.chats_list = displayed_chats
        self.mw.conversations_panel.chat_names = displayed_names

        # Restore selection / focus after DeleteAllItems() clears everything.
        # Prefer the previously focused item if it is still in the list to prevent jumping.
        panel = self.mw.conversations_panel
        target_idx = -1
        if focused_jid:
            for i, chat in enumerate(displayed_chats):
                if chat.get("remoteJid") == focused_jid:
                    target_idx = i
                    break

        if target_idx != -1:
            if _lst_had_focus:
                if panel.conversations_list.GetFocusedItem() != target_idx:
                    panel.conversations_list.Focus(target_idx)
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)
            elif panel.conversation is not None:
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
        elif getattr(self.mw, "_initial_sync_running", False):
            pass
        elif panel.conversation is None and displayed_chats:
            last_jid    = getattr(panel, "_last_open_jid", "")
            target_idx  = 0
            if last_jid:
                for i, chat in enumerate(displayed_chats):
                    if chat.get("remoteJid") == last_jid:
                        target_idx = i
                        break
            if focus_allowed:
                if panel.conversations_list.GetFocusedItem() != target_idx:
                    panel.conversations_list.Focus(target_idx)
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)
                search = getattr(panel, "search_field", None)
                focused_now = wx.Window.FindFocus()
                if _lst_had_focus or focused_now is None or focused_now is lst:
                    if focused_now is not search:
                        wx.CallAfter(lst.SetFocus)
        elif panel.conversation is not None:
            open_jid = panel.conversation.get("remoteJid", "")
            target_idx = -1
            for i, chat in enumerate(displayed_chats):
                if chat.get("remoteJid") == open_jid:
                    target_idx = i
                    break
            if target_idx != -1:
                if _lst_had_focus:
                    if panel.conversations_list.GetFocusedItem() != target_idx:
                        panel.conversations_list.Focus(target_idx)
                if not panel.conversations_list.IsSelected(target_idx):
                    panel.conversations_list.Select(target_idx)
                panel.conversations_list.EnsureVisible(target_idx)

            if focus_allowed:
                focus_ctrl = getattr(panel, "message_field", None)
                if focus_ctrl and focus_ctrl.IsShownOnScreen():
                    if wx.Window.FindFocus() is None and self.mw.IsActive():
                        wx.CallAfter(focus_ctrl.SetFocus)

        # Also refresh the archived panel if present
        if hasattr(self.mw, "archived_conversations_panel"):
            panel = self.mw.archived_conversations_panel
            arch_full_chats = list(getattr(panel, '_all_chats_list', panel.chats_list))
            arch_full_names = list(getattr(panel, '_all_chat_names', panel.chat_names))
            arch_displayed_chats: list = []
            arch_displayed_names: list = []
            panel.conversations_list.DeleteAllItems()
            for i, chat in enumerate(arch_full_chats):
                name = arch_full_names[i]
                unread = int(chat.get("unreadCount") or 0)
                if unread > 0:
                    unread_str = (
                        f" {unread} "
                        + (self.mw.i18n.t("unread_messages") if unread > 1 else self.mw.i18n.t("unread_message"))
                    )
                else:
                    unread_str = ""
                preview = self._last_msg_preview(chat)
                item_text = name + unread_str
                if preview:
                    item_text += f" {preview}"
                panel.conversations_list.Append((item_text,))
                arch_displayed_chats.append(chat)
                arch_displayed_names.append(name)
            panel.chats_list = arch_displayed_chats
            panel.chat_names = arch_displayed_names

            arch_list_has_focus = (wx.Window.FindFocus() == panel.conversations_list)

            # Keep focus on archived panel too
            if arch_displayed_chats:
                target_idx = -1
                if arch_focused_jid:
                    for i, chat in enumerate(arch_displayed_chats):
                        if chat.get("remoteJid") == arch_focused_jid:
                            target_idx = i
                            break
                if target_idx != -1:
                    if arch_list_has_focus:
                        if panel.conversations_list.GetFocusedItem() != target_idx:
                            panel.conversations_list.Focus(target_idx)
                    if not panel.conversations_list.IsSelected(target_idx):
                        panel.conversations_list.Select(target_idx)
                    panel.conversations_list.EnsureVisible(target_idx)
                elif not getattr(self.mw, "_initial_sync_running", False):
                    last_jid   = getattr(panel, "_last_open_jid", "")
                    target_idx = 0
                    if last_jid:
                        for i, chat in enumerate(arch_displayed_chats):
                            if chat.get("remoteJid") == last_jid:
                                target_idx = i
                                break
                    if arch_list_has_focus:
                        panel.conversations_list.Focus(target_idx)
                    panel.conversations_list.Select(target_idx)
                    panel.conversations_list.EnsureVisible(target_idx)
