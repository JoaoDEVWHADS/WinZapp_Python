"""Explicit comment reads/sends: no normal-message queue and no automatic retry."""

from urllib.parse import quote

from core.api_client import api_get, api_post
from core.community_comments import (CommunityCommentsError, apply_reply_count,
                                     comment_send_confirmed, latest_reply_preview,
                                     parse_comments)
from core.incremental_sync import timestamp_seconds
from core.locale_format import preview_time_text


class CommunityCommentsMixin:
    def _announcement_comment_id(self, jid, message):
        if not isinstance(jid, str) or not jid.endswith("@g.us"):
            raise CommunityCommentsError("not_announcement")
        key = message.get("key") or {}
        parent = self._serialize_msg_id(jid, key, message)
        parts = parent.split("_", 2) if isinstance(parent, str) else []
        if len(parts) != 3 or parts[1] != jid:
            raise CommunityCommentsError("unavailable")
        return parent

    def _community_comments_url(self, parent):
        return (f"{self.wpp_server}:{self.wpp_port}/api/{self.token}"
                f"/message-comments/{quote(parent, safe='')}")

    def get_announcement_comments(self, jid, message):
        parent = self._announcement_comment_id(jid, message)
        try:
            response = api_get(self._community_comments_url(parent),
                               headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
            payload = response.json()
            if response.status_code == 400 and payload.get("code") == "not_community_announcement":
                raise CommunityCommentsError("not_announcement")
            response.raise_for_status()
            return parse_comments(payload, parent)
        except CommunityCommentsError:
            raise
        except Exception:
            raise CommunityCommentsError("unavailable") from None

    def send_announcement_comment(self, jid, message, text):
        parent = self._announcement_comment_id(jid, message)
        if not isinstance(text, str) or not text.strip():
            raise CommunityCommentsError("invalid_text")
        try:
            response = api_post(self._community_comments_url(parent), json={"text": text},
                                headers={"Authorization": f"Bearer {self.token}"}, timeout=45)
            if comment_send_confirmed(response.status_code, response.json()):
                return True
        except Exception:
            pass
        # A timeout or a failed verdict may follow an actual delivery.
        raise CommunityCommentsError("unconfirmed")

    def on_announcement_reply_count(self, event):
        """UI thread: WhatsApp counted a reply to an announcement arriving or
        being deleted (`announcement-replies`, parsed by
        parse_reply_count_event). Updates the count the message row shows and
        has an open replies window for that announcement read itself again,
        so nobody has to press Refresh."""
        jid, count = event["chat"], event["count"]
        panel = getattr(self, "conversations_panel", None)
        if panel is not None:
            panel._update_announcement_reply_count(jid, {"key": {"id": event["key_id"]}}, count)
        apply_reply_count((getattr(self, "chats", None) or {}).get(jid), event["key_id"], count)
        for dialog in list(getattr(self, "_announcement_comment_dialogs", ())):
            dialog.on_reply_count_changed(jid, event["key_id"], count)

    def on_announcement_reply_preview(self, event):
        """UI thread: WhatsApp changed a group's chat-list preview. A reply
        becomes the preview at once and lifts the chat in the list, as it does
        on the phone, instead of waiting for the next list-chats poll."""
        chat = (getattr(self, "chats", None) or {}).get(event["chat"])
        if not isinstance(chat, dict):
            return
        preview = event["preview"]
        lifted = bool(preview) and preview["timestamp"] > timestamp_seconds(chat.get("t"))
        if chat.get("chatlistPreview") == preview and not lifted:
            # Every reaction in a group lands here: nothing to redraw.
            return
        chat["chatlistPreview"] = preview
        if lifted:
            chat["t"] = preview["timestamp"]
        self._schedule_set_chats()

    def _announcement_reply_preview_text(self, chat, newer_than):
        """ "Fulano respondeu a um aviso 14:32" when a reply to an
        announcement is the newest thing in *chat* (strictly newer than
        *newer_than*, in seconds), else "". The sender is a name, never an
        identifier."""
        reply = latest_reply_preview(chat)
        if reply is None or reply["timestamp"] <= newer_than:
            return ""
        i18n = self.i18n
        sender = self._normalize_jid(reply["sender"])
        if reply["from_me"] or self._is_self_jid(sender):
            label = i18n.t("announcement_reply_preview_you")
        else:
            name = (self._resolve_contact_name({"remoteJid": sender})
                    or self._preview_sender_from_jid(sender))
            if not name or "@" in name:
                name = i18n.t("unnamed_participant")
            label = i18n.t("announcement_reply_preview_them").format(name=name)
        time_text = preview_time_text(reply["timestamp"], i18n)
        return f"{label} {time_text}" if time_text else label
