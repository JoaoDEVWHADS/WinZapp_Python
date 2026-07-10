import base64 as _b64
import logging
import mimetypes
import os
import re
import tempfile
import threading
import time
import uuid
import wx
import wx.adv
import pyperclip
import pyaudio
import wave
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
    AccessibleMessagesListControl,
    AccessibleReadMoreButton,
    CompatListBoxMessagesCtrl,
)
from core.utils import format_number, decrypt_bytes, is_phone_like, encrypt, effective_unread_count
from app_paths import data_path
from core.message_queue import PendingMessage
from datetime import datetime

# Compiled URL regex used for link extraction from message text
_URL_RE = re.compile(r'https?://\S+|www\.\S+')


def _fmt_last_seen(ts, i18n) -> str:
    """Format a Unix timestamp as a localized last-seen string."""
    if not ts:
        return ""
    try:
        from datetime import datetime as _dt, timedelta as _td
        ts_val = int(ts)
        if ts_val > 1_000_000_000_000:
            ts_val //= 1000
        dt       = _dt.fromtimestamp(ts_val)
        now      = _dt.now()
        time_str = dt.strftime("%H:%M")
        if dt.date() == now.date():
            return i18n.t("last_seen_today").format(time=time_str)
        if dt.date() == (now - _td(days=1)).date():
            return i18n.t("last_seen_yesterday").format(time=time_str)
        date_str = dt.strftime(i18n.t("date_fmt"))
        return i18n.t("last_seen_date").format(date=date_str, time=time_str)
    except Exception:
        return ""


class ConversationsPanel(wx.Panel):
    # Windows' native SysListView32 (the classic wx.ListCtrl) truncates each
    # item's accessible text to this many characters — used to decide whether
    # the "Ler mais" button should appear for the focused row.
    _LIST_CTRL_TEXT_LIMIT = 512

    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent
        self.chats_list = []
        self.chat_names = []
        self.conversation = None
        self.conversation_name = ""
        self._last_open_jid = ""

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
        _saved_speed = self.main_window.settings.get("audio_playback", {}).get("audio_default_speed", 1.0)
        try:
            self._audio_speed_index = self._audio_speed_steps.index(float(_saved_speed))
        except (ValueError, TypeError):
            self._audio_speed_index = 0
        self._audio_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_audio_timer, self._audio_timer)
        # msg_id → position (samples) saved when a *different* audio starts while
        # this one is still mid-play.  Restored the next time _play_audio() is
        # called for the same message so playback resumes where it was left off.
        self._audio_positions: dict = {}
        # JID of the conversation where the current audio was started; used by
        # _auto_chain_next_audio and navigate_to_conversation to avoid operating
        # on the wrong conversation's message list.
        self._audio_conv_jid: str = ""

        # ── Typing status state ─────────────────────────────────────────────
        self._is_typing = False

        # ── Voice recording state ───────────────────────────────────────────
        self._is_recording         = False
        self._recording_paused     = False
        self._recording_frames: list = []   # list of bytes chunks from callback
        self._recording_stream     = None   # pyaudio.Stream
        self._recording_pa         = None   # pyaudio.PyAudio instance
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
        # Unread count captured before mark-as-read thread starts (avoids race)
        self._pending_open_unread: int = 0
        # True while the separator was placed from the initial open (not from a live message)
        self._sep_from_open: bool = False
        # One-shot timer: dismiss the separator 2 s after focus reaches it
        self._unread_sep_dismiss_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_unread_sep_dismiss_timer,
                  self._unread_sep_dismiss_timer)


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
        # @mention (display_name, jid) pairs for the currently focused message
        self._current_mentions: list = []

        # ── @mention input state ─────────────────────────────────────────────
        # Whether a mention suggestion dropdown is currently active
        self._mention_active: bool = False
        # Character position in the message field where the @ was typed
        self._mention_start_pos: int = -1
        # Text typed after the @ (the current filter query)
        self._mention_query: str = ""
        # Filtered suggestion pairs [(display_name, jid), ...]
        self._mention_suggestions: list = []
        # Participants of the current group, cached on conversation open
        self._group_participants_cache: list = []
        # JIDs confirmed for @mention to be sent with the next message
        self._pending_mentions: list = []
        # Maps JID → display_name for each pending mention (used to replace
        # @DisplayName with @phonenumber in the API payload — WhatsApp only
        # renders a mention when the text contains the bare phone number after @).
        self._pending_mention_display_names: dict = {}

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
        self.search_field.Bind(wx.EVT_KEY_DOWN, self._on_search_field_key_down)
        self.search_field.SetAccessible(AccessibleSearchConversations("Ctrl+F"))
        outer_sizer.Add(self.search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # ── Nova conversa button ────────────────────────────────────────────
        self._new_conv_btn = wx.Button(self, label=i18n.t("new_conversation"))
        self._new_conv_btn.SetAccessible(AccessibleNewConversationButton())
        self._new_conv_btn.Bind(wx.EVT_BUTTON, self._on_new_conversation)
        outer_sizer.Add(self._new_conv_btn, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 5)

        # ── Conversation filter tabs ─────────────────────────────────────────
        # Tracks the active filter key: 'all' | 'unread' | 'groups' | 'individual'
        self._conv_filter = 'all'
        self._filter_radio = wx.RadioBox(
            self,
            label=i18n.t("conv_filter_label"),
            choices=[
                i18n.t("conv_filter_all"),
                i18n.t("conv_filter_unread"),
                i18n.t("conv_filter_groups"),
                i18n.t("conv_filter_individual"),
            ],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self._filter_radio.Bind(wx.EVT_RADIOBOX, self._on_filter_changed)
        outer_sizer.Add(self._filter_radio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

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

        # The messages list control type is configurable: the classic
        # wx.ListCtrl (default — works with the OS native ListView, but
        # truncates each row's accessible text to ~512 characters) or
        # CompatListBoxMessagesCtrl (full message text via a native
        # wx.ListBox, which isn't subject to that truncation and — unlike
        # the DataView-based control this replaced — is natively accessible).
        message_list_mode = self.main_window.settings.get("user_interface", {}).get(
            "message_list_mode", "classic"
        )
        # "dataview" was the old (now-removed) alternative mode name — treat
        # it as "listbox" so settings saved before the switch still resolve
        # to the equivalent current option.
        if message_list_mode == "dataview":
            message_list_mode = "listbox"
        self._message_list_mode = message_list_mode
        if message_list_mode == "listbox":
            self.messages_list = CompatListBoxMessagesCtrl(self.conversation_panel)
        else:
            self.messages_list = wx.ListCtrl(
                self.conversation_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
            )
        # i18n "messages" carries a "&" mnemonic for the StaticText label above
        # the list; list-column headers and accessible names don't interpret
        # "&" as a mnemonic, so it must be stripped there to avoid a stray "&"
        # being shown/spoken.
        self.messages_list.InsertColumn(0, i18n.t("messages").replace("&", ""), width=360)
        self._messages_list_accessible = AccessibleMessagesListControl(i18n.t("messages").replace("&", ""))
        self.messages_list.SetAccessible(self._messages_list_accessible)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_message_activated)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)
        self.messages_list.Bind(wx.EVT_LIST_ITEM_FOCUSED, self._on_message_focused)
        self.messages_list.Bind(wx.EVT_CONTEXT_MENU, self.on_messages_context_menu)
        self.messages_list.Bind(wx.EVT_KEY_DOWN, self._on_messages_list_key_down)
        conv_sizer.Add(self.messages_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── "Ler mais" button (classic ListCtrl only) ─────────────────────────
        # SysListView32 truncates each row's accessible text to ~512 characters,
        # so a screen reader can't read the tail of a long text message just by
        # focusing it. This button is the first focusable control after the
        # list (created here, before any other conversation_panel child) and is
        # only shown when the focused row is a truncated text message.
        self._read_more_btn = wx.Button(
            self.conversation_panel, label=i18n.t("read_more_button")
        )
        self._read_more_btn.SetAccessible(AccessibleReadMoreButton())
        self._read_more_btn.Bind(wx.EVT_BUTTON, self._on_read_more)
        conv_sizer.Add(self._read_more_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._read_more_btn.Hide()

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

        # ── Mention controls (shown when focused message contains @mentions) ──
        self._mentions_panel = wx.Panel(self.conversation_panel)
        self._mentions_label = wx.StaticText(
            self._mentions_panel, label=i18n.t("mentions_section_label")
        )
        self._mentions_sizer = wx.BoxSizer(wx.VERTICAL)
        self._mentions_sizer.Add(self._mentions_label, 0, wx.LEFT | wx.TOP, 3)
        self._mentions_panel.SetSizer(self._mentions_sizer)
        self._mentions_panel.Hide()
        conv_sizer.Add(self._mentions_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

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

        # ── Mention suggestion list (hidden; shown when user types @ in group) ─
        self._mention_panel = wx.Panel(self.conversation_panel)
        _mention_sizer = wx.BoxSizer(wx.VERTICAL)
        self._mention_list_label = wx.StaticText(
            self._mention_panel, label=i18n.t("mention_suggestions_label")
        )
        _mention_sizer.Add(self._mention_list_label, 0, wx.LEFT | wx.TOP, 3)
        self._mention_list = wx.ListBox(self._mention_panel, style=wx.LB_SINGLE)
        self._mention_list.Bind(wx.EVT_KEY_DOWN, self._on_mention_list_key_down)
        self._mention_list.Bind(wx.EVT_CHAR,     self._on_mention_list_char)
        _mention_sizer.Add(self._mention_list, 0, wx.EXPAND | wx.ALL, 3)
        self._mention_panel.SetSizer(_mention_sizer)
        self._mention_panel.Hide()
        conv_sizer.Add(self._mention_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # ── Message input ───────────────────────────────────────────────────
        self.message_label = wx.StaticText(
            self.conversation_panel, label=i18n.t("type_message")
        )
        conv_sizer.Add(self.message_label, 0, wx.LEFT | wx.TOP, 5)

        self.message_field = wx.TextCtrl(
            self.conversation_panel,
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP,
        )
        self.message_field.Bind(wx.EVT_TEXT,       self.on_change_message_field)
        self.message_field.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.message_field.Bind(wx.EVT_KEY_DOWN,   self._on_message_field_key_down)
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

        # ── Pending mention pills (one label + remove button per @mention) ──
        self._pending_mentions_panel = wx.Panel(self.conversation_panel)
        self._pending_mentions_sizer = wx.BoxSizer(wx.VERTICAL)
        self._pending_mentions_panel.SetSizer(self._pending_mentions_sizer)
        self._pending_mentions_panel.Hide()
        conv_sizer.Add(
            self._pending_mentions_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5
        )

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
        self.conversation_panel.Bind(wx.EVT_CHAR_HOOK, self._on_conversation_char_hook)
        self.conversation_panel.Hide()
        outer_sizer.Add(self.conversation_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(outer_sizer)

    # ── Accelerators ────────────────────────────────────────────────────────

    def create_accelerator_table(self):
        self.ID_CTRL_F              = wx.NewIdRef()
        self.ID_CTRL_N              = wx.NewIdRef()
        self.ID_DELETE_CONV         = wx.NewIdRef()
        self.ID_ALT_SHIFT_C_LIST    = wx.NewIdRef()  # copy number from chat list
        self.ID_CONV_DATA_LIST      = wx.NewIdRef()
        self.ID_TOGGLE_READ_LIST    = wx.NewIdRef()
        self.ID_MUTE_LIST           = wx.NewIdRef()
        self.ID_BLOCK_LIST          = wx.NewIdRef()
        self.ID_CLEAR_LIST          = wx.NewIdRef()
        self.ID_ARCHIVE_LIST        = wx.NewIdRef()
        self.ID_PIN_LIST            = wx.NewIdRef()
        self.ID_CLOSE_CONV_LIST     = wx.NewIdRef()
        CS = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
        AS = wx.ACCEL_ALT | wx.ACCEL_SHIFT
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL,   ord("F"),        self.ID_CTRL_F),
            (wx.ACCEL_CTRL,   ord("N"),        self.ID_CTRL_N),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE,   self.ID_DELETE_CONV),
            (AS,              ord("C"),         self.ID_ALT_SHIFT_C_LIST),
            (CS,              ord("D"),         self.ID_CONV_DATA_LIST),
            (CS,              ord("M"),         self.ID_TOGGLE_READ_LIST),
            (AS,              ord("S"),         self.ID_MUTE_LIST),
            (CS,              ord("B"),         self.ID_BLOCK_LIST),
            (CS,              ord("L"),         self.ID_CLEAR_LIST),
            (wx.ACCEL_CTRL,   ord("Q"),         self.ID_ARCHIVE_LIST),
            (wx.ACCEL_CTRL,   ord("P"),         self.ID_PIN_LIST),
            (wx.ACCEL_CTRL,   ord("W"),         self.ID_CLOSE_CONV_LIST),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_ctrl_f,                    id=self.ID_CTRL_F)
        self.Bind(wx.EVT_MENU, self._on_new_conversation,         id=self.ID_CTRL_N)
        self.Bind(wx.EVT_MENU, self._on_accel_delete_conv,        id=self.ID_DELETE_CONV)
        self.Bind(wx.EVT_MENU, self._on_accel_copy_number_list,   id=self.ID_ALT_SHIFT_C_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_conversation_data_list, id=self.ID_CONV_DATA_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_toggle_read_list,    id=self.ID_TOGGLE_READ_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_mute_list,           id=self.ID_MUTE_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_block_list,          id=self.ID_BLOCK_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_clear_list,          id=self.ID_CLEAR_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_archive_list,        id=self.ID_ARCHIVE_LIST)
        self.Bind(wx.EVT_MENU, self._on_accel_pin_list,            id=self.ID_PIN_LIST)
        self.Bind(wx.EVT_MENU, self.on_context_menu_close,         id=self.ID_CLOSE_CONV_LIST)

    def create_accel_conversation(self):
        # ── Navigation / recording ──────────────────────────────────────────
        self.ID_CTRL_R          = wx.NewIdRef()  # record voice            (Ctrl+R)
        self.ID_ALT_2           = wx.NewIdRef()  # jump to last message    (Alt+2)
        self.ID_ESC             = wx.NewIdRef()  # close conversation      (Esc)
        self.CTRL_W             = wx.NewIdRef()  # close conversation      (Ctrl+W)
        self.ID_CTRL_SHIFT_D    = wx.NewIdRef()  # conv data / discard     (Ctrl+Shift+D)
        # ── Attachment / media ───────────────────────────────────────────────
        self.ID_CTRL_SHIFT_A    = wx.NewIdRef()  # add attachment          (Ctrl+Shift+A)
        self.ID_CTRL_SHIFT_B    = wx.NewIdRef()  # block contact           (Ctrl+Shift+B)
        # ── Message-level ────────────────────────────────────────────────────
        self.ID_ALT_R           = wx.NewIdRef()  # reply                   (Alt+R)
        self.ID_ALT_SHIFT_D     = wx.NewIdRef()  # message data            (Alt+Shift+D)
        self.ID_CTRL_SHIFT_E    = wx.NewIdRef()  # forward                 (Ctrl+Shift+E)
        self.ID_CTRL_SHIFT_P    = wx.NewIdRef()  # pause/resume recording  (Ctrl+Shift+P)
        self.ID_CTRL_SHIFT_R    = wx.NewIdRef()  # react to message        (Ctrl+Shift+R)
        self.ID_DELETE_MSG      = wx.NewIdRef()  # delete focused message  (Delete)
        self.ID_CTRL_C          = wx.NewIdRef()  # copy message            (Ctrl+C)
        self.ID_ALT_C           = wx.NewIdRef()  # show text popup         (Alt+C)
        self.ID_ALT_E           = wx.NewIdRef()  # edit message            (Alt+E)
        self.ID_ALT_L           = wx.NewIdRef()  # read-more (truncated)   (Alt+L)
        self.ID_ALT_SHIFT_L     = wx.NewIdRef()  # announce message status (Alt+Shift+L)
        self.ID_ALT_SHIFT_K     = wx.NewIdRef()  # announce message date   (Alt+Shift+K)
        # ── Conversation-level ───────────────────────────────────────────────
        self.ID_CTRL_SHIFT_S    = wx.NewIdRef()  # save as / download      (Ctrl+Shift+S)
        self.ID_CTRL_SHIFT_M    = wx.NewIdRef()  # toggle read / unread    (Ctrl+Shift+M)
        self.ID_CTRL_SHIFT_L    = wx.NewIdRef()  # clear conversation      (Ctrl+Shift+L)
        # ── Search / unread jump ─────────────────────────────────────────────
        self.ID_CTRL_SHIFT_F    = wx.NewIdRef()  # open search panel       (Ctrl+Shift+F)
        self.ID_ALT_3           = wx.NewIdRef()  # jump to unread sep      (Alt+3)
        # ── Conv-list shortcuts ───────────────────────────────────────────────
        self.ID_CONV_PIN        = wx.NewIdRef()  # pin / unpin chat        (Ctrl+P)
        self.ID_CONV_ARCHIVE    = wx.NewIdRef()  # archive / unarchive     (Ctrl+Q)
        # ── Group actions ────────────────────────────────────────────────────
        self.ID_ALT_SHIFT_R     = wx.NewIdRef()  # reply privately         (Alt+Shift+R)
        self.ID_ALT_SHIFT_C     = wx.NewIdRef()  # copy phone number       (Alt+Shift+C)
        self.ID_ALT_SHIFT_V     = wx.NewIdRef()  # converse with           (Alt+Shift+V)
        self.ID_ALT_SHIFT_Q     = wx.NewIdRef()  # goto quoted message     (Alt+Shift+Q)
        self.ID_ALT_SHIFT_S     = wx.NewIdRef()  # mute / unmute           (Alt+Shift+S)
        # ── Message star ─────────────────────────────────────────────────────
        self.ID_CTRL_SHIFT_O    = wx.NewIdRef()  # star message            (Ctrl+Shift+O)
        # ── Audio speed ──────────────────────────────────────────────────────
        self.ID_ALT_COMMA       = wx.NewIdRef()  # decrease audio speed    (Alt+,)
        self.ID_ALT_PERIOD      = wx.NewIdRef()  # increase audio speed    (Alt+.)

        CS  = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
        AS  = wx.ACCEL_ALT  | wx.ACCEL_SHIFT
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL,    ord("R"),         self.ID_CTRL_R),
            (wx.ACCEL_ALT,     ord("2"),         self.ID_ALT_2),
            (wx.ACCEL_NORMAL,  wx.WXK_ESCAPE,    self.ID_ESC),
            (wx.ACCEL_CTRL,    ord("W"),          self.CTRL_W),
            (CS,               ord("D"),          self.ID_CTRL_SHIFT_D),
            (CS,               ord("A"),          self.ID_CTRL_SHIFT_A),
            (CS,               ord("B"),          self.ID_CTRL_SHIFT_B),
            (wx.ACCEL_ALT,     ord("R"),          self.ID_ALT_R),
            (AS,               ord("D"),          self.ID_ALT_SHIFT_D),
            (CS,               ord("E"),          self.ID_CTRL_SHIFT_E),
            (CS,               ord("P"),          self.ID_CTRL_SHIFT_P),
            (CS,               ord("R"),          self.ID_CTRL_SHIFT_R),
            (wx.ACCEL_NORMAL,  wx.WXK_DELETE,     self.ID_DELETE_MSG),
            (wx.ACCEL_CTRL,    ord("C"),          self.ID_CTRL_C),
            (wx.ACCEL_ALT,     ord("C"),          self.ID_ALT_C),
            (wx.ACCEL_ALT,     ord("E"),          self.ID_ALT_E),
            (wx.ACCEL_ALT,     ord("L"),          self.ID_ALT_L),
            (AS,               ord("L"),          self.ID_ALT_SHIFT_L),
            (AS,               ord("K"),          self.ID_ALT_SHIFT_K),
            (CS,               ord("S"),          self.ID_CTRL_SHIFT_S),
            (CS,               ord("M"),          self.ID_CTRL_SHIFT_M),
            (CS,               ord("L"),          self.ID_CTRL_SHIFT_L),
            (CS,               ord("F"),          self.ID_CTRL_SHIFT_F),
            (wx.ACCEL_ALT,     ord("3"),          self.ID_ALT_3),
            (AS,               ord("R"),          self.ID_ALT_SHIFT_R),
            (AS,               ord("C"),          self.ID_ALT_SHIFT_C),
            (AS,               ord("V"),          self.ID_ALT_SHIFT_V),
            (AS,               ord("Q"),          self.ID_ALT_SHIFT_Q),
            (AS,               ord("S"),          self.ID_ALT_SHIFT_S),
            (CS,               ord("O"),           self.ID_CTRL_SHIFT_O),
            (wx.ACCEL_ALT,     ord(","),           self.ID_ALT_COMMA),
            (wx.ACCEL_ALT,     ord("."),           self.ID_ALT_PERIOD),
        ])
        self.conversation_panel.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message,       id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self._on_accel_jump_last,           id=self.ID_ALT_2)
        self.Bind(wx.EVT_MENU, self.close_conversation,            id=self.ID_ESC)
        self.Bind(wx.EVT_MENU, self.close_conversation,            id=self.CTRL_W)
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_d,              id=self.ID_CTRL_SHIFT_D)
        self.Bind(wx.EVT_MENU, self.on_add_attachment,             id=self.ID_CTRL_SHIFT_A)
        self.Bind(wx.EVT_MENU, self._on_action_save_as,            id=self.ID_CTRL_SHIFT_S)
        self.Bind(wx.EVT_MENU, self._on_accel_reply,               id=self.ID_ALT_R)
        self.Bind(wx.EVT_MENU, self._on_accel_message_data,        id=self.ID_ALT_SHIFT_D)
        self.Bind(wx.EVT_MENU, self._on_accel_forward,             id=self.ID_CTRL_SHIFT_E)
        self.Bind(wx.EVT_MENU, self._on_ctrl_shift_p,              id=self.ID_CTRL_SHIFT_P)
        self.Bind(wx.EVT_MENU, self._on_accel_react,               id=self.ID_CTRL_SHIFT_R)
        self.Bind(wx.EVT_MENU, self._on_accel_delete_message,      id=self.ID_DELETE_MSG)
        self.Bind(wx.EVT_MENU, self._on_accel_copy_message,        id=self.ID_CTRL_C)
        self.Bind(wx.EVT_MENU, self._on_accel_show_text_popup,     id=self.ID_ALT_C)
        self.Bind(wx.EVT_MENU, self._on_accel_edit_message,        id=self.ID_ALT_E)
        self.Bind(wx.EVT_MENU, self._on_read_more,                 id=self.ID_ALT_L)
        self.Bind(wx.EVT_MENU, self._on_accel_msg_status,          id=self.ID_ALT_SHIFT_L)
        self.Bind(wx.EVT_MENU, self._on_accel_msg_datetime,        id=self.ID_ALT_SHIFT_K)
        self.Bind(wx.EVT_MENU, self._on_accel_block,               id=self.ID_CTRL_SHIFT_B)
        self.Bind(wx.EVT_MENU, self._on_accel_toggle_read,         id=self.ID_CTRL_SHIFT_M)
        self.Bind(wx.EVT_MENU, self._on_accel_clear,               id=self.ID_CTRL_SHIFT_L)
        self.Bind(wx.EVT_MENU, self._on_accel_open_search,         id=self.ID_CTRL_SHIFT_F)
        self.Bind(wx.EVT_MENU, self._on_accel_jump_unread,         id=self.ID_ALT_3)
        self.Bind(wx.EVT_MENU, self._on_accel_reply_private,       id=self.ID_ALT_SHIFT_R)
        self.Bind(wx.EVT_MENU, self._on_accel_copy_number_speak,   id=self.ID_ALT_SHIFT_C)
        self.Bind(wx.EVT_MENU, self._on_accel_alt_shift_v,         id=self.ID_ALT_SHIFT_V)
        self.Bind(wx.EVT_MENU, self._on_accel_goto_quoted,         id=self.ID_ALT_SHIFT_Q)
        self.Bind(wx.EVT_MENU, self._on_accel_mute,                id=self.ID_ALT_SHIFT_S)
        self.Bind(wx.EVT_MENU, self._on_accel_star,                 id=self.ID_CTRL_SHIFT_O)
        self.Bind(wx.EVT_MENU, self._on_audio_speed_decrease,      id=self.ID_ALT_COMMA)
        self.Bind(wx.EVT_MENU, self._on_audio_speed_increase,      id=self.ID_ALT_PERIOD)

    # ── Conversations list events ───────────────────────────────────────────

    def on_conversation_selected(self, event):
        self.on_conversation_selected_by_index(event.GetIndex())

    def on_conversation_selected_by_index(self, index):
        try:
            self.navigate_to_conversation(self.chats_list[index])
        except Exception:
            return

    def _stop_typing_for_current_conversation(self):
        """Stop typing/recording status for the currently open conversation, if active."""
        if self._is_typing and self.conversation is not None:
            jid = self.conversation.get("remoteJid", "")
            if jid and not jid.endswith("@newsletter"):
                self.main_window.send_typing_status(jid, False, jid.endswith("@g.us"))
            self._is_typing = False
        if self._is_recording and self.conversation is not None:
            jid = self.conversation.get("remoteJid", "")
            if jid and not jid.endswith("@newsletter"):
                self.main_window.send_recording_status(jid, False, jid.endswith("@g.us"))

    def navigate_to_conversation(self, conversation):
        if self.conversation is not None and self.conversation.get("remoteJid") == conversation.get("remoteJid"):
            self.conversation = conversation
            # Conversation already open — just focus the message input field.
            wx.CallAfter(self.message_field.SetFocus)
            return
        self._stop_typing_for_current_conversation()
        # Audio keeps playing across conversation switches.  Save the current
        # position so it can be restored if the same message is played again
        # after a different audio has taken over and closed the stream.
        if self._current_audio_id is not None and self._audio_stream is not None:
            try:
                _ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
                pos   = _ctrl.get_position()
                total = _ctrl.get_length()
                if 0 < pos < total:
                    self._audio_positions[self._current_audio_id] = pos
            except Exception:
                pass
        self._hide_audio_controls()
        self._hide_all_media_controls()
        self._hide_attachment_panel()
        self._unread_sep_idx = -1  # reset separator for new conversation
        self._sep_from_open = False
        self._first_unread_msg_id = None
        self._first_unread_count = 0
        if self._unread_sep_dismiss_timer.IsRunning():
            self._unread_sep_dismiss_timer.Stop()
        self._quoted_message = None
        self._reaction_map   = {}
        # Reset mention state for the new conversation
        self._pending_mentions.clear()
        self._pending_mention_display_names.clear()
        self._group_participants_cache = []
        self._hide_mention_suggestions()
        if hasattr(self, "_pending_mentions_panel"):
            self._rebuild_mention_pills()
        # Reset search state
        self._search_results    = []
        self._search_result_idx = -1
        if hasattr(self, "_search_panel") and self._search_panel.IsShown():
            self._search_panel.Hide()
            self._search_open_btn.Show()
            self._search_field.SetValue("")
        self.conversation = conversation
        _conv_jid = conversation.get("remoteJid", "")
        self._last_open_jid = _conv_jid
        self.conversation_name = (
            self.main_window._resolve_contact_name(conversation)
            or self.main_window.find_name_through_messages(conversation)
            or conversation.get("name", "")
            or ("" if _conv_jid.endswith("@g.us") else conversation.get("pushName", ""))
            or self.main_window.find_jid_through_messages(conversation)
            or self.main_window._format_jid_for_display(_conv_jid)
            or (self.main_window.i18n.t("unknown_group") if _conv_jid.endswith("@g.us") else self.main_window.i18n.t("unknown_contact"))
        )
        jid      = conversation.get("remoteJid", "")
        is_group = jid.endswith("@g.us")
        i18n     = self.main_window.i18n

        # Update conversation-data button
        self._conv_data_btn.SetLabel(
            i18n.t("group_data") if is_group else i18n.t("conversation_data")
        )
        display_note = self.conversation_name
        if not is_group and is_phone_like(display_note):
            display_note = f"{i18n.t('phone_label')}: {display_note}"
        self._conv_data_btn.SetNote(display_note)

        is_channel = jid.endswith("@newsletter")
        if is_channel:
            self.message_field.Disable()
            self.send_message_btn.Disable()
            self.record_voice_message_btn.Disable()
            self._add_attachment_btn.Disable()
            self.message_label.SetLabel(i18n.t("channel_read_only"))
        else:
            self.message_field.Enable()
            self.send_message_btn.Enable()
            self.record_voice_message_btn.Enable()
            self._add_attachment_btn.Enable()
            self.message_label.SetLabel(
                f"{i18n.t('type_message_group') if is_group else i18n.t('type_message')} {self.conversation_name}"
            )
            
        if hasattr(self, "_remove_quote_btn"):
            self._remove_quote_btn.Hide()
        self.conversation_panel.Show()
        self.Layout()
        # Snapshot before the background thread zeros unreadCount on the same dict
        self._pending_open_unread = effective_unread_count(conversation)
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
        # Subscribe to presence events for this contact so last-seen and typing
        # indicators arrive via onpresencechanged Socket.IO events.
        self.main_window.subscribe_presence(jid)
        # Background: cache group participants for @mention suggestions
        if is_group:
            threading.Thread(
                target=self._fetch_group_participants,
                args=(jid,),
                daemon=True,
            ).start()
        if self.search_field.GetValue().strip():
            self.search_field.Clear()
        self.populate_messages()

        # Re-show audio controls only if the playing audio message is focused.
        if (self._current_audio_id is not None
                and self._audio_conv_jid == jid
                and self._audio_stream is not None
                and self._focused_msg_id() == self._current_audio_id):
            self._show_audio_controls()
            self.audio_speed_btn.SetLabel(
                self._format_speed(self._audio_speed_steps[self._audio_speed_index])
            )


        # Move keyboard focus based on user preference.
        # Deferred via wx.CallAfter so this is the last item in the event
        # queue — prevents add_chats_to_ui (which may have been scheduled
        # earlier by restore_window on a notification click) from scheduling
        # its own lst.SetFocus and stealing focus away from the conversation.
        focus_setting = self.main_window.settings.get("user_interface", {}).get("focus_on_open", "message_field")
        if focus_setting == "unread_or_last":
            wx.CallAfter(self.messages_list.SetFocus)
        else:
            wx.CallAfter(self.message_field.SetFocus)

    def on_search_query_changed(self, event):
        # Route through add_chats_to_ui so the active filter and proper sort
        # order are both respected (add_chats_to_ui reads search_field itself).
        self.main_window.add_chats_to_ui()

    def _on_filter_changed(self, event):
        """Update the active conversation filter and rebuild the list."""
        _filter_map = ['all', 'unread', 'groups', 'individual']
        sel = self._filter_radio.GetSelection()
        self._conv_filter = _filter_map[sel] if 0 <= sel < len(_filter_map) else 'all'
        self.main_window.add_chats_to_ui()

    def on_ctrl_f(self, event):
        self.search_field.SetFocus()

    def _on_search_field_key_down(self, event):
        """Down arrow in the search field moves focus to the first conversation."""
        if event.GetKeyCode() == wx.WXK_DOWN:
            lst = self.conversations_list
            if lst.GetItemCount() > 0:
                lst.SetFocus()
                lst.Focus(0)
                lst.Select(0)
            return
        event.Skip()

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
        # Sync typing status with WPPConnect (only on state transitions)
        if self.conversation is not None:
            jid = self.conversation.get("remoteJid", "")
            if jid and not jid.endswith("@newsletter"):
                is_group = jid.endswith("@g.us")
                now_typing = bool(msg.strip())
                if now_typing != self._is_typing:
                    self._is_typing = now_typing
                    self.main_window.send_typing_status(jid, now_typing, is_group)
        self._on_text_changed_mention_check()

    def _on_conversation_char_hook(self, event):
        kc = event.GetKeyCode()
        # Intercept Esc and Enter when the mention suggestion list has focus so
        # they are handled here, before the accelerator table fires
        # close_conversation for Esc or any other panel-level binding.
        if hasattr(self, "_mention_panel") and self._mention_panel.IsShown():
            if kc == wx.WXK_ESCAPE:
                self._hide_mention_suggestions()
                wx.CallAfter(self.message_field.SetFocus)
                return  # do NOT Skip — blocks the Esc → close_conversation accelerator
            if wx.Window.FindFocus() is self._mention_list and kc in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                idx = self._mention_list.GetSelection()
                if 0 <= idx < len(self._mention_suggestions):
                    name, jid = self._mention_suggestions[idx]
                    self._insert_mention(name, jid)
                return  # do NOT Skip
        if not self._should_redirect_char_to_message(event):
            event.Skip()
            return

        char = chr(event.GetUnicodeKey())
        self.message_field.SetFocus()
        self.message_field.WriteText(char)

    def _should_redirect_char_to_message(self, event) -> bool:
        if self.conversation is None or not self.conversation_panel.IsShown():
            return False
        if not self.message_field.IsShown() or not self.message_field.IsEnabled():
            return False
        if self._is_recording:
            return False
        if event.ControlDown() or event.AltDown() or event.ShiftDown():
            return False
        if hasattr(event, "MetaDown") and event.MetaDown():
            return False

        key = event.GetUnicodeKey()
        if key == wx.WXK_NONE:
            return False
        try:
            # Only redirect alphanumeric characters — this prevents special
            # keys like Delete (127), Backspace (8), and other control/function
            # characters from being swallowed and written into the message field.
            if not chr(key).isalnum():
                return False
        except (ValueError, OverflowError):
            return False

        focus = wx.Window.FindFocus()
        if focus is self.message_field or isinstance(focus, wx.TextCtrl):
            return False

        return True

    def refresh_labels(self):
        """Update all translatable labels and column headers after a language change."""
        i18n = self.main_window.i18n

        self.conversations_label.SetLabel(i18n.t("conversations"))
        col = wx.ListItem()
        col.SetText(i18n.t("conversations"))
        self.conversations_list.SetColumn(0, col)
        self.search_label.SetLabel(i18n.t("search_conversations"))

        if hasattr(self, "_filter_radio"):
            self._filter_radio.SetLabel(i18n.t("conv_filter_label"))
            for _fi, _fk in enumerate([
                "conv_filter_all", "conv_filter_unread",
                "conv_filter_groups", "conv_filter_individual",
            ]):
                self._filter_radio.SetItemLabel(_fi, i18n.t(_fk))

        self._new_conv_btn.SetLabel(i18n.t("new_conversation"))
        self._search_open_btn.SetLabel(i18n.t("search_in_conv"))
        self._search_close_btn.SetLabel(i18n.t("search_close"))
        self._search_field_label.SetLabel(i18n.t("search_in_conv"))
        self._search_prev_btn.SetLabel(i18n.t("search_prev_result"))
        self._search_next_btn.SetLabel(i18n.t("search_next_result"))

        self.messages_label.SetLabel(i18n.t("messages"))
        col2 = wx.ListItem()
        col2.SetText(i18n.t("messages").replace("&", ""))
        self.messages_list.SetColumn(0, col2)
        if hasattr(self, "_messages_list_accessible"):
            self._messages_list_accessible._label = i18n.t("messages").replace("&", "")

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

        # Guard against a single user action enqueueing the same message
        # twice — e.g. Enter's key-repeat firing EVT_TEXT_ENTER more than
        # once for what felt like one press, or a stray duplicate BUTTON/
        # TEXT_ENTER event. Each duplicate created its own pending message
        # and both went through independently, so the "sent" sound played
        # twice and the recipient got the text twice.
        now = time.monotonic()
        last = getattr(self, "_last_sent_signature", None)
        if last is not None:
            last_text, last_jid, last_time = last
            if last_text == text and last_jid == remote_jid and (now - last_time) < 1.5:
                return
        self._last_sent_signature = (text, remote_jid, now)

        # ── Edit mode: update existing message ──────────────────────────────
        if self._editing_message_id is not None:
            msg_id = self._editing_message_id
            idx    = self._editing_message_index

            # Call WPPConnect API to update the message
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
        _raw_mentions = list(self._pending_mentions) if self._pending_mentions else []
        _mentioned = _raw_mentions or None
        if _mentioned and hasattr(self.main_window, "_canonical_mention_jids"):
            _mentioned = self.main_window._canonical_mention_jids(_raw_mentions)

        # Build the API text: WhatsApp only highlights a mention when the message
        # body contains @{phonenumber} (not @{display_name}).  Replace each
        # @DisplayName with @phone so the official client renders the mention.
        api_text = text
        if _raw_mentions:
            _normalize = getattr(self.main_window, "_normalize_jid", lambda j: j)
            _lid_map   = getattr(self.main_window, "_lid_to_phone", {})
            for raw_jid in _raw_mentions:
                display = self._pending_mention_display_names.get(raw_jid, "")
                if not display:
                    continue
                if raw_jid.endswith("@lid"):
                    phone = _lid_map.get(raw_jid, raw_jid).split("@")[0]
                else:
                    phone = _normalize(raw_jid).split("@")[0]
                if phone and f"@{display}" in api_text:
                    api_text = api_text.replace(f"@{display}", f"@{phone}", 1)

        # When mentions are present, use extendedTextMessage so the rendering
        # pipeline can convert @phone → @DisplayName for the local display.
        if _mentioned:
            _msg_type  = "extendedTextMessage"
            _msg_body  = {"extendedTextMessage": {"text": api_text}}
        else:
            _msg_type  = "conversation"
            _msg_body  = {"conversation": text}

        virtual_msg = {
            "_local_pending": True,
            "_local_id":      local_id,
            "key": {
                "id":       local_id,
                "fromMe":   True,
                "remoteJid": remote_jid,
            },
            "messageType":      _msg_type,
            "message":          _msg_body,
            "messageTimestamp": int(time.time()),
            "pushName":         "",
        }
        if self._quoted_message:
            _qk = self._quoted_message.get("key", {})
            virtual_msg["contextInfo"] = {
                "stanzaId":      _qk.get("id", ""),
                "participant":   _qk.get("participant", ""),
                "quotedMessage": self._quoted_message.get("message") or {},
                "_quotedFromMe": bool(_qk.get("fromMe", False)),  # local hint for immediate render
            }
        if _mentioned:
            virtual_msg.setdefault("contextInfo", {})["mentionedJid"] = _mentioned

        # Add to sorted list and UI list immediately.
        self._sorted_messages.append(virtual_msg)
        self.messages_list.Append((self._render_message_line(virtual_msg),))
        # Scroll to the new item.
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)

        # Clear any pending @mentions before clearing the field.
        self._pending_mentions.clear()
        self._pending_mention_display_names.clear()
        self._hide_mention_suggestions()
        self._rebuild_mention_pills()

        # Clear the text field (this also hides send btn, shows record btn).
        self.message_field.SetValue("")
        self.message_field.SetFocus()

        # Enqueue for background sending (with retry on failure).
        pm = PendingMessage(
            local_id, remote_jid, text=api_text,
            quoted=self._quoted_message,
            mentioned_jids=_mentioned,
        )
        self.main_window.message_queue.enqueue(pm)
        self._on_cancel_reply()  # clear quoted state after send

        # Register the virtual message in chat records so the conversation
        # list preview updates immediately to show the sent message.
        self._register_virtual_msg(virtual_msg)
        self.main_window._schedule_set_chats()

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
        chat = self.main_window.get_chat(remote_jid)
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
        
        # Update chat timestamp (t) so the sending chat floats to the top immediately
        msg_ts = int(virtual_msg.get("messageTimestamp", 0) or time.time())
        if msg_ts > 1_000_000_000_000:
            msg_ts //= 1000
        current_t = int(chat.get("t", 0) or 0)
        if current_t > 1_000_000_000_000:
            current_t //= 1000
        if msg_ts > current_t:
            chat["t"] = msg_ts

    def _mark_message_sent(self, local_id: str, real_id: str = None):
        """
        Called on the main thread when a queued message is successfully delivered.
        Clears the _local_pending flag, refreshes the list item, plays the
        message-sent sound, and refreshes the conversation list preview.
        real_id (the WhatsApp message ID returned by the API) replaces the local
        UUID in the virtual message's key so that media playback can later look
        up the message in the WPPConnect API database.
        """
        # Panel-level guard: survive _sorted_messages rebuilds that replace dict
        # objects, keeping the per-dict _ui_sent flag from being seen by both callers.
        _played = getattr(self, "_played_sent_local_ids", None)
        if _played is None:
            self._played_sent_local_ids: set = set()
            _played = self._played_sent_local_ids
        if local_id in _played:
            return
        _played.add(local_id)
        if len(_played) > 500:
            _played.clear()

        for i, msg in enumerate(self._sorted_messages):
            if msg.get("_local_id") == local_id:
                if msg.get("_ui_sent"):
                    return  # Already marked sent on the UI, ignore to prevent duplicate sound and actions
                msg["_ui_sent"] = True
                msg["_local_pending"] = False
                # Replace the local UUID with the real WhatsApp message ID so
                # get_base64_from_media can find the message in the DB later.
                if real_id and isinstance(real_id, str):
                    msg.setdefault("key", {})["id"] = real_id
                    # Rename the local audio file so we don't have to download it!
                    try:
                        voice_messages_dir = data_path("voice_messages")
                        old_file = os.path.join(voice_messages_dir, f"{local_id}.msv")
                        new_file = os.path.join(voice_messages_dir, f"{real_id}.msv")
                        if os.path.isfile(old_file) and not os.path.isfile(new_file):
                            os.rename(old_file, new_file)
                    except Exception as e:
                        print(f"[_mark_message_sent] failed to rename local audio: {e}")
                    if getattr(self, "_current_audio_id", None) == local_id:
                        self._current_audio_id = real_id
                    if hasattr(self, "_audio_positions") and local_id in self._audio_positions:
                        self._audio_positions[real_id] = self._audio_positions.pop(local_id)
                    # For audio messages, kick off background download now that
                    # we have the real ID the WPPConnect API can look up.
                    if msg.get("messageType") == "audioMessage":
                        import threading as _threading
                        _threading.Thread(
                            target=self.main_window.sync_if_media,
                            args=(msg,),
                            daemon=True,
                        ).start()
                self.messages_list.SetItemText(i, self._render_message_line(msg))
                # Play sent sound — fires only when the originating conversation
                # is still the active one (otherwise local_id is not found here).
                # Audio messages are excluded: their sound is played by
                # _on_message_sent at API-confirmation time, guaranteeing it
                # fires even if the user navigated away during the upload.
                if hasattr(self.main_window, "message_sent_sound"):
                    if msg.get("messageType") != "audioMessage":
                        self.main_window.message_sent_sound.play()
                if self.conversation:
                    self.main_window._schedule_save(dirty_jid=self.conversation.get("remoteJid"))
                break
        # Refresh conversation list so the preview reflects the sent message.
        self.main_window._schedule_set_chats()


    def _mark_message_failed(self, local_id: str):
        """Mark a virtual pending message as permanently failed (exhausted retries)."""
        for i, msg in enumerate(self._sorted_messages):
            if msg.get("_local_id") == local_id:
                msg["_local_pending"] = False
                msg["_send_failed"]   = True
                self.messages_list.SetItemText(i, self._render_message_line(msg))
                if self.conversation:
                    self.main_window._schedule_save(dirty_jid=self.conversation.get("remoteJid"))
                break

    def refresh_message_status(self, msg_id: str, status: str):
        """Update the status icon for a single sent message without full redraw."""
        for i, msg in enumerate(self._sorted_messages):
            if msg.get("key", {}).get("id") == msg_id:
                # NOTE: MessageUpdate was already appended by on_message_status_update
                # in main.py before this method is called. Do NOT append again here
                # or the status history grows with duplicates on every update.
                # Just re-render the row and force an immediate visual repaint.
                self.messages_list.SetItemText(i, self._render_message_line(msg))
                # RefreshItem ensures the list control repaints this row immediately.
                # Without it, SetItemText updates the internal data but Windows may
                # defer the visual update until the next full paint cycle — making
                # the status icon appear frozen until the user leaves and re-enters
                # the conversation.
                try:
                    self.messages_list.RefreshItem(i)
                except Exception:
                    pass
                break

    # ── Voice recording ──────────────────────────────────────────────────────

    def _start_voice_recording(self):
        """
        Start capturing audio from the default input device.

        Quality strategy (highest to lowest preference):
          48 000 Hz stereo → 48 000 Hz mono → 44 100 Hz stereo → 44 100 Hz mono

        PyAudio delivers raw, unprocessed PCM — no noise suppression,
        no automatic-gain control, no resampling.  This preserves full voice
        naturalness and quality.
        """
        if self.conversation is None:
            return

        self._recording_frames = []
        self._recording_paused = False

        # Define callback once, outside the loop; captures self for pause check.
        def _callback(in_data, frame_count, time_info, status):
            # Runs on PyAudio's internal callback thread.
            # list.append is atomic under the GIL — no explicit lock needed.
            if status:
                # paInputOverflow: the capture buffer filled before we drained
                # it (CPU/GIL contention). Logged so choppy recordings are
                # diagnosable; the larger frames_per_buffer below minimises it.
                logging.debug("[audio] input stream status flag: %s", status)
            if not self._recording_paused:
                self._recording_frames.append(in_data)
            return (None, pyaudio.paContinue)

        # Try each (rate, channels) combination in preference order.
        # WhatsApp voice messages are natively 48 kHz Mono. Prioritizing Mono
        # avoids CPU-intensive downmixing loops in pure Python.
        _configs = [
            (48000, 1),   # 48 kHz mono   — native for WhatsApp/Opus, fastest
            (48000, 2),   # 48 kHz stereo
            (44100, 1),   # 44.1 kHz mono
            (44100, 2),   # 44.1 kHz stereo
        ]
        opened = False
        pa = pyaudio.PyAudio()
        for rate, ch in _configs:
            try:
                stream = pa.open(
                    rate=rate,
                    channels=ch,
                    format=pyaudio.paInt16,
                    input=True,
                    # Larger buffer (~85 ms at 48 kHz) so the Python callback
                    # can tolerate scheduling delays from background sync/media
                    # threads without PortAudio dropping samples (choppy audio).
                    frames_per_buffer=4096,
                    stream_callback=_callback,
                )
                stream.start_stream()
                self._recording_stream      = stream
                self._recording_pa          = pa
                self._recording_actual_rate = rate
                self._recording_actual_ch   = ch
                opened = True
                break
            except Exception:
                self._recording_stream = None

        if not opened:
            pa.terminate()
            return

        self._is_recording = True

        # Notify contacts that the user is recording audio
        _rec_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if _rec_jid and not _rec_jid.endswith("@newsletter"):
            self.main_window.send_recording_status(_rec_jid, True, _rec_jid.endswith("@g.us"))

        # UI: play sound, swap buttons, focus the configured recording action.
        self.main_window.voicemsg_startrecording_sound.play()
        self.send_message_btn.Hide()
        self.record_voice_message_btn.Hide()
        self._add_attachment_btn.Hide()
        self._pause_resume_btn.SetLabel(
            self.main_window.i18n.t("pause_recording")
        )
        self._voice_panel.Show()
        self.conversation_panel.Layout()
        voice_focus = self.main_window.settings.get("user_interface", {}).get(
            "voice_record_focus", "send"
        )
        if voice_focus == "discard":
            self._discard_voice_btn.SetFocus()
        else:
            self._send_voice_btn.SetFocus()

    def _stop_recording_stream(self):
        """Stop and close the active PyAudio stream (safe to call when None)."""
        if self._recording_stream is not None:
            try:
                self._recording_stream.stop_stream()
                self._recording_stream.close()
            except Exception:
                pass
            self._recording_stream = None
        if self._recording_pa is not None:
            try:
                self._recording_pa.terminate()
            except Exception:
                pass
            self._recording_pa = None

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
        # Notify contacts that recording stopped
        _rec_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if _rec_jid and not _rec_jid.endswith("@newsletter"):
            self.main_window.send_recording_status(_rec_jid, False, _rec_jid.endswith("@g.us"))
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

        # ── Phase 1: release audio device, play "tac" instantly ──────────────
        # Stop the recording stream FIRST so the audio device is fully released
        # before BASS tries to play the send sound — prevents device contention.
        self._stop_recording_stream()
        self._is_recording     = False
        self._recording_paused = False

        self.main_window.voicemsg_send_sound.play()

        # Notify contacts that recording stopped (runs in its own thread).
        _rec_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if _rec_jid and not _rec_jid.endswith("@newsletter"):
            self.main_window.send_recording_status(_rec_jid, False, _rec_jid.endswith("@g.us"))

        frames = self._recording_frames
        self._recording_frames = []

        if not frames:
            self._hide_voice_panel()
            self.message_field.SetFocus()
            return

        # ── Phase 2: instant UI update ────────────────────────────────────────
        remote_jid      = self.conversation.get("remoteJid", "")
        local_id        = str(uuid.uuid4())
        actual_rate     = self._recording_actual_rate
        actual_ch       = self._recording_actual_ch
        bytes_per_frame = 2 * actual_ch
        quoted_msg      = self._quoted_message

        # Duration from frame byte counts — no allocation, no join on UI thread.
        total_bytes  = sum(len(f) for f in frames)
        duration_sec = int(total_bytes / bytes_per_frame / actual_rate)

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
        if quoted_msg:
            _qk = quoted_msg.get("key", {})
            virtual_msg["contextInfo"] = {
                "stanzaId":      _qk.get("id", ""),
                "participant":   _qk.get("participant", ""),
                "quotedMessage": quoted_msg.get("message") or {},
                "_quotedFromMe": bool(_qk.get("fromMe", False)),
            }
        self._sorted_messages.append(virtual_msg)
        self.messages_list.Append((self._render_message_line(virtual_msg),))
        last = self.messages_list.GetItemCount() - 1
        if last >= 0:
            self.messages_list.EnsureVisible(last)

        self._register_virtual_msg(virtual_msg)
        self.main_window._schedule_set_chats()
        self._on_cancel_reply()
        self._hide_voice_panel()
        self.message_field.SetFocus()

        # ── Phase 3: heavy work off UI thread ─────────────────────────────────
        # • Join PCM frames
        # • Encode OGG Opus directly from PCM (no WAV roundtrip for encoding)
        # • Write WAV backup for .msv / retry
        # • Encrypt + save .msv local copy
        # • Enqueue with ogg_bytes already ready → worker only needs to POST
        mw      = self.main_window
        enc_key = mw.key

        def _write_and_enqueue():
            from core.ogg_opus import encode_pcm_to_ogg_opus

            # 1. Join raw PCM frames.
            audio_data = b"".join(frames)

            # 2. Encode OGG Opus from PCM directly (no WAV read-back).
            ogg_bytes = None
            try:
                ogg_bytes = encode_pcm_to_ogg_opus(audio_data, actual_rate, actual_ch)
            except Exception as exc:
                logging.warning("[_send_voice_message] OGG pre-encode failed, "
                                "queue will encode on send: %s", exc)

            # 3. Write WAV temp file (for .msv backup and retry fallback).
            try:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                with wave.open(tmp.name, "wb") as wf:
                    wf.setnchannels(actual_ch)
                    wf.setsampwidth(2)   # 16-bit PCM
                    wf.setframerate(actual_rate)
                    wf.writeframes(audio_data)
                wav_path = tmp.name
            except Exception as exc:
                logging.error("[_send_voice_message] failed to write WAV: %s", exc)
                return

            # 4. Encrypt raw PCM and save as .msv for offline playback.
            try:
                voice_messages_dir = data_path("voice_messages")
                os.makedirs(voice_messages_dir, exist_ok=True)
                local_audio_path = os.path.join(voice_messages_dir, f"{local_id}.msv")
                with open(local_audio_path, "wb") as f_out:
                    f_out.write(encrypt(audio_data, enc_key))
            except Exception as exc:
                logging.warning("[_send_voice_message] failed to save local audio copy: %s", exc)

            # 5. Enqueue — ogg_bytes pre-encoded so worker skips encoding, just POSTs.
            pm = PendingMessage(local_id, remote_jid, audio_path=wav_path,
                                ogg_bytes=ogg_bytes, quoted=quoted_msg)
            mw.message_queue.enqueue(pm)

        threading.Thread(target=_write_and_enqueue, daemon=True).start()

    def close_conversation(self, event=None):
        if hasattr(self, "_mention_panel") and self._mention_panel.IsShown():
            self._hide_mention_suggestions()
            self.message_field.SetFocus()
            return
        self._stop_typing_for_current_conversation()
        if self._is_recording:
            self._stop_recording_stream()
            self._is_recording     = False
            self._recording_paused = False
            self._recording_frames = []
            self._voice_panel.Hide()
            self.record_voice_message_btn.Show()
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
        closed_jid = self._last_open_jid
        self.conversation = None
        self.conversation_panel.Hide()
        self.Layout()
        mw = self.main_window
        # If the conversation being closed is archived, it was opened from the
        # archived list (ArchivedConversationsPanel), which stays hidden behind
        # this panel while the conversation is open — so Esc must send focus
        # back there instead of the regular conversations list.
        if (closed_jid and mw.is_chat_archived(closed_jid)
                and hasattr(mw, "archived_conversations_panel")):
            wx.CallAfter(self._restore_to_archived_list, closed_jid)
        else:
            # Defer focus restoration so it runs after the accelerator event is
            # fully processed — calling SetFocus() synchronously inside an EVT_MENU
            # handler can be overridden by wx's post-event focus management on Win32.
            wx.CallAfter(self._restore_conversation_selection)

    def _restore_conversation_selection(self):
        """Select, focus and give keyboard focus to the last-opened conversation."""
        lst = self.conversations_list
        target = 0
        if self._last_open_jid:
            for i, chat in enumerate(self.chats_list):
                if chat.get("remoteJid") == self._last_open_jid:
                    target = i
                    break
        if self.chats_list:
            lst.Focus(target)
            lst.Select(target)
            lst.EnsureVisible(target)
        lst.SetFocus()

    def _restore_to_archived_list(self, jid: str):
        """Switch back to the archived conversations list and re-select `jid`."""
        mw = self.main_window
        self.Hide()
        mw.archived_conversations_panel.Show()
        mw.content_panel.Layout()
        arch = mw.archived_conversations_panel
        lst = arch.conversations_list
        target = 0
        for i, chat in enumerate(arch.chats_list):
            if chat.get("remoteJid") == jid:
                target = i
                break
        if arch.chats_list:
            lst.Focus(target)
            lst.Select(target)
            lst.EnsureVisible(target)
        lst.SetFocus()

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
        is_self  = self.main_window._is_self_jid(jid)
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
            unread_item = menu.Append(wx.ID_ANY, f"{i18n.t('mark_as_unread')}\tCtrl+Shift+M")
            self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_mark_unread(j), unread_item)

        menu.AppendSeparator()

        # ── Mute ──────────────────────────────────────────────────────────
        if mw.is_chat_muted(jid):
            unmute_item = menu.Append(wx.ID_ANY, f"{i18n.t('unmute_chat')}\tAlt+Shift+S")
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
            menu.AppendSubMenu(mute_sub, f"{i18n.t('mute_chat')}\tAlt+Shift+S")

        if not is_group:
            menu.AppendSeparator()
            if not is_self:
                block_item = menu.Append(wx.ID_ANY, f"{i18n.t('block_contact')}\tCtrl+Shift+B")
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, c=chat, j=jid: self._on_menu_block(c, j),
                    block_item,
                )
            copy_num_item = menu.Append(wx.ID_ANY, f"{i18n.t('copy_number')}\tAlt+Shift+C")
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
        clear_item = menu.Append(wx.ID_ANY, f"{i18n.t('clear_chat')}\tCtrl+Shift+L")
        self.Bind(wx.EVT_MENU, lambda e, j=jid: self._on_menu_clear_chat(j), clear_item)

        delete_item = menu.Append(wx.ID_ANY, f"{i18n.t('delete_chat')}\tDelete")
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
        clean_msg_id = msg_id
        if "_" in msg_id:
            parts = msg_id.split("_")
            clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
        media_path = data_path("media", f"{clean_msg_id}.wzmedia")
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

        # ── Mention detection ─────────────────────────────────────────────
        self._update_mentions_panel(self._extract_mentions(msg))

    def on_message_activated(self, event):
        """Enter / double-click on a message item."""
        idx = self.messages_list.GetFocusedItem()
        if idx >= 0:
            self._do_activate_message(idx)

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

        # For text-based messages: open the first link if one is present,
        # otherwise show the full message text popup (same as Alt+C).
        if msg_type in ("conversation", "extendedTextMessage", ""):
            rendered = self.messages_list.GetItemText(index)
            links = self._extract_links(rendered)
            if links:
                try:
                    os.startfile(links[0])
                except Exception:
                    wx.LaunchDefaultBrowser(links[0])
                return
            self._show_message_text_popup(msg)
            return

        if msg_type == "audioMessage":
            duration = (msg_obj.get("audioMessage") or {}).get("seconds", 0) or 0
            clean_msg_id = msg_id
            if "_" in msg_id:
                parts = msg_id.split("_")
                clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
            import logging
            logging.info(f"[UI Audio Activation] msg_id={msg_id}, clean_msg_id={clean_msg_id}, duration={duration}, file={data_path('voice_messages', f'{clean_msg_id}.msv')}")
            self._toggle_playback(
                msg_id, duration, msg,
                file_path=data_path("voice_messages", f"{clean_msg_id}.msv"),
                audio_ext=".ogg",
            )

        elif msg_type == "videoMessage":
            video = msg_obj.get("videoMessage") or {}
            if video.get("gifPlayback"):
                return  # GIFs have no audio track to play
            duration = video.get("seconds", 0) or 0
            clean_msg_id = msg_id
            if "_" in msg_id:
                parts = msg_id.split("_")
                clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
            self._toggle_playback(
                msg_id, duration, msg,
                file_path=data_path("media", f"{clean_msg_id}.wzmedia"),
                audio_ext=".mp4",
            )

        elif msg_type in ("imageMessage", "documentMessage"):
            # Enter on an image or document → open in default app
            self._on_action_open(None, index=index)

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
                f"{i18n.t('goto_quoted')}\tAlt+Shift+Q",
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
        _TEXT_TYPES = ("conversation", "extendedTextMessage")
        if msg_type in _TEXT_TYPES:
            copy_item = menu.Append(wx.ID_ANY, f"{i18n.t('copy_message_text')}\tCtrl+C")
            self.Bind(
                wx.EVT_MENU,
                lambda e, m=msg: self._on_menu_copy_message(m),
                copy_item,
            )

        # Copy file (only for image, video, document messages)
        _MEDIA_TYPES = ("imageMessage", "videoMessage", "documentMessage")
        if msg_type in _MEDIA_TYPES:
            copy_file_item = menu.Append(wx.ID_ANY, f"{i18n.t('copy_file')}\tCtrl+C")
            self.Bind(
                wx.EVT_MENU,
                lambda e, m=msg: self._on_menu_copy_file(m),
                copy_file_item,
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

        # React (opens emoji picker) — Ctrl+Shift+R
        react_item = menu.Append(wx.ID_ANY, f"{i18n.t('react_to_message')}\tCtrl+Shift+R")
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

        # Star / Unstar (Ctrl+Shift+O)
        is_starred = bool(msg.get("starred"))
        star_label = i18n.t("unstar_message") if is_starred else i18n.t("star_message")
        star_item = menu.Append(wx.ID_ANY, f"{star_label}\tCtrl+Shift+O")
        self.Bind(
            wx.EVT_MENU,
            lambda e, m=msg: self._on_menu_star(m),
            star_item,
        )

        # Save As (media only, only when the file is already cached locally)
        _SAVEABLE = {"documentMessage", "imageMessage", "videoMessage"}
        clean_msg_id = msg_id
        if "_" in msg_id:
            parts = msg_id.split("_")
            clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
        if msg_type in _SAVEABLE and os.path.isfile(
            data_path("media", f"{clean_msg_id}.wzmedia")
        ):
            menu.AppendSeparator()
            save_item = menu.Append(
                wx.ID_ANY, f"{i18n.t('save_as')}\tCtrl+Shift+S"
            )
            self.Bind(wx.EVT_MENU, self._on_action_save_as, save_item)
        elif msg_type == "audioMessage":
            # Voice messages are cached separately (voice_messages/*.msv) and
            # can be saved even while a download is still pending — the save
            # flow downloads it first if needed, same as the other media types.
            menu.AppendSeparator()
            save_audio_item = menu.Append(
                wx.ID_ANY, f"{i18n.t('save_audio_as')}\tCtrl+Shift+S"
            )
            self.Bind(wx.EVT_MENU, self._on_action_save_as, save_audio_item)

        # Edit (own text messages within 3 hours)
        _is_own      = msg.get("key", {}).get("fromMe", False)
        _is_text     = msg_type in ("conversation", "extendedTextMessage")
        _msg_ts      = msg.get("messageTimestamp", 0)
        _within_3h   = (time.time() - _msg_ts) < 10800
        if _is_own and _is_text and _within_3h:
            edit_item = menu.Append(wx.ID_ANY, f"{i18n.t('edit_message')}\tAlt+E")
            self.Bind(
                wx.EVT_MENU,
                lambda e, i=index, m=msg: self._on_menu_edit_message(i, m),
                edit_item,
            )

        menu.AppendSeparator()

        # Delete message — Delete key
        del_item = menu.Append(wx.ID_ANY, f"{i18n.t('delete_message')}\tDelete")
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
        if msg_type in ("documentMessage", "imageMessage", "videoMessage", "audioMessage"):
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
        self._update_mentions_panel([])
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

    # ── @mention helpers ─────────────────────────────────────────────────────

    def _extract_mentions(self, msg: dict) -> list:
        """Return list of (display_name, jid) for @mentioned JIDs in msg."""
        msg_obj = msg.get("message") or {}
        ext     = (msg_obj.get("extendedTextMessage") or {}) if isinstance(msg_obj, dict) else {}
        mentioned = (
            (msg.get("contextInfo") or {}).get("mentionedJid")
            or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
            or ext.get("contextInfo", {}).get("mentionedJid")
            or []
        )
        if not mentioned:
            return []
        out = []
        seen = set()
        for jid in mentioned:
            if not jid or jid in seen:
                continue
            seen.add(jid)
            name = self._get_participant_name(jid)
            out.append((name, jid))
        return out

    def _update_mentions_panel(self, mentions: list):
        """Rebuild the @mention buttons below the messages list."""
        for child in list(self._mentions_panel.GetChildren()):
            if child is not self._mentions_label:
                child.Destroy()
        while self._mentions_sizer.GetItemCount() > 1:
            self._mentions_sizer.Remove(1)

        if not mentions:
            self._mentions_panel.Hide()
            self._current_mentions = []
            if self.conversation_panel.IsShown():
                self.conversation_panel.Layout()
            return

        self._current_mentions = mentions

        for display_name, jid in mentions:
            ctrl = wx.adv.HyperlinkCtrl(
                self._mentions_panel,
                id=wx.ID_ANY,
                label=f"@{display_name}",
                url=f"mention://{jid}",
                style=wx.adv.HL_DEFAULT_STYLE,
            )
            ctrl.Bind(
                wx.adv.EVT_HYPERLINK,
                lambda e, j=jid: self._on_mention_hyperlink(e, j),
            )
            ctrl.Bind(wx.EVT_KEY_DOWN, self._on_mention_display_key_down)
            self._mentions_sizer.Add(ctrl, 0, wx.LEFT | wx.BOTTOM, 3)

        self._mentions_panel.Show()
        self._mentions_panel.Layout()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _on_mention_open(self, jid: str):
        """Navigate to the conversation for the mentioned contact."""
        mw = self.main_window
        chat = mw.chats.get(jid)
        if chat is None:
            name = self._get_participant_name(jid)
            chat = {"remoteJid": jid, "pushName": name}
        self.navigate_to_conversation(chat)

    def _on_mention_hyperlink(self, event, jid: str):
        """Intercept EVT_HYPERLINK on a mention display link to navigate instead of open URL."""
        event.Skip(False)
        self._on_mention_open(jid)

    def _on_mention_display_key_down(self, event):
        """Space/Enter on a mention HyperlinkCtrl activates it (like click)."""
        kc = event.GetKeyCode()
        if kc in (wx.WXK_RETURN, wx.WXK_SPACE, wx.WXK_NUMPAD_ENTER):
            ctrl = event.GetEventObject()
            jid = ctrl.GetURL().replace("mention://", "")
            self._on_mention_open(jid)
        else:
            event.Skip()

    # ── @mention input system ────────────────────────────────────────────────

    def _get_mention_query(self):
        """Return (start_pos, query) when cursor is inside @word, else (None, None)."""
        text = self.message_field.GetValue()
        pos  = self.message_field.GetInsertionPoint()
        i = min(pos - 1, len(text) - 1)
        while i >= 0:
            ch = text[i]
            if ch == "@":
                return (i, text[i + 1:pos])
            if ch in (" ", "\n", "\t"):
                break
            i -= 1
        return (None, None)

    def _hide_mention_suggestions(self):
        """Hide the mention suggestion list without announcing anything."""
        self._mention_active = False
        if hasattr(self, "_mention_panel") and self._mention_panel.IsShown():
            self._mention_panel.Hide()
            if self.conversation_panel.IsShown():
                self.conversation_panel.Layout()

    def _update_mention_suggestions(self, query: str):
        """Rebuild the suggestion list for the given query and show/hide the panel."""
        i18n = self.main_window.i18n
        q = query.lower()

        # Collect JIDs of everyone who has sent at least one message in the current conversation
        participants_who_sent_message = set()
        for msg in getattr(self, "_sorted_messages", []):
            if not isinstance(msg, dict):
                continue
            key = msg.get("key") or {}
            p_jid = key.get("participant") or msg.get("participant")
            if not p_jid and not msg.get("isGroupMsg", False):
                p_jid = key.get("remoteJid")
            if p_jid:
                p_jid = self.main_window._normalize_jid(p_jid)
                participants_who_sent_message.add(p_jid)
                # Map alternate formats
                phone_jid = getattr(self.main_window, "_lid_to_phone", {}).get(p_jid, "")
                if phone_jid:
                    participants_who_sent_message.add(phone_jid)
                lid_jid = getattr(self.main_window, "_phone_to_lid", {}).get(p_jid, "")
                if lid_jid:
                    participants_who_sent_message.add(lid_jid)

        def is_saved(jid):
            local = jid.rsplit("@", 1)[0]
            candidates = [jid]
            if jid.endswith("@lid"):
                phone = getattr(self.main_window, "_lid_to_phone", {}).get(jid, "")
                if phone:
                    candidates.append(phone)
                    candidates.append(phone.rsplit("@", 1)[0] + "@c.us")
            elif jid.endswith("@s.whatsapp.net"):
                candidates.append(local + "@c.us")
                lid = getattr(self.main_window, "_phone_to_lid", {}).get(jid, "")
                if lid:
                    candidates.append(lid)
            elif jid.endswith("@c.us"):
                candidates.append(local + "@s.whatsapp.net")

            for cjid in candidates:
                c = self.main_window.contacts.get(cjid)
                if c:
                    if c.get("isMyContact") or c.get("isSaved") or c.get("syncToAddressbook"):
                        return True
                    name = (c.get("name") or "").strip()
                    if name and not name.isdigit() and not is_phone_like(name):
                        name_lower = name.lower()
                        if "sem nome" not in name_lower and "unnamed" not in name_lower and name_lower not in ("no name", "unknown", "desconhecido"):
                            return True
            return False

        # Individual participant matches filtered by rules:
        # Show if contact is saved in contacts OR has sent a message in the group
        matches = []
        for name, jid in self._group_participants_cache:
            norm_jid = self.main_window._normalize_jid(jid)
            if not q or q in name.lower() or q in norm_jid:
                matches.append((name, jid))

        # Sort: names that start with the query come first, then those that
        # contain it but don't start with it — both groups sorted alphabetically.
        if q:
            matches.sort(key=lambda x: (0 if x[0].lower().startswith(q) else 1, x[0].lower()))

        # @all/@todos special entry — always at the top when query is empty or matches
        all_kw = i18n.t("mention_all_keyword")  # "todos" or "all"
        if not q or q in all_kw or q in "all" or q in "todos":
            matches = [("__ALL__", "@all")] + matches

        self._mention_suggestions = matches

        if not matches:
            was_visible = self._mention_panel.IsShown()
            self._hide_mention_suggestions()
            if was_visible:
                self.main_window.output(i18n.t("mention_no_suggestions"), interrupt=True)
            return

        self._mention_list.Clear()
        all_label = i18n.t("mention_all_label")
        for name, jid in matches:
            if jid == "@all":
                self._mention_list.Append(all_label)
            else:
                self._mention_list.Append(f"@{name}")

        self._mention_panel.Show()
        self._mention_panel.Layout()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()
        self._mention_list.SetSelection(0)
        self.main_window.output(i18n.t("mention_suggestions_available"), interrupt=False)

    def _on_text_changed_mention_check(self):
        """Called from on_change_message_field to detect and update @mention suggestions."""
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if not jid.endswith("@g.us"):
            if self._mention_panel.IsShown():
                self._hide_mention_suggestions()
            return
        start, query = self._get_mention_query()
        if start is None:
            if self._mention_panel.IsShown():
                self._hide_mention_suggestions()
                self._mention_active = False
            return
        self._mention_active = True
        self._mention_start_pos = start
        self._mention_query = query
        self._update_mention_suggestions(query)

    def _insert_mention(self, display_name: str, jid: str):
        """Replace the current @query in the field with @display_name and track the JID."""
        # Use cached start/query so this works even when message_field doesn't
        # have focus (e.g. when called from the mention list via EVT_CHAR_HOOK).
        start = self._mention_start_pos
        query = self._mention_query
        if start < 0:
            return
        i18n = self.main_window.i18n

        if jid == "@all":
            # @todos/@all: use the localized keyword as the inserted text and add
            # every group participant JID to the pending mentions list.
            all_kw = i18n.t("mention_all_keyword")   # "todos" or "all"
            replacement = f"@{all_kw} "
            for _, p_jid in self._group_participants_cache:
                if p_jid not in self._pending_mentions:
                    self._pending_mentions.append(p_jid)
        else:
            replacement = f"@{display_name} "
            if jid not in self._pending_mentions:
                self._pending_mentions.append(jid)
            self._pending_mention_display_names[jid] = display_name

        text = self.message_field.GetValue()
        new_text = text[:start] + replacement + text[start + 1 + len(query):]
        # ChangeValue does NOT fire EVT_TEXT, preventing a mention-check loop.
        self.message_field.ChangeValue(new_text)
        self.message_field.SetInsertionPoint(start + len(replacement))
        self._hide_mention_suggestions()
        self._mention_active = False
        self._rebuild_mention_pills()
        self.message_field.SetFocus()

    def _rebuild_mention_pills(self):
        """Rebuild the pending-mention pill buttons panel (one row per @mention)."""
        i18n = self.main_window.i18n
        panel = self._pending_mentions_panel
        sizer = self._pending_mentions_sizer

        # Destroy existing pill widgets.
        for child in list(panel.GetChildren()):
            child.Destroy()
        sizer.Clear(delete_windows=False)

        if not self._pending_mentions:
            panel.Hide()
            if self.conversation_panel.IsShown():
                self.conversation_panel.Layout()
            return

        for jid in list(self._pending_mentions):
            display = self._pending_mention_display_names.get(jid) or jid.rsplit("@", 1)[0]
            row = wx.BoxSizer(wx.HORIZONTAL)
            lbl = wx.StaticText(panel, label=f"@{display}")
            btn_label = i18n.t("remove_mention").format(name=display)
            btn = wx.Button(panel, label=btn_label)
            # Capture jid/display in closure.
            def _make_handler(j, d):
                def _handler(evt):
                    self._on_remove_mention(j, d)
                return _handler
            btn.Bind(wx.EVT_BUTTON, _make_handler(jid, display))
            row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL)
            sizer.Add(row, 0, wx.LEFT | wx.BOTTOM, 3)

        panel.Show()
        panel.Layout()
        if self.conversation_panel.IsShown():
            self.conversation_panel.Layout()

    def _on_remove_mention(self, jid: str, display: str):
        """Remove a pending @mention pill and its text from the message field."""
        # Remove @display from message text if present.
        text = self.message_field.GetValue()
        # Try removing "@display " (with trailing space) first, then "@display" alone.
        if f"@{display} " in text:
            new_text = text.replace(f"@{display} ", "", 1)
        elif f"@{display}" in text:
            new_text = text.replace(f"@{display}", "", 1)
        else:
            new_text = text
        if new_text != text:
            self.message_field.ChangeValue(new_text)

        # Remove from pending state.
        if jid in self._pending_mentions:
            self._pending_mentions.remove(jid)
        self._pending_mention_display_names.pop(jid, None)

        self._rebuild_mention_pills()
        self.message_field.SetFocus()

    def _fetch_group_participants(self, jid: str):
        """Background: fetch participants for the group and populate the cache with retries if session is loading."""
        import logging
        import time
        max_retries = 3
        delay = 3
        for attempt in range(max_retries):
            # Check if this chat is still the active conversation before retrying
            if not self.conversation or self.conversation.get("remoteJid") != jid:
                logging.info(f"[mention] Active conversation changed. Aborting fetch for {jid}.")
                return
            try:
                data = self.main_window.get_group_info(jid)
                participants = data.get("participants", [])
                logging.info(f"[mention] get_group_info({jid}) attempt {attempt+1}/{max_retries} → {len(participants)} participants")
                if participants:
                    my_jid = getattr(self.main_window, "my_jid", "") or ""
                    mw_ref = self.main_window
                    
                    # Resolve any unknown @lid participant JIDs using API
                    lid_jids_to_resolve = []
                    lid_to_phone = getattr(mw_ref, "_lid_to_phone", {})
                    for p in participants:
                        if not isinstance(p, dict):
                            continue
                        p_jid = p.get("id", "")
                        if p_jid and p_jid.endswith("@lid") and p_jid not in lid_to_phone:
                            lid_jids_to_resolve.append(p_jid)
                    if lid_jids_to_resolve:
                        mw_ref.resolve_lid_jids_via_api(lid_jids_to_resolve)
                        
                    cache = []
                    for p in participants:
                        if not isinstance(p, dict):
                            continue
                        p_jid = p.get("id", "")
                        if not p_jid:
                            continue
                        if my_jid and p_jid.split("@")[0] == my_jid.split("@")[0]:
                            continue  # skip self
                        name = self._get_participant_name(p_jid, p)
                        cache.append((name, p_jid))
                    cache.sort(key=lambda x: x[0].lower())
                    logging.info(f"[mention] cache built: {[n for n,_ in cache]}")
                    wx.CallAfter(self._set_group_participants_cache, cache)
                    return
            except Exception as e:
                logging.error(f"[mention] _fetch_group_participants error on attempt {attempt+1}: {e}", exc_info=True)
            
            if attempt < max_retries - 1:
                logging.info(f"[mention] Empty participants response, retrying in {delay}s...")
                time.sleep(delay)

    def _set_group_participants_cache(self, cache: list):
        """Main-thread callback: store cache and refresh suggestions if active."""
        self._group_participants_cache = cache
        if self._mention_active:
            self._update_mention_suggestions(self._mention_query)

    def _on_message_field_key_down(self, event):
        """↓ moves focus to the mention list when suggestions are visible."""
        kc = event.GetKeyCode()
        if kc == wx.WXK_DOWN and self._mention_panel.IsShown():
            if self._mention_list.GetCount() > 0:
                self._mention_list.SetFocus()
                self._mention_list.SetSelection(0)
            return  # consume — don't let the field handle ↓
        event.Skip()

    def _on_mention_list_key_down(self, event):
        """Keyboard navigation inside the mention suggestion list."""
        kc = event.GetKeyCode()

        if kc in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            idx = self._mention_list.GetSelection()
            if 0 <= idx < len(self._mention_suggestions):
                name, jid = self._mention_suggestions[idx]
                self._insert_mention(name, jid)
            return

        if kc == wx.WXK_ESCAPE:
            self._hide_mention_suggestions()
            self.message_field.SetFocus()
            return

        if kc == wx.WXK_BACK:
            # Backspace: remove last char from message field and update filter
            pos = self.message_field.GetInsertionPoint()
            if pos > 0:
                text = self.message_field.GetValue()
                self.message_field.ChangeValue(text[:pos - 1] + text[pos:])
                self.message_field.SetInsertionPoint(pos - 1)
                wx.CallAfter(self._on_mention_list_after_char)
            return

        # ↑ / ↓ — let ListBox move the selection naturally; NVDA reads it
        event.Skip()

    def _on_mention_list_char(self, event):
        """Printable chars typed in the list are redirected to the message field."""
        uc = event.GetUnicodeKey()
        if uc == wx.WXK_NONE or uc < 32:
            event.Skip()
            return
        ch = chr(uc)
        pos = self.message_field.GetInsertionPoint()
        text = self.message_field.GetValue()
        self.message_field.ChangeValue(text[:pos] + ch + text[pos:])
        self.message_field.SetInsertionPoint(pos + 1)
        wx.CallAfter(self._on_mention_list_after_char)

    def _on_mention_list_after_char(self):
        """Update mention suggestions after a char was injected from the list."""
        i18n = self.main_window.i18n
        start, query = self._get_mention_query()
        if start is None:
            self._hide_mention_suggestions()
            self.main_window.output(i18n.t("mention_no_suggestions"), interrupt=True)
            self.message_field.SetFocus()
            return
        self._mention_query = query
        self._update_mention_suggestions(query)
        # Return focus to the list so the user can keep typing or navigate
        if self._mention_suggestions:
            self._mention_list.SetFocus()
            self._mention_list.SetSelection(0)

    # ── Lazy-loading: load older messages when the user focuses item 0 ─────────

    def _focused_msg_id(self) -> str:
        """Return the message ID of the currently focused list item, or ''."""
        idx = self.messages_list.GetFocusedItem()
        if idx < 0 or idx >= len(self._sorted_messages):
            return ""
        m = self._sorted_messages[idx]
        if self._is_separator(m):
            return ""
        return m.get("key", {}).get("id", "")

    def _on_message_focused(self, event):
        idx = event.GetIndex()
        if (
            idx == 0
            and not self._is_loading_more
        ):
            if self._messages_offset > 0:
                self._load_more_messages()
            else:
                self._load_older_messages()

        # Unread-separator dismiss logic:
        # - Focus at or past the separator → start the 2-s dismiss timer once.
        # Once the timer is armed it is intentionally NOT cancelled when focus
        # moves back above the separator, so the separator always disappears
        # after the user has reached the unread region.
        if self._unread_sep_idx >= 0:
            if idx >= self._unread_sep_idx:
                # Mark as read immediately (first time focus arrives)
                if not self._unread_sep_dismiss_timer.IsRunning():
                    if self.conversation is not None:
                        jid = self.conversation.get("remoteJid", "")
                        if jid:
                            threading.Thread(
                                target=self.main_window.mark_conversation_as_read,
                                args=(jid,),
                                daemon=True,
                            ).start()
                    self._unread_sep_dismiss_timer.StartOnce(2000)

        # Show audio controls only when the focused item IS the playing audio.
        if self._current_audio_id is not None and self._audio_stream is not None:
            if 0 <= idx < len(self._sorted_messages):
                m = self._sorted_messages[idx]
                if (not self._is_separator(m)
                        and m.get("key", {}).get("id") == self._current_audio_id):
                    self._show_audio_controls()
                else:
                    self._hide_audio_controls()

        self._update_read_more_button(idx)
        event.Skip()

    def _update_read_more_button(self, idx: int):
        """Show/hide the "Ler mais" button for a truncated text message row.

        Only meaningful in classic wx.ListCtrl mode — SysListView32 truncates
        the accessible name of each row at _LIST_CTRL_TEXT_LIMIT characters;
        CompatListBoxMessagesCtrl exposes the full text and has no such limit.
        """
        if getattr(self, "_message_list_mode", "classic") == "listbox":
            return
        show = False
        if 0 <= idx < len(self._sorted_messages):
            msg = self._sorted_messages[idx]
            if not self._is_separator(msg):
                msg_type = msg.get("messageType", "")
                if msg_type in ("conversation", "extendedTextMessage", ""):
                    rendered = self._render_message_line(msg)
                    if len(rendered) > self._LIST_CTRL_TEXT_LIMIT:
                        self._read_more_remainder = rendered[self._LIST_CTRL_TEXT_LIMIT:]
                        show = True
        if show:
            self._read_more_btn.Show()
        else:
            self._read_more_btn.Hide()
            self._read_more_remainder = ""
        self.conversation_panel.Layout()

    def _on_read_more(self, event):
        """Alt+L / button click: speak only the text cut off by the list-view limit."""
        remainder = getattr(self, "_read_more_remainder", "")
        if remainder:
            self.main_window.output(remainder, interrupt=True)

    def _on_unread_sep_dismiss_timer(self, event):
        """Fired 2 s after focus reached the unread separator — remove it."""
        self._dismiss_unread_separator()

    def _dismiss_unread_separator(self):
        """Remove the unread separator row without stealing focus."""
        if self._unread_sep_idx < 0:
            return
        sep_idx = self._unread_sep_idx
        focused = self.messages_list.GetFocusedItem()
        self.messages_list.Freeze()
        try:
            self._sorted_messages.pop(sep_idx)
            self.messages_list.DeleteItem(sep_idx)
        finally:
            self.messages_list.Thaw()
        self._unread_sep_idx  = -1
        self._sep_from_open   = False
        self._first_unread_msg_id  = None
        self._first_unread_count   = 0
        # Restore the focused row (shifted by 1 if it was after the separator)
        if focused > sep_idx:
            focused -= 1
        elif focused == sep_idx:
            focused = max(0, sep_idx - 1)
        if 0 <= focused < self.messages_list.GetItemCount():
            self.messages_list.Focus(focused)

    def _load_older_messages(self):
        """Load older messages from the local database, or fall back to the server if none remain locally."""
        if not self.conversation or not self._all_sorted_messages:
            return

        self._is_loading_more = True
        try:
            remote_jid = self.conversation.get("remoteJid", "")
            limit = int(
                self.main_window.settings.get("user_interface", {}).get("messages_page_size", 200)
            )
            # Count separator objects to get the actual database message count currently in memory.
            loaded_db_count = sum(1 for m in self._all_sorted_messages if not self._is_separator(m))
            
            # Fetch from local DB
            local_msgs = self.main_window.db.get_messages(remote_jid, limit=limit, offset=loaded_db_count)
            
            if local_msgs:
                # We found older messages in the local DB!
                # Reverse them so they are in ascending chronological order (older first)
                local_msgs.reverse()
                displayable = [m for m in local_msgs if self._is_displayable_message(m)]
                if displayable:
                    n_new = len(displayable)
                    self.messages_list.Freeze()
                    try:
                        self._all_sorted_messages = displayable + self._all_sorted_messages
                        self._sorted_messages     = displayable + self._sorted_messages
                        self._messages_offset     = 0
                        if self._unread_sep_idx >= 0:
                            self._unread_sep_idx += n_new
                            
                        self.messages_list.DeleteAllItems()
                        for msg in self._sorted_messages:
                            self.messages_list.Append((self._render_message_line(msg),))
                            
                        self.messages_list.Focus(n_new)
                        self.messages_list.Select(n_new, True)
                        self.messages_list.EnsureVisible(n_new)
                    finally:
                        self.messages_list.Thaw()
                    self._is_loading_more = False
                    return
            
            # No older messages in local DB, fetch from server
            self._load_older_messages_from_server()
        except Exception as e:
            print(f"[_load_older_messages] error: {e}")
            self._is_loading_more = False

    def _load_older_messages_from_server(self):
        """Fetch older messages from server when the beginning of local history is reached."""
        if not self.conversation or not self._all_sorted_messages:
            return
        
        # Get oldest non-separator and non-pending message ID
        oldest_msg = None
        for m in self._all_sorted_messages:
            if m.get("_type") == "unread_separator":
                continue
            m_id = m.get("key", {}).get("id", "")
            # Skip local pending/virtual messages (UUIDs contain hyphens or start with 'pending-')
            if m.get("_local_pending") or m_id.startswith("pending-") or "-" in m_id:
                continue
            oldest_msg = m
            break

        if oldest_msg is None:
            # Fallback to the first message if all are pending/separators
            oldest_msg = self._all_sorted_messages[0]

        oldest_id = oldest_msg.get("key", {}).get("id", "")
        if not oldest_id:
            return

        self._is_loading_more = True
        
        def _fetch():
            try:
                phone_jid = self.conversation.get("remoteJid", "")
                fetched = self.main_window.fetch_older_messages(phone_jid, oldest_msg)
                if fetched:
                    wx.CallAfter(self._on_older_messages_loaded, fetched)
                else:
                    self._is_loading_more = False
            except Exception as e:
                print(f"[_load_older_messages_from_server] error: {e}")
                self._is_loading_more = False

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_older_messages_loaded(self, fetched_messages):
        """Prepend fetched history to UI message list."""
        self._is_loading_more = False
        if not fetched_messages:
            return
            
        displayable = [
            m for m in fetched_messages if self._is_displayable_message(m)
        ]
        if not displayable:
            return
            
        # Sort displayable older messages
        try:
            displayable = sorted(
                displayable, key=lambda m: self._extract_timestamp(m) or 0
            )
        except Exception:
            pass
            
        n_new = len(displayable)
        
        self.messages_list.Freeze()
        try:
            self._all_sorted_messages = displayable + self._all_sorted_messages
            self._sorted_messages     = displayable + self._sorted_messages
            self._messages_offset     = 0
            if self._unread_sep_idx >= 0:
                self._unread_sep_idx += n_new
                
            self.messages_list.DeleteAllItems()
            for msg in self._sorted_messages:
                self.messages_list.Append((self._render_message_line(msg),))
                
            self.messages_list.Focus(n_new)
            self.messages_list.Select(n_new, True)
            self.messages_list.EnsureVisible(n_new)
        finally:
            self.messages_list.Thaw()


    def _load_more_messages(self):
        """Prepend the previous page of messages to the list."""
        self._is_loading_more = True
        try:
            limit = int(
                self.main_window.settings.get("user_interface", {}).get("messages_page_size", 200)
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

    def _open_file_safely(self, filepath: str):
        """Open a file with the default associated program in the foreground.
        Falls back to Windows 'openas' dialog if no program is associated."""
        import sys
        import os
        import ctypes
        if sys.platform == "win32":
            try:
                # SW_SHOW = 5
                res = ctypes.windll.shell32.ShellExecuteW(None, "open", filepath, None, None, 5)
                # ShellExecuteW returns <= 32 if failed
                if res <= 32:
                    if res == 31:  # SE_ERR_NOASSOC
                        ctypes.windll.shell32.ShellExecuteW(None, "openas", filepath, None, None, 5)
                    else:
                        raise OSError(f"ShellExecuteW failed with code {res}")
            except Exception:
                try:
                    ctypes.windll.shell32.ShellExecuteW(None, "openas", filepath, None, None, 5)
                except Exception:
                    os.startfile(filepath)
        else:
            if sys.platform == "darwin":
                import subprocess
                subprocess.call(["open", filepath])
            else:
                import subprocess
                try:
                    subprocess.call(["xdg-open", filepath])
                except Exception:
                    if hasattr(os, "startfile"):
                        os.startfile(filepath)

    def _on_action_open(self, event, index=None):
        if index is None:
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

        clean_msg_id = msg_id
        if "_" in msg_id:
            parts = msg_id.split("_")
            clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
        media_path = data_path("media", f"{clean_msg_id}.wzmedia")

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
                wx.CallAfter(lambda: self._open_file_safely(tmp.name))
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
        elif msg_type == "audioMessage":
            mime = (msg_obj.get("audioMessage") or {}).get("mimetype", "audio/ogg")
            ext  = mime.split("/")[-1].split(";")[0].strip() if "/" in mime else "ogg"
            default_file = f"audio_{msg_id}.{ext or 'ogg'}"
        else:
            return

        dlg_title = (
            self.main_window.i18n.t("save_audio_as") if msg_type == "audioMessage"
            else self.main_window.i18n.t("save_as")
        )
        with wx.FileDialog(
            self,
            dlg_title,
            defaultFile=default_file,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            save_path = dlg.GetPath()

        clean_msg_id = msg_id
        if "_" in msg_id:
            parts = msg_id.split("_")
            clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
        if msg_type == "audioMessage":
            media_path = data_path("voice_messages", f"{clean_msg_id}.msv")
        else:
            media_path = data_path("media", f"{clean_msg_id}.wzmedia")

        def _run():
            if not os.path.isfile(media_path):
                wx.CallAfter(
                    self.main_window.output, self.main_window.i18n.t("downloading")
                )
                try:
                    if msg_type == "audioMessage":
                        self.main_window.handle_audio_message(msg)
                    else:
                        self.main_window.handle_media_message(msg)
                except Exception:
                    return
            if not os.path.isfile(media_path):
                # Download silently failed — nothing to save.
                wx.CallAfter(
                    wx.MessageBox,
                    self.main_window.i18n.t("media_download_failed"),
                    self.main_window.i18n.t("error").format(
                        app_name=self.main_window.app_name
                    ),
                    wx.OK | wx.ICON_ERROR,
                )
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
                try:
                    _ctrl.pause()
                except Exception:
                    # BASS may report "not playing" if the user switches
                    # messages faster than the audio backend updates state.
                    pass
                self._is_audio_playing = False
                self._audio_timer.Stop()
            else:
                try:
                    _ctrl.play()
                except Exception:
                    self._stop_audio()
                    return
                self._is_audio_playing = True
                self._audio_timer.Start(200)
            return

        # Save position of the outgoing audio before the stream is destroyed so
        # the user can resume it later if they come back to that message.
        if self._current_audio_id is not None and self._audio_stream is not None:
            try:
                _ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
                pos   = _ctrl.get_position()
                total = _ctrl.get_length()
                if 0 < pos < total:
                    self._audio_positions[self._current_audio_id] = pos
            except Exception:
                pass
        self._stop_audio()

        if os.path.isfile(file_path):
            self._play_audio(msg_id, duration_seconds, file_path, audio_ext)
        else:
            if not hasattr(self, "_downloading_audio_ids"):
                self._downloading_audio_ids = set()
            
            if msg_id in self._downloading_audio_ids:
                self.main_window.output(self.main_window.i18n.t("downloading"))
                return

            import logging
            logging.info(f"[UI Audio Playback] File not found local, launching download thread. file_path={file_path}")
            self.main_window.output(self.main_window.i18n.t("downloading"))
            self._downloading_audio_ids.add(msg_id)

            def _download_and_play():
                try:
                    msg_type = msg.get("messageType", "") if msg else ""
                    try:
                        if msg_type == "audioMessage":
                            if msg is not None:
                                logging.info(f"[UI Audio Playback] Calling handle_audio_message for {msg_id}")
                                self.main_window.handle_audio_message(msg)
                        else:
                            if msg is not None:
                                logging.info(f"[UI Audio Playback] Calling handle_media_message for {msg_id}")
                                self.main_window.handle_media_message(msg)
                    except Exception as e:
                        logging.warning(
                            "[_download_and_play] download failed for %s: %s", msg_id, e,
                            exc_info=True,
                        )
                    # Only play if the file was actually downloaded (non-empty)
                    exists = os.path.isfile(file_path)
                    size = os.path.getsize(file_path) if exists else 0
                    logging.info(f"[UI Audio Playback] Finished download try. exists={exists}, size={size}")
                    if exists and size > 16:
                        wx.CallAfter(
                            self._play_audio, msg_id, duration_seconds, file_path, audio_ext
                        )
                    else:
                        # Download silently failed (timeout, expired CDN link,
                        # WPPConnect error) — the user's last feedback was
                        # "baixando..." with no follow-up; tell them it failed
                        # instead of leaving that as the final word.
                        wx.CallAfter(
                            self.main_window.output,
                            self.main_window.i18n.t("media_download_failed"),
                        )
                finally:
                    self._downloading_audio_ids.discard(msg_id)

            threading.Thread(target=_download_and_play, daemon=True).start()

    def _play_audio(self, msg_id, duration_seconds, file_path, audio_ext=".ogg"):
        if not os.path.isfile(file_path):
            return

        # ── Decrypt and write to a temp file ────────────────────────────────
        try:
            with open(file_path, "rb") as fh:
                content = decrypt_bytes(fh.read(), self.main_window.key)
            import logging
            logging.info(
                f"[UI Audio Playback] Decrypted {len(content)} bytes. "
                f"Header hex: {content[:16].hex()} "
                f"(OGG magic = 4f676753, Opus head = 4f707573)"
            )
            tmp = tempfile.NamedTemporaryFile(suffix=audio_ext, delete=False)
            tmp.write(content)
            tmp.close()
            self._audio_temp_file = tmp.name
        except Exception as e:
            import logging
            logging.exception(f"[UI Audio Playback] Error decrypting or creating temp audio file: {e}")
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
            except Exception as e:
                import logging
                logging.exception(f"[UI Audio Playback] Error creating fallback FileStream: {e}")
                self._stop_audio()
                return

        # ── Start playback ───────────────────────────────────────────────────
        # When Tempo FX is active the decode stream has no audio output of its
        # own; playback must be started on the Tempo wrapper instead.
        self._audio_stream_duration = int(duration_seconds)
        self._current_audio_id = msg_id
        self._audio_conv_jid   = (
            self.conversation.get("remoteJid", "") if self.conversation else ""
        )
        try:
            playback_ctrl = self._audio_tempo_ctrl if self._audio_tempo_ctrl is not None else self._audio_stream
            # Restore saved position (e.g. when another audio preempted this one)
            saved_pos = self._audio_positions.pop(msg_id, None)
            if saved_pos:
                try:
                    playback_ctrl.set_position(saved_pos)
                except Exception:
                    pass
            playback_ctrl.play()
        except Exception as e:
            import logging
            logging.exception(f"[UI Audio Playback] Error starting playback: {e}")
            self._stop_audio()
            return

        self._is_audio_playing = True
        self._audio_timer.Start(200)
        # Show controls only if the playing message is currently focused in the list.
        _speed = self._audio_speed_steps[self._audio_speed_index]
        if self._focused_msg_id() == msg_id:
            self._show_audio_controls()
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
        # Don't chain if the user has navigated to a different conversation —
        # _sorted_messages belongs to the current conversation, not the one
        # where the audio was playing.
        current_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if current_jid != self._audio_conv_jid:
            return

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
                # Only move list focus to the next audio if the user hasn't
                # already scrolled past it — avoids disrupting reading when
                # sequential audio plays in the background.
                current_focus = self.messages_list.GetFocusedItem()
                if current_focus < 0 or current_focus <= next_idx:
                    self.messages_list.Focus(next_idx)
                    self.messages_list.Select(next_idx, True)
                    self.messages_list.EnsureVisible(next_idx)
                clean_msg_id = msg_id
                if "_" in msg_id:
                    parts = msg_id.split("_")
                    clean_msg_id = parts[2] if len(parts) > 2 else parts[-1]
                self._toggle_playback(
                    msg_id, duration, next_msg,
                    file_path=data_path("voice_messages", f"{clean_msg_id}.msv"),
                    audio_ext=".ogg",
                )
            break  # stop regardless (either play next or not)

    def on_audio_speed_btn(self, event):
        self._audio_speed_index = (self._audio_speed_index + 1) % len(
            self._audio_speed_steps
        )
        self._apply_audio_speed()

    def _on_audio_speed_decrease(self, event):
        """Alt+, — step down one speed level (wraps at minimum)."""
        if self._audio_speed_index > 0:
            self._audio_speed_index -= 1
            self._apply_audio_speed()

    def _on_audio_speed_increase(self, event):
        """Alt+. — step up one speed level (wraps at maximum)."""
        if self._audio_speed_index < len(self._audio_speed_steps) - 1:
            self._audio_speed_index += 1
            self._apply_audio_speed()

    def _apply_audio_speed(self):
        """Apply the current speed index to the active stream and persist it."""
        speed = self._audio_speed_steps[self._audio_speed_index]
        self.audio_speed_btn.SetLabel(self._format_speed(speed))
        if self._audio_tempo_ctrl is not None:
            try:
                self._audio_tempo_ctrl.tempo = self._audio_tempo_map[speed]
            except Exception:
                pass
        self.main_window.settings.setdefault("audio_playback", {})["audio_default_speed"] = speed
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
            ts_val = int(ts)
            if ts_val > 1_000_000_000_000:
                ts_val //= 1000
            return ts_val
        except Exception:
            return None

    def _format_date(self, ts):
        if not ts:
            return ""
        try:
            ts_val = int(ts)
            if ts_val > 1_000_000_000_000:
                ts_val //= 1000
            dt    = datetime.fromtimestamp(ts_val)
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

    def _resolve_mentions_in_text(self, text: str, mentioned: list) -> str:
        """Replace @{number}/@{lid} placeholders in *text* with display names.

        Shared by both the main message renderer and the quoted-message
        preview renderer, so a quoted message that itself contains a mention
        gets the same @lid → contact-name resolution as a normal message
        instead of showing the raw @<lid digits>.
        """
        for jid in mentioned or []:
            mw_ref = self.main_window
            if mw_ref._is_self_jid(jid):
                name = "eu"
            else:
                name = self._get_participant_name(jid)

            # Check what pattern (LID local part or phone number) is used in the text
            lid_local = jid.rsplit("@", 1)[0]
            _lid_map = getattr(mw_ref, "_lid_to_phone", {})
            phone_jid = _lid_map.get(jid, "") if jid.endswith("@lid") else ""
            phone = phone_jid.split("@")[0] if phone_jid else jid.split("@")[0]

            placeholder = None
            if f"@{lid_local}" in text:
                placeholder = lid_local
            elif phone and f"@{phone}" in text:
                placeholder = phone

            if not placeholder:
                continue

            if name and name != placeholder and name != jid:
                text = text.replace(f"@{placeholder}", f"@{name}", 1)
        return text

    def _get_message_content(self, msg) -> str:
        """
        Return the human-readable text for a message item in the list.
        Field names match the WPPConnect API v2 / Baileys proto definitions.
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
            ext  = msg_obj.get("extendedTextMessage") or {}
            text = ext.get("text", "") or ""
            # Resolve @mentions: replace @{number} with @{display_name}.
            # mentionedJid may live at the top-level contextInfo (WPPConnect API
            # normalises it there) or inside extendedTextMessage.contextInfo.
            ctx_top = msg.get("contextInfo") or {}
            ctx_msg = msg_obj.get("contextInfo") or {}
            ctx_ext = ext.get("contextInfo") or {}
            mentioned = (
                ctx_top.get("mentionedJid") or ctx_top.get("mentionedJidList")
                or ctx_msg.get("mentionedJid") or ctx_msg.get("mentionedJidList")
                or ctx_ext.get("mentionedJid") or ctx_ext.get("mentionedJidList")
                or []
            )
            return self._resolve_mentions_in_text(text, mentioned)

        # ── Audio ────────────────────────────────────────────────────────────
        if msg_type == "audioMessage":
            audio = msg_obj.get("audioMessage") or {}
            dur   = self._format_duration(audio.get("seconds"))
            return f"{i18n.t('message_type_audio')}, {i18n.t('duration')}: {dur}"

        # ── Document ─────────────────────────────────────────────────────────
        if msg_type == "documentMessage":
            doc      = msg_obj.get("documentMessage") or {}
            filename = doc.get("fileName") or doc.get("title") or i18n.t("document")
            size_str = self._format_filesize(doc.get("fileLength"))
            msg_id   = msg.get("key", {}).get("id", "")
            progress = self._download_progress.get(msg_id)
            if progress is not None and progress < 1.0:
                pct      = int(progress * 100)
                prog_str = i18n.t("downloading_progress").format(pct=pct)
                return f"{i18n.t('document')}, {filename}, {prog_str}"
            parts = [i18n.t("document"), filename]
            if size_str:
                parts.append(size_str)
            return ", ".join(parts)

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

        # ── Poll ─────────────────────────────────────────────────────────────
        if msg_type in ("pollCreationMessage", "pollCreationMessageV2", "pollCreationMessageV3", "pollUpdateMessage"):
            poll = msg_obj.get("pollCreationMessage") or msg_obj.get("pollCreationMessageV2") or msg_obj.get("pollCreationMessageV3") or {}
            name = poll.get("name") or ""
            return f"📊 Enquete: {name}" if name else "📊 Enquete"

        # ── Location ─────────────────────────────────────────────────────────
        if msg_type in ("locationMessage", "liveLocationMessage"):
            return "📍 Localização"

        # ── Template ─────────────────────────────────────────────────────────
        if msg_type == "templateMessage":
            return "📝 Modelo"

        # ── Revoked / Protocol Message ───────────────────────────────────────
        if msg_type == "protocolMessage":
            protocol = msg_obj.get("protocolMessage") or {}
            p_type = protocol.get("type")
            if p_type in (3, "REVOKE", "revoke"):
                return "Mensagem apagada"
            return "⚙️ Mensagem do sistema"

        # ── Interactive / Button reply ───────────────────────────────────────
        if msg_type == "buttonsResponseMessage":
            btn = msg_obj.get("buttonsResponseMessage") or {}
            text = btn.get("selectedDisplayText") or ""
            return text or i18n.t("interactive_reply")

        if msg_type == "listResponseMessage":
            lst = msg_obj.get("listResponseMessage") or {}
            title = lst.get("title", "")
            reply = (lst.get("singleSelectReply") or {}).get("selectedRowId", "")
            return title or reply or i18n.t("list_reply")

        if msg_type == "interactiveMessage":
            inter = msg_obj.get("interactiveMessage") or {}
            body = (inter.get("body") or {}).get("text", "")
            return body or i18n.t("interactive_message")

        # ── Fallback ─────────────────────────────────────────────────────────
        return i18n.t("unsupported_message").format(
            app_name=self.main_window.app_name
        )

    def _is_displayable_message(self, m) -> bool:
        if not isinstance(m, dict):
            return False
        msg_type = m.get("messageType", "")

        # Whitelist of user-visible/displayable message types
        allowed_types = (
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
        )

        if msg_type not in allowed_types:
            return False

        if msg_type == "protocolMessage":
            # Only display if it's a revoke/delete message
            protocol = (m.get("message") or {}).get("protocolMessage") or {}
            p_type = protocol.get("type")
            return p_type in (3, "REVOKE", "revoke")
        return True

    def _map_status(self, msg) -> str:
        i18n = self.main_window.i18n
        # Locally-queued messages have their own pending status.
        if msg.get("_local_pending"):
            return i18n.t("status_pending")
        if msg.get("_send_failed"):
            return i18n.t("status_failed")

        statuses = []
        updates = msg.get("MessageUpdate")
        if isinstance(updates, list) and updates:
            for u in updates:
                if isinstance(u, dict):
                    st = u.get("status") or ""
                    statuses.append(str(st).upper())
        
        # Fallback: check status directly on the message (2=sent, 3=delivered, 4=read, 5=played)
        root_status = msg.get("status")
        if root_status is not None:
            statuses.append(str(root_status).upper())
            
        # Fallback: check ack directly on the message (WPPConnect format: 1=sent, 2=delivered, 3=read, 4=played)
        root_ack = msg.get("ack")
        if root_ack is not None:
            status_map = {1: 2, 2: 3, 3: 4, 4: 5}
            mapped_ack = status_map.get(root_ack, root_ack)
            statuses.append(str(mapped_ack).upper())

        from_me = msg.get("key", {}).get("fromMe", False)

        for s in statuses:
            if "PLAYED" in s or s == "5":
                return i18n.t("status_played")

        if not from_me:
            # Received messages only show status if they were played
            return ""

        for s in statuses:
            if "READ" in s or s == "4":
                return i18n.t("status_read")
        for s in statuses:
            if "DELIVERED" in s or "DELIVERY_ACK" in s or s == "3":
                return i18n.t("status_delivered")
        for s in statuses:
            if "SENT" in s or "ACK" in s or s == "2":
                return i18n.t("status_sent")
        return ""

    def _sender_label(self, msg) -> str:
        if msg.get("key", {}).get("fromMe"):
            return self.main_window.self_reference_label()
        key         = msg.get("key", {})
        participant = key.get("participant", "")
        jid         = key.get("remoteJid", "")
        lookup_jid  = participant or jid
        mw = self.main_window
        lid_to_phone = getattr(mw, "_lid_to_phone", {})

        def _strip_device(j: str) -> str:
            """Remove Baileys device suffix (':N') from a JID, e.g.
            '5511:5@s.whatsapp.net' → '5511@s.whatsapp.net'."""
            if ":" in j and "@" in j:
                local, domain = j.rsplit("@", 1)
                return f"{local.split(':')[0]}@{domain}"
            return j

        def _contact_name(lj: str) -> str:
            """Return saved contact name for lj, trying all three JID formats
            (@s.whatsapp.net, @c.us, @lid), stripping Baileys device suffixes."""
            lj_clean = _strip_device(lj)
            # Normalise @c.us → @s.whatsapp.net so we always start from the modern format
            if lj_clean.endswith("@c.us"):
                lj_clean = lj_clean[:-5] + "@s.whatsapp.net"
            candidates = [lj_clean]
            if lj_clean != lj:
                candidates.append(lj)  # also try original pre-normalisation form
            if lj_clean.endswith("@lid"):
                phone = lid_to_phone.get(lj_clean, "")
                if phone:
                    candidates.append(phone)
                    # contacts may be indexed under @c.us legacy format
                    candidates.append(phone.rsplit("@", 1)[0] + "@c.us")
            elif lj_clean.endswith("@s.whatsapp.net"):
                # Also try @c.us — contacts dict may still hold the legacy format
                candidates.append(lj_clean.rsplit("@", 1)[0] + "@c.us")
                # O(1) reverse lookup for @lid equivalent
                lid = getattr(mw, "_phone_to_lid", {}).get(lj_clean, "")
                if lid:
                    candidates.append(lid)

            ppm = getattr(mw, "_presence_pushname_map", {})
            for cjid in candidates:
                c = mw.contacts.get(cjid)
                if c:
                    n = (c.get("name") or c.get("pushName") or "").strip()
                    if n and not n.isdigit() and not is_phone_like(n):
                         n_lower = n.lower()
                         if "sem nome" in n_lower or "unnamed" in n_lower or n_lower in ("no name", "unknown", "desconhecido"):
                             pass
                         else:
                             return n
                chat_obj = mw.chats.get(cjid)
                if chat_obj:
                    cn = (chat_obj.get("name") or "").strip()
                    if cn and not cn.isdigit() and not is_phone_like(cn):
                        cn_lower = cn.lower()
                        if "sem nome" in cn_lower or "unnamed" in cn_lower or cn_lower in ("no name", "unknown", "desconhecido"):
                            pass
                        else:
                            return cn
            # Fallback: presence-learned pushName map
            for cjid in candidates:
                pname = (ppm.get(cjid) or "").strip()
                if pname and not pname.isdigit() and not is_phone_like(pname):
                    return pname
            return ""

        # Don't use the group JID (@g.us) itself as a sender lookup — when
        # key.participant is absent, lookup_jid falls back to the remoteJid of
        # the group, and _contact_name would return the group name for every
        # message, making all messages appear to be from the same sender.
        if lookup_jid and not lookup_jid.endswith("@g.us"):
            n = _contact_name(lookup_jid)
            if n:
                return n

        # For private chats the contact resolution above may have missed the
        # name when the message JID and chat storage key differ (e.g. @lid vs
        # @s.whatsapp.net).  Use the same resolution chain as the chat list so
        # the sender name stays consistent with what is shown there.
        if not participant:
            conv = self.conversation
            if conv and not conv.get("remoteJid", "").endswith("@g.us"):
                n = (
                    mw._resolve_contact_name(conv)
                    or mw.find_name_through_messages(conv)
                    or conv.get("name", "")
                    or conv.get("pushName", "")
                )
                if n:
                    return n

        push = msg.get("pushName", "")
        if push and not is_phone_like(push):
            return push

        # Last resort: format the phone number
        alt = key.get("remoteJidAlt", "")
        if alt and alt.endswith("@s.whatsapp.net"):
            return format_number(alt)
        phone_jid = participant or jid
        if phone_jid.endswith("@lid"):
            phone_jid = lid_to_phone.get(phone_jid, "")
        # Never use the group JID itself as a display name for a message sender.
        if phone_jid and not phone_jid.endswith("@lid") and not phone_jid.endswith("@g.us"):
            return format_number(phone_jid)
        return ""

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
            ext = quoted_msg.get("extendedTextMessage") or {}
            text = ext.get("text") or ""
            # The quoted message may itself contain @mentions; resolve them
            # the same way the main message renderer does, instead of
            # leaving the raw @<lid digits> placeholder in the preview.
            ctx_top = quoted_msg.get("contextInfo") or {}
            ctx_ext = ext.get("contextInfo") or {}
            mentioned = (
                ctx_top.get("mentionedJid") or ctx_top.get("mentionedJidList")
                or ctx_ext.get("mentionedJid") or ctx_ext.get("mentionedJidList")
                or []
            )
            if mentioned:
                text = self._resolve_mentions_in_text(text, mentioned)
            return text

        # Support raw WPPConnect types and body/text keys
        msg_type_raw = quoted_msg.get("type")
        if msg_type_raw:
            _wpp_type_map = {
                "audio": "message_type_audio",
                "ptt": "message_type_audio",
                "image": "photo",
                "video": "video",
                "document": "document",
                "sticker": "sticker",
                "contact": "contact_label",
            }
            if msg_type_raw in _wpp_type_map:
                cap = quoted_msg.get("caption") or quoted_msg.get("body") or ""
                # Avoid displaying base64 thumbnails
                if cap and not cap.startswith("data:") and not cap.startswith("/9j/"):
                    label = i18n.t(_wpp_type_map[msg_type_raw])
                    return f"{label[0].upper() + label[1:] if label else ''}: {cap}"
                label = i18n.t(_wpp_type_map[msg_type_raw])
                return label[0].upper() + label[1:] if label else ""

        if "body" in quoted_msg:
            body_val = quoted_msg.get("body") or ""
            if not body_val.startswith("data:") and not body_val.startswith("/9j/"):
                return body_val
        if "text" in quoted_msg:
            return (quoted_msg.get("text") or "")

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
        """Extract contextInfo from wherever it sits in the message hierarchy.

        WPPConnect API's prepareMessage() merges extendedTextMessage.contextInfo
        into the top-level 'contextInfo' field before erasing the sub-object,
        so we check there first.  For audio/image/video replies the contextInfo
        stays inside the respective sub-message type.
        """
        # Top-level contextInfo (WPPConnect API normalised text replies)
        top_ctx = msg.get("contextInfo")
        if isinstance(top_ctx, dict) and ("quotedMessage" in top_ctx or top_ctx.get("stanzaId")):
            return top_ctx

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
                if isinstance(ctx, dict) and ("quotedMessage" in ctx or ctx.get("stanzaId")):
                    return ctx
        return None

    def _get_quoted_sender(self, ctx: dict, msg: dict) -> str:
        """Resolve the display name of the quoted message sender from contextInfo."""
        mw   = self.main_window
        i18n = mw.i18n

        def _strip_dev(j: str) -> str:
            if ":" in j and "@" in j:
                local, domain = j.rsplit("@", 1)
                return f"{local.split(':')[0]}@{domain}"
            return j

        def _phone_part(j: str) -> str:
            return j.rsplit("@", 1)[0].split(":")[0]

        participant = ctx.get("participant", "")

        if not participant:
            # Fast path: use local hint set when building virtual reply message.
            if "_quotedFromMe" in ctx:
                return mw.self_reference_label() if ctx["_quotedFromMe"] else (
                    mw._resolve_contact_name(self.conversation or {})
                    or (self.conversation or {}).get("pushName", "")
                    or ""
                )
            # 1:1 chat: Baileys leaves participant empty; resolve by stanzaId lookup.
            stanza_id = ctx.get("stanzaId", "")
            if stanza_id:
                for m in self._sorted_messages:
                    if m.get("key", {}).get("id") == stanza_id:
                        if m.get("key", {}).get("fromMe", False):
                            return mw.self_reference_label()
                        # Not fromMe → the other party in the conversation
                        conv = self.conversation or {}
                        remote = conv.get("remoteJid", "")
                        return (
                            mw._resolve_contact_name(conv)
                            or conv.get("pushName", "")
                            or (format_number(remote) if remote and not remote.endswith(("@g.us", "@lid")) else "")
                        )
            # Fallback when the quoted message is not in local _sorted_messages:
            # In a 1:1 chat, if I sent this reply, I am replying to the other party.
            # If the other party sent this reply, they are replying to me ("você").
            from_me = msg.get("key", {}).get("fromMe", False)
            if from_me:
                conv = self.conversation or {}
                remote = conv.get("remoteJid", "")
                return (
                    mw._resolve_contact_name(conv)
                    or conv.get("pushName", "")
                    or (format_number(remote) if remote and not remote.endswith(("@g.us", "@lid")) else "")
                )
            else:
                return mw.self_reference_label()

        # Strip Baileys device suffix before contact lookup
        clean_p = _strip_dev(participant)

        # Bridge @lid → phone
        if clean_p.endswith("@lid"):
            clean_p = getattr(mw, "_lid_to_phone", {}).get(clean_p, clean_p)

        # Private (1:1) chat fallback: resolve to the other participant or "me"
        # without contact lookup to handle unresolved @lid JIDs and digit-only pushNames.
        conv = self.conversation or {}
        remote = conv.get("remoteJid", "")
        if remote and not remote.endswith("@g.us"):
            p_phone = _phone_part(clean_p)
            r_phone = _phone_part(remote)
            my_jid = getattr(mw, "my_jid", "")
            my_phone = _phone_part(my_jid) if my_jid else ""
            if my_phone and p_phone == my_phone:
                return mw.self_reference_label()
            elif p_phone == r_phone:
                return (
                    mw._resolve_contact_name(conv)
                    or conv.get("pushName", "")
                    or (format_number(remote) if not remote.endswith("@lid") else "")
                )
            else:
                return mw.self_reference_label()

        # Check if the quoted sender is "me" — strip device suffix from both sides
        my_jid = getattr(mw, "my_jid", "")
        if my_jid and _phone_part(clean_p) == _phone_part(my_jid):
            return mw.self_reference_label()

        return self._get_participant_name(clean_p)

    def _render_message_line(self, msg) -> str:
        """Produce the full display string for a single message row."""
        # Unread separator sentinel
        if self._is_separator(msg):
            return self._render_separator(msg.get("count", 1))
        ts       = self._extract_timestamp(msg)
        time_str = self._format_date(ts) if ts else ""
        body     = (self._get_message_content(msg) or "")
        sender   = self._sender_label(msg)
        status   = self._map_status(msg)
        i18n     = self.main_window.i18n

        # Check for quoted/reply context
        ctx           = self._get_context_info(msg)
        quoted_sender = self._get_quoted_sender(ctx, msg) if ctx else ""

        if quoted_sender:
            header = f"{sender}, {i18n.t('replying_to').format(name=quoted_sender)}"
        else:
            header = sender

        pieces = [f"{header}: {body}"]
        if msg.get("starred"):
            pieces[0] = f"★ {pieces[0]}"
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
        """Pause/resume recording when active (no-op otherwise)."""
        if self._is_recording:
            self._toggle_pause_recording(event)

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

        For private chats the note comes from the _presence_cache (populated
        by presence.update WebSocket events) rather than from fetchProfile,
        because the WPPConnect API's fetchProfile response does not include
        lastSeen or online fields.
        """
        jid      = conversation.get("remoteJid", "")
        mw       = self.main_window
        i18n     = mw.i18n
        
        # Subscribe to presence updates for this conversation to receive typing/online events
        mw.subscribe_presence(jid)

        note = (
            mw._resolve_contact_name(conversation)
            or mw.find_name_through_messages(conversation)
            or conversation.get("name", "")
            or conversation.get("pushName", "")
            or format_number(jid)
        )
        try:
            if jid.endswith("@g.us"):
                data = mw.get_group_info(jid)
                # "size" may be absent in some WPPConnect API builds; fall back to
                # counting the participants list which is always present.
                participants = data.get("participants", [])
                size = data.get("size") or len(participants)
                group_name = (
                    mw._resolve_contact_name(conversation)
                    or mw.find_name_through_messages(conversation)
                    or conversation.get("name", "")
                    or conversation.get("pushName", "")
                    or format_number(jid)
                )
                note = f"{group_name}, {i18n.t('group_size').format(count=size)}"
            else:
                # Private chat: resolve the canonical JID for cache lookup
                canonical = mw._normalize_jid(jid)
                if canonical.endswith("@lid"):
                    mapped = getattr(mw, "_lid_to_phone", {}).get(canonical)
                    if not mapped:
                        logging.info(f"[_fetch_and_update_profile] On-demand JID mapping missing for {canonical}. Triggering background query.")
                        # Fetch profile in background to resolve JID mapping
                        mw.get_contact_profile(canonical)
                    canonical = getattr(mw, "_lid_to_phone", {}).get(canonical, canonical)
                presence = getattr(mw, "_presence_cache", {}).get(canonical, {})
                lkp      = presence.get("lastKnownPresence", "")
                # Fall back to a direct last-seen fetch when no presence event
                # has arrived yet (so the note isn't left without it).
                last_seen = presence.get("lastSeen") or mw.get_last_seen(canonical)
                if lkp in ("available", "composing", "recording"):
                    note = i18n.t("online_status")
                elif last_seen:
                    ls_str = _fmt_last_seen(last_seen, i18n)
                    if ls_str:
                        note = ls_str
        except Exception:
            pass

        def _update():
            if (self.conversation is not None
                    and self.conversation.get("remoteJid") == jid):
                try:
                    display_note = note
                    if not jid.endswith("@g.us") and is_phone_like(display_note):
                        display_note = f"{i18n.t('phone_label')}: {display_note}"
                    self._conv_data_btn.SetNote(display_note)
                    self.conversation_panel.Layout()
                except Exception:
                    pass

        wx.CallAfter(_update)

    def _refresh_presence_note(self, canonical_jid: str):
        """
        Called on the main thread by on_presence_update when a presence.update
        arrives for the currently open conversation.  Updates the button note
        immediately without going through the background-fetch path.
        """
        if self.conversation is None:
            return
        mw    = self.main_window
        i18n  = mw.i18n
        presence  = getattr(mw, "_presence_cache", {}).get(canonical_jid, {})
        lkp       = presence.get("lastKnownPresence", "")
        last_seen  = presence.get("lastSeen")

        jid = self.conversation.get("remoteJid", "")
        # Default note stays as the contact name
        note = (
            mw._resolve_contact_name(self.conversation)
            or mw.find_name_through_messages(self.conversation)
            or self.conversation.get("name", "")
            or self.conversation.get("pushName", "")
            or format_number(jid)
        )

        if lkp in ("available", "composing", "recording"):
            note = i18n.t("online_status")
        elif lkp == "unavailable" and last_seen:
            ls_str = _fmt_last_seen(last_seen, i18n)
            if ls_str:
                note = ls_str

        try:
            display_note = note
            if not jid.endswith("@g.us") and is_phone_like(display_note):
                display_note = f"{i18n.t('phone_label')}: {display_note}"
            self._conv_data_btn.SetNote(display_note)
            self.conversation_panel.Layout()
        except Exception:
            pass

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
        self.main_window.clear_chat(jid)
        # Refresh messages list if this conversation is open
        if self.conversation and self.conversation.get("remoteJid") == jid:
            self._sorted_messages = []
            self.messages_list.DeleteAllItems()
        # Refresh the conversations list immediately so the now-empty chat is
        # removed, keeping focus on a neighbouring conversation.
        self.main_window._schedule_set_chats()

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
        self.main_window.delete_chat(jid)

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
        elif msg_type == "extendedTextMessage":
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        if text:
            try:
                pyperclip.copy(text)
                self.main_window.output(self.main_window.i18n.t("msg_copied"))
            except Exception:
                self.main_window.output(self.main_window.i18n.t("msg_copy_error"))
        else:
            self.main_window.output(self.main_window.i18n.t("msg_copy_error"))

    def _on_menu_copy_file(self, msg: dict):
        """Decrypt media file and place it on the clipboard as a file object."""
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        msg_id   = msg.get("key", {}).get("id", "")
        if not msg_id:
            return

        if msg_type == "documentMessage":
            ext = ""
            doc = msg_obj.get("documentMessage") or {}
            filename = doc.get("fileName", f"documento_{msg_id}")
            if "." in filename:
                ext = "." + filename.split(".")[-1]
        elif msg_type == "imageMessage":
            mime = (msg_obj.get("imageMessage") or {}).get("mimetype", "image/jpeg")
            ext  = "." + (mime.split("/")[-1] if "/" in mime else "jpg")
        elif msg_type == "videoMessage":
            mime = (msg_obj.get("videoMessage") or {}).get("mimetype", "video/mp4")
            ext  = "." + (mime.split("/")[-1] if "/" in mime else "mp4")
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
                
                # Write decrypted content to a temp file
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(content)
                tmp.close()
                
                # Copy the temporary file to clipboard (must run on the main thread)
                def _to_clipboard(path=tmp.name):
                    try:
                        if wx.TheClipboard.Open():
                            file_data = wx.FileDataObject()
                            file_data.AddFile(path)
                            wx.TheClipboard.SetData(file_data)
                            wx.TheClipboard.Close()
                            self.main_window.output(self.main_window.i18n.t("msg_copied"))
                        else:
                            self.main_window.output(self.main_window.i18n.t("msg_copy_error"))
                    except Exception as e:
                        print(f"[_to_clipboard] Clipboard error: {e}")
                        self.main_window.output(self.main_window.i18n.t("msg_copy_error"))

                wx.CallAfter(_to_clipboard)
            except Exception as exc:
                print(f"[_on_menu_copy_file] Error copying file: {exc}")
                wx.CallAfter(self.main_window.output, self.main_window.i18n.t("msg_copy_error"))

        threading.Thread(target=_run, daemon=True).start()

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
        if mw._is_self_jid(participant_jid):
            return mw.self_reference_label()
        lid_to_phone = getattr(mw, "_lid_to_phone", {})
        ppm = getattr(mw, "_presence_pushname_map", {})

        # Build candidates covering all three JID formats for the same person.
        # Address-book name (contact["name"]) always takes priority over pushName.
        local = participant_jid.rsplit("@", 1)[0]
        candidates = [participant_jid]
        if participant_jid.endswith("@lid"):
            phone = lid_to_phone.get(participant_jid, "")
            if phone:
                candidates.append(phone)
                candidates.append(phone.rsplit("@", 1)[0] + "@c.us")
        elif participant_jid.endswith("@s.whatsapp.net"):
            candidates.append(local + "@c.us")
            lid = getattr(mw, "_phone_to_lid", {}).get(participant_jid, "")
            if lid:
                candidates.append(lid)
        elif participant_jid.endswith("@c.us"):
            candidates.append(local + "@s.whatsapp.net")

        for cjid in candidates:
            contact = mw.contacts.get(cjid)
            if contact:
                name = (contact.get("name") or contact.get("pushName") or "").strip()
                if name and not name.isdigit() and not is_phone_like(name):
                    return name
            chat_obj = mw.chats.get(cjid)
            if chat_obj:
                cn = (chat_obj.get("name") or "").strip()
                if cn and not cn.isdigit() and not is_phone_like(cn):
                    return cn
        if msg is not None:
            for key_candidate in ("pushName", "pushname", "name", "displayName"):
                push = msg.get(key_candidate, "")
                if push and not push.isdigit() and not is_phone_like(push):
                    return push
        # Fallback: presence-learned pushName map
        for cjid in candidates:
            pname = (ppm.get(cjid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname
        # Fallback 2: scan sorted messages in the current conversation
        for m in getattr(self, "_sorted_messages", []):
            if not isinstance(m, dict):
                continue
            m_part = m.get("key", {}).get("participant") or m.get("participant")
            if m_part:
                m_part = mw._normalize_jid(m_part)
                if m_part in candidates:
                    push = m.get("pushName", "")
                    if push and not push.isdigit() and not is_phone_like(push):
                        return push
        # Fallback 3: check self._group_participants_cache
        for pname, p_jid in getattr(self, "_group_participants_cache", []):
            if p_jid in candidates:
                if pname and not pname.isdigit() and not is_phone_like(pname):
                    return pname
        if not participant_jid.endswith("@lid"):
            return format_number(participant_jid) or participant_jid
        phone = lid_to_phone.get(participant_jid, "")
        if not phone and isinstance(msg, dict):
            pn = msg.get("phoneNumber") or msg.get("pnJid")
            if pn:
                if isinstance(pn, dict):
                    phone = pn.get("_serialized") or pn.get("id") or ""
                else:
                    phone = str(pn)
                if phone:
                    phone = mw._normalize_jid(phone)
                    mw.register_jid_mapping(participant_jid, phone)
        if phone:
            return format_number(phone)
        # No phone mapping for this @lid — return just the local part (strip "@lid")
        # so the display shows the raw identifier without the domain suffix.
        return participant_jid.rsplit("@", 1)[0]


    def refresh_active_conversation_messages(self):
        """Re-render all messages in the active message list (useful after background name/LID resolution)."""
        if not self.conversation or not hasattr(self, "messages_list"):
            return
        for i, msg in enumerate(self._sorted_messages):
            if not self._is_separator(msg):
                self.messages_list.SetItemText(i, self._render_message_line(msg))

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
        quoted_id = ctx.get("stanzaId") or ""
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

        vsz.Add(
            wx.StaticText(p, label=i18n.t("forward_search_label")),
            0, wx.LEFT | wx.TOP | wx.RIGHT, 6,
        )
        search_field = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        search_field.SetHint(i18n.t("search_conversations"))
        vsz.Add(search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

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

        # ── Extract forwardable text from the message ─────────────────────────
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        text = ""

        if msg_type == "conversation":
            text = msg_obj.get("conversation") or ""
        elif msg_type == "extendedTextMessage":
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        else:
            for sub_key in ("imageMessage", "videoMessage", "documentMessage", "audioMessage"):
                sub = msg_obj.get(sub_key) or {}
                if sub:
                    text = sub.get("caption", "")
                    break

        if not text:
            return

        # ── Enqueue and add virtual message so the UI reflects the send ───────
        from core.message_queue import PendingMessage
        local_id = str(uuid.uuid4())
        virtual_msg = {
            "_local_pending":   True,
            "_local_id":        local_id,
            "key": {
                "id":        local_id,
                "fromMe":    True,
                "remoteJid": target_jid,
            },
            "messageType":      "conversation",
            "message":          {"conversation": text},
            "messageTimestamp": int(time.time()),
            "pushName":         "",
        }

        mw.message_queue.enqueue(
            PendingMessage(local_id=local_id, jid=target_jid, text=text)
        )

        # Register in chat records so _last_msg_preview shows the forwarded text.
        self._register_virtual_msg(virtual_msg)

        # If the target conversation is currently open, add to the visible list.
        current_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if target_jid == current_jid:
            self._sorted_messages.append(virtual_msg)
            self.conversation.setdefault("messages", {}).setdefault("messages", {}).setdefault("records", []).append(virtual_msg)
            self.messages_list.Append((self._render_message_line(virtual_msg),))
            last = self.messages_list.GetItemCount() - 1
            if last >= 0:
                self.messages_list.EnsureVisible(last)

        mw._schedule_set_chats()

    def _on_menu_star(self, msg: dict):
        msg["starred"] = not msg.get("starred")
        jid = self.conversation.get("remoteJid", "")
        if jid:
            self.main_window._schedule_save()
            self.populate_messages(preserve_focus=True)

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
            # Revoke for everyone via WPPConnect API (off the UI thread). The
            # message key carries fromMe/participant so the server can build the
            # correct serialized id and actually revoke it.
            msg_key = msg.get("key", {})
            jid = msg_key.get("remoteJid", "") or (
                self.conversation.get("remoteJid", "") if self.conversation else ""
            )

            def _revoke(k=dict(msg_key), j=jid):
                ok = self.main_window.delete_message_for_everyone(j, k)
                if not ok:
                    wx.CallAfter(
                        wx.MessageBox,
                        i18n.t("delete_for_everyone_failed"),
                        i18n.t("delete_message"),
                        wx.OK | wx.ICON_WARNING,
                    )
            threading.Thread(target=_revoke, daemon=True).start()

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
            try:
                self.main_window.db.delete_message(
                    self.conversation.get("remoteJid", ""), msg_id
                )
            except Exception:
                logging.exception("[conversations] delete_message failed")

    def _on_accel_edit_message(self, event):
        """Alt+E: enter edit mode for the focused own text message."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        if not msg.get("key", {}).get("fromMe", False):
            return
        if msg.get("messageType") not in ("conversation", "extendedTextMessage"):
            return
        if (time.time() - msg.get("messageTimestamp", 0)) >= 10800:
            return
        self._on_menu_edit_message(index, msg)

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
        self.message_field.SetFocus()

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
        self.message_field.SetFocus()

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

    def _on_accel_block(self, event):
        """Ctrl+Shift+B: block/unblock the current contact."""
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if not jid or jid.endswith("@g.us"):
            return
        if self.main_window._is_self_jid(jid):
            return  # cannot block yourself
        self._on_menu_block(self.conversation, jid)

    def _on_accel_toggle_read(self, event):
        """Ctrl+Shift+M: mark conversation as read if it has unreads, else unread."""
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if not jid:
            return
        if int(self.conversation.get("unreadCount") or 0) > 0:
            self.main_window.mark_conversation_as_read(jid)
        else:
            self.main_window.mark_conversation_as_unread(jid)

    def _on_accel_clear(self, event):
        """Ctrl+Shift+L: clear all local messages from the current conversation."""
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if jid:
            self._on_menu_clear_chat(jid)

    def _on_accel_react(self, event):
        """Ctrl+Shift+R: open the reaction picker for the focused message."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if not self._is_separator(msg):
            self._on_menu_react(msg)

    def _on_accel_star(self, event):
        """Ctrl+Shift+I: star/favourite the focused message."""
        index = self.messages_list.GetFirstSelected()
        if 0 <= index < len(self._sorted_messages):
            msg = self._sorted_messages[index]
            if not self._is_separator(msg):
                self._on_menu_star(msg)

    def _on_accel_delete_conv(self, event):
        """Delete (in chat list): delete the focused conversation."""
        chat = self._selected_chat_from_list()
        if chat:
            jid = chat.get("remoteJid", "")
            if jid:
                self._on_menu_delete_chat(jid)

    def _selected_chat_from_list(self):
        selected = self.conversations_list.GetFirstSelected()
        if selected < 0:
            selected = self.conversations_list.GetFocusedItem()
        if 0 <= selected < len(self.chats_list):
            return self.chats_list[selected]
        return None

    def _on_accel_conversation_data_list(self, event):
        chat = self._selected_chat_from_list()
        if chat:
            self._show_conversation_data(chat=chat)

    def _on_accel_toggle_read_list(self, event):
        chat = self._selected_chat_from_list()
        if not chat:
            return
        jid = chat.get("remoteJid", "")
        if not jid:
            return
        if int(chat.get("unreadCount") or 0) > 0:
            self._on_menu_mark_read(jid)
        else:
            self._on_menu_mark_unread(jid)

    def _on_accel_mute_list(self, event):
        chat = self._selected_chat_from_list()
        if not chat:
            return
        jid = chat.get("remoteJid", "")
        if not jid:
            return
        if self.main_window.is_chat_muted(jid):
            self._on_menu_unmute(jid)
        else:
            self._on_menu_mute(jid, 28800)

    def _on_accel_block_list(self, event):
        chat = self._selected_chat_from_list()
        if not chat:
            return
        jid = chat.get("remoteJid", "")
        if not jid or jid.endswith("@g.us") or self.main_window._is_self_jid(jid):
            return
        self._on_menu_block(chat, jid)

    def _on_accel_clear_list(self, event):
        chat = self._selected_chat_from_list()
        if chat:
            jid = chat.get("remoteJid", "")
            if jid:
                self._on_menu_clear_chat(jid)

    def _on_accel_archive_list(self, event):
        chat = self._selected_chat_from_list()
        if not chat:
            return
        jid = chat.get("remoteJid", "")
        if not jid:
            return
        if self.main_window.is_chat_archived(jid):
            self._on_menu_unarchive(jid)
        else:
            self._on_menu_archive(jid)

    def _on_accel_pin_list(self, event):
        chat = self._selected_chat_from_list()
        if not chat:
            return
        jid = chat.get("remoteJid", "")
        if not jid:
            return
        if self.main_window.is_chat_pinned(jid):
            self._on_menu_unpin(jid)
        else:
            self._on_menu_pin(jid)

    def _on_accel_copy_message(self, event):
        """Ctrl+C: copy focused message text to clipboard."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        msg_type = msg.get("messageType", "")
        if msg_type in ("imageMessage", "videoMessage", "documentMessage"):
            self._on_menu_copy_file(msg)
        else:
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

    # ── Alt+Shift+L / Alt+Shift+K: announce message status / date-time ────

    def _on_accel_msg_status(self, event):
        """Alt+Shift+L: speak the focused message's current status."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        i18n   = self.main_window.i18n
        status = self._map_status(msg)
        self.main_window.output(status or i18n.t("msg_status_none"), interrupt=True)

    def _on_accel_msg_datetime(self, event):
        """Alt+Shift+K: speak the focused message's date/time, as shown in the list."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        ts       = self._extract_timestamp(msg)
        date_str = self._format_date(ts) if ts else ""
        i18n     = self.main_window.i18n
        self.main_window.output(
            date_str or i18n.t("msg_datetime_none"), interrupt=True
        )

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

    # ── Alt+Shift+C: copy phone number + speak ──────────────────────────────

    def _copy_and_speak_jid(self, jid: str):
        """Internal: copy formatted phone number for jid to clipboard and speak it."""
        if not jid or jid.endswith("@g.us"):
            return
        number = format_number(jid)
        if not number:
            return
        try:
            pyperclip.copy(number)
        except Exception:
            pass
        self.main_window.speak_output.output(number)

    def _on_accel_copy_number_speak(self, event):
        """Alt+Shift+C (conversation panel): copy current conversation's phone number."""
        if self.conversation is None:
            return
        self._copy_and_speak_jid(self.conversation.get("remoteJid", ""))

    def _on_accel_copy_number_list(self, event):
        """Alt+Shift+C (chat list): copy selected conversation's phone number."""
        idx = self.conversations_list.GetFirstSelected()
        if idx < 0 or idx >= len(self.chats_list):
            # Fall back to the currently open conversation if nothing selected
            if self.conversation:
                self._copy_and_speak_jid(self.conversation.get("remoteJid", ""))
            return
        self._copy_and_speak_jid(self.chats_list[idx].get("remoteJid", ""))

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

    # ── Alt+Shift+Q: goto quoted message ────────────────────────────────────────

    def _on_accel_goto_quoted(self, event):
        """Alt+Shift+Q: navigate to the quoted message of the focused message."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg):
            return
        ctx = self._get_context_info(msg)
        if ctx:
            self._on_menu_goto_quoted(msg, ctx)

    # ── Alt+Shift+S: mute / unmute conversation ──────────────────────────────

    def _on_accel_mute(self, event):
        """Alt+Shift+S: mute for 8 hours if not muted, otherwise unmute."""
        if self.conversation is None:
            return
        jid = self.conversation.get("remoteJid", "")
        if not jid:
            return
        mw = self.main_window
        if mw.is_chat_muted(jid):
            self._on_menu_unmute(jid)
        else:
            self._on_menu_mute(jid, 28800)  # 8 hours default

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
        # mark_conversation_as_read is triggered by _on_message_focused which
        # fires when Focus() is called above — no need to call it here again.

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
        """Open a read-only dialog showing the full message text."""
        msg_type = msg.get("messageType", "")
        msg_obj  = msg.get("message") or {}
        text = ""
        if msg_type == "conversation":
            text = msg_obj.get("conversation", "")
        elif msg_type == "extendedTextMessage":
            text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        if not text:
            return

        i18n = self.main_window.i18n

        def _word_wrap(raw: str, width: int = 100) -> str:
            """Wrap at word boundaries around *width* chars; never breaks mid-word."""
            out = []
            for para in raw.split("\n"):
                if not para:
                    out.append("")
                    continue
                line = ""
                for word in para.split(" "):
                    if not line:
                        line = word
                    elif len(line) + 1 + len(word) <= width:
                        line += " " + word
                    else:
                        out.append(line)
                        line = word
                if line:
                    out.append(line)
            return "\n".join(out)

        # Use wx.Frame with parent=None so the window is completely independent:
        # it appears in the taskbar, stays visible when Alt+Tab switches away from
        # WinZapp, and never blocks the main window's input focus.
        dlg = wx.Frame(
            None,
            title=i18n.t("msg_text_title"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_NO_TASKBAR,
            size=(480, 320),
        )
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        text_ctrl = wx.TextCtrl(
            panel, value=_word_wrap(text),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        close_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.Destroy())
        dlg.Bind(wx.EVT_CLOSE, lambda e: dlg.Destroy())
        dlg.Bind(
            wx.EVT_CHAR_HOOK,
            lambda e: dlg.Destroy() if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip(),
        )
        text_ctrl.SetFocus()
        dlg.CentreOnScreen()
        dlg.Show()

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
        """Background: send reaction via WPPConnect API."""
        jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        ok = self.main_window.send_reaction(jid, msg_key, emoji)
        if ok:
            # Apply optimistically — the WebSocket echo for own reactions is
            # suppressed in on_messages_upsert to avoid double-counting.
            wx.CallAfter(self._on_own_reaction_sent, jid, msg_key, emoji)

    def _on_own_reaction_sent(self, jid: str, msg_key: dict, emoji: str):
        """Update reaction_map, re-render the original message, and refresh the list."""
        orig_id = msg_key.get("id", "")
        if not orig_id:
            return

        # Update in-memory reaction map
        if orig_id not in self._reaction_map:
            self._reaction_map[orig_id] = {}
        if emoji:
            self._reaction_map[orig_id][emoji] = (
                self._reaction_map[orig_id].get(emoji, 0) + 1
            )

        # Re-render the original message row if currently visible
        for i, m in enumerate(self._sorted_messages):
            if not self._is_separator(m) and m.get("key", {}).get("id") == orig_id:
                self.messages_list.SetItemText(i, self._render_message_line(m))
                break

        # Persist reaction in chat records so _last_msg_preview and populate_messages
        # can reflect it after a conversation close/reopen.
        chat = self.main_window.get_chat(jid)
        if chat:
            reaction_record = {
                "messageType": "reactionMessage",
                "message": {
                    "reactionMessage": {
                        "key":  msg_key,
                        "text": emoji,
                    }
                },
                "key": {
                    "remoteJid": jid,
                    "fromMe":    True,
                    "id":        f"_rxn_{orig_id}",
                },
                "messageTimestamp": int(time.time()),
            }
            records = (
                chat.setdefault("messages", {})
                    .setdefault("messages", {})
                    .setdefault("records", [])
            )
            # Avoid duplicates for the same message+emoji pair
            rxn_key = f"_rxn_{orig_id}"
            if not any(r.get("key", {}).get("id") == rxn_key for r in records):
                records.append(reaction_record)
                try:
                    self.main_window.db.insert_message(jid, reaction_record)
                except Exception:
                    logging.exception("[conversations] insert reaction failed")

        self.main_window._schedule_set_chats()

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
            contact.get("pushName")
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
        if self._quoted_message:
            _qk = self._quoted_message.get("key", {})
            virtual_msg["contextInfo"] = {
                "stanzaId":      _qk.get("id", ""),
                "participant":   _qk.get("participant", ""),
                "quotedMessage": self._quoted_message.get("message") or {},
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

        # WPPConnect limits: media (image/video/audio) = 70 MB, documents = 1 GB.
        _MAX_MEDIA_BYTES    = 70  * 1024 * 1024
        _MAX_DOC_BYTES      = 1   * 1024 * 1024 * 1024
        i18n = self.main_window.i18n
        for attachment in list(self._staged_attachments):
            path       = attachment["path"]
            media_type = attachment.get("media_type", "document")

            is_doc    = media_type == "document"
            max_bytes = _MAX_DOC_BYTES if is_doc else _MAX_MEDIA_BYTES
            max_mb    = 1024 if is_doc else 70

            try:
                if os.path.getsize(path) > max_bytes:
                    wx.MessageBox(
                        i18n.t("media_too_large").format(max_mb=max_mb),
                        i18n.t("app_name"),
                        wx.OK | wx.ICON_ERROR,
                        self,
                    )
                    continue
            except OSError:
                pass

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
            if quoted:
                _qk = quoted.get("key", {})
                virtual_msg["contextInfo"] = {
                    "stanzaId":      _qk.get("id", ""),
                    "participant":   _qk.get("participant", ""),
                    "quotedMessage": quoted.get("message") or {},
                }
            self._sorted_messages.append(virtual_msg)
            self.conversation.setdefault("messages", {}).setdefault("messages", {}).setdefault("records", []).append(virtual_msg)
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
        self.main_window._schedule_set_chats()

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
        chat = self.main_window.get_chat(self._contact_msg_jid)
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
        
        conv_jid = self.conversation.get("remoteJid", "")
        jids_match = (conv_jid == remote_jid)
        if not jids_match:
            mapped_lid = getattr(self.main_window, "_phone_to_lid", {}).get(conv_jid, "")
            mapped_phone = getattr(self.main_window, "_lid_to_phone", {}).get(conv_jid, "")
            if (mapped_lid and mapped_lid == remote_jid) or (mapped_phone and mapped_phone == remote_jid):
                jids_match = True

        if not jids_match:
            return

        # Get the top visible item before inserting the message
        top_msg_id = None
        top_idx = -1
        if getattr(self.main_window, "_allow_ui_focus_changes", lambda: False)():
            if hasattr(self.messages_list, "GetTopItem"):
                top_idx = self.messages_list.GetTopItem()
            else:
                try:
                    import ctypes
                    hwnd = self.messages_list.GetHandle()
                    top_idx = ctypes.windll.user32.SendMessageW(hwnd, 0x018E, 0, 0)
                except Exception:
                    pass
            if top_idx != -1 and 0 <= top_idx < len(self._sorted_messages):
                m = self._sorted_messages[top_idx]
                if not self._is_separator(m):
                    top_msg_id = m.get("key", {}).get("id", "")
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

        # Batch all list operations so the screen reader receives a single
        # accessibility event rather than one per insertion/update.
        self.messages_list.Freeze()
        try:
            # Manage unread separator
            if self._unread_sep_idx == -1:
                # No separator yet — insert one before this new message
                sep_pos = len(self._sorted_messages)
                sep = {"_type": "unread_separator", "count": 1}
                self._sorted_messages.insert(sep_pos, sep)
                self.messages_list.InsertItem(sep_pos, self._render_separator(1))
                self._unread_sep_idx = sep_pos
                self._sep_from_open = False
            elif self._sep_from_open:
                # Separator was placed when the conversation was opened (old
                # unread messages). Move it just before this new message and
                # reset the count to 1.
                old_idx = self._unread_sep_idx
                self._sorted_messages.pop(old_idx)
                self.messages_list.DeleteItem(old_idx)
                sep_pos = len(self._sorted_messages)
                sep = {"_type": "unread_separator", "count": 1}
                self._sorted_messages.insert(sep_pos, sep)
                self.messages_list.InsertItem(sep_pos, self._render_separator(1))
                self._unread_sep_idx = sep_pos
                self._sep_from_open = False
            else:
                # Separator was placed by a previous live message — increment count
                sep = self._sorted_messages[self._unread_sep_idx]
                sep["count"] = sep.get("count", 0) + 1
                self.messages_list.SetItemText(
                    self._unread_sep_idx, self._render_separator(sep["count"])
                )

            # Append the real message (focus must NOT move)
            self._sorted_messages.append(msg)
            self.messages_list.Append((self._render_message_line(msg),))
        finally:
            self.messages_list.Thaw()

        # Only scroll while WinZapp is already active; incoming notifications
        # must never move focus or alter the user's current foreground context.
        if getattr(self.main_window, "_allow_ui_focus_changes", lambda: False)():
            scrolled = False
            if top_msg_id:
                is_near_bottom = False
                last_idx_before = len(self._sorted_messages) - 2
                if last_idx_before - top_idx < 15:
                    is_near_bottom = True
                
                if not is_near_bottom:
                    for idx, msg in enumerate(self._sorted_messages):
                        if isinstance(msg, dict) and msg.get("key", {}).get("id") == top_msg_id:
                            self.messages_list.EnsureVisible(idx)
                            scrolled = True
                            break
            
            if not scrolled:
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

    def populate_messages(self, preserve_focus: bool = False):
        """Rebuild the messages list from self.conversation.

        preserve_focus=True keeps whatever message is currently focused
        instead of resetting to the unread separator / last message — used
        by background refreshes (e.g. the on-demand sync kicked off by
        navigate_to_conversation) so they don't silently yank focus away
        from the user a few seconds after a conversation was opened.
        """
        _preserved_msg_id = self._focused_msg_id() if preserve_focus else None
        _had_focus = (wx.Window.FindFocus() is self.messages_list)

        top_msg_id = None
        if preserve_focus:
            top_idx = -1
            if hasattr(self.messages_list, "GetTopItem"):
                top_idx = self.messages_list.GetTopItem()
            else:
                try:
                    import ctypes
                    hwnd = self.messages_list.GetHandle()
                    top_idx = ctypes.windll.user32.SendMessageW(hwnd, 0x018E, 0, 0)
                except Exception:
                    pass
            if top_idx != -1 and 0 <= top_idx < len(self._sorted_messages):
                m = self._sorted_messages[top_idx]
                if not self._is_separator(m):
                    top_msg_id = m.get("key", {}).get("id", "")

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

        # Deduplicate by key.id — records may accumulate duplicates when the
        # same message arrives via both the initial sync and messages.upsert.
        # Keep the last occurrence (latest version of the message wins).
        _seen_ids: dict = {}
        for i, m in enumerate(messages_sorted):
            if not isinstance(m, dict):
                continue
            mid = m.get("key", {}).get("id", "")
            if mid:
                _seen_ids[mid] = i
        _kept = set(_seen_ids.values())
        messages_sorted = [
            m for i, m in enumerate(messages_sorted)
            if isinstance(m, dict) and (
                not m.get("key", {}).get("id", "") or i in _kept
            )
        ]

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
            m for m in messages_sorted if self._is_displayable_message(m)
        ]

        # Insert unread separator before the first unread message.
        # Use the snapshot taken before mark_conversation_as_read() zeros the dict.
        unread_count = self._pending_open_unread
        self._pending_open_unread = 0
        if unread_count > 0 and len(displayable) >= unread_count:
            first_unread_idx = len(displayable) - unread_count
            first_unread_msg = displayable[first_unread_idx]
            if isinstance(first_unread_msg, dict):
                self._first_unread_msg_id = first_unread_msg.get("key", {}).get("id")
                self._first_unread_count = unread_count

        if getattr(self, "_first_unread_msg_id", None):
            sep_pos = -1
            for idx, msg in enumerate(displayable):
                if isinstance(msg, dict) and msg.get("key", {}).get("id") == self._first_unread_msg_id:
                    sep_pos = idx
                    break
            if sep_pos >= 0:
                sep = {"_type": "unread_separator", "count": getattr(self, "_first_unread_count", 1)}
                displayable = displayable[:sep_pos] + [sep] + displayable[sep_pos:]
                self._unread_sep_idx = sep_pos
                self._sep_from_open = True

        # ── Pagination: show only last N messages ────────────────────────────
        self._all_sorted_messages = displayable
        limit = int(
            self.main_window.settings.get("user_interface", {}).get("messages_page_size", 200)
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

        # Restore scroll position if preserve_focus is True and we tracked a top visible message
        scrolled = False
        if preserve_focus and top_msg_id:
            for idx, msg in enumerate(self._sorted_messages):
                if isinstance(msg, dict) and msg.get("key", {}).get("id") == top_msg_id:
                    self.messages_list.EnsureVisible(idx)
                    scrolled = True
                    break

        # A background refresh (preserve_focus=True) should keep the user's
        # current position instead of jumping back to the separator/last
        # message — only fall back to the default placement below if the
        # previously-focused message is no longer present (e.g. it was
        # cleared or paginated out).
        if _preserved_msg_id:
            for idx, msg in enumerate(self._sorted_messages):
                if isinstance(msg, dict) and msg.get("key", {}).get("id") == _preserved_msg_id:
                    if _had_focus:
                        self.messages_list.SetFocus()
                    self.messages_list.Focus(idx)
                    self.messages_list.Select(idx)
                    if not scrolled:
                        self.messages_list.EnsureVisible(idx)
                    return

        # Make the unread separator visible, or select and focus the last (newest) message by default
        if not scrolled:
            if self._unread_sep_idx >= 0:
                last = self.messages_list.GetItemCount() - 1
                target_visible = min(self._unread_sep_idx + 3, last)
                if target_visible >= 0:
                    self.messages_list.EnsureVisible(target_visible)
                self.messages_list.EnsureVisible(self._unread_sep_idx)
                self.messages_list.Focus(self._unread_sep_idx)
                self.messages_list.Select(self._unread_sep_idx)
            else:
                last = self.messages_list.GetItemCount() - 1
                if last >= 0:
                    self.messages_list.EnsureVisible(last)
                    self.messages_list.Focus(last)
                    self.messages_list.Select(last)


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

        # ── Conversation filter tabs ─────────────────────────────────────────
        # Tracks the active filter key: 'all' | 'unread' | 'groups' | 'individual'
        self._conv_filter = 'all'
        self._filter_radio = wx.RadioBox(
            self,
            label=i18n.t("conv_filter_label"),
            choices=[
                i18n.t("conv_filter_all"),
                i18n.t("conv_filter_unread"),
                i18n.t("conv_filter_groups"),
                i18n.t("conv_filter_individual"),
            ],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self._filter_radio.Bind(wx.EVT_RADIOBOX, self._on_filter_changed)
        sizer.Add(self._filter_radio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

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

    def _on_filter_changed(self, event):
        """Update the active conversation filter and rebuild the list."""
        _filter_map = ['all', 'unread', 'groups', 'individual']
        sel = self._filter_radio.GetSelection()
        self._conv_filter = _filter_map[sel] if 0 <= sel < len(_filter_map) else 'all'
        self.main_window.add_chats_to_ui()

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

        if hasattr(self, "_filter_radio"):
            self._filter_radio.SetLabel(i18n.t("conv_filter_label"))
            for _fi, _fk in enumerate([
                "conv_filter_all", "conv_filter_unread",
                "conv_filter_groups", "conv_filter_individual",
            ]):
                self._filter_radio.SetItemLabel(_fi, i18n.t(_fk))
