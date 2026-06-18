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
  - A single long-lived worker thread owns the Toaster object so that WinRT
    COM objects are always created and used on the same thread, avoiding the
    [WinError -2147417842] RPC_E_WRONG_THREAD error that occurs when the
    toaster is created in one thread and show_toast() called in another.
"""

import os
import queue
import sys
import threading
import uuid
import wx
from app_paths import _is_frozen
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


def _resolve_participant_name(p_jid: str, push_name: str, main_window) -> str:
    """
    Return the best display name for a group participant.
    Priority: saved contact/chat name → WhatsApp pushName → phone number.
    """
    from core.utils import format_number, is_phone_like
    if p_jid:
        # Use _resolve_contact_name with the participant's own chat object so
        # step 4 (chat.name) is also available.
        p_chat = main_window.chats.get(p_jid) or {"remoteJid": p_jid}
        saved = main_window._resolve_contact_name(p_chat)
        if saved:
            return saved
    if push_name and not is_phone_like(push_name):
        return push_name
    if p_jid and not p_jid.endswith("@lid"):
        return format_number(p_jid)
    return p_jid or ""


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
        p_jid = key.get("participant") or msg.get("participant") or ""
        return _resolve_participant_name(p_jid, push_name, main_window) or remote_jid.split("@")[0]

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
            or chat.get("name", "")
            or chat.get("pushName", "")
            or remote_jid.split("@")[0]
        )
        # Resolve participant name — saved name takes priority over pushName
        p_jid = key.get("participant") or msg.get("participant") or ""
        participant_name = _resolve_participant_name(p_jid, push_name, main_window)
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
        self._toaster      = None
        self._interactable = False
        # Register the AUMID on the main thread before starting the worker so
        # the registry key exists before any WinRT notifier is created.
        self._register_aumid_registry()
        # Queue consumed by a single long-lived worker thread so that the
        # WinRT/COM toaster object is always created and used in the same
        # thread (avoids [WinError -2147417842] RPC_E_WRONG_THREAD).
        self._queue  = queue.Queue()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    # ── Worker thread (owns the toaster for its whole lifetime) ───────────────

    def _worker_loop(self):
        """Long-lived thread: creates the toaster once, then drains the queue."""
        self._setup_toaster()
        while True:
            item = self._queue.get()
            if item is None:
                break
            title, body, remote_jid = item
            self._dispatch(title, body, remote_jid)

    @staticmethod
    def _outer_exe_path() -> str:
        """Return the user-facing exe path (outer exe, not the Nuitka temp extraction)."""
        if sys.argv and sys.argv[0]:
            return os.path.abspath(sys.argv[0])
        return sys.executable

    @staticmethod
    def _register_aumid_registry():
        """Write HKCU\\SOFTWARE\\Classes\\AppUserModelId\\WinZapp to the registry.

        The windows-toasts library (and WinRT in general) requires the AUMID to be
        registered in the user-hive registry before a toast can be sent from an
        unpackaged app.  Installed builds have this key written by the NSIS
        installer; portable/zip builds have no installer, so we register it here
        at runtime.  Writing the same values twice is harmless.

        We use sys.argv[0] (not sys.executable) for the IconUri because in Nuitka
        onefile mode sys.executable points to the inner extracted exe in a temp
        directory, while sys.argv[0] always points to the user-visible outer exe.
        """
        try:
            import winreg
            key_path = r"SOFTWARE\Classes\AppUserModelId\WinZapp"
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path,
                                    0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "WinZapp")
                if _is_frozen():
                    exe = sys.argv[0] if sys.argv and sys.argv[0] else sys.executable
                    winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ,
                                      os.path.abspath(exe))
        except Exception as e:
            print(f"[NotificationManager] AUMID registry write failed: {e}")

    def _setup_toaster(self):
        # Ensure the AUMID is registered in the current-user registry so that
        # portable builds (which have no NSIS installer) can send toasts.
        self._register_aumid_registry()

        # Build a prioritised list of AUMID candidates to try.
        # Installed build: registered AUMID "WinZapp" first, outer exe as fallback.
        # Dev build / portable: outer exe path (always available to Windows).
        # _is_frozen() handles both PyInstaller (sys.frozen) and Nuitka (__compiled__).
        # Use sys.argv[0] as the exe fallback — in Nuitka onefile sys.executable
        # points to a temp-dir extraction; sys.argv[0] is the user-visible path.
        if _is_frozen():
            outer_exe = self._outer_exe_path()
            candidates = [self.APP_ID, outer_exe]
        else:
            candidates = [sys.executable]

        for app_id in candidates:
            # Try interactable first (supports inline reply text box).
            try:
                from windows_toasts import InteractableWindowsToaster
                # Pass notifierAUMID explicitly — without it the library defaults
                # to cmd.exe's AUMID, which causes Windows to label the
                # notification as "Prompt de Comando" / "Command Prompt".
                self._toaster      = InteractableWindowsToaster(app_id, notifierAUMID=app_id)
                self._interactable = True
                print(f"[NotificationManager] interactable toaster ready (app_id={app_id!r})")
                return
            except Exception as e:
                print(f"[NotificationManager] InteractableWindowsToaster({app_id!r}) failed: {e}")
            # Fall back to basic toaster (no inline reply).
            try:
                from windows_toasts import WindowsToaster
                self._toaster = WindowsToaster(app_id)
                print(f"[NotificationManager] basic toaster ready (app_id={app_id!r})")
                return
            except Exception as e:
                print(f"[NotificationManager] WindowsToaster({app_id!r}) failed: {e}")

        print("[NotificationManager] toast system unavailable — all candidates failed")

    def _dispatch(self, title: str, body: str, remote_jid: str):
        if not self._toaster:
            return
        try:
            from windows_toasts import Toast, ToastInputTextBox, ToastAudio, ToastDuration

            self.i18n.get_language()
            reply_hint = self.i18n.t("notif_reply_hint")

            toast          = Toast()
            toast.tag      = self.TOAST_TAG
            toast.group    = self.TOAST_GRP
            toast.duration = ToastDuration.Short   # ~5 seconds on screen
            toast.text_fields = [title, body]
            toast.audio    = ToastAudio(silent=True)  # suppress Windows sound

            jid_snapshot = remote_jid

            if self._interactable:
                toast.AddInput(ToastInputTextBox("reply_box", reply_hint, ""))

                def on_activated(event):
                    inputs     = getattr(event, "inputs", {}) or {}
                    reply_text = (inputs.get("reply_box") or "").strip()
                    if reply_text:
                        wx.CallAfter(self._do_reply, jid_snapshot, reply_text)
                    else:
                        wx.CallAfter(self._do_open, jid_snapshot)

                toast.on_activated = on_activated
            else:
                def on_activated(event):
                    wx.CallAfter(self._do_open, jid_snapshot)

                toast.on_activated = on_activated

            self._toaster.show_toast(toast)

            # Play custom OGG sound after the toast is sent
            wx.CallAfter(self._play_sound)

        except Exception as e:
            print(f"[NotificationManager] send_worker error: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def send(self, title: str, body: str, remote_jid: str):
        """Enqueue a toast notification (non-blocking)."""
        self._queue.put((title, body, remote_jid))

    # ── Callbacks (called on wx main thread via CallAfter) ────────────────────

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
