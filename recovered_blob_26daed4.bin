import base64 as _b64
import os
import tempfile
import threading
import wx
import sound_lib.stream as sl_stream
from sound_lib.effects import Tempo
from accessible import (
    AccessibleSearchConversations,
    AccessibleRecordVoiceMessage,
    AccessibleAudioSlider,
    AccessibleSaveAs,
)
from utils import format_number, decrypt_bytes
from app_paths import data_path
from datetime import datetime


class ConversationsPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent
        self.chats_list = []
        self.chat_names = []
        self.conversation = None
        self.conversation_name = ""

        # ── Audio / video player state ──────────────────────────────────────
        self._sorted_messages = []
        self._current_audio_id = None
        self._audio_stream = None
        self._audio_tempo_ctrl = None
        self._is_audio_playing = False
        self._audio_stream_duration = 0
        self._audio_temp_file = None
        self._audio_speed_index = 0
        self._audio_speed_steps = [1.0, 1.5, 2.0]
        self._audio_tempo_map = {1.0: 0, 1.5: 50, 2.0: 100}
        self._audio_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_audio_timer, self._audio_timer)

        # ── Media download progress ─────────────────────────────────────────
        # msg_id -> float 0.0-1.0  (absent = not tracked / already complete)
        self._download_progress: dict = {}

        self.init_UI()
        self.create_accelerator_table()
        self.create_accel_conversation()

    # ── UI ──────────────────────────────────────────────────────────────────

    def init_UI(self):
        i18n = self.main_window.i18n
        outer_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Conversations list ──────────────────────────────────────────────
        self.conversations_label = wx.StaticText(self, label=i18n.t("conversations"))
        outer_sizer.Add(self.conversations_label, 0, wx.LEFT | wx.TOP, 5)

        self.conversations_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_conversations_context_menu)
        outer_sizer.Add(self.conversations_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Search ──────────────────────────────────────────────────────────
        self.search_label = wx.StaticText(self, label=i18n.t("search_conversations"))
        outer_sizer.Add(self.search_label, 0, wx.LEFT, 5)

        self.search_field = wx.TextCtrl(self, style=wx.TE_DONTWRAP)
        self.search_field.Bind(wx.EVT_TEXT, self.on_search_query_changed)
        self.search_field.SetAccessible(AccessibleSearchConversations("Ctrl+F"))
        outer_sizer.Add(self.search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # ── Conversation panel ──────────────────────────────────────────────
        self.conversation_panel = wx.Panel(self)
        conv_sizer = wx.BoxSizer(wx.VERTICAL)

        self.messages_label = wx.StaticText(
            self.conversation_panel, label=i18n.t("messages")
        )
        conv_sizer.Add(self.messages_label, 0, wx.LEFT | wx.TOP, 5)

        self.messages_list = wx.ListCtrl(self.conversation_panel, style=wx.LC_REPORT)
        self.messages_list.InsertColumn(0, i18n.t("messages"), width=360)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_message_activated)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)
        self.messages_list.Bind(wx.EVT_CONTEXT_MENU, self.on_messages_context_menu)
        conv_sizer.Add(self.messages_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Thumbnail (image / sticker / video) ─────────────────────────────
        self._media_bitmap = wx.StaticBitmap(
            self.conversation_panel, bitmap=wx.NullBitmap
        )
        conv_sizer.Add(self._media_bitmap, 0, wx.ALIGN_LEFT | wx.LEFT | wx.BOTTOM, 5)
        self._media_bitmap.Hide()

        # ── Action buttons (document / image / video) ───────────────────────
        self._action_open_btn = wx.Button(
            self.conversation_panel, label=i18n.t("open")
        )
        self._action_open_btn.Bind(wx.EVT_BUTTON, self._on_action_open)
        conv_sizer.Add(self._action_open_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._action_open_btn.Hide()

        self._action_save_as_btn = wx.Button(
            self.conversation_panel, label=i18n.t("save_as")
        )
        self._action_save_as_btn.SetAccessible(AccessibleSaveAs())
        self._action_save_as_btn.Bind(wx.EVT_BUTTON, self._on_action_save_as)
        conv_sizer.Add(self._action_save_as_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._action_save_as_btn.Hide()

        # ── Business reply buttons container ───────────────────────────────
        self._buttons_container = wx.Panel(self.conversation_panel)
        self._buttons_container.SetSizer(wx.WrapSizer(wx.HORIZONTAL))
        conv_sizer.Add(
            self._buttons_container, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5
        )
        self._buttons_container.Hide()

        # ── Audio / video playback controls ────────────────────────────────
        self.audio_speed_btn = wx.Button(
            self.conversation_panel, label=self._format_speed(1.0)
        )
        self.audio_speed_btn.Bind(wx.EVT_BUTTON, self.on_audio_speed_btn)
        conv_sizer.Add(self.audio_speed_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self.audio_speed_btn.Hide()

        self.audio_progress_label = wx.StaticText(
            self.conversation_panel, label=i18n.t("audio_progress_label")
        )
        conv_sizer.Add(self.audio_progress_label, 0, wx.LEFT, 5)
        self.audio_progress_label.Hide()

        self.audio_slider = wx.Slider(
            self.conversation_panel, value=0, minValue=0, maxValue=1000
        )
        self.audio_slider.SetAccessible(AccessibleAudioSlider(self))
        self.audio_slider.Bind(wx.EVT_SLIDER, self.on_audio_slider)
        conv_sizer.Add(self.audio_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        self.audio_slider.Hide()

        # ── Message input ───────────────────────────────────────────────────
        self.message_label = wx.StaticText(
            self.conversation_panel, label=i18n.t("type_message")
        )
        conv_sizer.Add(self.message_label, 0, wx.LEFT | wx.TOP, 5)

        self.message_field = wx.TextCtrl(
            self.conversation_panel,
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP,
        )
        self.message_field.Bind(wx.EVT_TEXT, self.on_change_message_field)
        conv_sizer.Add(self.message_field, 0, wx.EXPAND | wx.ALL, 5)

        self.send_message_btn = wx.Button(
            self.conversation_panel, label=i18n.t("send_message")
        )
        conv_sizer.Add(self.send_message_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self.send_message_btn.Hide()

        self.record_voice_message_btn = wx.Button(
            self.conversation_panel, label=i18n.t("record_voice_message")
        )
        self.record_voice_message_btn.SetAccessible(
            AccessibleRecordVoiceMessage("Ctrl+R")
        )
        self.record_voice_message_btn.Bind(wx.EVT_BUTTON, self.on_record_voice_message)
        conv_sizer.Add(self.record_voice_message_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self.conversation_panel.SetSizer(conv_sizer)
        self.conversation_panel.Hide()
        outer_sizer.Add(self.conversation_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(outer_sizer)

    # ── Accelerators ────────────────────────────────────────────────────────

    def create_accelerator_table(self):
        self.ID_CTRL_F = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("F"), self.ID_CTRL_F)
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_ctrl_f, id=self.ID_CTRL_F)

    def create_accel_conversation(self):
        self.ID_CTRL_R     = wx.NewIdRef()
        self.ID_ESC        = wx.NewIdRef()
        self.CTRL_W        = wx.NewIdRef()
        self.ID_CTRL_SHIFT_S = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL,                  ord("R"), self.ID_CTRL_R),
            (wx.ACCEL_NORMAL,     wx.WXK_ESCAPE,       self.ID_ESC),
            (wx.ACCEL_CTRL,                  ord("W"), self.CTRL_W),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"), self.ID_CTRL_SHIFT_S),
        ])
        self.conversation_panel.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message, id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self.close_conversation,      id=self.ID_ESC)
        self.Bind(wx.EVT_MENU, self.close_conversation,      id=self.CTRL_W)
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_s,        id=self.ID_CTRL_SHIFT_S)

    # ── Conversations list events ───────────────────────────────────────────

    def on_conversation_selected(self, event):
        index = event.GetIndex()
        try:
            self.navigate_to_conversation(self.chats_list[index])
        except Exception:
            return

    def navigate_to_conversation(self, conversation):
        self._stop_audio()
        self._hide_audio_controls()
        self._hide_all_media_controls()
        self.conversation = conversation
        self.conversation_name = (
            self.main_window._resolve_contact_name(conversation)
            or self.main_window.find_name_through_messages(conversation)
            or conversation.get("pushName", "")
            or self.main_window.find_jid_through_messages(conversation)
            or format_number(conversation.get("remoteJid", ""))
        )
        self.message_label.SetLabel(
            f"{self.main_window.i18n.t('type_message')} {self.conversation_name}"
        )
        self.conversation_panel.Show()
        self.Layout()
        self.preselect_messages()
        self.message_field.SetFocus()
        self.mark_as_read_thread = threading.Thread(
            target=self.main_window.mark_conversation_as_read,
            args=(self.conversation.get("remoteJid", ""),),
            daemon=True,
        )
        self.mark_as_read_thread.start()
        if self.search_field.GetValue().strip():
            self.search_field.Clear()
        self.populate_messages()

    def preselect_messages(self):
        self.messages_list.Focus(0)
        self.messages_list.Select(0)

    def on_search_query_changed(self, event):
        self.chats_list = list(self.main_window.chats.values())
        self.chat_names = list(self.main_window.chat_names)
        query = self.search_field.GetValue().lower()
        self.chats_list.clear()
        self.chat_names.clear()
        self.conversations_list.DeleteAllItems()
        for i, chat in enumerate(self.main_window.chats.values()):
            name = self.main_window.chat_names[i]
            if query in name.lower():
                self.conversations_list.Append((name,))
                self.chats_list.append(chat)
                self.chat_names.append(name)
        self.main_window.preselect_conversations()

    def on_ctrl_f(self, event):
        self.search_field.SetFocus()

    def on_change_message_field(self, event):
        msg = self.message_field.GetValue()
        if msg.strip():
            self.send_message_btn.Show()
            self.record_voice_message_btn.Hide()
        else:
            self.send_message_btn.Hide()
            self.record_voice_message_btn.Show()

    def refresh_labels(self):
        """Update all translatable labels and column headers after a language change."""
        i18n = self.main_window.i18n

        self.conversations_label.SetLabel(i18n.t("conversations"))
        col = wx.ListItem()
        col.SetText(i18n.t("conversations"))
        self.conversations_list.SetColumn(0, col)
        self.search_label.SetLabel(i18n.t("search_conversations"))

        self.messages_label.SetLabel(i18n.t("messages"))
        col2 = wx.ListItem()
        col2.SetText(i18n.t("messages"))
        self.messages_list.SetColumn(0, col2)

        self.audio_progress_label.SetLabel(i18n.t("audio_progress_label"))
        self._action_save_as_btn.SetLabel(i18n.t("save_as"))

        if self.conversation is not None and self.conversation_panel.IsShown():
            if self.conversation_name:
                self.message_label.SetLabel(
                    f"{i18n.t('type_message')} {self.conversation_name}"
                )
            else:
                self.message_label.SetLabel(i18n.t("type_message"))
        else:
            self.message_label.SetLabel(i18n.t("type_message"))

        self.send_message_btn.SetLabel(i18n.t("send_message"))
        self.record_voice_message_btn.SetLabel(i18n.t("record_voice_message"))

    def on_record_voice_message(self, event):
        pass

    def close_conversation(self, event):
        self._stop_audio()
        self._hide_audio_controls()
        self._hide_all_media_controls()
        self.conversation_panel.Hide()
        self.Layout()
        self.conversations_list.SetFocus()

    # ── Conversations context menu ──────────────────────────────────────────

    def on_conversations_context_menu(self, event):
        selected_index = self.conversations_list.GetFirstSelected()
        if selected_index == -1:
            return
        menu = wx.Menu()
        close_item = menu.Append(
            wx.ID_ANY,
            f"{self.main_window.i18n.t('close_conversation')}\tCtrl+W",
        )
        self.Bind(wx.EVT_MENU, self.on_context_menu_close, close_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_context_menu_close(self, event):
        if self.conversation_panel.IsShown():
            self.close_conversation(event)

    # ── Messages list events ────────────────────────────────────────────────

    def on_message_selected(self, event):
        """Show / hide action controls when the selection changes in the messages list."""
        index = event.GetIndex()
        self._hide_all_media_controls()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg     = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")
        media_path = data_path("media", f"{msg_id}.wzmedia")
        is_downloaded = os.path.isfile(media_path)

        if msg_type == "documentMessage":
            if is_downloaded:
                self._action_open_btn.SetLabel(self.main_window.i18n.t("open"))
                self._action_open_btn.Show()
                self._action_save_as_btn.Show()
                self.conversation_panel.Layout()

        elif msg_type == "imageMessage":
            jpeg = (msg_obj.get("imageMessage") or {}).get("jpegThumbnail", "")
            self._try_show_thumbnail(jpeg)
            self._action_open_btn.SetLabel(self.main_window.i18n.t("open_image"))
            self._action_open_btn.Show()
            self._action_save_as_btn.Show()
            self.conversation_panel.Layout()

        elif msg_type == "stickerMessage":
            jpeg = (msg_obj.get("stickerMessage") or {}).get("jpegThumbnail", "")
            self._try_show_thumbnail(jpeg)
            # No action buttons for stickers

        elif msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            jpeg = video.get("jpegThumbnail", "")
            self._try_show_thumbnail(jpeg)
            if not video.get("gifPlayback"):
                self._action_save_as_btn.Show()
            self.conversation_panel.Layout()

        elif msg_type == "buttonsMessage":
            buttons = (msg_obj.get("buttonsMessage") or {}).get("buttons", [])
            remote_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
            self._show_reply_buttons(buttons, remote_jid)

        elif msg_type == "listMessage":
            sections = (msg_obj.get("listMessage") or {}).get("sections", [])
            rows: list = []
            for sec in sections:
                rows.extend(sec.get("rows", []) if isinstance(sec, dict) else [])
            remote_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
            self._show_list_rows(rows, remote_jid)

    def on_message_activated(self, event):
        """Enter / double-click on a message item."""
        index = event.GetIndex()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")

        if msg_type == "audioMessage":
            duration = (msg_obj.get("audioMessage") or {}).get("seconds", 0) or 0
            self._toggle_playback(
                msg_id, duration, msg,
                file_path=data_path("voice_messages", f"{msg_id}.msv"),
                audio_ext=".ogg",
            )

        elif msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            if video.get("gifPlayback"):
                return  # GIFs have no audio track to play
            duration = video.get("seconds", 0) or 0
            self._toggle_playback(
                msg_id, duration, msg,
                file_path=data_path("media", f"{msg_id}.wzmedia"),
                audio_ext=".mp4",
            )

        elif msg_type == "imageMessage":
            # Enter on an image → open in default app
            self._on_action_open(None)

    def on_messages_context_menu(self, event):
        """Context menu for the messages list (Save As for media types)."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_id   = msg.get("key", {}).get("id", "")
        _SAVEABLE = {"documentMessage", "imageMessage", "videoMessage"}
        if msg_type not in _SAVEABLE:
            return
        media_path = data_path("media", f"{msg_id}.wzmedia")
        if not os.path.isfile(media_path):
            return
        menu = wx.Menu()
        save_item = menu.Append(
            wx.ID_ANY,
            f"{self.main_window.i18n.t('save_as')}\tCtrl+Shift+S",
        )
        self.Bind(wx.EVT_MENU, self._on_action_save_as, save_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_ctrl_shift_s(self, event):
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg_type = self._sorted_messages[index].get("messageType", "")
        if msg_type in ("documentMessage", "imageMessage", "videoMessage"):
            self._on_action_save_as(None)

    # ── Media controls helpers ──────────────────────────────────────────────

    def _hide_all_media_controls(self):
        self._media_bitmap.Hide()
        self._action_open_btn.Hide()
        self._action_save_as_btn.Hide()
        self._buttons_container.Hide()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _try_show_thumbnail(self, jpeg_b64: str):
        """Decode and display an inline JPEG thumbnail (base64-encoded)."""
        if not jpeg_b64:
            return
        try:
            jpeg_data = _b64.b64decode(jpeg_b64)
            stream    = wx.MemoryInputStream(jpeg_data)
            image     = wx.Image(stream, wx.BITMAP_TYPE_JPEG)
            if not image.IsOk():
                return
            w, h = image.GetWidth(), image.GetHeight()
            max_side = 200
            if w > max_side or h > max_side:
                ratio = min(max_side / w, max_side / h)
                image = image.Scale(
                    int(w * ratio), int(h * ratio), wx.IMAGE_QUALITY_HIGH
                )
            self._media_bitmap.SetBitmap(wx.Bitmap(image))
            self._media_bitmap.Show()
            self.conversation_panel.Layout()
        except Exception:
            pass

    def _show_reply_buttons(self, buttons: list, remote_jid: str):
        """Render interactive message buttons (buttonsMessage) in the container."""
        self._buttons_container.DestroyChildren()
        sizer = wx.WrapSizer(wx.HORIZONTAL)
        for btn_data in buttons:
            if not isinstance(btn_data, dict):
                continue
            label = (btn_data.get("buttonText") or {}).get("displayText", "").strip()
            if not label:
                continue
            btn = wx.Button(self._buttons_container, label=label)
            btn.Bind(
                wx.EVT_BUTTON,
                lambda e, d=btn_data, jid=remote_jid: self._on_reply_button(d, jid),
            )
            sizer.Add(btn, 0, wx.ALL, 4)
        self._buttons_container.SetSizer(sizer, True)
        self._buttons_container.Layout()
        self._buttons_container.Show()
        self.conversation_panel.Layout()

    def _show_list_rows(self, rows: list, remote_jid: str):
        """Render list-message rows as reply buttons."""
        self._buttons_container.DestroyChildren()
        sizer = wx.WrapSizer(wx.HORIZONTAL)
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = row.get("title", "").strip()
            if not label:
                continue
            btn = wx.Button(self._buttons_container, label=label)
            btn.Bind(
                wx.EVT_BUTTON,
                lambda e, r=row, jid=remote_jid: self._on_list_row_selected(r, jid),
            )
            sizer.Add(btn, 0, wx.ALL, 4)
        self._buttons_container.SetSizer(sizer, True)
        self._buttons_container.Layout()
        self._buttons_container.Show()
        self.conversation_panel.Layout()

    def _on_reply_button(self, btn_data: dict, remote_jid: str):
        label = (btn_data.get("buttonText") or {}).get("displayText", "").strip()
        if not label or not remote_jid:
            return
        threading.Thread(
            target=self.main_window.send_text_message,
            args=(remote_jid, label),
            daemon=True,
        ).start()

    def _on_list_row_selected(self, row: dict, remote_jid: str):
        label = row.get("title", "").strip()
        if not label or not remote_jid:
            return
        threading.Thread(
            target=self.main_window.send_text_message,
            args=(remote_jid, label),
            daemon=True,
        ).start()

    # ── Open / Save As ──────────────────────────────────────────────────────

    def _on_action_open(self, event):
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")

        if msg_type == "documentMessage":
            filename = (msg_obj.get("documentMessage") or {}).get(
                "fileName", f"document_{msg_id}"
            )
            ext = os.path.splitext(filename)[1] or ".bin"
        elif msg_type == "imageMessage":
            mime = (msg_obj.get("imageMessage") or {}).get("mimetype", "image/jpeg")
            ext = "." + (mime.split("/")[-1] if "/" in mime else "jpg")
        else:
            return

        media_path = data_path("media", f"{msg_id}.wzmedia")

        def _run():
            if not os.path.isfile(media_path):
                wx.CallAfter(
                    self.main_window.output, self.main_window.i18n.t("downloading")
                )
                try:
                    self.main_window.handle_media_message(msg)
                except Exception:
                    return
            try:
                with open(media_path, "rb") as fh:
                    content = decrypt_bytes(fh.read(), self.main_window.key)
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(content)
                tmp.close()
                wx.CallAfter(lambda: os.startfile(tmp.name))
            except Exception as exc:
                wx.CallAfter(
                    wx.MessageBox,
                    str(exc),
                    self.main_window.i18n.t("error").format(
                        app_name=self.main_window.app_name
                    ),
                    wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_run, daemon=True).start()

    def _on_action_save_as(self, event):
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")

        if msg_type == "documentMessage":
            default_file = (msg_obj.get("documentMessage") or {}).get(
                "fileName", f"documento_{msg_id}"
            )
        elif msg_type == "imageMessage":
            mime = (msg_obj.get("imageMessage") or {}).get("mimetype", "image/jpeg")
            ext  = mime.split("/")[-1] if "/" in mime else "jpg"
            default_file = f"foto_{msg_id}.{ext}"
        elif msg_type == "videoMessage":
            mime = (msg_obj.get("videoMessage") or {}).get("mimetype", "video/mp4")
            ext  = mime.split("/")[-1] if "/" in mime else "mp4"
            default_file = f"video_{msg_id}.{ext}"
        else:
            return

        with wx.FileDialog(
            self,
            self.main_window.i18n.t("save_as"),
            defaultFile=default_file,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            save_path = dlg.GetPath()

        media_path = data_path("media", f"{msg_id}.wzmedia")

        def _run():
            if not os.path.isfile(media_path):
                wx.CallAfter(
                    self.main_window.output, self.main_window.i18n.t("downloading")
                )
                try:
                    self.main_window.handle_media_message(msg)
                except Exception:
                    return
            try:
                with open(media_path, "rb") as fh:
                    content = decrypt_bytes(fh.read(), self.main_window.key)
                with open(save_path, "wb") as fh:
                    fh.write(content)
            except Exception as exc:
                wx.CallAfter(
                    wx.MessageBox,
                    str(exc),
                    self.main_window.i18n.t("error").format(
                        app_name=self.main_window.app_name
                    ),
                    wx.OK | wx.ICON_ERROR,
                )

        threading.Thread(target=_run, daemon=True).start()

    # ── Audio / video playback ──────────────────────────────────────────────

    def _toggle_playback(self, msg_id, duration_seconds, msg, file_path, audio_ext):
        """
        Generic play/pause toggle for both audio messages (voice_messages/)
        and video messages (media/).
        """
        # Same item: toggle play / pause
        if msg_id == self._current_audio_id and self._audio_stream is not None:
            if self._is_audio_playing:
                self._audio_stream.pause()
                self._is_audio_playing = False
                self._audio_timer.Stop()
            else:
                self._audio_stream.play()
                self._is_audio_playing = True
                self._audio_timer.Start(200)
            return

        self._stop_audio()

        if os.path.isfile(file_path):
            self._play_audio(msg_id, duration_seconds, file_path, audio_ext)
        else:
            self.main_window.output(self.main_window.i18n.t("downloading"))

            def _download_and_play():
                msg_type = msg.get("messageType", "") if msg else ""
                if msg_type == "audioMessage":
                    if msg is not None:
                        self.main_window.handle_audio_message(msg)
                else:
                    if msg is not None:
                        self.main_window.handle_media_message(msg)
                wx.CallAfter(
                    self._play_audio, msg_id, duration_seconds, file_path, audio_ext
                )

            threading.Thread(target=_download_and_play, daemon=True).start()

    def _play_audio(self, msg_id, duration_seconds, file_path, audio_ext=".ogg"):
        if not os.path.isfile(file_path):
            return
        try:
            with open(file_path, "rb") as fh:
                content = decrypt_bytes(fh.read(), self.main_window.key)
            tmp = tempfile.NamedTemporaryFile(suffix=audio_ext, delete=False)
            tmp.write(content)
            tmp.close()
            self._audio_temp_file = tmp.name
            self._audio_stream = sl_stream.FileStream(
                file=self._audio_temp_file, decode=True
            )
            self._audio_tempo_ctrl = Tempo(self._audio_stream)
            self._audio_tempo_ctrl.tempo = 0          # 1.0× default
            self._audio_stream_duration = int(duration_seconds)
            self._current_audio_id = msg_id
            self._audio_speed_index = 0
            self._audio_stream.play()
            self._is_audio_playing = True
            self._audio_timer.Start(200)
            self._show_audio_controls()
            self.audio_speed_btn.SetLabel(self._format_speed(1.0))
        except Exception:
            self._stop_audio()

    def _stop_audio(self):
        if self._audio_timer.IsRunning():
            self._audio_timer.Stop()
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop()
            except Exception:
                pass
            self._audio_stream = None
        self._audio_tempo_ctrl = None
        self._is_audio_playing = False
        self._current_audio_id = None
        if self._audio_temp_file and os.path.exists(self._audio_temp_file):
            try:
                os.unlink(self._audio_temp_file)
            except Exception:
                pass
            self._audio_temp_file = None

    def on_audio_timer(self, event):
        if self._audio_stream is None:
            return
        try:
            pos   = self._audio_stream.get_position()
            total = self._audio_stream.get_length()
            if total > 0:
                if pos >= total:
                    self._stop_audio()
                    self._hide_audio_controls()
                    return
                self.audio_slider.SetValue(int(pos / total * 1000))
                self.audio_slider.Refresh()
        except Exception:
            pass

    def on_audio_speed_btn(self, event):
        self._audio_speed_index = (self._audio_speed_index + 1) % len(
            self._audio_speed_steps
        )
        speed = self._audio_speed_steps[self._audio_speed_index]
        self.audio_speed_btn.SetLabel(self._format_speed(speed))
        if self._audio_tempo_ctrl is not None:
            try:
                self._audio_tempo_ctrl.tempo = self._audio_tempo_map[speed]
            except Exception:
                pass

    def on_audio_slider(self, event):
        if self._audio_stream is None:
            return
        try:
            val   = self.audio_slider.GetValue()
            total = self._audio_stream.get_length()
            self._audio_stream.set_position(int(val / 1000 * total))
        except Exception:
            pass

    def _show_audio_controls(self):
        self.audio_speed_btn.Show()
        self.audio_progress_label.Show()
        self.audio_slider.Show()
        self.conversation_panel.Layout()

    def _hide_audio_controls(self):
        self.audio_speed_btn.Hide()
        self.audio_progress_label.Hide()
        self.audio_slider.Hide()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _format_speed(self, speed):
        sep = self.main_window.i18n.t("decimal_separator")
        return f"{speed:.1f}".replace(".", sep) + "×"

    # ── Message content helpers ─────────────────────────────────────────────

    def _extract_timestamp(self, msg):
        if not isinstance(msg, dict):
            return None
        ts = msg.get("messageTimestamp")
        if ts is None:
            return None
        try:
            return int(ts)
        except Exception:
            return None

    def _format_date(self, ts):
        if not ts:
            return ""
        try:
            dt    = datetime.fromtimestamp(int(ts))
            today = datetime.now()
            if dt.date() == today.date():
                return dt.strftime("%H:%M")
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ""

    def _format_duration(self, seconds):
        if seconds is None:
            return ""
        try:
            seconds = int(seconds)
        except (ValueError, TypeError):
            return ""
        i18n = self.main_window.i18n
        if seconds < 60:
            unit = i18n.t("second") if seconds == 1 else i18n.t("seconds")
            return f"{seconds} {unit}"
        elif seconds < 3600:
            m, s = seconds // 60, seconds % 60
            return (
                f"{m} {i18n.t('minute') if m == 1 else i18n.t('minutes')}"
                f" {i18n.t('and')} {s} {i18n.t('second') if s == 1 else i18n.t('seconds')}"
            )
        else:
            h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
            return (
                f"{h} {i18n.t('hour') if h == 1 else i18n.t('hours')},"
                f" {m} {i18n.t('minute') if m == 1 else i18n.t('minutes')}"
                f" {i18n.t('and')} {s} {i18n.t('second') if s == 1 else i18n.t('seconds')}"
            )

    def _format_filesize(self, size_bytes) -> str:
        if size_bytes is None:
            return ""
        try:
            size = int(size_bytes)
        except (ValueError, TypeError):
            return ""
        sep = self.main_window.i18n.t("decimal_separator")
        if size < 1024:
            return f"{size} b"
        elif size < 1024 ** 2:
            return f"{size / 1024:.1f}".replace(".", sep) + " kb"
        elif size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f}".replace(".", sep) + " mb"
        else:
            return f"{size / 1024 ** 3:.2f}".replace(".", sep) + " gb"

    def _get_message_content(self, msg) -> str:
        """
        Return the human-readable text for a message item in the list.
        Field names match the Evolution API v2 / Baileys proto definitions.
        """
        msg_type = msg.get("messageType", "conversation")
        msg_obj  = msg.get("message") or {}
        i18n     = self.main_window.i18n

        if not isinstance(msg_obj, dict):
            return i18n.t("unsupported_message").format(
                app_name=self.main_window.app_name
            )

        # ── Text ────────────────────────────────────────────────────────────
        if msg_type == "conversation":
            return msg_obj.get("conversation", "")

        if msg_type == "extendedTextMessage":
            # extendedTextMessage.text holds the body; .description is link preview
            ext = msg_obj.get("extendedTextMessage") or {}
            return ext.get("text", "") or ""

        # ── Audio ────────────────────────────────────────────────────────────
        if msg_type == "audioMessage":
            audio = msg_obj.get("audioMessage") or {}
            dur   = self._format_duration(audio.get("seconds"))
            return f"{i18n.t('message_type_audio')}, {i18n.t('duration')}: {dur}"

        # ── Document ─────────────────────────────────────────────────────────
        if msg_type == "documentMessage":
            doc      = msg_obj.get("documentMessage") or {}
            filename = doc.get("fileName") or doc.get("title") or "documento"
            size_str = self._format_filesize(doc.get("fileLength"))
            msg_id   = msg.get("key", {}).get("id", "")
            progress = self._download_progress.get(msg_id)
            if progress is not None and progress < 1.0:
                pct      = int(progress * 100)
                prog_str = i18n.t("downloading_progress").format(pct=pct)
                return f"{i18n.t('document')}, {filename}, {prog_str}"
            return f"{i18n.t('document')}, {filename}, {size_str}"

        # ── Image ────────────────────────────────────────────────────────────
        if msg_type == "imageMessage":
            img     = msg_obj.get("imageMessage") or {}
            caption = (img.get("caption") or "").strip()
            if caption:
                return f"{i18n.t('photo')}, {caption}"
            return i18n.t("photo_no_caption")

        # ── Sticker ──────────────────────────────────────────────────────────
        if msg_type == "stickerMessage":
            return i18n.t("sticker")

        # ── Video / GIF ──────────────────────────────────────────────────────
        if msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            if video.get("gifPlayback"):
                # Animated GIF — treat identically to sticker
                return i18n.t("sticker")
            dur = self._format_duration(video.get("seconds"))
            return f"{i18n.t('video')}, {i18n.t('duration')}: {dur}"

        # ── Interactive buttons ───────────────────────────────────────────────
        if msg_type == "buttonsMessage":
            btns_msg = msg_obj.get("buttonsMessage") or {}
            # contentText = message body; text = header when headerType=TEXT
            content  = (btns_msg.get("contentText") or btns_msg.get("text") or "").strip()
            buttons  = btns_msg.get("buttons") or []
            labels   = [
                (b.get("buttonText") or {}).get("displayText", "")
                for b in buttons
                if isinstance(b, dict)
            ]
            opts = ", ".join(l for l in labels if l)
            if opts:
                return f"{content} {i18n.t('options')}: {opts}"
            return content

        # ── List message ─────────────────────────────────────────────────────
        if msg_type == "listMessage":
            list_msg = msg_obj.get("listMessage") or {}
            # title = header; description = body
            title    = (list_msg.get("title") or list_msg.get("description") or "").strip()
            sections = list_msg.get("sections") or []
            all_opts = [
                row.get("title", "")
                for sec in sections if isinstance(sec, dict)
                for row in (sec.get("rows") or []) if isinstance(row, dict)
            ]
            opts = ", ".join(o for o in all_opts if o)
            if opts:
                return f"{title} {i18n.t('options')}: {opts}"
            return title

        # ── Fallback ─────────────────────────────────────────────────────────
        return i18n.t("unsupported_message").format(
            app_name=self.main_window.app_name
        )

    def _map_status(self, msg) -> str:
        i18n    = self.main_window.i18n
        updates = msg.get("MessageUpdate")
        if isinstance(updates, list) and updates:
            statuses = []
            for u in updates:
                if isinstance(u, dict):
                    st = u.get("status") or u.get("ack") or ""
                    statuses.append(str(st).upper())
            for s in statuses:
                if "READ" in s:
                    return i18n.t("status_read")
            for s in statuses:
                if "DELIVERED" in s or "DELIVERY_ACK" in s:
                    return i18n.t("status_delivered")
            for s in statuses:
                if "SENT" in s or "ACK" in s:
                    return i18n.t("status_sent")
        return ""

    def _sender_label(self, msg) -> str:
        if msg.get("key", {}).get("fromMe"):
            return self.main_window.i18n.t("sender_you")
        push = msg.get("pushName", "")
        if push and not push.isdigit():
            return push
        key = msg.get("key", {})
        if key.get("addressingMode") == "lid":
            return format_number(key.get("remoteJidAlt", ""))
        return format_number(key.get("remoteJid", ""))

    def _render_message_line(self, msg) -> str:
        """Produce the full display string for a single message row."""
        ts       = self._extract_timestamp(msg)
        time_str = self._format_date(ts) if ts else ""
        body     = (self._get_message_content(msg) or "").replace("\n", " ")
        sender   = self._sender_label(msg)
        status   = self._map_status(msg)
        pieces   = [f"{sender}: {body}"]
        if time_str:
            pieces.append(f", {time_str}")
        if status:
            pieces[-1] += f", {status}"
        return " ".join(pieces)

    # ── Download progress ───────────────────────────────────────────────────

    def update_message_download_progress(self, msg_id: str, progress: float):
        """
        Called from the main thread (via wx.CallAfter) when a media file's
        download progress changes.  Refreshes the relevant row in the list.
        """
        self._download_progress[msg_id] = progress
        for i, msg in enumerate(self._sorted_messages):
            if msg.get("key", {}).get("id") == msg_id:
                self.messages_list.SetItemText(i, self._render_message_line(msg))
                break

    # ── Populate ─────────────────────────────────────────────────────────────

    def populate_messages(self):
        self.messages_list.DeleteAllItems()
        messages_container = (
            self.conversation.get("messages", {}) if self.conversation else {}
        )
        messages: list = []
        if isinstance(messages_container, dict):
            inner = messages_container.get("messages")
            if isinstance(inner, dict) and isinstance(inner.get("records"), list):
                messages = inner["records"]
        try:
            messages_sorted = sorted(
                messages, key=lambda m: self._extract_timestamp(m) or 0
            )
        except Exception:
            messages_sorted = messages

        # Exclude reaction messages — they must not affect index mapping
        displayable = [
            m for m in messages_sorted if m.get("messageType", "") != "reactionMessage"
        ]
        self._sorted_messages = displayable

        for msg in displayable:
            self.messages_list.Append((self._render_message_line(msg),))
