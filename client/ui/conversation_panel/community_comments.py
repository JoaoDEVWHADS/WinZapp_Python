"""Open the comment thread of the focused announcement, keeping its message identity."""

from core.community_comments import can_open_comments, is_announcement_group


class CommunityCommentsPanelMixin:
    def _can_open_announcement_comments(self, message):
        chat = self.conversation
        # The list's own copy of the chat holds what /group-info said.
        known = getattr(self.main_window, "chats", {}).get((chat or {}).get("remoteJid"))
        if isinstance(known, dict) and is_announcement_group(known):
            chat = dict(chat or {}, groupMetadata=known["groupMetadata"])
        return can_open_comments(chat, message)

    def _show_announcement_comments(self, message):
        if not self._can_open_announcement_comments(message):
            return
        from ui.dialogs.community_comments import CommunityCommentsDialog

        jid = self.conversation["remoteJid"]
        name = self.main_window._resolve_contact_name(self.conversation)
        if not name or "@" in name:
            name = self.main_window.i18n.t("community_comments_title")
        dialog = CommunityCommentsDialog(
            self, self.main_window, jid, message, name,
            on_count=lambda count: self._update_announcement_reply_count(jid, message, count))
        try:
            dialog.ShowModal()
        finally:
            dialog.close_comments()
            dialog.Destroy()

    def _update_announcement_reply_count(self, jid, message, count):
        if (self.conversation or {}).get("remoteJid") != jid:
            return
        mid = (message.get("key") or {}).get("id")
        records = self.conversation.get("messages", {}).get("messages", {}).get("records", [])
        changed = False
        for row in [message, *records, *getattr(self, "_sorted_messages", [])]:
            if (row.get("key") or {}).get("id") == mid and row.get("replyCount") != count:
                row["replyCount"] = count
                changed = True
        if changed:
            self._repaint_or_repopulate([mid])
