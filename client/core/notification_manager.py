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
import re as _re
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


def _extract_context_info(msg: dict) -> dict:
    """Return the first non-empty contextInfo found anywhere in the message."""
    ctx = msg.get("contextInfo")
    if ctx and isinstance(ctx, dict):
        return ctx
    msg_obj = msg.get("message") or {}
    for sub_key in ("extendedTextMessage", "audioMessage", "imageMessage",
                    "videoMessage", "documentMessage", "stickerMessage",
                    "contactMessage", "locationMessage"):
        sub = msg_obj.get(sub_key)
        if sub and isinstance(sub, dict):
            ctx = sub.get("contextInfo")
            if ctx and isinstance(ctx, dict):
                return ctx
    return {}


def _extract_msg_text(msg: dict) -> str:
    """Return the plain text body of a message (used for @all pattern detection)."""
    msg_obj = msg.get("message") or {}
    text = msg_obj.get("conversation") or ""
    if not text:
        text = (msg_obj.get("extendedTextMessage") or {}).get("text") or ""
    return text


def _build_notif_prefix(msg: dict, main_window, i18n) -> str:
    """
    Return the appropriate context prefix for a toast notification title:
      notif_replied_to_you  — this message quotes one of the user's own messages
      notif_mentioned_you   — the user is directly @mentioned
      notif_mentioned_all   — @all / @todos / @everyone was used
      ''                    — no special context
    Only the first matching condition is returned (reply takes priority).
    """
    ctx = _extract_context_info(msg)
    if not ctx:
        return ""

    my_jid   = getattr(main_window, "my_jid", "")
    my_phone = my_jid.split("@")[0] if my_jid else ""

    # ── Reply to me? ──────────────────────────────────────────────────────────
    stanza_id = ctx.get("stanzaId", "")
    if stanza_id:
        # participant = JID of whoever sent the quoted message
        participant = (ctx.get("participant") or ctx.get("quotedParticipant") or "")
        remote_jid  = msg.get("key", {}).get("remoteJid", "")
        is_group    = remote_jid.endswith("@g.us")

        if my_jid:
            p_phone = participant.split("@")[0] if participant else ""
            replied_to_me = (
                participant == my_jid               # exact JID match
                or (p_phone and p_phone == my_phone)  # phone prefix match
                # In a private chat, participant may be absent — any reply comes from them to us
                or (not participant and not is_group)
            )
            if replied_to_me:
                return i18n.t("notif_replied_to_you")

    # ── Mentions ──────────────────────────────────────────────────────────────
    mentioned = ctx.get("mentionedJid") or []
    if not mentioned:
        return ""

    # @all / @todos / @everyone — check text for the keyword
    text = _extract_msg_text(msg)
    if _re.search(r"@(all|todos|everyone)\b", text, _re.IGNORECASE):
        return i18n.t("notif_mentioned_all")

    # Direct @mention of the user
    if my_jid and my_phone:
        for m_jid in mentioned:
            if m_jid == my_jid or m_jid.split("@")[0] == my_phone:
                return i18n.t("notif_mentioned_you")

    return ""


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
        return msg_obj.get("conversation") or ""

    if msg_type == "extendedTextMessage":
        ext = msg_obj.get("extendedTextMessage") or {}
        return ext.get("text") or ""

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
        candidates = [p_jid]
        local = p_jid.rsplit("@", 1)[0]
        lid_to_phone = getattr(main_window, "_lid_to_phone", {})
        if p_jid.endswith("@lid"):
            phone = lid_to_phone.get(p_jid, "")
            if phone:
                candidates.append(phone)
                candidates.append(phone.rsplit("@", 1)[0] + "@c.us")
        elif p_jid.endswith("@s.whatsapp.net"):
            candidates.append(local + "@c.us")
            lid = getattr(main_window, "_phone_to_lid", {}).get(p_jid, "")
            if lid:
                candidates.append(lid)
        elif p_jid.endswith("@c.us"):
            candidates.append(local + "@s.whatsapp.net")

        for cjid in candidates:
            p_chat = main_window.chats.get(cjid) or main_window.contacts.get(cjid) or {"remoteJid": cjid}
            saved = main_window._resolve_contact_name(p_chat)
            if saved:
                return saved

    if push_name and not is_phone_like(push_name):
        return push_name

    ppm = getattr(main_window, "_presence_pushname_map", {})
    if p_jid:
        for cjid in candidates:
            pname = (ppm.get(cjid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname

    if p_jid:
        if not p_jid.endswith("@lid"):
            return format_number(p_jid)
        phone = lid_to_phone.get(p_jid, "")
        if phone:
            return format_number(phone)
    return ""


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
        if (not p_jid or p_jid.endswith("@g.us")) and push_name and push_name.isdigit():
            p_jid = f"{push_name}@s.whatsapp.net"
        return _resolve_participant_name(p_jid, push_name, main_window) or i18n.t("unnamed_participant") or "Participante sem nome"

    chat = main_window.chats.get(remote_jid) or {"remoteJid": remote_jid}
    return (
        main_window._resolve_contact_name(chat)
        or push_name
        or format_number(remote_jid)
    )


def format_notification_title(msg: dict, main_window, i18n) -> str:
    """
    Build the notification title for a toast notification.

    Private chat  → [prefix] sender name
    Group message → [prefix] 'Participant em GroupName'

    prefix is one of notif_replied_to_you / notif_mentioned_you /
    notif_mentioned_all, or absent when none of those conditions apply.
    """
    from core.utils import format_number

    key        = msg.get("key", {})
    remote_jid = key.get("remoteJid", "")
    push_name  = msg.get("pushName", "")

    if remote_jid.endswith("@g.us"):
        chat = main_window.chats.get(remote_jid) or {"remoteJid": remote_jid}
        group_name = (
            main_window._resolve_contact_name(chat)
            or chat.get("name", "")
            or chat.get("pushName", "")
        )
        if not group_name or not group_name.strip():
            group_name = i18n.t("unknown_group") or "Grupo sem nome"

        # Resolve participant name — saved name takes priority over pushName
        p_jid = key.get("participant") or msg.get("participant") or ""
        if (not p_jid or p_jid.endswith("@g.us")) and push_name and push_name.isdigit():
            p_jid = f"{push_name}@s.whatsapp.net"
        participant_name = _resolve_participant_name(p_jid, push_name, main_window)
        if not participant_name:
            participant_name = i18n.t("unnamed_participant") or "Participante sem nome"
        base = i18n.t("notif_in_group").format(
            participant=participant_name, group=group_name
        )
    else:
        chat = main_window.chats.get(remote_jid) or {"remoteJid": remote_jid}
        base = (
            main_window._resolve_contact_name(chat)
            or push_name
            or format_number(remote_jid)
        )

    prefix = _build_notif_prefix(msg, main_window, i18n)
    return f"{prefix} {base}" if prefix else base


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
        self.main_window.restore_window()
        # navigate_to_conversation captures unreadCount BEFORE starting its own
        # mark-as-read thread, so we must not start a competing thread here —
        # that race condition would zero unreadCount before the snapshot is taken
        # and suppress the unread separator.
        wx.CallAfter(self.main_window.navigate_to_conversation_jid, jid)

    def refresh_language(self):
        self.i18n.get_language()
