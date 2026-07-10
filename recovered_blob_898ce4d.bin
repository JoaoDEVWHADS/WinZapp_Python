import os
import tempfile
import threading
import wx
import sound_lib.stream as sl_stream
from sound_lib.effects import Tempo
from accessible import AccessibleSearchConversations, AccessibleRecordVoiceMessage, AccessibleAudioSlider
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

        # Audio player state
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

        self.init_UI()
        self.create_accelerator_table()
        self.create_accel_conversation()

    def init_UI(self):
        outer_sizer = wx.BoxSizer(wx.VERTICAL)

        # Conversations list
        self.conversations_label = wx.StaticText(self, label=self.main_window.i18n.t("conversations"))
        outer_sizer.Add(self.conversations_label, 0, wx.LEFT | wx.TOP, 5)

        self.conversations_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, self.main_window.i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_conversations_context_menu)
        outer_sizer.Add(self.conversations_list, 1, wx.EXPAND | wx.ALL, 5)

        # Search
        self.search_label = wx.StaticText(self, label=self.main_window.i18n.t("search_conversations"))
        outer_sizer.Add(self.search_label, 0, wx.LEFT, 5)

        self.search_field = wx.TextCtrl(self, style=wx.TE_DONTWRAP)
        self.search_field.Bind(wx.EVT_TEXT, self.on_search_query_changed)
        self.search_field.SetAccessible(AccessibleSearchConversations("Ctrl+F"))
        outer_sizer.Add(self.search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Conversation panel (shown when a conversation is open)
        self.conversation_panel = wx.Panel(self)
        conv_sizer = wx.BoxSizer(wx.VERTICAL)

        self.messages_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("messages"))
        conv_sizer.Add(self.messages_label, 0, wx.LEFT | wx.TOP, 5)

        self.messages_list = wx.ListCtrl(self.conversation_panel, style=wx.LC_REPORT)
        self.messages_list.InsertColumn(0, self.main_window.i18n.t("messages"), width=360)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_message_activated)
        conv_sizer.Add(self.messages_list, 1, wx.EXPAND | wx.ALL, 5)

        # Audio controls (hidden by default, shown only when audio is playing)
        self.audio_speed_btn = wx.Button(self.conversation_panel, label=self._format_speed(1.0))
        self.audio_speed_btn.Bind(wx.EVT_BUTTON, self.on_audio_speed_btn)
        conv_sizer.Add(self.audio_speed_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self.audio_speed_btn.Hide()

        self.audio_progress_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("audio_progress_label"))
        conv_sizer.Add(self.audio_progress_label, 0, wx.LEFT, 5)
        self.audio_progress_label.Hide()

        self.audio_slider = wx.Slider(self.conversation_panel, value=0, minValue=0, maxValue=1000)
        self.audio_slider.SetAccessible(AccessibleAudioSlider(self))
        self.audio_slider.Bind(wx.EVT_SLIDER, self.on_audio_slider)
        conv_sizer.Add(self.audio_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        self.audio_slider.Hide()

        # Message input area
        self.message_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("type_message"))
        conv_sizer.Add(self.message_label, 0, wx.LEFT | wx.TOP, 5)

        self.message_field = wx.TextCtrl(self.conversation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP)
        self.message_field.Bind(wx.EVT_TEXT, self.on_change_message_field)
        conv_sizer.Add(self.message_field, 0, wx.EXPAND | wx.ALL, 5)

        self.send_message_btn = wx.Button(self.conversation_panel, label=self.main_window.i18n.t("send_message"))
        conv_sizer.Add(self.send_message_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self.send_message_btn.Hide()

        self.record_voice_message_btn = wx.Button(self.conversation_panel, label=self.main_window.i18n.t("record_voice_message"))
        self.record_voice_message_btn.SetAccessible(AccessibleRecordVoiceMessage("Ctrl+R"))
        self.record_voice_message_btn.Bind(wx.EVT_BUTTON, self.on_record_voice_message)
        conv_sizer.Add(self.record_voice_message_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self.conversation_panel.SetSizer(conv_sizer)
        self.conversation_panel.Hide()
        outer_sizer.Add(self.conversation_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(outer_sizer)

    def on_conversation_selected(self, event):
        index = event.GetIndex()
        try:
            self.navigate_to_conversation(self.chats_list[index])
        except Exception:
            return

    def navigate_to_conversation(self, conversation):
        # Stop any playing audio before switching conversations
        self._stop_audio()
        self._hide_audio_controls()
        self.conversation = conversation
        self.conversation_name = (
            self.main_window._resolve_contact_name(conversation)
            or self.main_window.find_name_through_messages(conversation)
            or conversation.get("pushName", "")
            or self.main_window.find_jid_through_messages(conversation)
            or format_number(conversation.get("remoteJid", ""))
        )
        self.message_label.SetLabel(f"{self.main_window.i18n.t('type_message')} {self.conversation_name}")
        self.conversation_panel.Show()
        self.Layout()
        self.preselect_messages()
        self.message_field.SetFocus()
        #Mark conversation as read in background
        self.mark_as_read_thread = threading.Thread(target=self.main_window.mark_conversation_as_read, args=(self.conversation.get("remoteJid", ""),), daemon=True)
        self.mark_as_read_thread.start()
        #Clear the conversation search field if it has text
        if self.search_field.GetValue().strip():
            self.search_field.Clear()
        # Populate messages list from local store
        self.populate_messages()

    def preselect_messages(self):
        self.messages_list.Focus(0)
        self.messages_list.Select(0)

    def create_accelerator_table(self):
        self.ID_CTRL_F = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('F'), self.ID_CTRL_F)
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_ctrl_f, id=self.ID_CTRL_F)

    def create_accel_conversation(self):
        self.ID_CTRL_R = wx.NewIdRef()
        self.ID_ESC = wx.NewIdRef()
        self.CTRL_W = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('R'), self.ID_CTRL_R),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.ID_ESC),
            (wx.ACCEL_CTRL, ord('W'), self.CTRL_W)
        ])
        self.conversation_panel.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message, id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.ID_ESC)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.CTRL_W)

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

        # Conversations section
        self.conversations_label.SetLabel(i18n.t("conversations"))
        col = wx.ListItem()
        col.SetText(i18n.t("conversations"))
        self.conversations_list.SetColumn(0, col)

        self.search_label.SetLabel(i18n.t("search_conversations"))

        # Conversation panel
        self.messages_label.SetLabel(i18n.t("messages"))
        col2 = wx.ListItem()
        col2.SetText(i18n.t("messages"))
        self.messages_list.SetColumn(0, col2)

        self.audio_progress_label.SetLabel(i18n.t("audio_progress_label"))

        # Message label: keep conversation name if a conversation is open
        if self.conversation is not None and self.conversation_panel.IsShown():
            if hasattr(self, "conversation_name") and self.conversation_name:
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
        self.conversation_panel.Hide()
        self.Layout()
        self.conversations_list.SetFocus()

    def on_conversations_context_menu(self, event):
        selected_index = self.conversations_list.GetFirstSelected()
        if selected_index == -1:
            return
        menu = wx.Menu()
        close_item = menu.Append(wx.ID_ANY, f"{self.main_window.i18n.t('close_conversation')}\tCtrl+W")
        self.Bind(wx.EVT_MENU, self.on_context_menu_close, close_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_context_menu_close(self, event):
        if self.conversation_panel.IsShown():
            self.close_conversation(event)

    # ── Audio playback ──────────────────────────────────────────────────────

    def on_message_activated(self, event):
        index = event.GetIndex()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if msg.get("messageType") != "audioMessage":
            return
        msg_id = msg.get("key", {}).get("id", "")
        duration = msg.get("message", {}).get("audioMessage", {}).get("seconds", 0) or 0
        self._toggle_audio(msg_id, duration, msg)

    def _toggle_audio(self, msg_id, duration_seconds, msg=None):
        # Same audio: toggle play/pause
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

        # Different audio: stop current and load new one
        self._stop_audio()
        audio_path = data_path("voice_messages", f"{msg_id}.msv")
        if os.path.isfile(audio_path):
            self._play_audio(msg_id, duration_seconds)
        else:
            self.main_window.output(self.main_window.i18n.t("downloading"))
            def download_and_play():
                if msg is not None:
                    self.main_window.handle_audio_message(msg)
                wx.CallAfter(self._play_audio, msg_id, duration_seconds)
            t = threading.Thread(target=download_and_play, daemon=True)
            t.start()

    def _play_audio(self, msg_id, duration_seconds):
        audio_path = data_path("voice_messages", f"{msg_id}.msv")
        if not os.path.isfile(audio_path):
            return
        try:
            with open(audio_path, "rb") as f:
                encrypted = f.read()
            audio_bytes = decrypt_bytes(encrypted, self.main_window.key)
            # Write decrypted bytes to a temp file (BASS requires a file path)
            tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            self._audio_temp_file = tmp.name
            # decode=True is required for effects to work
            self._audio_stream = sl_stream.FileStream(file=self._audio_temp_file, decode=True)
            self._audio_tempo_ctrl = Tempo(self._audio_stream)
            self._audio_tempo_ctrl.tempo = 0  # default 1.0×
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
            pos = self._audio_stream.get_position()
            total = self._audio_stream.get_length()
            if total > 0:
                # Detect end of playback
                if pos >= total:
                    self._stop_audio()
                    self._hide_audio_controls()
                    return
                slider_val = int(pos / total * 1000)
                self.audio_slider.SetValue(slider_val)
                # Notify accessibility layer of the updated position
                self.audio_slider.Refresh()
        except Exception:
            pass

    def on_audio_speed_btn(self, event):
        self._audio_speed_index = (self._audio_speed_index + 1) % len(self._audio_speed_steps)
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
            val = self.audio_slider.GetValue()  # 0–1000
            total = self._audio_stream.get_length()
            new_pos = int(val / 1000 * total)
            self._audio_stream.set_position(new_pos)
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
        decimal_sep = self.main_window.i18n.t("decimal_separator")
        return f"{speed:.1f}".replace(".", decimal_sep) + "×"

    # ── Message helpers ─────────────────────────────────────────────────────

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
            dt = datetime.fromtimestamp(int(ts))
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
            if seconds == 1:
                return f"{seconds} {i18n.t('second')}"
            else:
                return f"{seconds} {i18n.t('seconds')}"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            min_str = i18n.t("minute") if minutes == 1 else i18n.t("minutes")
            sec_str = i18n.t("second") if secs == 1 else i18n.t("seconds")
            return f"{minutes} {min_str} {i18n.t('and')} {secs} {sec_str}"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            hour_str = i18n.t("hour") if hours == 1 else i18n.t("hours")
            min_str = i18n.t("minute") if minutes == 1 else i18n.t("minutes")
            sec_str = i18n.t("second") if secs == 1 else i18n.t("seconds")
            return f"{hours} {hour_str}, {minutes} {min_str} {i18n.t('and')} {secs} {sec_str}"

    def _get_message_content(self, msg):
        message_type = msg.get("messageType", "conversation")
        message_obj = msg.get("message") or {}

        if not isinstance(message_obj, dict):
            return self.main_window.i18n.t("unsupported_message").format(app_name=self.main_window.app_name)

        i18n = self.main_window.i18n

        if message_type == "audioMessage":
            audio_msg = message_obj.get("audioMessage", {})
            if isinstance(audio_msg, dict):
                duration = audio_msg.get("seconds")
                duration_str = self._format_duration(duration)
                return f"{i18n.t('message_type_audio')}, {i18n.t('duration')}: {duration_str}"
            return i18n.t("message_type_audio")
        elif message_type == "conversation":
            return message_obj.get("conversation", "")
        else:
            return i18n.t("unsupported_message").format(app_name=self.main_window.app_name)

    def _map_status(self, msg):
        i18n = self.main_window.i18n
        updates = msg.get("MessageUpdate")
        if isinstance(updates, list) and len(updates) > 0:
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

    def populate_messages(self):
        self.messages_list.DeleteAllItems()
        messages_container = self.conversation.get("messages", {}) if self.conversation else {}
        messages = []
        if isinstance(messages_container, dict):
            inner = messages_container.get("messages")
            if isinstance(inner, dict) and isinstance(inner.get("records"), list):
                messages = inner.get("records", [])
        try:
            messages_sorted = sorted(messages, key=lambda m: self._extract_timestamp(m) or 0)
        except Exception:
            messages_sorted = messages

        # Exclude reaction messages — they are not displayed and must not affect index mapping
        displayable = [m for m in messages_sorted if m.get("messageType", "") != "reactionMessage"]
        self._sorted_messages = displayable

        for msg in displayable:
            ts = self._extract_timestamp(msg)
            time_str = self._format_date(ts) if ts else ""
            body = self._get_message_content(msg)
            if msg.get("key", {}).get("fromMe"):
                sender_label = self.main_window.i18n.t("sender_you")
            else:
                sender_label = msg.get("pushName", "") if not msg.get("pushName", "").isdigit() else format_number(msg.get("key", {}).get("", "") if msg.get("key", {}).get("addressingMode", "") == "lid" else msg.get("key", {}).get("remoteJid", ""))
            status = self._map_status(msg)
            body = (body or "").replace("\n", " ")
            pieces = [f"{sender_label}: {body}"]
            if time_str:
                pieces.append(f", {time_str}")
            if status:
                pieces[-1] = pieces[-1] + f", {status}"
            line = " ".join(pieces)
            self.messages_list.Append((line,))
