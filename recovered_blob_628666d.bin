import base64 as _b64
import mimetypes
import os
import re
import tempfile
import threading
import time
import uuid
import wx
import wx.adv
import numpy as np
import pyperclip
import sounddevice as sd
import soundfile as sf
import sound_lib.stream as sl_stream
from sound_lib.effects import Tempo
from ui.accessible import (
    AccessibleSearchConversations,
    AccessibleRecordVoiceMessage,
    AccessibleAudioSlider,
    AccessibleSaveAs,
    AccessibleConversationDataButton,
    AccessibleAddAttachmentButton,
    AccessibleDiscardVoiceMessage,
    AccessiblePauseResumeRecording,
    AccessibleSendVoiceMessage,
    AccessibleSearchInConversation,
    AccessibleSearchNextResult,
    AccessibleSearchPrevResult,
    AccessibleNewConversationButton,
)
from core.utils import format_number, decrypt_bytes
from app_paths import data_path
from core.message_queue import PendingMessage
from datetime import datetime

# Compiled URL regex used for link extraction from message text
_URL_RE = re.compile(r'https?://\S+|www\.\S+')


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
        self._audio_speed_steps = [1.0, 1.5, 2.0]
        self._audio_tempo_map = {1.0: 0, 1.5: 50, 2.0: 100}
        # Restore the last-used speed from settings (persists across conversations/sessions)
        _saved_speed = self.main_window.settings.get("general", {}).get("audio_default_speed", 1.0)
        try:
            self._audio_speed_index = self._audio_speed_steps.index(float(_saved_speed))
        except (ValueError, TypeError):
            self._audio_speed_index = 0
        self._audio_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_audio_timer, self._audio_timer)

        # ── Voice recording state ───────────────────────────────────────────
        self._is_recording         = False
        self._recording_paused     = False
        self._recording_frames: list = []   # list of numpy arrays from callback
        self._recording_stream     = None   # sd.InputStream
        # Actual rate/channels are resolved at open time (stereo → mono fallback).
        self._recording_actual_rate: int = 48000
        self._recording_actual_ch:   int = 1

        # ── Attachment staging ──────────────────────────────────────────────
        # list of {"path": str, "media_type": str}
        self._staged_attachments: list = []

        # ── Contact message state ───────────────────────────────────────────
        self._contact_msg_jid: str | None = None  # JID in currently-selected contactMessage

        # ── Edit message state ──────────────────────────────────────────────
        self._editing_message_id: str | None = None    # key.id of msg being edited
        self._editing_message_index: int = -1          # list row index

        # ── Media download progress ─────────────────────────────────────────
        # msg_id -> float 0.0-1.0  (absent = not tracked / already complete)
        self._download_progress: dict = {}

        # ── Unread separator ────────────────────────────────────────────────
        # Index in _sorted_messages of the unread-separator sentinel, or -1
        self._unread_sep_idx: int = -1

        # ── Reaction tracking ───────────────────────────────────────────────
        # Maps original_msg_id → {emoji: count}
        self._reaction_map: dict = {}

        # ── Reply / quoted message state ────────────────────────────────────
        # When not None, the next sent message will be a quoted reply
        self._quoted_message: dict | None = None

        # ── Search in conversation state ─────────────────────────────────────
        # Indices in _sorted_messages that match the current search query
        self._search_results: list = []
        # Current position in _search_results (-1 = no active navigation)
        self._search_result_idx: int = -1

        # ── Link extraction state ────────────────────────────────────────────
        # URLs found in the currently focused message
        self._current_links: list = []

        # ── Lazy-loading / pagination state ─────────────────────────────────
        # Full sorted+displayable list (never paginated)
        self._all_sorted_messages: list = []
        # How many messages from _all_sorted_messages are before _sorted_messages[0]
        self._messages_offset: int = 0
        # Guard to prevent recursive load-more triggers during list rebuild
        self._is_loading_more: bool = False

        self.init_UI()
        self.create_accelerator_table()
        self.create_accel_conversation()

    # ── UI ──────────────────────────────────────────────────────────────────

    def init_UI(self):
        i18n = self.main_window.i18n
        outer_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Search ──────────────────────────────────────────────────────────
        self.search_label = wx.StaticText(self, label=i18n.t("search_conversations"))
        outer_sizer.Add(self.search_label, 0, wx.LEFT | wx.TOP, 5)

        self.search_field = wx.TextCtrl(self, style=wx.TE_DONTWRAP)
        self.search_field.Bind(wx.EVT_TEXT, self.on_search_query_changed)
        self.search_field.SetAccessible(AccessibleSearchConversations("Ctrl+F"))
        outer_sizer.Add(self.search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # ── Nova conversa button ────────────────────────────────────────────
        self._new_conv_btn = wx.Button(self, label=i18n.t("new_conversation"))
        self._new_conv_btn.SetAccessible(AccessibleNewConversationButton())
        self._new_conv_btn.Bind(wx.EVT_BUTTON, self._on_new_conversation)
        outer_sizer.Add(self._new_conv_btn, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 5)

        # ── Conversations list ──────────────────────────────────────────────
        self.conversations_label = wx.StaticText(self, label=i18n.t("conversations"))
        outer_sizer.Add(self.conversations_label, 0, wx.LEFT, 5)

        self.conversations_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversations_list.Bind(wx.EVT_CONTEXT_MENU, self.on_conversations_context_menu)
        self.conversations_list.Bind(wx.EVT_KEY_DOWN, self._on_conv_list_key_down)
        outer_sizer.Add(self.conversations_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Conversation panel ──────────────────────────────────────────────
        self.conversation_panel = wx.Panel(self)
        conv_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Conversation / group data button ───────────────────────────────
        self._conv_data_btn = wx.adv.CommandLinkButton(
            self.conversation_panel,
            mainLabel=i18n.t("conversation_data"),
            note="",
        )
        self._conv_data_btn.SetAccessible(AccessibleConversationDataButton())
        self._conv_data_btn.Bind(wx.EVT_BUTTON, self._show_conversation_data)
        conv_sizer.Add(self._conv_data_btn, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # ── Add attachment button (before messages list for easy keyboard reach) ─
        self._add_attachment_btn = wx.Button(
            self.conversation_panel, label=i18n.t("add_attachment")
        )
        self._add_attachment_btn.SetAccessible(AccessibleAddAttachmentButton())
        self._add_attachment_btn.Bind(wx.EVT_BUTTON, self.on_add_attachment)
        conv_sizer.Add(self._add_attachment_btn, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        # ── Search in conversation button ───────────────────────────────────
        self._search_open_btn = wx.Button(
            self.conversation_panel, label=i18n.t("search_in_conv")
        )
        self._search_open_btn.SetAccessible(AccessibleSearchInConversation())
        self._search_open_btn.Bind(wx.EVT_BUTTON, self._on_open_search)
        conv_sizer.Add(self._search_open_btn, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        # ── Search panel (hidden by default) ───────────────────────────────
        self._search_panel = wx.Panel(self.conversation_panel)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._search_close_btn = wx.Button(self._search_panel, label=i18n.t("search_close"))
        self._search_close_btn.Bind(wx.EVT_BUTTON, self._on_close_search)
        search_sizer.Add(self._search_close_btn, 0, wx.RIGHT, 5)

        self._search_field_label = wx.StaticText(self._search_panel, label=i18n.t("search_in_conv"))
        search_sizer.Add(self._search_field_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self._search_field = wx.TextCtrl(self._search_panel, style=wx.TE_DONTWRAP | wx.TE_PROCESS_ENTER)
        self._search_field.Bind(wx.EVT_TEXT, self._on_search_text_changed)
        self._search_field.Bind(wx.EVT_KEY_DOWN, self._on_search_key_down)
        search_sizer.Add(self._search_field, 1, wx.EXPAND | wx.RIGHT, 5)

        self._search_prev_btn = wx.Button(self._search_panel, label=i18n.t("search_prev_result"))
        self._search_prev_btn.SetAccessible(AccessibleSearchPrevResult())
        self._search_prev_btn.Bind(wx.EVT_BUTTON, self._on_search_prev)
        search_sizer.Add(self._search_prev_btn, 0, wx.RIGHT, 5)

        self._search_next_btn = wx.Button(self._search_panel, label=i18n.t("search_next_result"))
        self._search_next_btn.SetAccessible(AccessibleSearchNextResult())
        self._search_next_btn.Bind(wx.EVT_BUTTON, self._on_search_next)
        search_sizer.Add(self._search_next_btn, 0)

        self._search_panel.SetSizer(search_sizer)
        self._search_panel.Hide()
        conv_sizer.Add(self._search_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.messages_label = wx.StaticText(
            self.conversation_panel, label=i18n.t("messages")
        )
        conv_sizer.Add(self.messages_label, 0, wx.LEFT | wx.TOP, 5)

        self.messages_list = wx.ListCtrl(self.conversation_panel, style=wx.LC_REPORT)
        self.messages_list.InsertColumn(0, i18n.t("messages"), width=360)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_message_activated)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_FOCUSED, self._on_message_focused)
        self.messages_list.Bind(wx.EVT_CONTEXT_MENU, self.on_messages_context_menu)
        self.messages_list.Bind(wx.EVT_KEY_DOWN, self._on_messages_list_key_down)
        conv_sizer.Add(self.messages_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Link controls (shown when focused message contains URLs) ─────────
        self._links_panel = wx.Panel(self.conversation_panel)
        self._links_label = wx.StaticText(
            self._links_panel, label=i18n.t("links_section_label")
        )
        self._links_sizer = wx.BoxSizer(wx.VERTICAL)
        self._links_sizer.Add(self._links_label, 0, wx.LEFT | wx.TOP, 3)
        self._links_panel.SetSizer(self._links_sizer)
        self._links_panel.Hide()
        conv_sizer.Add(self._links_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

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

        # ── Download button (shown when media is not yet cached locally) ───
        self._action_download_btn = wx.Button(
            self.conversation_panel, label=i18n.t("download")
        )
        self._action_download_btn.Bind(wx.EVT_BUTTON, self._on_action_download)
        conv_sizer.Add(self._action_download_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._action_download_btn.Hide()

        # ── Business reply buttons container ───────────────────────────────
        self._buttons_container = wx.Panel(self.conversation_panel)
        self._buttons_container.SetSizer(wx.WrapSizer(wx.HORIZONTAL))
        conv_sizer.Add(
            self._buttons_container, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5
        )
        self._buttons_container.Hide()

        # ── Contact message — Converse button ──────────────────────────────
        self._contact_converse_btn = wx.Button(
            self.conversation_panel, label=i18n.t("converse")
        )
        self._contact_converse_btn.Bind(wx.EVT_BUTTON, self._on_contact_converse)
        conv_sizer.Add(self._contact_converse_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._contact_converse_btn.Hide()

        # ── Audio / video playback controls ────────────────────────────────
        self.audio_speed_btn = wx.Button(
            self.conversation_panel,
            label=self._format_speed(self._audio_speed_steps[self._audio_speed_index]),
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
        self.message_field.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        conv_sizer.Add(self.message_field, 0, wx.EXPAND | wx.ALL, 5)

        self._cancel_edit_btn = wx.Button(
            self.conversation_panel, label=i18n.t("cancel_edit")
        )
        self._cancel_edit_btn.Bind(wx.EVT_BUTTON, self._on_cancel_edit)
        conv_sizer.Add(self._cancel_edit_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._cancel_edit_btn.Hide()

        self._remove_quote_btn = wx.Button(
            self.conversation_panel, label=i18n.t("remove_quote")
        )
        self._remove_quote_btn.Bind(wx.EVT_BUTTON, self._on_cancel_reply)
        conv_sizer.Add(self._remove_quote_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._remove_quote_btn.Hide()

        self.send_message_btn = wx.Button(
            self.conversation_panel, label=i18n.t("send_message")
        )
        self.send_message_btn.Bind(wx.EVT_BUTTON, self.on_send_message)
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

        # ── Attachment staging panel (hidden until files are chosen) ─────────
        self._attachment_panel = wx.Panel(self.conversation_panel)
        attach_sizer = wx.BoxSizer(wx.VERTICAL)

        # Dynamic list of "Remover anexo <filename>" buttons, rebuilt on every change
        self._attachments_list_panel = wx.Panel(self._attachment_panel)
        self._attachments_list_sizer = wx.BoxSizer(wx.VERTICAL)
        self._attachments_list_panel.SetSizer(self._attachments_list_sizer)
        attach_sizer.Add(self._attachments_list_panel, 0, wx.EXPAND | wx.LEFT | wx.TOP, 5)

        self._add_more_btn = wx.Button(
            self._attachment_panel, label=i18n.t("add_more_files")
        )
        self._add_more_btn.Bind(wx.EVT_BUTTON, self._on_add_more_files)
        attach_sizer.Add(self._add_more_btn, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        self._caption_label = wx.StaticText(
            self._attachment_panel, label=i18n.t("attachment_caption_hint")
        )
        attach_sizer.Add(self._caption_label, 0, wx.LEFT | wx.TOP, 5)

        self._caption_field = wx.TextCtrl(
            self._attachment_panel,
            style=wx.TE_DONTWRAP | wx.TE_PROCESS_ENTER,
        )
        self._caption_field.SetHint(i18n.t("attachment_caption_hint"))
        self._caption_field.Bind(wx.EVT_TEXT_ENTER, self._on_send_attachment)
        attach_sizer.Add(self._caption_field, 0, wx.EXPAND | wx.ALL, 5)

        self._send_attachment_btn = wx.Button(
            self._attachment_panel, label=i18n.t("send_attachment")
        )
        self._send_attachment_btn.Bind(wx.EVT_BUTTON, self._on_send_attachment)
        attach_sizer.Add(self._send_attachment_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._attachment_panel.SetSizer(attach_sizer)
        self._attachment_panel.Hide()
        conv_sizer.Add(self._attachment_panel, 0, wx.EXPAND | wx.ALL, 5)

        # ── Voice recording panel (hidden until recording starts) ───────────
        self._voice_panel = wx.Panel(self.conversation_panel)
        voice_sizer = wx.BoxSizer(wx.VERTICAL)

        self._discard_voice_btn = wx.Button(
            self._voice_panel, label=i18n.t("discard_voice_message")
        )
        self._discard_voice_btn.SetAccessible(AccessibleDiscardVoiceMessage())
        self._discard_voice_btn.Bind(wx.EVT_BUTTON, self._discard_voice_message)
        voice_sizer.Add(self._discard_voice_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._pause_resume_btn = wx.Button(
            self._voice_panel, label=i18n.t("pause_recording")
        )
        self._pause_resume_btn.SetAccessible(AccessiblePauseResumeRecording())
        self._pause_resume_btn.Bind(wx.EVT_BUTTON, self._toggle_pause_recording)
        voice_sizer.Add(self._pause_resume_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._send_voice_btn = wx.Button(
            self._voice_panel, label=i18n.t("send_voice_message")
        )
        self._send_voice_btn.SetAccessible(AccessibleSendVoiceMessage())
        self._send_voice_btn.Bind(wx.EVT_BUTTON, self._send_voice_message)
        voice_sizer.Add(self._send_voice_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._voice_panel.SetSizer(voice_sizer)
        self._voice_panel.Hide()
        conv_sizer.Add(self._voice_panel, 0, wx.LEFT | wx.BOTTOM, 5)

        self.conversation_panel.SetSizer(conv_sizer)
        self.conversation_panel.Hide()
        outer_sizer.Add(self.conversation_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(outer_sizer)

    # ── Accelerators ────────────────────────────────────────────────────────

    def create_accelerator_table(self):
        self.ID_CTRL_F = wx.NewIdRef()
        self.ID_CTRL_N = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("F"), self.ID_CTRL_F),
            (wx.ACCEL_CTRL, ord("N"), self.ID_CTRL_N),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_ctrl_f,           id=self.ID_CTRL_F)
        self.Bind(wx.EVT_MENU, self._on_new_conversation, id=self.ID_CTRL_N)

    def create_accel_conversation(self):
        # ── Navigation / recording ──────────────────────────────────────────
        self.ID_CTRL_R          = wx.NewIdRef()  # record voice            (Ctrl+R)
        self.ID_ALT_2           = wx.NewIdRef()  # jump to last message    (Alt+2)
        self.ID_ESC             = wx.NewIdRef()  # close conversation      (Esc)
        self.CTRL_W             = wx.NewIdRef()  # close conversation      (Ctrl+W)
        self.ID_CTRL_SHIFT_D    = wx.NewIdRef()  # conv data / discard     (Ctrl+Shift+D)
        # ── Attachment / media ───────────────────────────────────────────────
        self.ID_CTRL_SHIFT_A    = wx.NewIdRef()  # add attachment          (Ctrl+Shift+A)
        self.ID_CTRL_SHIFT_B    = wx.NewIdRef()  # save as / download      (Ctrl+Shift+B)
        # ── Message-level ────────────────────────────────────────────────────
        self.ID_ALT_R           = wx.NewIdRef()  # reply                   (Alt+R)
        self.ID_ALT_SHIFT_D     = wx.NewIdRef()  # message data            (Alt+Shift+D)
        self.ID_CTRL_SHIFT_E    = wx.NewIdRef()  # forward                 (Ctrl+Shift+E)
        self.ID_CTRL_SHIFT_P    = wx.NewIdRef()  # pause/resume OR delete  (Ctrl+Shift+P)
        self.ID_CTRL_C          = wx.NewIdRef()  # copy message            (Ctrl+C)
        self.ID_ALT_C           = wx.NewIdRef()  # show text popup         (Alt+C)
        # ── Conversation-level ───────────────────────────────────────────────
        self.ID_CTRL_SHIFT_S    = wx.NewIdRef()  # mute / unmute           (Ctrl+Shift+S)
        self.ID_CTRL_SHIFT_M    = wx.NewIdRef()  # mark as read            (Ctrl+Shift+M)
        # ── Search / unread jump ─────────────────────────────────────────────
        self.ID_CTRL_SHIFT_F    = wx.NewIdRef()  # open search panel       (Ctrl+Shift+F)
        self.ID_ALT_3           = wx.NewIdRef()  # jump to unread sep      (Alt+3)
        # ── Conv-list shortcuts ───────────────────────────────────────────────
        self.ID_CONV_PIN        = wx.NewIdRef()  # pin / unpin chat        (Ctrl+P)
        self.ID_CONV_ARCHIVE    = wx.NewIdRef()  # archive / unarchive     (Ctrl+Q)
        # ── Group actions ────────────────────────────────────────────────────
        self.ID_ALT_SHIFT_R     = wx.NewIdRef()  # reply privately         (Alt+Shift+R)
        self.ID_ALT_SHIFT_C     = wx.NewIdRef()  # goto quoted message     (Alt+Shift+C)
        self.ID_ALT_SHIFT_V     = wx.NewIdRef()  # converse with           (Alt+Shift+V)

        CS = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
        AS = wx.ACCEL_ALT  | wx.ACCEL_SHIFT
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL,    ord("R"),        self.ID_CTRL_R),
            (wx.ACCEL_ALT,     ord("2"),        self.ID_ALT_2),
            (wx.ACCEL_NORMAL,  wx.WXK_ESCAPE,   self.ID_ESC),
            (wx.ACCEL_CTRL,    ord("W"),         self.CTRL_W),
            (CS,               ord("D"),         self.ID_CTRL_SHIFT_D),
            (CS,               ord("A"),         self.ID_CTRL_SHIFT_A),
            (CS,               ord("B"),         self.ID_CTRL_SHIFT_B),
            (wx.ACCEL_ALT,     ord("R"),         self.ID_ALT_R),
            (AS,               ord("D"),         self.ID_ALT_SHIFT_D),
            (CS,               ord("E"),         self.ID_CTRL_SHIFT_E),
            (CS,               ord("P"),         self.ID_CTRL_SHIFT_P),
            (wx.ACCEL_CTRL,    ord("C"),         self.ID_CTRL_C),
            (wx.ACCEL_ALT,     ord("C"),         self.ID_ALT_C),
            (CS,               ord("S"),         self.ID_CTRL_SHIFT_S),
            (CS,               ord("M"),         self.ID_CTRL_SHIFT_M),
            (CS,               ord("F"),         self.ID_CTRL_SHIFT_F),
            (wx.ACCEL_ALT,     ord("3"),         self.ID_ALT_3),
            (AS,               ord("R"),         self.ID_ALT_SHIFT_R),
            (AS,               ord("C"),         self.ID_ALT_SHIFT_C),
            (AS,               ord("V"),         self.ID_ALT_SHIFT_V),
        ])
        self.conversation_panel.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message,   id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self._on_accel_jump_last,       id=self.ID_ALT_2)
        self.Bind(wx.EVT_MENU, self.close_conversation,        id=self.ID_ESC)
        self.Bind(wx.EVT_MENU, self.close_conversation,        id=self.CTRL_W)
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_d,          id=self.ID_CTRL_SHIFT_D)
        self.Bind(wx.EVT_MENU, self.on_add_attachment,         id=self.ID_CTRL_SHIFT_A)
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_s,          id=self.ID_CTRL_SHIFT_B)   # save as
        self.Bind(wx.EVT_MENU, self._on_accel_reply,           id=self.ID_ALT_R)
        self.Bind(wx.EVT_MENU, self._on_accel_message_data,    id=self.ID_ALT_SHIFT_D)
        self.Bind(wx.EVT_MENU, self._on_accel_forward,         id=self.ID_CTRL_SHIFT_E)
        # Ctrl+Shift+P: pause/resume when recording, delete message otherwise
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_p,          id=self.ID_CTRL_SHIFT_P)
        self.Bind(wx.EVT_MENU, self._on_accel_copy_message,    id=self.ID_CTRL_C)
        self.Bind(wx.EVT_MENU, self._on_accel_show_text_popup, id=self.ID_ALT_C)
        self.Bind(wx.EVT_MENU, self._on_accel_mute,            id=self.ID_CTRL_SHIFT_S)
        self.Bind(wx.EVT_MENU, self._on_accel_mark_read,       id=self.ID_CTRL_SHIFT_M)
        self.Bind(wx.EVT_MENU, self._on_accel_open_search,     id=self.ID_CTRL_SHIFT_F)
        self.Bind(wx.EVT_MENU, self._on_accel_jump_unread,     id=self.ID_ALT_3)
        self.Bind(wx.EVT_MENU, self._on_accel_reply_private,   id=self.ID_ALT_SHIFT_R)
        self.Bind(wx.EVT_MENU, self._on_accel_alt_shift_c,     id=self.ID_ALT_SHIFT_C)
        self.Bind(wx.EVT_MENU, self._on_accel_alt_shift_v,     id=self.ID_ALT_SHIFT_V)

    # ── Conversations list events ───────────────────────────────────────────

    def on_conversation_selected(self, event):
        self.on_conversation_selected_by_index(event.GetIndex())

    def on_conversation_selected_by_index(self, index):
        try:
            self.navigate_to_conversation(self.chats_list[index])
        except Exception:
            return

    def navigate_to_conversation(self, conversation):
        self._stop_audio()
        self._hide_audio_controls()
        self._hide_all_media_controls()
        self._hide_attachment_panel()
        self._unread_sep_idx = -1  # reset separator for new conversation
        self._quoted_message = None
        self._reaction_map   = {}
        # Reset search state
        self._search_results    = []
        self._search_result_idx = -1
        if hasattr(self, "_search_panel") and self._search_panel.IsShown():
            self._search_panel.Hide()
            self._search_open_btn.Show()
            self._search_field.SetValue("")
        self.conversation = conversation
        self.conversation_name = (
            self.main_window._resolve_contact_name(conversation)
            or self.main_window.find_name_through_messages(conversation)
            or conversation.get("pushName", "")
            or self.main_window.find_jid_through_messages(conversation)
            or format_number(conversation.get("remoteJid", ""))
        )
        jid      = conversation.get("remoteJid", "")
        is_group = jid.endswith("@g.us")
        i18n     = self.main_window.i18n

        # Update conversation-data button
        self._conv_data_btn.SetLabel(
            i18n.t("group_data") if is_group else i18n.t("conversation_data")
        )
        self._conv_data_btn.SetNote(self.conversation_name)

        self.message_label.SetLabel(
            f"{i18n.t('type_message_group') if is_group else i18n.t('type_message')} {self.conversation_name}"
        )
        if hasattr(self, "_remove_quote_btn"):
            self._remove_quote_btn.Hide()
        self.conversation_panel.Show()
        self.Layout()
        self.preselect_messages()
        threading.Thread(
            target=self.main_window.mark_conversation_as_read,
            args=(jid,),
            daemon=True,
        ).start()
        # Background: fetch profile/last-seen and update button note
        threading.Thread(
            target=self._fetch_and_update_profile,
            args=(conversation,),
            daemon=True,
        ).start()
        if self.search_field.GetValue().strip():
            self.search_field.Clear()
        self.populate_messages()

        # Set focus based on user preference
        focus_setting = self.main_window.settings.get("ui", {}).get("focus_on_open", "message_field")
        if focus_setting == "unread_or_last":
            if self._unread_sep_idx < 0:
                # No unread separator — focus on last message
                last = self.messages_list.GetItemCount() - 1
                if last >= 0:
                    self.messages_list.Focus(last)
                    self.messages_list.Select(last, True)
                    self.messages_list.EnsureVisible(last)
            # else: populate_messages already made the separator visible
        else:
            self.message_field.SetFocus()

    def preselect_messages(self):
        self.messages_list.Focus(0)
        self.messages_list.Select(0)

    def on_search_query_changed(self, event):
        query    = self.search_field.GetValue().lower()
        mw       = self.main_window
        deleted  = set(mw.settings.get("deleted_chats",  []))
        archived = set(mw.settings.get("archived_chats", []))

        self.chats_list = []
        self.chat_names = []
        self.conversations_list.DeleteAllItems()

        for jid, chat in mw.chats.items():
            if jid in deleted or jid in archived:
                continue
            name = (
                mw._resolve_contact_name(chat)
                or mw.find_name_through_messages(chat)
                or chat.get("pushName", "")
                or mw.find_jid_through_messages(chat)
                or format_number(jid)
            )
            if not query or query in name.lower():
                self.conversations_list.Append((name,))
                self.chats_list.append(chat)
                self.chat_names.append(name)
        mw.preselect_conversations()

    def on_ctrl_f(self, event):
        self.search_field.SetFocus()

    def on_change_message_field(self, event):
        # Don't touch button visibility while recording or staging attachments.
        if self._is_recording or self._attachment_panel.IsShown():
            return
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

        self._new_conv_btn.SetLabel(i18n.t("new_conversation"))
        self._search_open_btn.SetLabel(i18n.t("search_in_conv"))
        self._search_close_btn.SetLabel(i18n.t("search_close"))
        self._search_field_label.SetLabel(i18n.t("search_in_conv"))
        self._search_prev_btn.SetLabel(i18n.t("search_prev_result"))
        self._search_next_btn.SetLabel(i18n.t("search_next_result"))

        self.messages_label.SetLabel(i18n.t("messages"))
        col2 = wx.ListItem()
        col2.SetText(i18n.t("messages"))
        self.messages_list.SetColumn(0, col2)

        self.audio_progress_label.SetLabel(i18n.t("audio_progress_label"))
        self._action_save_as_btn.SetLabel(i18n.t("save_as"))
        self._action_download_btn.SetLabel(i18n.t("download"))

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
        self._cancel_edit_btn.SetLabel(i18n.t("cancel_edit"))
        if hasattr(self, "_remove_quote_btn"):
            self._remove_quote_btn.SetLabel(i18n.t("remove_quote"))
        self.record_voice_message_btn.SetLabel(i18n.t("record_voice_message"))
        self._add_attachment_btn.SetLabel(i18n.t("add_attachment"))
        self._add_more_btn.SetLabel(i18n.t("add_more_files"))
        self._caption_label.SetLabel(i18n.t("attachment_caption_hint"))
        self._send_attachment_btn.SetLabel(i18n.t("send_attachment"))
        self._contact_converse_btn.SetLabel(i18n.t("converse"))
        self._discard_voice_btn.SetLabel(i18n.t("discard_voice_message"))
        self._send_voice_btn.SetLabel(i18n.t("send_voice_message"))
        if self._is_recording and self._recording_paused:
            self._pause_resume_btn.SetLabel(i18n.t("resume_recording"))
        else:
            self._pause_resume_btn.SetLabel(i18n.t("pause_recording"))
        # Update conv-data button label
        if self.conversation is not None:
            jid = self.conversation.get("remoteJid", "")
            self._conv_data_btn.SetLabel(
                i18n.t("group_data") if jid.endswith("@g.us")
                else i18n.t("conversation_data")
            )

    def on_record_voice_message(self, event):
        """
        Ctrl+R / button handler.
        • When NOT recording → start a new voice recording.
        • When recording is active → send the recorded audio (same shortcut).
        """
        if self._is_recording:
            self._send_voice_message(event)
        else:
            self._start_voice_recording()

    # ── Text message sending ─────────────────────────────────────────────────

    def on_send_message(self, event):
        """Send button handler: enqueue message, add to UI immediately as pending.
        If in edit mode, instead calls the edit API and updates the existing message."""
        if self.conversation is None:
            return
        text = self.message_field.GetValue().strip()
        if not text:
            return
        remote_jid = self.conversation.get("remoteJid", "")
        if not remote_jid:
            return

        # ── Edit mode: update existing message ──────────────────────────────
        if self._editing_message_id is not None:
            msg_id = self._editing_message_id
            idx    = self._editing_message_index

            # Call Evolution API to update the message
            self.main_window.edit_message(remote_jid, msg_id, text)

            # Update local state
            if 0 <= idx < len(self._sorted_messages):
                self._sorted_messages[idx]["message"] = {"conversation": text}
                self._sorted_messages[idx]["messageType"] = "conversation"
                self.messages_list.SetItemText(
                    idx, self._render_message_line(self._sorted_messages[idx])
                )

            self._on_cancel_edit()
            return

        # ── Normal send ──────────────────────────────────────────────────────
        # Build a virtual message dict that renders identically to real messages.
        local_id = str(uuid.uuid4())
        virtual_msg = {
            "_local_pending": True,
            "_local_id":      local_id,
            "key": {
                "id":       local_id,
                "fromMe":   True,
                "remoteJid": remote_jid,
            },
            "messageType":      "conversation",
            "message":          {"conversation": text},
            "messageTimestamp": int(time.time()),
            "pushName":         "",
        }

        # Add to sorted list and UI list immediately.
        self._sorted_messages.append(virtual_msg)
        self.messages_list.Append((self._render_message_line(virtual_msg),))
        # Scroll to the new item.
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)

        # Clear the text field (this also hides send btn, shows record btn).
        self.message_field.SetValue("")
        self.message_field.SetFocus()

        # Enqueue for background sending (with retry on failure).
        pm = PendingMessage(local_id, remote_jid, text=text, quoted=self._quoted_message)
        self.main_window.message_queue.enqueue(pm)
        self._on_cancel_reply()  # clear quoted state after send

        # Register the virtual message in chat records so the conversation
        # list preview updates immediately to show the sent message.
        self._register_virtual_msg(virtual_msg)
        self.main_window.set_chats()

    def _register_virtual_msg(self, virtual_msg: dict):
        """
        Add a just-sent virtual message to the chat's records dict so that
        _last_msg_preview() can pick it up and set_chats() shows the correct
        preview in the conversation list.

        Because virtual_msg is the *same* Python dict object that sits in
        _sorted_messages, clearing _local_pending later (in _mark_message_sent)
        automatically updates the records entry too.
        """
        remote_jid = virtual_msg.get("key", {}).get("remoteJid", "")
        if not remote_jid:
            return
        chat = self.main_window.chats.get(remote_jid)
        if chat is None:
            return
        records = (
            chat.setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
        )
        local_id = virtual_msg.get("_local_id", "")
        if local_id and any(r.get("_local_id") == local_id for r in records):
            return  # already registered
        records.append(virtual_msg)

    def _mark_message_sent(self, local_id: str):
        """
        Called on the main thread when a queued message is successfully delivered.
        Clears the _local_pending flag, refreshes the list item, plays the
        message-sent sound, and refreshes the conversation list preview.
        """
        for i, msg in enumerate(self._sorted_messages):
            if msg.get("_local_id") == local_id:
                msg["_local_pending"] = False
                self.messages_list.SetItemText(i, self._render_message_line(msg))
                # Play sent sound — fires only when the originating conversation
                # is still the active one (otherwise local_id is not found here).
                if hasattr(self.main_window, "message_sent_sound"):
                    self.main_window.message_sent_sound.play()
                break
        # Refresh conversation list so the preview reflects the sent message.
        self.main_window.set_chats()

    # ── Voice recording ──────────────────────────────────────────────────────

    def _start_voice_recording(self):
        """
        Start capturing audio from the default input device.

        Quality strategy (highest to lowest preference):
          48 000 Hz stereo → 48 000 Hz mono → 44 100 Hz stereo → 44 100 Hz mono

        sounddevice delivers raw, unprocessed PCM — no noise suppression,
        no automatic-gain control, no resampling.  This preserves full voice
        naturalness and quality.
        """
        if self.conversation is None:
            return

        self._recording_frames = []
        self._recording_paused = False

        # Define callback once, outside the loop; captures self for pause check.
        def _callback(indata, frames, t, status):
            # Runs on sounddevice's internal callback thread.
            # list.append is atomic under the GIL — no explicit lock needed.
            if not self._recording_paused:
                self._recording_frames.append(indata.copy())

        # Try each (rate, channels) combination in preference order.
        _configs = [
            (48000, 2),   # 48 kHz stereo — highest quality
            (48000, 1),   # 48 kHz mono   — if device is mono-only
            (44100, 2),   # 44.1 kHz stereo
            (44100, 1),   # 44.1 kHz mono  — last resort
        ]
        opened = False
        for rate, ch in _configs:
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=ch,
                    dtype="float32",   # float32 → best internal precision
                    callback=_callback,
                )
                stream.start()
                self._recording_stream      = stream
                self._recording_actual_rate = rate
                self._recording_actual_ch   = ch
                opened = True
                break
            except Exception:
                self._recording_stream = None

        if not opened:
            return

        self._is_recording = True

        # UI: play sound, swap buttons, focus Discard.
        self.main_window.voicemsg_startrecording_sound.play()
        self.send_message_btn.Hide()
        self.record_voice_message_btn.Hide()
        self._add_attachment_btn.Hide()
        self._pause_resume_btn.SetLabel(
            self.main_window.i18n.t("pause_recording")
        )
        self._voice_panel.Show()
        self.conversation_panel.Layout()
        self._discard_voice_btn.SetFocus()

    def _stop_recording_stream(self):
        """Stop and close the active InputStream (safe to call when None)."""
        if self._recording_stream is not None:
            try:
                self._recording_stream.stop()
                self._recording_stream.close()
            except Exception:
                pass
            self._recording_stream = None

    def _hide_voice_panel(self):
        """Hide the voice panel and restore the record / send button visibility."""
        self._voice_panel.Hide()
        if self.message_field.GetValue().strip():
            self.send_message_btn.Show()
        else:
            self.record_voice_message_btn.Show()
        self._add_attachment_btn.Show()
        self.conversation_panel.Layout()

    def _discard_voice_message(self, event):
        """Discard the current recording without sending."""
        if not self._is_recording:
            return
        self.main_window.voicemsg_discard_sound.play()
        self._stop_recording_stream()
        self._is_recording     = False
        self._recording_paused = False
        self._recording_frames = []
        self._hide_voice_panel()
        self.message_field.SetFocus()

    def _toggle_pause_recording(self, event):
        """Pause or resume the ongoing recording."""
        if not self._is_recording:
            return
        self.main_window.voicemsg_pauserecording_sound.play()
        self._recording_paused = not self._recording_paused
        label_key = "resume_recording" if self._recording_paused else "pause_recording"
        self._pause_resume_btn.SetLabel(self.main_window.i18n.t(label_key))

    def _send_voice_message(self, event):
        """Stop recording and enqueue the audio for delivery."""
        if not self._is_recording:
            return
        self.main_window.voicemsg_send_sound.play()
        self._stop_recording_stream()
        self._is_recording     = False
        self._recording_paused = False

        frames = self._recording_frames
        self._recording_frames = []

        if not frames:
            self._hide_voice_panel()
            self.message_field.SetFocus()
            return

        # Save recording to a temporary WAV file (deleted after successful upload).
        # PCM_16 (16-bit integer) halves the file size vs float32 while remaining
        # perceptually transparent at 48 / 44.1 kHz.
        try:
            audio_data = np.concatenate(frames, axis=0)
            actual_rate = self._recording_actual_rate
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            sf.write(tmp.name, audio_data, actual_rate, subtype="PCM_16")
            wav_path = tmp.name
        except Exception:
            self._hide_voice_panel()
            self.message_field.SetFocus()
            return

        remote_jid   = self.conversation.get("remoteJid", "")
        local_id     = str(uuid.uuid4())
        duration_sec = int(len(audio_data) / self._recording_actual_rate)

        # Virtual message shown immediately as pending in the messages list.
        virtual_msg = {
            "_local_pending": True,
            "_local_id":      local_id,
            "key": {
                "id":        local_id,
                "fromMe":    True,
                "remoteJid": remote_jid,
            },
            "messageType": "audioMessage",
            "message": {
                "audioMessage": {
                    "seconds": duration_sec,
                    "ptt":     True,
                }
            },
            "messageTimestamp": int(time.time()),
            "pushName":         "",
        }
        self._sorted_messages.append(virtual_msg)
        self.messages_list.Append((self._render_message_line(virtual_msg),))
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)

        # Enqueue for background upload.
        pm = PendingMessage(local_id, remote_jid, audio_path=wav_path, quoted=self._quoted_message)
        self.main_window.message_queue.enqueue(pm)
        self._on_cancel_reply()  # clear quoted state after send

        # Register the virtual message so the conversation list preview updates.
        self._register_virtual_msg(virtual_msg)
        self.main_window.set_chats()

        self._hide_voice_panel()
        self.message_field.SetFocus()

    def close_conversation(self, event=None):
        if self._is_recording:
            self._stop_recording_stream()
            self._is_recording     = False
            self._recording_paused = False
            self._recording_frames = []
            self._voice_panel.Hide()
            self.record_voice_message_btn.Show()
        self._stop_audio()
        self._hide_audio_controls()
        self._hide_all_media_controls()
        self._hide_attachment_panel()
        # Clear any active edit state
        if self._editing_message_id is not None:
            self._on_cancel_edit()
        if self._quoted_message is not None:
            self._on_cancel_reply()
        # Clear search state
        self._search_results    = []
        self._search_result_idx = -1
        if hasattr(self, "_search_panel") and self._search_panel.IsShown():
            self._search_panel.Hide()
            self._search_open_btn.Show()
            self._search_field.SetValue("")
        self.conversation = None
        self.conversation_panel.Hide()
        self.Layout()
        self.conversations_list.SetFocus()

    # ── Conversations context menu ──────────────────────────────────────────

    def on_conversations_context_menu(self, event):
        selected_index = self.conversations_list.GetFirstSelected()
        if selected_index == -1:
            return
        try:
            chat = self.chats_list[selected_index]
        except IndexError:
            return
        jid      = chat.get("remoteJid", "")
        is_group = jid.endswith("@g.us")
        mw       = self.main_window
        i18n     = mw.i18n

        menu = wx.Menu()

        # ── Conversation / group data ─────────────────────────────────────
        data_label = i18n.t("group_data") if is_group else i18n.t("conversation_data")
        data_item = menu.Append(wx.ID_ANY, f"{data_label}\tCtrl+Shift+D")
        self.Bind(
            wx.EVT_MENU,
            lambda e, c=chat: self._show_conversation_data(chat=c),
            data_item,
        )

        menu.AppendSeparator()

        # ── Read / Unread — mutually exclusive: show only the applicable one ──
        has_unread = int(chat.get("unreadCount") or 0) > 0
        if has_unread:
            read_item = menu.Append(wx.ID_ANY, f"{i18n.t('mark_as_read')}\tCtrl+Shift+M")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_mark_read(j), read_item)
        else:
            unread_item = menu.Append(wx.ID_ANY, i18n.t("mark_as_unread"))
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_mark_unread(j), unread_item)

        menu.AppendSeparator()

        # ── Mute ──────────────────────────────────────────────────────────
        if mw.is_chat_muted(jid):
            unmute_item = menu.Append(wx.ID_ANY, f"{i18n.t('unmute_chat')}\tCtrl+Shift+S")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_unmute(j), unmute_item)
        else:
            mute_sub = wx.Menu()
            for key, secs in [
                ("mute_1h", 3600), ("mute_3h", 10800),
                ("mute_8h", 28800), ("mute_1d", 86400), ("mute_always", -1),
            ]:
                item = mute_sub.Append(wx.ID_ANY, i18n.t(key))
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, j=jid, s=secs: self._on_menu_mute(j, s),
                    item,
                )
            menu.AppendSubMenu(mute_sub, f"{i18n.t('mute_chat')}\tCtrl+Shift+S")

        if not is_group:
            menu.AppendSeparator()
            block_item = menu.Append(wx.ID_ANY, i18n.t("block_contact"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, c=chat, j=jid: self._on_menu_block(c, j),
                block_item,
            )
            copy_num_item = menu.Append(wx.ID_ANY, i18n.t("copy_number"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, j=jid: self._on_menu_copy_number(j),
                copy_num_item,
            )

        menu.AppendSeparator()

        # ── Archive / Unarchive ───────────────────────────────────────────
        if mw.is_chat_archived(jid):
            ua_item = menu.Append(wx.ID_ANY, f"{i18n.t('unarchive_chat')}\tCtrl+Q")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_unarchive(j), ua_item)
        else:
            arch_item = menu.Append(wx.ID_ANY, f"{i18n.t('archive_chat')}\tCtrl+Q")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_archive(j), arch_item)

        # ── Pin / Unpin ───────────────────────────────────────────────────
        if mw.is_chat_pinned(jid):
            unpin_item = menu.Append(wx.ID_ANY, f"{i18n.t('unpin_chat')}\tCtrl+P")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_unpin(j), unpin_item)
        else:
            pin_item = menu.Append(wx.ID_ANY, f"{i18n.t('pin_chat')}\tCtrl+P")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_pin(j), pin_item)

        menu.AppendSeparator()

        # ── Clear / Delete / Leave ────────────────────────────────────────
        clear_item = menu.Append(wx.ID_ANY, i18n.t("clear_chat"))
        self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_clear_chat(j), clear_item)

        delete_item = menu.Append(wx.ID_ANY, i18n.t("delete_chat"))
        self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_delete_chat(j), delete_item)

        if is_group:
            leave_item = menu.Append(wx.ID_ANY, i18n.t("leave_group"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, j=jid: self._on_menu_leave_group(j),
                leave_item,
            )
            add_member_item = menu.Append(wx.ID_ANY, i18n.t("add_member"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, j=jid: self._on_menu_add_member(j),
                add_member_item,
            )

        menu.AppendSeparator()

        close_item = menu.Append(wx.ID_ANY, f"{i18n.t('close_conversation')}\tCtrl+W")
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
        self._hide_all_media_controls()   # also clears links panel
        if index < 0 or index >= len(self._sorted_messages):
            return
        if self._is_separator(self._sorted_messages[index]):
            return  # separator row — no action controls
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
            else:
                self._action_download_btn.Show()
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
                if is_downloaded:
                    self._action_open_btn.SetLabel(self.main_window.i18n.t("open"))
                    self._action_open_btn.Show()
                    self._action_save_as_btn.Show()
                else:
                    self._action_download_btn.Show()
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

        elif msg_type == "contactMessage":
            contact = msg_obj.get("contactMessage") or {}
            vcard = contact.get("vcard", "")
            self._contact_msg_jid = self._jid_from_vcard(vcard)
            if self._contact_msg_jid:
                self._contact_converse_btn.Show()
                self.conversation_panel.Layout()

        # ── Link detection ────────────────────────────────────────────────
        # Always check the rendered text for URLs (regardless of msg_type)
        rendered = self.messages_list.GetItemText(index)
        self._update_links_panel(self._extract_links(rendered))

    def on_message_activated(self, event):
        """Enter / double-click on a message item."""
        self._do_activate_message(event.GetIndex())

    def _do_activate_message(self, index: int):
        """Core activation logic shared by Enter, double-click, and Space."""
        if index < 0 or index >= len(self._sorted_messages):
            return
        if self._is_separator(self._sorted_messages[index]):
            return  # separator row — no action
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")

        # For text-based messages: open the first link if one is present
        if msg_type in ("conversation", "extendedTextMessage", ""):
            rendered = self.messages_list.GetItemText(index)
            links = self._extract_links(rendered)
            if links:
                try:
                    os.startfile(links[0])
                except Exception:
                    wx.LaunchDefaultBrowser(links[0])
                return

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
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        if self._is_separator(self._sorted_messages[index]):
            return  # no context menu for separator
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_id   = msg.get("key", {}).get("id", "")
        i18n     = self.main_window.i18n

        menu = wx.Menu()

        # ── "Ir para a mensagem citada" (only for reply messages) ─────────────
        ctx_reply = self._get_context_info(msg)
        if ctx_reply:
            goto_item = menu.Append(
                wx.ID_ANY,
                f"{i18n.t('goto_quoted')}\tAlt+Shift+C",
            )
            self.Bind(
                wx.EVT_MENU,
                lambda e, m=msg, c=ctx_reply: self._on_menu_goto_quoted(m, c),
                goto_item,
            )
            menu.AppendSeparator()

        # ── Most-used reactions submenu (if this conversation has reactions) ──
        if self._reaction_map:
            all_emojis: dict = {}
            for msg_reactions in self._reaction_map.values():
                for em, cnt in msg_reactions.items():
                    all_emojis[em] = all_emojis.get(em, 0) + cnt
            if all_emojis:
                top_emojis = sorted(all_emojis.items(), key=lambda x: x[1], reverse=True)[:5]
                most_used_sub = wx.Menu()
                for em, _cnt in top_emojis:
                    sub_item = most_used_sub.Append(wx.ID_ANY, em)
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, m=msg, em=em: self._send_reaction(m, em),
                        sub_item,
                    )
                menu.AppendSubMenu(most_used_sub, i18n.t("most_used_reactions"))
                menu.AppendSeparator()

        # Message info (Alt+Shift+D)
        data_item = menu.Append(wx.ID_ANY, f"{i18n.t('message_data')}\tAlt+Shift+D")
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_message_data(m),
            data_item,
        )

        menu.AppendSeparator()

        # Copy text (only for text messages)
        _TEXT_TYPES = ("conversation", "extendedTextMessage", "textMessage")
        if msg_type in _TEXT_TYPES:
            copy_item = menu.Append(wx.ID_ANY, f"{i18n.t('copy_message_text')}\tCtrl+C")
            self.Bind(
                wx.EVT_MENU,
                lambda e, m=msg: self._on_menu_copy_message(m),
                copy_item,
            )

        # Reply (Alt+R)
        reply_item = menu.Append(wx.ID_ANY, f"{i18n.t('reply_message')}\tAlt+R")
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_reply(m),
            reply_item,
        )

        # ── Group-only: Reply privately / Converse with participant ────────────
        _conv_jid    = self.conversation.get("remoteJid", "") if self.conversation else ""
        _is_group    = _conv_jid.endswith("@g.us")
        _is_from_me  = msg.get("key", {}).get("fromMe", False)
        if _is_group and not _is_from_me:
            _participant_jid = (
                msg.get("key", {}).get("participant", "")
                or msg.get("participant", "")
            )
            if _participant_jid:
                private_reply_item = menu.Append(
                    wx.ID_ANY,
                    f"{i18n.t('reply_private')}\tAlt+Shift+R",
                )
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, m=msg, pj=_participant_jid: self._on_menu_reply_private(m, pj),
                    private_reply_item,
                )
                _pname = self._get_participant_name(_participant_jid, msg)
                converse_item = menu.Append(
                    wx.ID_ANY,
                    f"{i18n.t('converse_with').format(name=_pname)}\tAlt+Shift+V",
                )
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, pj=_participant_jid, pn=_pname: self._on_menu_converse_private(pj, pn),
                    converse_item,
                )

        # React (opens emoji picker)
        react_item = menu.Append(wx.ID_ANY, i18n.t("react_to_message"))
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_react(m),
            react_item,
        )

        # Show text popup (only for text messages)
        if msg_type in _TEXT_TYPES:
            show_text_item = menu.Append(wx.ID_ANY, f"{i18n.t('show_msg_text')}\tAlt+C")
            self.Bind(
                wx.EVT_MENU,
                lambda e, m=msg: self._show_message_text_popup(m),
                show_text_item,
            )

        # Forward (Ctrl+Shift+E)
        fwd_item = menu.Append(wx.ID_ANY, f"{i18n.t('forward_message')}\tCtrl+Shift+E")
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_forward(m),
            fwd_item,
        )

        # Star
        star_item = menu.Append(wx.ID_ANY, i18n.t("star_message"))
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_star(m),
            star_item,
        )

        # Save As (media only, only when the file is already cached locally)
        _SAVEABLE = {"documentMessage", "imageMessage", "videoMessage"}
        if msg_type in _SAVEABLE and os.path.isfile(
            data_path("media", f"{msg_id}.wzmedia")
        ):
            menu.AppendSeparator()
            save_item = menu.Append(
                wx.ID_ANY, f"{i18n.t('save_as')}\tCtrl+Shift+B"
            )
            self.Bind(wx.EVT_MENU, self._on_action_save_as, save_item)

        # Edit (own text messages within 3 hours)
        _is_own      = msg.get("key", {}).get("fromMe", False)
        _is_text     = msg_type in ("conversation", "extendedTextMessage")
        _msg_ts      = msg.get("messageTimestamp", 0)
        _within_3h   = (time.time() - _msg_ts) < 10800
        if _is_own and _is_text and _within_3h:
            edit_item = menu.Append(wx.ID_ANY, i18n.t("edit_message"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, i=index, m=msg: self._on_menu_edit_message(i, m),
                edit_item,
            )

        menu.AppendSeparator()

        # Delete message (with scope dialog — Ctrl+Shift+P)
        del_item = menu.Append(wx.ID_ANY, f"{i18n.t('delete_message')}\tCtrl+Shift+P")
        self.Bind(
            wx.EVT_MENU,
            lambda e, i=index: self._on_menu_delete_message(i),
            del_item,
        )

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
        self._action_download_btn.Hide()
        self._buttons_container.Hide()
        self._contact_converse_btn.Hide()
        self._contact_msg_jid = None
        self._update_links_panel([])
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    # ── URL / link helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_links(text: str) -> list:
        """Return deduplicated list of URLs found in *text*."""
        matches = _URL_RE.findall(text)
        seen = set()
        out  = []
        for m in matches:
            # Strip trailing punctuation that is not part of the URL
            m = m.rstrip('.,;:!?)\'"\\>]')
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _update_links_panel(self, links: list):
        """Rebuild the hyperlink controls below the messages list."""
        # Destroy all child controls except the static label (first item)
        for child in list(self._links_panel.GetChildren()):
            if child is not self._links_label:
                child.Destroy()
        # Remove all items except the first (label) from the sizer
        while self._links_sizer.GetItemCount() > 1:
            self._links_sizer.Remove(1)

        if not links:
            self._links_panel.Hide()
            self._current_links = []
            if self.conversation_panel.IsShown():
                self.conversation_panel.Layout()
            return

        self._current_links = links
        i18n = self.main_window.i18n

        for url in links:
            ctrl = wx.adv.HyperlinkCtrl(
                self._links_panel,
                id=wx.ID_ANY,
                label=url,
                url=url,
                style=wx.adv.HL_DEFAULT_STYLE,
            )
            ctrl.Bind(wx.adv.EVT_HYPERLINK, self._on_hyperlink_open)
            ctrl.Bind(wx.EVT_KEY_DOWN,  self._on_link_key_down)
            self._links_sizer.Add(ctrl, 0, wx.LEFT | wx.BOTTOM, 3)

        self._links_panel.Show()
        self._links_panel.Layout()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _on_hyperlink_open(self, event):
        """Open a link URL in the system's default application."""
        url = event.GetURL()
        try:
            os.startfile(url)
        except Exception:
            wx.LaunchDefaultBrowser(url)

    def _on_link_key_down(self, event):
        """Ensure Space and Enter activate a focused HyperlinkCtrl."""
        kc = event.GetKeyCode()
        if kc in (wx.WXK_RETURN, wx.WXK_SPACE, wx.WXK_NUMPAD_ENTER):
            ctrl = event.GetEventObject()
            try:
                os.startfile(ctrl.GetURL())
            except Exception:
                wx.LaunchDefaultBrowser(ctrl.GetURL())
        else:
            event.Skip()

    # ── Lazy-loading: load older messages when the user focuses item 0 ─────────

    def _on_message_focused(self, event):
        if (
            event.GetIndex() == 0
            and self._messages_offset > 0
            and not self._is_loading_more
        ):
            self._load_more_messages()
        event.Skip()

    def _load_more_messages(self):
        """Prepend the previous page of messages to the list."""
        self._is_loading_more = True
        try:
            limit = int(
                self.main_window.settings.get("ui", {}).get("messages_page_size", 50)
            )
            new_start = max(0, self._messages_offset - limit)
            new_msgs  = self._all_sorted_messages[new_start:self._messages_offset]
            if not new_msgs:
                return

            n_new = len(new_msgs)

            # Extend the in-memory list and update the offset
            self._sorted_messages   = new_msgs + self._sorted_messages
            self._messages_offset   = new_start
            if self._unread_sep_idx >= 0:
                self._unread_sep_idx += n_new

            # Rebuild the wx.ListCtrl from the updated _sorted_messages
            self.messages_list.DeleteAllItems()
            for msg in self._sorted_messages:
                self.messages_list.Append((self._render_message_line(msg),))

            # Keep the previously-first item in view (now at index n_new)
            self.messages_list.Focus(n_new)
            self.messages_list.Select(n_new, True)
            self.messages_list.EnsureVisible(n_new)
        finally:
            self._is_loading_more = False

    # ── Keyboard Space-as-activate helpers ──────────────────────────────────

    def _on_messages_list_key_down(self, event):
        """Make Space fire the same activation as Enter / double-click."""
        if event.GetKeyCode() == wx.WXK_SPACE:
            idx = self.messages_list.GetFocusedItem()
            if idx >= 0:
                self._do_activate_message(idx)
        else:
            event.Skip()

    def _on_conv_list_key_down(self, event):
        """Make Space open the focused conversation (same as Enter).
        Ctrl+P pins/unpins, Ctrl+Q archives/unarchives."""
        key  = event.GetKeyCode()
        ctrl = event.ControlDown()

        if key == wx.WXK_SPACE:
            idx = self.conversations_list.GetFocusedItem()
            if idx >= 0:
                self.conversations_list.Select(idx)
                self.on_conversation_selected_by_index(idx)
        elif ctrl and key == ord("P"):
            idx = self.conversations_list.GetFocusedItem()
            if 0 <= idx < len(self.chats_list):
                jid = self.chats_list[idx].get("remoteJid", "")
                if jid:
                    if self.main_window.is_chat_pinned(jid):
                        self._on_menu_unpin(jid)
                    else:
                        self._on_menu_pin(jid)
        elif ctrl and key == ord("Q"):
            idx = self.conversations_list.GetFocusedItem()
            if 0 <= idx < len(self.chats_list):
                jid = self.chats_list[idx].get("remoteJid", "")
                if jid:
                    if self.main_window.is_chat_archived(jid):
                        self._on_menu_unarchive(jid)
                    else:
                        self._on_menu_archive(jid)
        else:
            event.Skip()

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
        elif msg_type == "videoMessage":
            mime = (msg_obj.get("videoMessage") or {}).get("mimetype", "video/mp4")
            ext = "." + (mime.split("/")[-1] if "/" in mime else "mp4")
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

    def _on_action_download(self, event):
        """
        Download the media file for the currently selected document or video.
        Announces 'baixando...' via AO2, downloads in background, then replaces
        the Download button with Open + Save As once the file is ready.
        """
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg      = self._sorted_messages[index]
        msg_type = msg.get("messageType", "")
        msg_id   = msg.get("key", {}).get("id", "")
        mw       = self.main_window
        i18n     = mw.i18n
        media_path = data_path("media", f"{msg_id}.wzmedia")

        mw.output(i18n.t("downloading"))
        self._action_download_btn.Disable()

        def _run():
            try:
                if msg_type == "audioMessage":
                    mw.handle_audio_message(msg)
                else:
                    mw.handle_media_message(msg)
            except Exception:
                pass

            def _done():
                self._action_download_btn.Enable()
                if os.path.isfile(media_path) and os.path.getsize(media_path) > 0:
                    # File ready — swap Download for Open + Save As
                    self._action_download_btn.Hide()
                    self._action_open_btn.SetLabel(i18n.t("open"))
                    self._action_open_btn.Show()
                    self._action_save_as_btn.Show()
                    self.conversation_panel.Layout()

            wx.CallAfter(_done)

        threading.Thread(target=_run, daemon=True).start()

    # ── Audio / video playback ──────────────────────────────────────────────

    def _toggle_playback(self, msg_id, duration_seconds, msg, file_path, audio_ext):
        """
        Generic play/pause toggle for both audio messages (voice_messages/)
        and video messages (media/).
        """
        # Same item: toggle play / pause
        if msg_id == self._current_audio_id and self._audio_stream is not None:
            _ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
            if self._is_audio_playing:
                _ctrl.pause()
                self._is_audio_playing = False
                self._audio_timer.Stop()
            else:
                _ctrl.play()
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
                # Only play if the file was actually downloaded (non-empty)
                if os.path.isfile(file_path) and os.path.getsize(file_path) > 16:
                    wx.CallAfter(
                        self._play_audio, msg_id, duration_seconds, file_path, audio_ext
                    )

            threading.Thread(target=_download_and_play, daemon=True).start()

    def _play_audio(self, msg_id, duration_seconds, file_path, audio_ext=".ogg"):
        if not os.path.isfile(file_path):
            return

        # ── Decrypt and write to a temp file ────────────────────────────────
        try:
            with open(file_path, "rb") as fh:
                content = decrypt_bytes(fh.read(), self.main_window.key)
            tmp = tempfile.NamedTemporaryFile(suffix=audio_ext, delete=False)
            tmp.write(content)
            tmp.close()
            self._audio_temp_file = tmp.name
        except Exception:
            self._stop_audio()
            return

        # ── Try decoded stream + Tempo FX (enables speed control) ───────────
        # A decoded stream (BASS_STREAM_DECODE) cannot be played directly; it
        # must be wrapped by a BASS FX processor such as Tempo.  If the FX
        # plugin is unavailable, fall back to a plain stream without the effect.
        stream_ok = False
        try:
            self._audio_stream = sl_stream.FileStream(
                file=self._audio_temp_file, decode=True
            )
            self._audio_tempo_ctrl = Tempo(self._audio_stream)
            _speed = self._audio_speed_steps[self._audio_speed_index]
            self._audio_tempo_ctrl.tempo = self._audio_tempo_map.get(_speed, 0)
            stream_ok = True
        except Exception:
            # BASS FX not available or format not supported with decode=True;
            # discard the broken stream and retry without decode.
            self._audio_tempo_ctrl = None
            self._audio_stream = None

        if not stream_ok:
            try:
                self._audio_stream = sl_stream.FileStream(
                    file=self._audio_temp_file
                )
            except Exception:
                self._stop_audio()
                return

        # ── Start playback ───────────────────────────────────────────────────
        # When Tempo FX is active the decode stream has no audio output of its
        # own; playback must be started on the Tempo wrapper instead.
        self._audio_stream_duration = int(duration_seconds)
        self._current_audio_id = msg_id
        try:
            playback_ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
            playback_ctrl.play()
        except Exception:
            self._stop_audio()
            return

        self._is_audio_playing = True
        self._audio_timer.Start(200)
        self._show_audio_controls()
        _speed = self._audio_speed_steps[self._audio_speed_index]
        self.audio_speed_btn.SetLabel(self._format_speed(_speed))

    def _stop_audio(self):
        if self._audio_timer.IsRunning():
            self._audio_timer.Stop()
        # Stop the Tempo FX controller first (it owns the audio output channel)
        if self._audio_tempo_ctrl is not None:
            try:
                self._audio_tempo_ctrl.stop()
            except Exception:
                pass
            self._audio_tempo_ctrl = None
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop()
            except Exception:
                pass
            self._audio_stream = None
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
            _ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
            pos   = _ctrl.get_position()
            total = _ctrl.get_length()
            if total > 0:
                if pos >= total:
                    # Save the ID before _stop_audio() clears it
                    finished_id = self._current_audio_id
                    self._stop_audio()
                    self._hide_audio_controls()
                    # Try to auto-play the next consecutive audio message
                    if finished_id:
                        self._auto_chain_next_audio(finished_id)
                    return
                self.audio_slider.SetValue(int(pos / total * 1000))
                self.audio_slider.Refresh()
        except Exception:
            pass

    def _auto_chain_next_audio(self, finished_id: str):
        """
        After an audio message finishes playing, automatically start the next
        consecutive audio message if one exists immediately after in the list.
        Stops at the first non-audio (or separator) message.
        """
        # Find the index of the just-finished message
        current_idx = -1
        for i, msg in enumerate(self._sorted_messages):
            if not self._is_separator(msg) and msg.get("key", {}).get("id") == finished_id:
                current_idx = i
                break
        if current_idx < 0:
            return

        # Walk forward, skipping separators, to find the next message
        next_idx = current_idx + 1
        while next_idx < len(self._sorted_messages):
            next_msg = self._sorted_messages[next_idx]
            if self._is_separator(next_msg):
                next_idx += 1
                continue
            # Only auto-play if the next message is also an audio message
            if next_msg.get("messageType") == "audioMessage":
                msg_id   = next_msg.get("key", {}).get("id", "")
                duration = (
                    (next_msg.get("message") or {}).get("audioMessage") or {}
                ).get("seconds", 0) or 0
                # Update list selection to the next audio
                self.messages_list.Focus(next_idx)
                self.messages_list.Select(next_idx, True)
                self._toggle_playback(
                    msg_id, duration, next_msg,
                    file_path=data_path("voice_messages", f"{msg_id}.msv"),
                    audio_ext=".ogg",
                )
            break  # stop regardless (either play next or not)

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
        # Persist the new speed so it applies to all future playbacks/conversations
        self.main_window.settings.setdefault("general", {})["audio_default_speed"] = speed
        self.main_window.save_settings()

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
            return dt.strftime(self.main_window.i18n.t("datetime_fmt"))
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

        # ── Contact ──────────────────────────────────────────────────────────
        if msg_type == "contactMessage":
            contact = msg_obj.get("contactMessage") or {}
            name    = contact.get("displayName") or ""
            return i18n.t("contact_message").format(name=name)

        # ── Fallback ─────────────────────────────────────────────────────────
        return i18n.t("unsupported_message").format(
            app_name=self.main_window.app_name
        )

    def _map_status(self, msg) -> str:
        i18n = self.main_window.i18n
        # Locally-queued messages have their own pending status.
        if msg.get("_local_pending"):
            return i18n.t("status_pending")
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
        key = msg.get("key", {})
        # Look up the contact by participant JID (groups) or remoteJid (DMs)
        participant = key.get("participant", "")
        jid         = key.get("remoteJid", "")
        lookup_jid  = participant or jid
        if lookup_jid:
            contact = self.main_window.contacts.get(lookup_jid)
            if contact:
                n = (contact.get("name") or contact.get("fullName")
                     or contact.get("verifiedName") or contact.get("pushName") or "")
                if n and not n.isdigit():
                    return n
        push = msg.get("pushName", "")
        if push and not push.isdigit():
            return push
        if key.get("addressingMode") == "lid":
            return format_number(key.get("remoteJidAlt", ""))
        return format_number(participant or jid)

    def _is_separator(self, msg: dict) -> bool:
        """Return True if msg is the unread-messages separator sentinel."""
        return isinstance(msg, dict) and msg.get("_type") == "unread_separator"

    def _render_separator(self, count: int) -> str:
        i18n = self.main_window.i18n
        if count == 1:
            return i18n.t("unread_sep_singular")
        return i18n.t("unread_sep_plural").format(count=count)

    def _get_quoted_preview(self, quoted_msg: dict) -> str:
        """Return a short preview string for the content of a quoted message."""
        i18n = self.main_window.i18n
        if not quoted_msg or not isinstance(quoted_msg, dict):
            return ""
        if "conversation" in quoted_msg:
            return (quoted_msg.get("conversation") or "")
        if "extendedTextMessage" in quoted_msg:
            return ((quoted_msg.get("extendedTextMessage") or {}).get("text") or "")
        # Non-text types: return the localized type label (first letter upper)
        _type_map = [
            ("audioMessage",    "message_type_audio"),
            ("imageMessage",    "photo"),
            ("videoMessage",    "video"),
            ("documentMessage", "document"),
            ("stickerMessage",  "sticker"),
            ("contactMessage",  "contact_label"),
        ]
        for key, i18n_key in _type_map:
            if key in quoted_msg:
                label = i18n.t(i18n_key)
                return label[0].upper() + label[1:] if label else ""
        return ""

    def _get_context_info(self, msg) -> "dict | None":
        """Extract contextInfo from wherever it sits in the message hierarchy."""
        msg_obj = msg.get("message") or {}
        if not isinstance(msg_obj, dict):
            return None
        for sub_key in (
            "extendedTextMessage", "audioMessage", "imageMessage",
            "videoMessage", "documentMessage", "stickerMessage",
            "locationMessage", "contactMessage", "buttonsMessage",
            "listMessage",
        ):
            sub = msg_obj.get(sub_key)
            if isinstance(sub, dict):
                ctx = sub.get("contextInfo")
                if isinstance(ctx, dict) and "quotedMessage" in ctx:
                    return ctx
        return None

    def _get_quoted_sender(self, ctx: dict) -> str:
        """Resolve the display name of the quoted message sender from contextInfo."""
        participant = ctx.get("participant", "")
        if not participant:
            return ""
        mw = self.main_window
        contact = mw.contacts.get(participant)
        if contact:
            name = (contact.get("name") or contact.get("fullName") or
                    contact.get("verifiedName") or contact.get("pushName") or "")
            if name:
                return name
        return format_number(participant) or participant

    def _render_message_line(self, msg) -> str:
        """Produce the full display string for a single message row."""
        # Unread separator sentinel
        if self._is_separator(msg):
            return self._render_separator(msg.get("count", 1))
        ts       = self._extract_timestamp(msg)
        time_str = self._format_date(ts) if ts else ""
        body     = (self._get_message_content(msg) or "").replace("\n", " ")
        sender   = self._sender_label(msg)
        status   = self._map_status(msg)
        i18n     = self.main_window.i18n

        # Check for quoted/reply context
        ctx           = self._get_context_info(msg)
        quoted_sender = self._get_quoted_sender(ctx) if ctx else ""

        if quoted_sender:
            header = f"{sender}, {i18n.t('replying_to').format(name=quoted_sender)}"
        else:
            header = sender

        pieces = [f"{header}: {body}"]
        if time_str:
            pieces.append(f", {time_str}")
        if status:
            pieces[-1] += f", {status}"

        # Append quoted message preview (if this is a reply)
        if ctx:
            quoted_msg_obj = ctx.get("quotedMessage") or {}
            quoted_preview = self._get_quoted_preview(quoted_msg_obj)
            if quoted_preview:
                pieces.append(
                    f", {i18n.t('quoted_message_label')}: {quoted_preview}"
                )

        # Append reactions if any
        msg_id    = msg.get("key", {}).get("id", "")
        reactions = self._reaction_map.get(msg_id, {})
        if reactions:
            r_parts = []
            for emoji, count in reactions.items():
                r_parts.append(f"{emoji}, {count} {i18n.t('total_label')}")
            pieces.append(f". {i18n.t('reactions_label')} {', '.join(r_parts)}.")

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

    # ── Ctrl+Shift+D / Ctrl+Shift+P dispatch ────────────────────────────────

    def _on_ctrl_shift_d(self, event):
        """Discard voice recording if active; otherwise show conversation data."""
        if self._is_recording:
            self._discard_voice_message(event)
        elif self.conversation is not None:
            self._show_conversation_data()

    def _on_ctrl_shift_p(self, event):
        """Pause/resume recording when active; delete focused message otherwise."""
        if self._is_recording:
            self._toggle_pause_recording(event)
        else:
            self._on_accel_delete_message(event)

    # ── Conversation / group data ────────────────────────────────────────────

    def _show_conversation_data(self, event=None, chat=None):
        target = chat if chat is not None else self.conversation
        if target is None:
            return
        from ui.dialogs.conversation_data_dialog import ConversationDataDialog
        dlg = ConversationDataDialog(self.main_window, target)
        dlg.ShowModal()
        dlg.Destroy()

    def _fetch_and_update_profile(self, conversation: dict):
        """
        Background: fetch contact profile / group info and update the
        conversation-data button note with a last-seen or group-size string.
        """
        jid      = conversation.get("remoteJid", "")
        mw       = self.main_window
        i18n     = mw.i18n
        # Default note: resolved contact name, falling back to formatted number
        note = (
            mw._resolve_contact_name(conversation)
            or mw.find_name_through_messages(conversation)
            or conversation.get("pushName", "")
            or format_number(jid)
        )

        try:
            if jid.endswith("@g.us"):
                data = mw.get_group_info(jid)
                size = data.get("size", 0)
                note = i18n.t("group_size").format(count=size)
            else:
                data = mw.get_contact_profile(jid)
                if data.get("presence") == "available":
                    note = i18n.t("online_status")
                else:
                    ls = data.get("lastSeen") or data.get("lastKnownPresence")
                    if ls and isinstance(ls, (int, float, str)):
                        try:
                            dt  = datetime.fromtimestamp(int(ls))
                            now = datetime.now()
                            if dt.date() == now.date():
                                note = i18n.t("last_seen_today").format(
                                    time=dt.strftime("%H:%M")
                                )
                            elif (now.date() - dt.date()).days == 1:
                                note = i18n.t("last_seen_yesterday").format(
                                    time=dt.strftime("%H:%M")
                                )
                            else:
                                note = i18n.t("last_seen_date").format(
                                    date=dt.strftime(i18n.t("date_fmt")),
                                    time=dt.strftime("%H:%M"),
                                )
                        except Exception:
                            pass
        except Exception:
            pass

        def _update():
            if (self.conversation is not None
                    and self.conversation.get("remoteJid") == jid):
                try:
                    self._conv_data_btn.SetNote(note)
                    self.conversation_panel.Layout()
                except Exception:
                    pass

        wx.CallAfter(_update)

    # ── Conversation context menu handlers ───────────────────────────────────

    def _on_menu_mark_read(self, jid: str):
        threading.Thread(
            target=self.main_window.mark_conversation_as_read,
            args=(jid,),
            daemon=True,
        ).start()

    def _on_menu_mark_unread(self, jid: str):
        self.main_window.mark_conversation_as_unread(jid)

    def _on_menu_mute(self, jid: str, duration_secs: int):
        self.main_window.mute_chat(jid, duration_secs)

    def _on_menu_unmute(self, jid: str):
        self.main_window.unmute_chat(jid)

    def _on_menu_block(self, chat: dict, jid: str):
        name = (
            self.main_window._resolve_contact_name(chat)
            or self.main_window.find_name_through_messages(chat)
            or format_number(jid)
        )
        msg = self.main_window.i18n.t("block_confirm_msg").format(name=name)
        if wx.MessageBox(
            msg,
            self.main_window.i18n.t("block_contact"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) == wx.YES:
            threading.Thread(
                target=self.main_window.block_contact,
                args=(jid, "block"),
                daemon=True,
            ).start()

    def _on_menu_copy_number(self, jid: str):
        number = format_number(jid)
        try:
            pyperclip.copy(number)
        except Exception:
            pass

    def _on_menu_archive(self, jid: str):
        # Close conversation if currently open
        if self.conversation and self.conversation.get("remoteJid") == jid:
            self.close_conversation()
        self.main_window.archive_chat(jid)

    def _on_menu_unarchive(self, jid: str):
        self.main_window.unarchive_chat(jid)

    def _on_menu_pin(self, jid: str):
        self.main_window.pin_chat(jid)

    def _on_menu_unpin(self, jid: str):
        self.main_window.unpin_chat(jid)

    def _on_menu_clear_chat(self, jid: str):
        i18n = self.main_window.i18n
        if wx.MessageBox(
            i18n.t("clear_confirm_msg"),
            i18n.t("clear_chat"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        self.main_window.clear_chat_messages_local(jid)
        # Refresh messages list if this conversation is open
        if self.conversation and self.conversation.get("remoteJid") == jid:
            self._sorted_messages = []
            self.messages_list.DeleteAllItems()

    def _on_menu_delete_chat(self, jid: str):
        i18n = self.main_window.i18n
        if wx.MessageBox(
            i18n.t("delete_confirm_msg"),
            i18n.t("delete_chat"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        if self.conversation and self.conversation.get("remoteJid") == jid:
            self.close_conversation()
        self.main_window.delete_chat_local(jid)

    def _on_menu_leave_group(self, jid: str):
        i18n = self.main_window.i18n
        if wx.MessageBox(
            i18n.t("delete_confirm_msg"),
            i18n.t("leave_group"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        if self.conversation and self.conversation.get("remoteJid") == jid:
            self.close_conversation()
        threading.Thread(
            target=self.main_window.leave_group,
            args=(jid,),
            daemon=True,
        ).start()

    def _on_menu_add_member(self, group_jid: str):
        """Open the add-member dialog for a group."""
        from ui.dialogs.add_member_dialog import AddMemberDialog
        dlg = AddMemberDialog(self.main_window, group_jid)
        dlg.ShowModal()
        dlg.Destroy()

    # ── Message context menu handlers ────────────────────────────────────────

    def _on_menu_message_data(self, msg: dict):
        i18n     = self.main_window.i18n
        ts       = self._extract_timestamp(msg)
        time_str = self._format_date(ts) if ts else ""
        sender   = self._sender_label(msg)
        status   = self._map_status(msg)
        content  = self._get_message_content(msg)

        lines = [f"{sender}: {content}"]
        if time_str:
            lines.append(time_str)
        if status:
            lines.append(f"Status: {status}")

        dlg = wx.Dialog(
            self.main_window, title=i18n.t("message_data"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(420, 280),
        )
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        info_ctrl = wx.TextCtrl(
            panel, value="\n".join(lines),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        sizer.Add(info_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        close_btn = wx.Button(panel, wx.ID_OK, label=i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)
        info_ctrl.SetFocus()
        dlg.ShowModal()
        dlg.Destroy()

    def _on_menu_copy_message(self, msg: dict):
        msg_obj  = msg.get("message") or {}
        msg_type = msg.get("messageType", "")
        text = ""
        if msg_type == "conversation":
            text = msg_obj.get("conversation", "")
        elif msg_type in ("extendedTextMessage", "textMessage"):
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        if text:
            try:
                pyperclip.copy(text)
                self.main_window.output(self.main_window.i18n.t("msg_copied"))
            except Exception:
                self.main_window.output(self.main_window.i18n.t("msg_copy_error"))
        else:
            self.main_window.output(self.main_window.i18n.t("msg_copy_error"))

    def _on_menu_reply(self, msg: dict):
        """Enter reply mode: change field label, store quoted message, focus field."""
        self._quoted_message = msg
        i18n      = self.main_window.i18n
        sender    = self._sender_label(msg)
        jid       = self.conversation.get("remoteJid", "") if self.conversation else ""
        is_group  = jid.endswith("@g.us")

        if is_group and not msg.get("key", {}).get("fromMe", False):
            group_name = self.conversation_name
            label = i18n.t("reply_to_group").format(name=sender, group=group_name)
        else:
            label = i18n.t("reply_to").format(name=sender)

        self.message_label.SetLabel(label)
        self._remove_quote_btn.Show()
        self.conversation_panel.Layout()
        self.message_field.SetFocus()

    def _get_participant_name(self, participant_jid: str, msg: dict | None = None) -> str:
        """Return a display name for a group participant."""
        mw = self.main_window
        contact = mw.contacts.get(participant_jid)
        if contact:
            name = (
                contact.get("name") or contact.get("fullName")
                or contact.get("verifiedName") or contact.get("pushName") or ""
            )
            if name:
                return name
        if msg is not None:
            push = msg.get("pushName", "")
            if push and not push.isdigit():
                return push
        return format_number(participant_jid) or participant_jid

    def _on_menu_reply_private(self, msg: dict, participant_jid: str):
        """Open a private conversation with the group participant and cite their message."""
        mw = self.main_window
        chat = mw.chats.get(participant_jid)
        if chat is None:
            pname = self._get_participant_name(participant_jid, msg)
            chat = {"remoteJid": participant_jid, "pushName": pname}
        self.navigate_to_conversation(chat)
        # Set up reply quoting the group message
        self._quoted_message = msg
        self._on_menu_reply(msg)

    def _on_menu_converse_private(self, participant_jid: str, participant_name: str):
        """Open a private conversation with the group participant (no citation)."""
        mw = self.main_window
        chat = mw.chats.get(participant_jid)
        if chat is None:
            chat = {"remoteJid": participant_jid, "pushName": participant_name}
        self.navigate_to_conversation(chat)

    def _on_menu_goto_quoted(self, msg: dict, ctx: dict):
        """Move focus in the messages list to the quoted message."""
        quoted_id = ctx.get("stanzaId") or ctx.get("quotedMessageId") or ""
        if not quoted_id:
            self._show_quoted_not_found_error()
            return
        for i, m in enumerate(self._sorted_messages):
            if not self._is_separator(m) and m.get("key", {}).get("id") == quoted_id:
                self.messages_list.Focus(i)
                self.messages_list.Select(i, True)
                self.messages_list.EnsureVisible(i)
                self.messages_list.SetFocus()
                return
        self._show_quoted_not_found_error()

    def _show_quoted_not_found_error(self):
        wx.MessageBox(
            self.main_window.i18n.t("goto_quoted_error"),
            self.main_window.i18n.t("app_name"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _on_menu_forward(self, msg: dict):
        """Open a conversation-picker dialog and forward *msg* to the chosen chat."""
        mw   = self.main_window
        i18n = mw.i18n

        # ── Collect available conversations ───────────────────────────────────
        panel       = mw.conversations_panel
        all_chats   = list(getattr(panel, "_all_chats_list", panel.chats_list))
        all_names   = list(getattr(panel, "_all_chat_names", panel.chat_names))
        if not all_chats:
            return

        # ── Build a simple picker dialog ──────────────────────────────────────
        dlg = wx.Dialog(
            self,
            title=i18n.t("forward_message"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(400, 480),
        )
        p     = wx.Panel(dlg)
        vsz   = wx.BoxSizer(wx.VERTICAL)

        search_field = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        search_field.SetHint(i18n.t("search_conversations"))
        vsz.Add(search_field, 0, wx.EXPAND | wx.ALL, 6)

        lst = wx.ListBox(p, choices=all_names, style=wx.LB_SINGLE)
        vsz.Add(lst, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        btn_sizer  = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(p, wx.ID_OK,     label=i18n.t("forward_message"))
        cancel_btn = wx.Button(p, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vsz.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)

        p.SetSizer(vsz)
        dlg_sz = wx.BoxSizer(wx.VERTICAL)
        dlg_sz.Add(p, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sz)
        dlg.Layout()

        # Filter list as user types
        _filtered_chats = list(all_chats)
        _filtered_names = list(all_names)

        def _on_search(event):
            nonlocal _filtered_chats, _filtered_names
            q = search_field.GetValue().strip().lower()
            if q:
                pairs = [(c, n) for c, n in zip(all_chats, all_names)
                         if q in n.lower()]
            else:
                pairs = list(zip(all_chats, all_names))
            _filtered_chats = [c for c, _ in pairs]
            _filtered_names = [n for _, n in pairs]
            lst.Set(_filtered_names)
            if _filtered_names:
                lst.SetSelection(0)

        search_field.Bind(wx.EVT_TEXT, _on_search)
        if all_names:
            lst.SetSelection(0)
        ok_btn.SetDefault()

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        sel = lst.GetSelection()
        dlg.Destroy()
        if sel == wx.NOT_FOUND or sel >= len(_filtered_chats):
            return

        target_jid = _filtered_chats[sel].get("remoteJid", "")
        if not target_jid:
            return

        # ── Extract forwardable content from the message ──────────────────────
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}

        if msg_type in ("conversation", "textMessage"):
            text = (
                msg_obj.get("conversation")
                or (msg_obj.get("extendedTextMessage") or {}).get("text")
                or ""
            )
            if text:
                import uuid
                local_id = str(uuid.uuid4())
                from core.message_queue import PendingMessage
                mw.message_queue.enqueue(
                    PendingMessage(local_id=local_id, jid=target_jid, text=text)
                )
        elif msg_type == "extendedTextMessage":
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
            if text:
                import uuid
                local_id = str(uuid.uuid4())
                from core.message_queue import PendingMessage
                mw.message_queue.enqueue(
                    PendingMessage(local_id=local_id, jid=target_jid, text=text)
                )
        else:
            # For media types, try to forward caption or a type label
            caption = ""
            for sub_key in ("imageMessage", "videoMessage", "documentMessage", "audioMessage"):
                sub = msg_obj.get(sub_key) or {}
                if sub:
                    caption = sub.get("caption", "")
                    break
            if not caption:
                # No text content to forward — nothing to do
                pass
            else:
                import uuid
                local_id = str(uuid.uuid4())
                from core.message_queue import PendingMessage
                mw.message_queue.enqueue(
                    PendingMessage(local_id=local_id, jid=target_jid, text=caption)
                )

    def _on_menu_star(self, msg: dict):
        # Star not yet fully implemented — no-op for now
        pass

    def _on_menu_delete_message(self, index: int):
        """Show delete-scope dialog and delete locally or for everyone."""
        if index < 0 or index >= len(self._sorted_messages):
            return
        if self._is_separator(self._sorted_messages[index]):
            return
        msg    = self._sorted_messages[index]
        msg_id = msg.get("key", {}).get("id", "")
        i18n   = self.main_window.i18n

        # ── Ask the user: delete for me only, or for everyone ─────────────────
        dlg = wx.Dialog(
            self,
            title=i18n.t("delete_message"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        panel  = wx.Panel(dlg)
        sizer  = wx.BoxSizer(wx.VERTICAL)

        rb_me  = wx.RadioButton(panel, label=i18n.t("delete_for_me"),    style=wx.RB_GROUP)
        rb_all = wx.RadioButton(panel, label=i18n.t("delete_for_everyone"))
        rb_me.SetValue(True)
        sizer.Add(rb_me,  0, wx.ALL, 8)
        sizer.Add(rb_all, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(panel, wx.ID_OK,     label=i18n.t("delete_message"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)
        dlg.Fit()
        dlg.CentreOnParent()

        result     = dlg.ShowModal()
        for_everyone = rb_all.GetValue()
        dlg.Destroy()

        if result != wx.ID_OK:
            return

        if for_everyone:
            # Delete for everyone via Evolution API
            jid   = msg.get("key", {}).get("remoteJid", "") or (
                self.conversation.get("remoteJid", "") if self.conversation else ""
            )
            from_me = msg.get("key", {}).get("fromMe", False)
            self.main_window.delete_message_for_everyone(jid, msg_id, from_me)

        # Always delete locally
        self._sorted_messages.pop(index)
        self.messages_list.DeleteItem(index)
        if self.conversation:
            records = (
                self.conversation.get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            self.conversation["messages"]["messages"]["records"] = [
                m for m in records
                if m.get("key", {}).get("id") != msg_id
            ]
            self.main_window.save_data(
                self.main_window.chats, self.main_window.contacts
            )

    def _on_menu_edit_message(self, index: int, msg: dict):
        """Enter edit mode: pre-fill message field with message text."""
        content = self._get_message_content(msg) or ""
        # Strip any leading quote block (from a previous reply prefix)
        if content.startswith("> ") and "\n" in content:
            content = content[content.index("\n") + 1:]

        self._editing_message_id    = msg.get("key", {}).get("id", "")
        self._editing_message_index = index

        self.message_field.SetValue(content)
        self.message_field.SetInsertionPointEnd()
        self.message_field.SetFocus()

        # Show cancel button so the user knows they're in edit mode
        self._cancel_edit_btn.Show()
        self.conversation_panel.Layout()

    def _on_cancel_edit(self, event=None):
        """Leave edit mode without saving."""
        self._editing_message_id    = None
        self._editing_message_index = -1
        self.message_field.SetValue("")
        self._cancel_edit_btn.Hide()
        self.conversation_panel.Layout()

    def _on_cancel_reply(self, event=None):
        """Leave reply mode without sending."""
        self._quoted_message = None
        i18n     = self.main_window.i18n
        jid      = self.conversation.get("remoteJid", "") if self.conversation else ""
        is_group = jid.endswith("@g.us")
        label = (
            i18n.t("type_message_group") if is_group else i18n.t("type_message")
        )
        if self.conversation_name:
            label = f"{label} {self.conversation_name}"
        self.message_label.SetLabel(label)
        self._remove_quote_btn.Hide()
        self.conversation_panel.Layout()

    # ── Accelerator shims ─────────────────────────────────────────────────────

    def _on_accel_message_data(self, event):
        index = self.messages_list.GetFirstSelected()
        if 0 <= index < len(self._sorted_messages):
            self._on_menu_message_data(self._sorted_messages[index])

    def _on_accel_reply(self, event):
        index = self.messages_list.GetFirstSelected()
        if 0 <= index < len(self._sorted_messages):
            self._on_menu_reply(self._sorted_messages[index])

    def _on_accel_forward(self, event):
        index = self.messages_list.GetFirstSelected()
        if 0 <= index < len(self._sorted_messages):
            self._on_menu_forward(self._sorted_messages[index])

    def _on_accel_delete_message(self, event):
        index = self.messages_list.GetFirstSelected()
        if index >= 0:
            self._on_menu_delete_message(index)

    def _on_accel_mute(self, event):
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if not jid:
            return
        mw = self.main_window
        if mw.is_chat_muted(jid):
            mw.unmute_chat(jid)
        else:
            # Default: mute for 8 hours
            mw.mute_chat(jid, 8 * 3600)

    def _on_accel_mark_read(self, event):
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if jid:
            self.main_window.mark_conversation_as_read(jid)

    def _on_accel_copy_message(self, event):
        """Ctrl+C: copy focused message text to clipboard."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        self._on_menu_copy_message(msg)

    def _on_accel_show_text_popup(self, event):
        """Alt+C: show focused message text in a popup dialog."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        self._show_message_text_popup(msg)

    # ── Alt+Shift+R: reply privately ────────────────────────────────────────

    def _on_accel_reply_private(self, event):
        """Alt+Shift+R: reply privately to the focused group message."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        jid      = self.conversation.get("remoteJid", "") if self.conversation else ""
        from_me  = msg.get("key", {}).get("fromMe", False)
        if not jid.endswith("@g.us") or from_me:
            return
        participant_jid = (
            msg.get("key", {}).get("participant", "")
            or msg.get("participant", "")
        )
        if participant_jid:
            self._on_menu_reply_private(msg, participant_jid)

    # ── Alt+Shift+C: goto quoted message ────────────────────────────────────

    def _on_accel_alt_shift_c(self, event):
        """Alt+Shift+C: go to the quoted message for the focused reply."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        ctx = self._get_context_info(msg)
        if ctx:
            self._on_menu_goto_quoted(msg, ctx)

    # ── Alt+Shift+V: converse with participant ───────────────────────────────

    def _on_accel_alt_shift_v(self, event):
        """Alt+Shift+V: open a private chat with the focused group message's author."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        jid     = self.conversation.get("remoteJid", "") if self.conversation else ""
        from_me = msg.get("key", {}).get("fromMe", False)
        if jid.endswith("@g.us") and not from_me:
            participant_jid = (
                msg.get("key", {}).get("participant", "")
                or msg.get("participant", "")
            )
            if participant_jid:
                pname = self._get_participant_name(participant_jid, msg)
                self._on_menu_converse_private(participant_jid, pname)

    # ── Ctrl+N: nova conversa ─────────────────────────────────────────────────

    def _on_new_conversation(self, event=None):
        """Ctrl+N / Nova conversa button: open the New Conversation dialog."""
        from ui.dialogs.new_conversation import NewConversationDialog
        dlg = NewConversationDialog(self.main_window)
        dlg.ShowModal()
        dlg.Destroy()

    # ── Alt+2: jump to last message ────────────────────────────────────────

    def _on_accel_jump_last(self, event):
        """Alt+2: move focus to the last message in the current conversation."""
        count = self.messages_list.GetItemCount()
        if count > 0:
            last = count - 1
            self.messages_list.Focus(last)
            self.messages_list.Select(last, True)
            self.messages_list.EnsureVisible(last)
            self.messages_list.SetFocus()

    # ── Alt+3: jump to unread separator ────────────────────────────────────

    def _on_accel_jump_unread(self, event):
        i18n = self.main_window.i18n
        if self._unread_sep_idx < 0 or self._unread_sep_idx >= self.messages_list.GetItemCount():
            self.main_window.output(i18n.t("no_unread_in_conv"), interrupt=True)
            return
        self.messages_list.Focus(self._unread_sep_idx)
        self.messages_list.Select(self._unread_sep_idx, True)
        self.messages_list.EnsureVisible(self._unread_sep_idx)
        self.messages_list.SetFocus()
        self.main_window.output(
            self.messages_list.GetItemText(self._unread_sep_idx),
            interrupt=True,
        )

    # ── Ctrl+Shift+F: search in conversation ───────────────────────────────

    def _on_accel_open_search(self, event):
        self._on_open_search(event)

    def _on_open_search(self, event):
        self._search_panel.Show()
        self._search_open_btn.Hide()
        self.conversation_panel.Layout()
        self._search_field.SetFocus()

    def _on_close_search(self, event):
        self._search_panel.Hide()
        self._search_open_btn.Show()
        self._search_results = []
        self._search_result_idx = -1
        self._search_field.SetValue("")
        self.conversation_panel.Layout()
        self.messages_list.SetFocus()

    def _on_search_text_changed(self, event):
        query = self._search_field.GetValue()
        if not query.strip():
            self._search_results = []
            self._search_result_idx = -1
            return
        qlow = query.lower()
        self._search_results = [
            i for i, msg in enumerate(self._sorted_messages)
            if not self._is_separator(msg)
            and qlow in self._render_message_line(msg).lower()
        ]
        self._search_result_idx = -1

    def _on_search_key_down(self, event):
        key   = event.GetKeyCode()
        shift = event.ShiftDown()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if shift:
                self._on_search_prev(None)
            else:
                self._on_search_next(None)
        else:
            event.Skip()

    def _on_search_next(self, event):
        i18n = self.main_window.i18n
        if not self._search_results:
            self.main_window.output(i18n.t("search_no_results"), interrupt=True)
            return
        self._search_result_idx = (self._search_result_idx + 1) % len(self._search_results)
        self._jump_to_search_result()

    def _on_search_prev(self, event):
        i18n = self.main_window.i18n
        if not self._search_results:
            self.main_window.output(i18n.t("search_no_results"), interrupt=True)
            return
        self._search_result_idx = (self._search_result_idx - 1) % len(self._search_results)
        self._jump_to_search_result()

    def _jump_to_search_result(self):
        i18n  = self.main_window.i18n
        idx   = self._search_results[self._search_result_idx]
        total = len(self._search_results)
        self.messages_list.Focus(idx)
        self.messages_list.Select(idx, True)
        self.messages_list.EnsureVisible(idx)
        ann = i18n.t("search_result").format(
            current=self._search_result_idx + 1,
            total=total,
        )
        self.main_window.output(ann, interrupt=True)

    def _show_message_text_popup(self, msg: dict):
        """Open a read-only dialog showing the full message text (100-char lines)."""
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        text = ""
        if msg_type in ("conversation", "textMessage"):
            text = msg_obj.get("conversation", "")
        elif msg_type == "extendedTextMessage":
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        if not text:
            return

        i18n = self.main_window.i18n
        # Split into 100-char lines
        lines = []
        while len(text) > 100:
            lines.append(text[:100])
            text = text[100:]
        if text:
            lines.append(text)
        full_text = "\n".join(lines)

        dlg = wx.Dialog(
            self.main_window,
            title=i18n.t("msg_text_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(480, 320),
        )
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        text_ctrl = wx.TextCtrl(
            panel, value=full_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        close_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)
        # ESC also closes (wx.ID_CANCEL handles this automatically)
        dlg.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CANCEL), close_btn)
        text_ctrl.SetFocus()
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def _on_menu_react(self, msg: dict):
        """Open the emoji picker dialog to react to a message."""
        i18n = self.main_window.i18n
        EMOJIS = [
            ("❤️", "❤️"),
            ("👍", "👍"),
            ("👎", "👎"),
            ("😂", "😂"),
            ("😮", "😮"),
            ("😢", "😢"),
            ("🙏", "🙏"),
            ("🔥", "🔥"),
            ("🎉", "🎉"),
            ("💯", "💯"),
            ("😎", "😎"),
            ("🥰", "🥰"),
        ]

        dlg = wx.Dialog(
            self.main_window,
            title=i18n.t("react_dialog_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
            size=(300, 380),
        )
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        hint_label = wx.StaticText(panel, label=i18n.t("react_dialog_hint"))
        sizer.Add(hint_label, 0, wx.ALL, 8)

        emoji_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        emoji_list.InsertColumn(0, i18n.t("react_dialog_title"), width=240)
        for emoji, display in EMOJIS:
            emoji_list.Append((display,))
        sizer.Add(emoji_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("cancel"))
        sizer.Add(cancel_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)

        selected_emoji = [None]

        def _on_emoji_activated(event):
            idx = event.GetIndex()
            if 0 <= idx < len(EMOJIS):
                selected_emoji[0] = EMOJIS[idx][0]
                dlg.EndModal(wx.ID_OK)

        def _on_emoji_selected(event):
            # Single click: just move selection, don't send yet
            pass

        emoji_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, _on_emoji_activated)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CANCEL))
        dlg.Bind(wx.EVT_CHAR_HOOK, lambda e: dlg.EndModal(wx.ID_CANCEL) if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())

        emoji_list.SetFocus()
        dlg.CentreOnParent()
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_OK and selected_emoji[0]:
            emoji = selected_emoji[0]
            msg_key = msg.get("key", {})
            threading.Thread(
                target=self._do_send_reaction,
                args=(msg_key, emoji),
                daemon=True,
            ).start()

    def _send_reaction(self, msg: dict, emoji: str):
        """Send reaction directly (called from most-used submenu)."""
        msg_key = msg.get("key", {})
        threading.Thread(
            target=self._do_send_reaction,
            args=(msg_key, emoji),
            daemon=True,
        ).start()

    def _do_send_reaction(self, msg_key: dict, emoji: str):
        """Background: send reaction via Evolution API."""
        jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        self.main_window.send_reaction(jid, msg_key, emoji)

    # ── Attachment handling ──────────────────────────────────────────────────

    _PHOTO_VIDEO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp",
                        ".mp4", ".avi", ".mov", ".mkv", ".3gp"}
    _AUDIO_EXT       = {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".flac"}
    _EXT_TYPE_MAP    = {
        ".jpg": "image", ".jpeg": "image", ".png": "image",
        ".gif": "image", ".webp": "image",
        ".mp4": "video", ".avi": "video", ".mov": "video",
        ".mkv": "video", ".3gp": "video",
        ".mp3": "audio", ".ogg": "audio", ".wav": "audio",
        ".m4a": "audio", ".aac": "audio", ".flac": "audio",
    }

    def on_add_attachment(self, event=None):
        """Open a popup menu to choose the attachment type."""
        if self.conversation is None:
            return
        i18n = self.main_window.i18n
        menu = wx.Menu()
        pv_item  = menu.Append(wx.ID_ANY, i18n.t("attachment_photos_videos"))
        doc_item = menu.Append(wx.ID_ANY, i18n.t("attachment_document"))
        aud_item = menu.Append(wx.ID_ANY, i18n.t("attachment_audio_file"))
        con_item = menu.Append(wx.ID_ANY, i18n.t("attachment_contact"))
        self.Bind(wx.EVT_MENU, self._on_attach_photo_video, pv_item)
        self.Bind(wx.EVT_MENU, self._on_attach_document,    doc_item)
        self.Bind(wx.EVT_MENU, self._on_attach_audio_file,  aud_item)
        self.Bind(wx.EVT_MENU, self._on_attach_contact,     con_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_attach_photo_video(self, event):
        i18n = self.main_window.i18n
        wildcard = (
            f"{i18n.t('attachment_photos_videos')} "
            "(*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv)|"
            "*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv"
        )
        with wx.FileDialog(
            self, i18n.t("attachment_photos_videos"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            for path in dlg.GetPaths():
                ext      = os.path.splitext(path)[1].lower()
                mtype    = self._EXT_TYPE_MAP.get(ext, "image")
                self._staged_attachments.append({"path": path, "media_type": mtype})
        if self._staged_attachments:
            self._show_attachment_panel()

    def _on_attach_document(self, event):
        with wx.FileDialog(
            self, self.main_window.i18n.t("attachment_document"),
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            for path in dlg.GetPaths():
                self._staged_attachments.append(
                    {"path": path, "media_type": "document"}
                )
        if self._staged_attachments:
            self._show_attachment_panel()

    def _on_attach_audio_file(self, event):
        i18n     = self.main_window.i18n
        wildcard = (
            f"{i18n.t('attachment_audio_file')} "
            "(*.mp3;*.ogg;*.wav;*.m4a;*.aac;*.flac)|"
            "*.mp3;*.ogg;*.wav;*.m4a;*.aac;*.flac"
        )
        with wx.FileDialog(
            self, i18n.t("attachment_audio_file"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            for path in dlg.GetPaths():
                self._staged_attachments.append(
                    {"path": path, "media_type": "audio"}
                )
        if self._staged_attachments:
            self._show_attachment_panel()

    def _on_attach_contact(self, event):
        from ui.dialogs.attach_contact_dialog import AttachContactDialog
        dlg = AttachContactDialog(self.main_window)
        if dlg.ShowModal() != wx.ID_OK or dlg.selected_contact is None:
            dlg.Destroy()
            return
        contact    = dlg.selected_contact
        dlg.Destroy()
        remote_jid = self.conversation.get("remoteJid", "")
        if not remote_jid:
            return
        local_id = str(uuid.uuid4())
        name = (
            contact.get("name") or contact.get("pushName")
            or contact.get("verifiedName")
            or format_number(contact.get("remoteJid", ""))
        )
        virtual_msg = {
            "_local_pending": True,
            "_local_id":      local_id,
            "key": {"id": local_id, "fromMe": True, "remoteJid": remote_jid},
            "messageType": "contactMessage",
            "message": {
                "contactMessage": {
                    "displayName": name,
                    "vcard": "",
                }
            },
            "messageTimestamp": int(time.time()),
            "pushName": "",
        }
        self._sorted_messages.append(virtual_msg)
        self.messages_list.Append((self._render_message_line(virtual_msg),))
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)
        pm = PendingMessage(local_id, remote_jid, contact_info=contact,
                            quoted=self._quoted_message)
        self.main_window.message_queue.enqueue(pm)
        self._on_cancel_reply()  # clear quoted state after send

    def _show_attachment_panel(self):
        self._rebuild_attachment_list()
        self.message_label.Hide()
        self.message_field.Hide()
        self.send_message_btn.Hide()
        self.record_voice_message_btn.Hide()
        self._add_attachment_btn.Hide()
        self._attachment_panel.Show()
        self.conversation_panel.Layout()
        self._caption_field.SetFocus()

    def _rebuild_attachment_list(self):
        """Rebuild the per-file remove-buttons to match _staged_attachments."""
        i18n  = self.main_window.i18n
        panel = self._attachments_list_panel
        sizer = self._attachments_list_sizer
        for child in list(panel.GetChildren()):
            child.Destroy()
        sizer.Clear()
        for att in self._staged_attachments:
            filename = os.path.basename(att["path"])
            btn = wx.Button(
                panel,
                label=f"{i18n.t('remove_attachment')} {filename}",
            )
            btn.Bind(
                wx.EVT_BUTTON,
                lambda evt, p=att["path"]: self._on_remove_attachment(p),
            )
            sizer.Add(btn, 0, wx.BOTTOM, 3)
        panel.Layout()
        if self._attachment_panel.IsShown():
            self._attachment_panel.Layout()
            self.conversation_panel.Layout()

    def _on_remove_attachment(self, path: str):
        """Remove one staged file and rebuild the list (or close the panel)."""
        self._staged_attachments = [
            a for a in self._staged_attachments if a["path"] != path
        ]
        if not self._staged_attachments:
            self._hide_attachment_panel()
        else:
            self._rebuild_attachment_list()

    def _hide_attachment_panel(self):
        self._staged_attachments = []
        self._attachment_panel.Hide()
        if hasattr(self, "message_label"):
            self.message_label.Show()
            self.message_field.Show()
            if self.message_field.GetValue().strip():
                self.send_message_btn.Show()
            else:
                self.record_voice_message_btn.Show()
            self._add_attachment_btn.Show()
        if hasattr(self, "conversation_panel") and self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _on_add_more_files(self, event):
        """Re-open the file picker to add more files to the staging list."""
        self.on_add_attachment(event)

    def _on_send_attachment(self, event=None):
        """Enqueue all staged attachments as outgoing messages."""
        if not self._staged_attachments or self.conversation is None:
            return
        remote_jid = self.conversation.get("remoteJid", "")
        if not remote_jid:
            return
        caption = self._caption_field.GetValue().strip()

        _VTYPE = {
            "image":    "imageMessage",
            "video":    "videoMessage",
            "audio":    "audioMessage",
            "document": "documentMessage",
        }
        # Capture quoted state before looping (cleared after all enqueued)
        quoted = self._quoted_message

        for attachment in list(self._staged_attachments):
            path       = attachment["path"]
            media_type = attachment.get("media_type", "document")
            vtype      = _VTYPE.get(media_type, "documentMessage")
            local_id   = str(uuid.uuid4())
            virtual_msg = {
                "_local_pending": True,
                "_local_id":      local_id,
                "key": {"id": local_id, "fromMe": True, "remoteJid": remote_jid},
                "messageType": vtype,
                "message": {
                    vtype: {
                        "caption":  caption,
                        "fileName": os.path.basename(path),
                        "mimetype": mimetypes.guess_type(path)[0]
                                    or "application/octet-stream",
                    }
                },
                "messageTimestamp": int(time.time()),
                "pushName": "",
            }
            self._sorted_messages.append(virtual_msg)
            self.messages_list.Append((self._render_message_line(virtual_msg),))
            last = self.messages_list.GetItemCount() - 1
            if last >= 0:
                self.messages_list.EnsureVisible(last)
            pm = PendingMessage(
                local_id, remote_jid,
                media_path=path, media_type=media_type, caption=caption,
                quoted=quoted,
            )
            self.main_window.message_queue.enqueue(pm)

        self._on_cancel_reply()  # clear quoted state after send
        self._hide_attachment_panel()
        self.message_field.SetFocus()

        # Refresh conversation list preview to show the last sent attachment.
        self.main_window.set_chats()

    # ── Contact message helpers ──────────────────────────────────────────────

    def _jid_from_vcard(self, vcard: str) -> str | None:
        """Extract the WhatsApp JID from a vCard string."""
        if not vcard:
            return None
        m = re.search(r"waid=(\d+)", vcard)
        if m:
            return m.group(1) + "@s.whatsapp.net"
        m2 = re.search(r"TEL[^:]*:\+?([\d\s\-()]+)", vcard)
        if m2:
            digits = re.sub(r"\D", "", m2.group(1))
            if digits:
                return digits + "@s.whatsapp.net"
        return None

    def _on_contact_converse(self, event):
        """Navigate to the conversation with the contact from the selected message."""
        if not self._contact_msg_jid:
            return
        chat = self.main_window.chats.get(self._contact_msg_jid)
        if chat is not None:
            self.navigate_to_conversation(chat)

    # ── Real-time incoming message ────────────────────────────────────────────

    def on_incoming_message(self, remote_jid: str, msg: dict):
        """
        Called (on the main thread) when a new message arrives via WebSocket.
        If the conversation matching remote_jid is currently open, appends the
        message to the list; otherwise does nothing (the unread badge in the
        conversations list is updated separately via set_chats).
        """
        if self.conversation is None:
            return
        if self.conversation.get("remoteJid", "") != remote_jid:
            return
        # ── Reaction messages: update reaction_map and re-render original ────
        if msg.get("messageType") == "reactionMessage":
            reaction = (msg.get("message") or {}).get("reactionMessage") or {}
            emoji    = reaction.get("text", "")
            orig_id  = (reaction.get("key") or {}).get("id", "")
            if orig_id:
                if orig_id not in self._reaction_map:
                    self._reaction_map[orig_id] = {}
                if emoji:
                    self._reaction_map[orig_id][emoji] = (
                        self._reaction_map[orig_id].get(emoji, 0) + 1
                    )
                elif orig_id in self._reaction_map:
                    # empty emoji = remove reaction (just rebuild, can't easily track sender)
                    pass
                # Re-render the original message in the list
                for i, m in enumerate(self._sorted_messages):
                    if not self._is_separator(m) and m.get("key", {}).get("id") == orig_id:
                        self.messages_list.SetItemText(i, self._render_message_line(m))
                        break
            return  # Don't add reaction as a separate row
        # Avoid duplicates
        msg_id = msg.get("key", {}).get("id", "")
        if msg_id:
            for existing in self._sorted_messages:
                if self._is_separator(existing):
                    continue
                if existing.get("key", {}).get("id", "") == msg_id:
                    return

        # Manage unread separator
        if self._unread_sep_idx == -1:
            # First new message in this session — insert separator before it
            sep_pos = len(self._sorted_messages)
            sep = {"_type": "unread_separator", "count": 1}
            self._sorted_messages.insert(sep_pos, sep)
            self.messages_list.InsertItem(sep_pos, self._render_separator(1))
            self._unread_sep_idx = sep_pos
        else:
            # Separator already present — increment its count
            sep = self._sorted_messages[self._unread_sep_idx]
            sep["count"] = sep.get("count", 0) + 1
            self.messages_list.SetItemText(
                self._unread_sep_idx, self._render_separator(sep["count"])
            )

        # Append the real message (focus must NOT move)
        self._sorted_messages.append(msg)
        self.messages_list.Append((self._render_message_line(msg),))
        # Scroll to the new message but keep keyboard focus where it is
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)

    def navigate_to_jid(self, jid: str):
        """Select and open the conversation matching jid, clearing any search."""
        # Clear search so all chats are visible
        if self.search_field.GetValue():
            self.search_field.SetValue("")
            self.main_window.add_chats_to_ui()

        # Find the chat index and activate it
        for i, chat in enumerate(self.chats_list):
            if chat.get("remoteJid", "") == jid:
                self.conversations_list.Focus(i)
                self.conversations_list.Select(i)
                self.conversations_list.EnsureVisible(i)
                self.navigate_to_conversation(chat)
                break

    # ── Populate ─────────────────────────────────────────────────────────────

    def populate_messages(self):
        self.messages_list.DeleteAllItems()
        self._unread_sep_idx = -1
        self._reaction_map = {}
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

        # Build reaction map from all reaction messages
        for m in messages_sorted:
            if isinstance(m, dict) and m.get("messageType") == "reactionMessage":
                reaction = (m.get("message") or {}).get("reactionMessage") or {}
                emoji    = reaction.get("text", "")
                orig_id  = (reaction.get("key") or {}).get("id", "")
                if orig_id:
                    if orig_id not in self._reaction_map:
                        self._reaction_map[orig_id] = {}
                    if emoji:
                        self._reaction_map[orig_id][emoji] = (
                            self._reaction_map[orig_id].get(emoji, 0) + 1
                        )

        # Exclude reaction messages — they must not affect index mapping
        displayable = [
            m for m in messages_sorted if m.get("messageType", "") != "reactionMessage"
        ]

        # Insert unread separator before the first unread message
        unread_count = int((self.conversation or {}).get("unreadCount") or 0)
        if unread_count > 0 and len(displayable) >= unread_count:
            sep_pos = len(displayable) - unread_count
            sep = {"_type": "unread_separator", "count": unread_count}
            displayable = displayable[:sep_pos] + [sep] + displayable[sep_pos:]
            self._unread_sep_idx = sep_pos

        # ── Pagination: show only last N messages ────────────────────────────
        self._all_sorted_messages = displayable
        limit = int(
            self.main_window.settings.get("ui", {}).get("messages_page_size", 50)
        )
        if len(displayable) > limit:
            self._messages_offset = len(displayable) - limit
            paginated = displayable[self._messages_offset:]
            if self._unread_sep_idx >= 0:
                self._unread_sep_idx -= self._messages_offset
                if self._unread_sep_idx < 0:
                    self._unread_sep_idx = -1
        else:
            self._messages_offset = 0
            paginated = displayable

        self._sorted_messages = paginated

        for msg in paginated:
            self.messages_list.Append((self._render_message_line(msg),))

        # Make the unread separator visible (focus is set by navigate_to_conversation)
        if self._unread_sep_idx >= 0:
            self.messages_list.EnsureVisible(self._unread_sep_idx)
            self.messages_list.Focus(self._unread_sep_idx)
            self.messages_list.Select(self._unread_sep_idx)


# ── Archived Conversations Panel ─────────────────────────────────────────────


class ArchivedConversationsPanel(wx.Panel):
    """
    Shows archived chats in a list.  Activating a chat opens it in the
    main ConversationsPanel.  A context menu allows unarchiving.
    """

    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.chats_list: list = []
        self.chat_names: list = []
        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        i18n  = self.main_window.i18n
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.conversations_label = wx.StaticText(
            self, label=i18n.t("archived_chats")
        )
        sizer.Add(self.conversations_label, 0, wx.LEFT | wx.TOP, 5)

        self.conversations_list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self.conversations_list.InsertColumn(0, i18n.t("archived_chats"), width=250)
        self.conversations_list.Bind(
            wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected
        )
        self.conversations_list.Bind(
            wx.EVT_CONTEXT_MENU, self.on_context_menu
        )
        self.conversations_list.Bind(wx.EVT_KEY_DOWN, self._on_arch_list_key_down)
        sizer.Add(self.conversations_list, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_arch_list_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_SPACE:
            idx = self.conversations_list.GetFocusedItem()
            if idx >= 0:
                self.conversations_list.Select(idx)
                class _E:
                    def GetIndex(self): return idx
                self.on_conversation_selected(_E())
        else:
            event.Skip()

    def on_conversation_selected(self, event):
        index = event.GetIndex()
        try:
            chat = self.chats_list[index]
        except IndexError:
            return
        mw = self.main_window
        # Switch to conversations panel and open the chat there
        mw.archived_conversations_panel.Hide()
        mw.conversations_panel.Show()
        mw.content_panel.Layout()
        mw.conversations_panel.navigate_to_conversation(chat)

    def on_context_menu(self, event):
        selected = self.conversations_list.GetFirstSelected()
        if selected < 0 or selected >= len(self.chats_list):
            return
        chat = self.chats_list[selected]
        jid  = chat.get("remoteJid", "")
        i18n = self.main_window.i18n
        menu = wx.Menu()

        unarch_item = menu.Append(wx.ID_ANY, i18n.t("unarchive_chat"))
        self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_unarchive(j), unarch_item)

        del_item = menu.Append(wx.ID_ANY, i18n.t("delete_chat"))
        self.Bind(
            wx.EVT_MENU,
            lambda e, j=jid: self._on_delete(j),
            del_item,
        )

        self.PopupMenu(menu)
        menu.Destroy()

    def _on_unarchive(self, jid: str):
        self.main_window.unarchive_chat(jid)

    def _on_delete(self, jid: str):
        i18n = self.main_window.i18n
        if wx.MessageBox(
            i18n.t("delete_confirm_msg"),
            i18n.t("delete_chat"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) == wx.YES:
            self.main_window.delete_chat_local(jid)

    def refresh_labels(self):
        i18n = self.main_window.i18n
        self.conversations_label.SetLabel(i18n.t("archived_chats"))
        col = wx.ListItem()
        col.SetText(i18n.t("archived_chats"))
        self.conversations_list.SetColumn(0, col)
