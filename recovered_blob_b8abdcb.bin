"""
WinZapp Notification Manager
-----------------------------
Sends native Windows 11 toast notifications for incoming messages.

Design decisions:
  - Uses windows-toasts (WinRT-based) for proper Win11 notifications.
  - Sets toast.audio = silent=True and plays message_background.ogg manually
    so the default Windows notification sound is suppressed.
  - Uses InteractableWindowsToaster so the quick-reply TextBox works and
    activations (click / reply) call back into the running Python process.
  - Setting the same toast.tag replaces the previous notification on screen
    while moving it to the Action Center, giving the natural '5-second then
    to Action Center' behaviour even if multiple messages arrive quickly.
  - SetCurrentProcessExplicitAppUserModelID("WinZapp") (called in main.py)
    ensures that Windows displays "WinZapp" — not the exe filename — as the
    sender inside the notification.
"""

import threading
import uuid
import wx
from core.i18n import I18n
from core.message_queue import PendingMessage


def _notif_duration(seconds) -> str:
    """Format seconds as M:SS or H:MM:SS for notification body."""
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return "0:00"
    h   = s // 3600
    m   = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _notif_filesize(size_bytes, decimal_separator=".") -> str:
    """Format bytes as human-readable size."""
    try:
        size = int(size_bytes or 0)
    except (TypeError, ValueError):
        return ""
    sep = decimal_separator
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.1f}".replace(".", sep) + " KB"
    else:
        return f"{size / (1024 ** 2):.2f}".replace(".", sep) + " MB"


def format_notification_body(msg: dict, i18n) -> str:
    """
    Build a compact notification body for any supported message type.
    Mirrors the display logic in ConversationsPanel._get_message_content
    but uses compact duration (M:SS) and avoids i18n verbose duration strings.
    """
    msg_type = msg.get("messageType", "conversation")
    msg_obj  = msg.get("message") or {}
    sep      = i18n.t("decimal_separator")

    if not isinstance(msg_obj, dict):
        return i18n.t("notif_unsupported")

    # ── Text ──────────────────────────────────────────────────────────────────
    if msg_type == "conversation":
        text = msg_obj.get("conversation") or ""
        # Truncate long text — Windows caps at ~256 chars in notification body
        if len(text) > 200:
            text = text[:197] + "..."
        return text

    if msg_type == "extendedTextMessage":
        ext  = msg_obj.get("extendedTextMessage") or {}
        text = ext.get("text") or ""
        if len(text) > 200:
            text = text[:197] + "..."
        return text

    # ── Audio ─────────────────────────────────────────────────────────────────
    if msg_type == "audioMessage":
        audio = msg_obj.get("audioMessage") or {}
        dur   = _notif_duration(audio.get("seconds"))
        return f"{i18n.t('notif_voice_message')} ({dur})"

    # ── Video ─────────────────────────────────────────────────────────────────
    if msg_type == "videoMessage":
        video = msg_obj.get("videoMessage") or {}
        if video.get("gifPlayback"):
            return i18n.t("sticker")
        dur = _notif_duration(video.get("seconds"))
        if dur and dur != "0:00":
            return f"{i18n.t('video')} ({dur})"
        return i18n.t("video")

    # ── Image ─────────────────────────────────────────────────────────────────
    if msg_type == "imageMessage":
        img     = msg_obj.get("imageMessage") or {}
        caption = (img.get("caption") or "").strip()
        if caption:
            if len(caption) > 150:
                caption = caption[:147] + "..."
            return f"{i18n.t('photo')}: {caption}"
        return i18n.t("photo_no_caption")

    # ── Document ──────────────────────────────────────────────────────────────
    if msg_type == "documentMessage":
        doc      = msg_obj.get("documentMessage") or {}
        filename = doc.get("fileName") or doc.get("title") or i18n.t("document")
        size_str = _notif_filesize(doc.get("fileLength"), sep)
        if size_str:
            return f"{i18n.t('document')}: {filename}, {size_str}"
        return f"{i18n.t('document')}: {filename}"

    # ── Sticker ───────────────────────────────────────────────────────────────
    if msg_type == "stickerMessage":
        return i18n.t("sticker")

    # ── Contact ───────────────────────────────────────────────────────────────
    if msg_type == "contactMessage":
        contact = msg_obj.get("contactMessage") or {}
        name    = contact.get("displayName") or ""
        return i18n.t("contact_message").format(name=name)

    # ── Location ──────────────────────────────────────────────────────────────
    if msg_type == "locationMessage":
        return i18n.t("notif_location")

    # ── Reaction ──────────────────────────────────────────────────────────────
    if msg_type == "reactionMessage":
        reaction = msg_obj.get("reactionMessage") or {}
        emoji    = reaction.get("text") or ""
        return i18n.t("notif_reaction").format(emoji=emoji)

    # ── Fallback ──────────────────────────────────────────────────────────────
    return i18n.t("notif_unsupported")


def format_foreground_sender(msg: dict, main_window, i18n) -> str:
    """
    Sender label for foreground (scenario 1 — active conversation).
    Private chat  → sender name only.
    Group message → participant name only (no group name).
    """
    from core.utils import format_number
    key        = msg.get("key", {})
    remote_jid = key.get("remoteJid", "")
    push_name  = msg.get("pushName", "")

    if remote_jid.endswith("@g.us"):
        participant_name = push_name
        if not participant_name:
            p_jid = key.get("participant", "")
            if p_jid:
                c = main_window.contacts.get(p_jid, {})
                participant_name = (
                    c.get("pushName") or format_number(p_jid)
                )
        return participant_name or remote_jid.split("@")[0]

    chat = main_window.chats.get(remote_jid, {})
    return (
        main_window._resolve_contact_name(chat)
        or push_name
        or format_number(remote_jid)
    )


def format_notification_title(msg: dict, main_window, i18n) -> str:
    """
    Build the notification title.

    Private chat  → sender name
    Group message → 'Participant em GroupName'
    """
    from core.utils import format_number

    key        = msg.get("key", {})
    remote_jid = key.get("remoteJid", "")
    push_name  = msg.get("pushName", "")

    if remote_jid.endswith("@g.us"):
        # Resolve group name
        chat = main_window.chats.get(remote_jid, {})
        group_name = (
            main_window._resolve_contact_name(chat)
            or chat.get("pushName", "")
            or remote_jid.split("@")[0]
        )
        # Resolve participant name from pushName or participant JID
        participant_name = push_name
        if not participant_name:
            p_jid = key.get("participant", "")
            if p_jid:
                c = main_window.contacts.get(p_jid, {})
                participant_name = (
                    c.get("pushName") or format_number(p_jid)
                )
        if not participant_name:
            participant_name = remote_jid.split("@")[0]

        return i18n.t("notif_in_group").format(
            participant=participant_name, group=group_name
        )

    # Private chat — use contact name or pushName
    chat = main_window.chats.get(remote_jid, {})
    name = (
        main_window._resolve_contact_name(chat)
        or push_name
        or format_number(remote_jid)
    )
    return name


class NotificationManager:
    """Manages Windows 11 toast notifications for incoming WinZapp messages."""

    APP_ID    = "WinZapp"
    TOAST_TAG = "winzapp_active"
    TOAST_GRP = "winzapp_msgs"

    def __init__(self, main_window):
        self.main_window = main_window
        self.i18n = I18n(main_window)
        self.i18n.get_language()
        self._toaster  = None
        self._lock     = threading.Lock()
        self._setup()

    def _setup(self):
        try:
            from windows_toasts import InteractableWindowsToaster
            self._toaster = InteractableWindowsToaster(self.APP_ID)
        except Exception as e:
            print(f"[NotificationManager] Toast system unavailable: {e}")

    def send(self, title: str, body: str, remote_jid: str):
        """Send a toast notification (non-blocking)."""
        if not self._toaster:
            return
        threading.Thread(
            target=self._send_worker,
            args=(title, body, remote_jid),
            daemon=True,
        ).start()

    def _send_worker(self, title: str, body: str, remote_jid: str):
        try:
            from windows_toasts import Toast, ToastInputTextBox, ToastAudio, ToastDuration

            with self._lock:
                self.i18n.get_language()
                reply_hint = self.i18n.t("notif_reply_hint")

                toast          = Toast()
                toast.tag      = self.TOAST_TAG
                toast.group    = self.TOAST_GRP
                toast.duration = ToastDuration.Short   # ~5 seconds on screen
                toast.text_fields = [title, body]
                toast.audio    = ToastAudio(silent=True)  # suppress Windows sound

                toast.AddInput(ToastInputTextBox("reply_box", reply_hint, ""))

                jid_snapshot = remote_jid

                def on_activated(event):
                    inputs     = getattr(event, "inputs", {}) or {}
                    reply_text = (inputs.get("reply_box") or "").strip()
                    if reply_text:
                        wx.CallAfter(self._do_reply, jid_snapshot, reply_text)
                    else:
                        wx.CallAfter(self._do_open, jid_snapshot)

                toast.on_activated = on_activated
                self._toaster.show_toast(toast)

            # Play custom OGG sound after releasing the lock
            wx.CallAfter(self._play_sound)

        except Exception as e:
            print(f"[NotificationManager] send_worker error: {e}")

    def _play_sound(self):
        if hasattr(self.main_window, "message_background_sound"):
            self.main_window.message_background_sound.play()

    def _do_reply(self, jid: str, text: str):
        if not text:
            return
        local_id = str(uuid.uuid4())
        pm = PendingMessage(local_id=local_id, jid=jid, text=text)
        self.main_window.message_queue.enqueue(pm)

    def _do_open(self, jid: str):
        import threading
        self.main_window.restore_window()
        wx.CallAfter(self.main_window.navigate_to_conversation_jid, jid)
        # Mark conversation as read in a background thread (navigate already does
        # this, but we repeat it here so a standalone notification click also clears
        # the unread count even if the conversation panel doesn't re-open).
        threading.Thread(
            target=self.main_window.mark_conversation_as_read,
            args=(jid,),
            daemon=True,
        ).start()

    def refresh_language(self):
        self.i18n.get_language()
