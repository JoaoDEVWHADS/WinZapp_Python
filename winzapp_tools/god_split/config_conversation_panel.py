SRC = "client/ui/conversations.py"
CLASS = "ConversationsPanel"
PKG = "ui.conversation_panel"
PKG_DIR = "client/ui/conversation_panel"
IMPORT_PREFIX = "ui.conversation_panel."

REEXPORT_COMMENT = (
    "# ConversationsPanel is assembled from the mixins in ui/conversation_panel/\n"
    "# (one module per responsibility — see ui/conversation_panel/__init__.py for\n"
    "# the map). The helpers and ArchivedConversationsPanel are re-exported here\n"
    "# because tests and callers reach them as ui.conversations.<name>; new code\n"
    "# should import them from their module."
)

ANCHORS = [
    ("__init__", "KEEP"),
    ("create_accelerator_table", "accelerators"),
    ("_on_conversation_focused", "conversation_navigation"),
    ("_spell_check_enabled", "composer"),
    ("refresh_labels", "KEEP"),
    ("_default_recording_stereo", "voice_recording"),
    ("_sync_voice_call_button", "composer"),
    ("on_send_message", "text_sending"),
    ("refresh_message_status", "list_refresh"),
    ("_voice_recording_silence_enabled", "voice_recording"),
    ("_close_conversation_core", "conversation_navigation"),
    ("on_conversations_context_menu", "chat_menu"),
    ("_no_conversation_open_announced", "message_list"),
    ("on_messages_context_menu", "message_menu"),
    ("_on_ctrl_shift_s", "media_files"),
    ("_extract_links", "links"),
    ("_raw_mentioned_jids", "mentions"),
    ("_on_message_field_key_down", "composer"),
    ("_focused_msg_id", "message_list"),
    ("_should_dismiss_unread_separator", "unread_separator"),
    ("_deduplicate_messages", "history_loading"),
    ("_page_jump_size", "message_list"),
    ("_select_chat_at", "chat_selection"),
    ("_try_show_thumbnail", "message_list"),
    ("_open_file_safely", "media_files"),
    ("toggle_current_audio_playback", "audio_playback"),
    ("_extract_timestamp", "formatting"),
    ("_message_mentioned_jids", "message_rendering"),
    ("_clear_empty_placeholder", "unread_separator"),
    ("_get_quoted_preview", "message_rendering"),
    ("update_message_download_progress", "media_files"),
    ("_on_ctrl_shift_d", "conversation_info"),
    ("_on_menu_mark_read", "chat_menu"),
    ("_on_menu_message_data", "message_menu"),
    ("_get_participant_name", "message_rendering"),
    ("refresh_active_conversation_messages", "list_refresh"),
    ("_on_menu_reply_private", "message_menu"),
    ("_forward_target_chats", "forwarding"),
    ("_persist_message_local_flag", "message_actions"),
    ("_on_accel_message_data", "message_accels"),
    ("_selected_chat_from_list", "chat_selection"),
    ("_on_accel_copy_message", "message_accels"),
    ("_on_accel_jump_last", "message_list"),
    ("_select_bookmarked_message", "bookmarks"),
    ("_on_accel_open_search", "message_search"),
    ("_show_message_text_popup", "message_menu"),
    ("_on_menu_react", "reactions"),
    ("on_add_attachment", "attachments"),
    ("_location_maps_url", "contact_messages"),
    ("_matches_open_conversation", "list_refresh"),
    ("_on_mass_clear_chats", "chat_selection"),
    ("_on_mass_copy_messages", "bulk_messages"),
    ("_on_accel_recent_reactions", "message_accels"),
]

MODULE_DEFS = {
    "_URL_RE": "text_helpers",
    "_fmt_last_seen": "text_helpers",
    "message_caption": "text_helpers",
    "_SAVEABLE_MESSAGE_TYPES": "media_paths",
    "local_media_cache_paths": "media_paths",
    "media_cache_id": "media_paths",
    "cached_media_path": "media_paths",
    "saved_media_path": "media_paths",
    "reveal_file_in_folder": "media_paths",
    "promote_local_media_cache": "media_paths",
    "discard_local_media_cache": "media_paths",
    "probe_media_duration": "media_paths",
    "_FocusedTransferGaugeAccessible": "transfer_gauge",
    "_FocusedTransferGauge": "transfer_gauge",
    "toggle_jid_selection": "selection_rules",
    "visible_jid_selected": "selection_rules",
    "ArchivedConversationsPanel": "archived_panel",
}

HELPER_DOCS = {
    "text_helpers": "Small pure text helpers shared by ConversationsPanel's mixins.\n\nMoved verbatim out of ui/conversations.py, which re-exports every name.\n",
    "media_paths": "Where a message's media lives on disk: cache paths, saved paths,\nrevealing a file in Explorer and probing a media file's duration.\n\nMoved verbatim out of ui/conversations.py, which re-exports every name.\n",
    "transfer_gauge": "The media transfer gauge that keeps screen-reader focus while it moves.\n\nMoved verbatim out of ui/conversations.py, which re-exports every name.\n",
    "selection_rules": "Pure rules for the multi-selection of chats in the conversation list.\n\nMoved verbatim out of ui/conversations.py, which re-exports every name.\n",
    "archived_panel": "ArchivedConversationsPanel — the Alt+3 archived chats list.\n\nMoved verbatim out of ui/conversations.py, which re-exports it.\n",
}

MIXIN_NAMES = {
    "accelerators": "AcceleratorsMixin",
    "conversation_navigation": "ConversationNavigationMixin",
    "composer": "ComposerMixin",
    "voice_recording": "VoiceRecordingMixin",
    "text_sending": "TextSendingMixin",
    "list_refresh": "ListRefreshMixin",
    "chat_menu": "ChatMenuMixin",
    "message_list": "MessageListMixin",
    "message_menu": "MessageMenuMixin",
    "media_files": "MediaFilesMixin",
    "links": "LinksMixin",
    "mentions": "MentionsMixin",
    "unread_separator": "UnreadSeparatorMixin",
    "history_loading": "HistoryLoadingMixin",
    "chat_selection": "ChatSelectionMixin",
    "audio_playback": "AudioPlaybackMixin",
    "formatting": "FormattingMixin",
    "message_rendering": "MessageRenderingMixin",
    "conversation_info": "ConversationInfoMixin",
    "forwarding": "ForwardingMixin",
    "message_actions": "MessageActionsMixin",
    "message_accels": "MessageAccelsMixin",
    "bookmarks": "BookmarksMixin",
    "message_search": "MessageSearchMixin",
    "reactions": "ReactionsMixin",
    "attachments": "AttachmentsMixin",
    "contact_messages": "ContactMessagesMixin",
    "bulk_messages": "BulkMessagesMixin",
}
MIXIN_ORDER = list(MIXIN_NAMES)

MIXIN_DOCS = {
    "accelerators": "Keyboard accelerator tables for the conversations list and the open conversation.",
    "conversation_navigation": "Opening, focusing, closing and restoring a conversation; composer permissions and the chat-list search filter.",
    "composer": "The message composer: spell check, link preview, emoji picker, key/char/paste handling and the call buttons next to it.",
    "voice_recording": "Recording, previewing and sending voice messages.",
    "text_sending": "Sending and editing text messages: virtual pending rows, sent/failed/unconfirmed marks and cancelled sends.",
    "list_refresh": "Keeping the message list in sync with the data: status repaints, incoming messages, signature-based repaint and populate_messages.",
    "chat_menu": "The conversations-list context menu and its chat actions (read, mute, block, archive, pin, clear, delete, leave).",
    "message_list": "Moving around the message list: selection, activation, focus, paging, quick-reply buttons and jumps.",
    "message_menu": "The message context menu and its read-only actions: data, copy, reply, go to quoted, text popup.",
    "media_files": "Media on disk: opening, the media viewer, video, saving, downloading and transfer progress.",
    "links": "The links panel of the focused message.",
    "mentions": "@mentions: extracting them, the mentions panel and the composer's mention suggestions.",
    "unread_separator": "The unread-messages separator row: placing, moving and dismissing it.",
    "history_loading": "Loading older history into the open conversation, locally and from the server.",
    "chat_selection": "Multi-selection in the conversations list, its key handling and the bulk chat actions.",
    "audio_playback": "Playing voice/audio messages: play/pause, chaining, speed, seek and the audio controls.",
    "formatting": "Formatting timestamps, dates, durations and file sizes for display.",
    "message_rendering": "Turning a message record into its list row text: content, status, sender, quotes and participant names.",
    "conversation_info": "Conversation data dialog, profile fetch and the presence note.",
    "forwarding": "Forwarding messages to other chats.",
    "message_actions": "Message actions that change state: star, pin, delete, cancel, edit and resend.",
    "message_accels": "Accelerator handlers for the open conversation's messages.",
    "bookmarks": "Message bookmarks and temporary bookmarks.",
    "message_search": "Searching inside the open conversation (Ctrl+Shift+F).",
    "reactions": "Sending, applying, persisting and backfilling reactions.",
    "attachments": "Attaching files and contacts and sending attachments.",
    "contact_messages": "Contact (vCard) and location messages.",
    "bulk_messages": "Bulk actions on selected messages.",
}

MIXIN_FILE_DOCS = {m: f"{MIXIN_NAMES[m]} — part of ConversationsPanel (see ui/conversation_panel/__init__.py).\n\nMoved verbatim out of ui/conversations.py. Methods run with ``self`` bound to\nthe ConversationsPanel instance, so every attribute set in\nConversationsPanel.__init__/init_UI is available here.\n" for m in MIXIN_NAMES}

FILE_FIX = {}
POST = {}


def _archived_post(text):
    # MUTE_PRESETS is a class attribute that now lives on ChatMenuMixin; the
    # value ConversationsPanel.MUTE_PRESETS resolved to is the same object.
    assert text.count("ConversationsPanel.MUTE_PRESETS") == 2
    text = text.replace("ConversationsPanel.MUTE_PRESETS", "ChatMenuMixin.MUTE_PRESETS")
    doc_end = text.index('"""', 3) + 3
    cut = text.index("\n\n\n", doc_end)
    return text[:cut] + "\nfrom ui.conversation_panel.chat_menu import ChatMenuMixin" + text[cut:]


POST["archived_panel"] = _archived_post
