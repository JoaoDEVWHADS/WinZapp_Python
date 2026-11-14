SRC = "client/main.py"
CLASS = "MainWindow"
PKG = "main_window"
PKG_DIR = "client/main_window"
IMPORT_PREFIX = "main_window."

REEXPORT_COMMENT = (
    "# MainWindow is assembled from the mixins in main_window/ (one module per\n"
    "# responsibility — see main_window/__init__.py for the map). The helper\n"
    "# functions are re-exported here because tests and older call sites reach\n"
    "# them as main.<name>; new code should import them from their module."
)

ANCHORS = [
    ("__init__", "KEEP"),
    ("_format_title", "window_chrome"),
    ("_on_power_suspended", "connection"),
    ("_on_menu_toggle_offline", "sync"),
    ("_on_force_update", "updates"),
    ("_on_window_activate", "window_lifecycle"),
    ("navigate_to_conversation_jid", "chat_list"),
    ("_cancel_incoming_call_watchdog", "calls"),
    ("_normalize_jid", "identity"),
    ("_apply_remote_revoke", "message_events"),
    ("connect_websocket", "connection"),
    ("find_headless_shell", "wpp_server"),
    ("meta_ai_terms_state", "sending"),
    ("_shutdown_audit", "session_lifecycle"),
    ("_stop_wpp_server", "wpp_server"),
    ("create_accelerator_table", "shortcuts"),
    ("_ensure_language_selected", "settings"),
    ("_token_key", "session_tokens"),
    ("_load_chat_lock_vault", "chat_lock"),
    ("prepare_sync", "sync"),
    ("start_connection_health_checker", "account_link"),
    ("_probe_whatsapp_host", "connection"),
    ("_live_snapshot_cancelled", "session_lifecycle"),
    ("_note_live_wpp_event", "connection"),
    ("_try_start_sync_thread", "sync"),
    ("_store_status_update", "chats_store"),
    ("_is_group_send_restricted", "groups"),
    ("save_data", "chats_store"),
    ("_load_local_lid_cache", "contacts"),
    ("_compute_chat_lists", "chat_list"),
    ("_build_lid_to_phone_cache", "identity"),
    ("_capture_chat_sync_baseline", "sync"),
    ("_initial_backfill_delay", "backfill"),
    ("_normalize_fetched_messages", "conversation_sync"),
    ("_media_max_download_days", "media"),
    ("_check_wa_connection_closed", "sending"),
    ("on_message_status_update", "chat_events"),
    ("_resolve_jid_name", "identity"),
    ("_presence_label_for_chat", "chat_events"),
    ("handle_audio_message", "media"),
    ("_oldest_stored_message", "history"),
    ("save_audio_locally", "media"),
    ("_persist_locally_read_at", "read_state"),
    ("resolve_self_lid", "identity"),
    ("get_group_info", "groups"),
    ("_bare_phone_digits", "chat_actions"),
    ("leave_group", "groups"),
    ("send_media_attachment", "sending"),
    ("edit_message", "message_actions"),
    ("_preview_sender_from_jid", "chat_list"),
    ("generate_secret_key", "KEEP"),
]

_win32 = ["_is_elevated", "_Win32Proc", "_HotkeyManager", "_vk_mod_to_str",
          "_get_short_path_name", "_spawn_delevated", "BOOKMARK_ZERO_HOTKEY_ID"]
_runtime = ["LEGACY_API_STATE_MARKER", "LEGACY_API_STATE_DIRS", "shorten_windows_path",
            "migrate_legacy_api_state", "NPM_HEALTH_MARKER_NAME", "npm_health_recorded",
            "record_npm_health", "pick_restore_generation", "node_runtime_needs_download",
            "_looks_like_json_response"]
_logs = ["_LazyLogFile", "_consolidate_legacy_log_dir"]
_rules = ["MediaExpiredError", "_MAX_RESIDENT_MESSAGES_PER_CHAT", "_PREVIEW_ONLY_MESSAGE_TYPES",
          "_MEDIA_ASSUMED_BYTES_PER_SECOND", "_MEDIA_FETCH_TIMEOUT_CEILING", "media_fetch_timeout",
          "is_countable_message", "_discount_non_countable_unread", "_media_not_in_store_lock",
          "_media_not_in_store", "_MEDIA_MISSING_LOG_EVERY", "_MAX_EMPTY_DELTA_RETRIES",
          "_MAX_ABSENT_CHAT_RETRIES", "_report_media_fetch_failure", "media_not_in_store_count",
          "reset_media_not_in_store_count", "describe_history_sync_health", "_UNREAD_UNDISCOUNTED",
          "note_unread_discount_state", "records_cover_snapshot",
          "apply_history_sync_unread_correction", "_message_ts", "own_message_marks_chat_read",
          "unread_after_history_sync", "reconcile_open_chat_unread", "_log_refused_read_receipt",
          "_unread_seconds", "reconcile_snapshot_unread", "history_gap_detected", "history_gap_closed"]
_ident = ["_MIN_COMPARABLE_PHONE_DIGITS", "linked_phone_digits", "linked_number_differs",
          "record_linked_phone_if_unknown", "participant_digits", "group_participant_is_me",
          "set_group_participant_admin", "group_participant_admin_flag",
          "group_send_permission_from_metadata", "unexpired_group_send_verdict"]
MODULE_DEFS = {}
for names, mod in ((_win32, "win32_helpers"), (_runtime, "runtime_setup"), (_logs, "log_files"),
                   (_rules, "message_rules"), (_ident, "identity_rules")):
    for n in names:
        MODULE_DEFS[n] = mod

HELPER_DOCS = {
    "win32_helpers": "Win32 process, elevation and global-hotkey helpers used by MainWindow.\n\nMoved verbatim out of main.py; main.py re-exports every name.\n",
    "runtime_setup": "Pure helpers for the local API/Node runtime setup (legacy state\nmigration, npm health marker, profile restore choice).\n\nMoved verbatim out of main.py; main.py re-exports every name.\n",
    "log_files": "Log-file plumbing that has to exist before MainWindow does.\n\nMoved verbatim out of main.py; main.py re-exports every name.\n",
    "message_rules": "Pure message/unread/history rules shared by the sync and event mixins.\n\nEverything here takes plain dicts and lists and is tested directly — the\nshape to copy when logic is pulled off MainWindow. Moved verbatim out of\nmain.py; main.py re-exports every name.\n",
    "identity_rules": "Pure phone-number and group-participant identity rules.\n\nMoved verbatim out of main.py; main.py re-exports every name.\n",
}

MIXIN_NAMES = {
    "window_chrome": "WindowChromeMixin",
    "connection": "ConnectionMixin",
    "sync": "SyncMixin",
    "updates": "UpdatesMixin",
    "window_lifecycle": "WindowLifecycleMixin",
    "chat_list": "ChatListMixin",
    "calls": "CallsMixin",
    "identity": "IdentityMixin",
    "message_events": "MessageEventsMixin",
    "wpp_server": "WppServerMixin",
    "sending": "SendingMixin",
    "session_lifecycle": "SessionLifecycleMixin",
    "shortcuts": "ShortcutsMixin",
    "settings": "SettingsMixin",
    "session_tokens": "SessionTokensMixin",
    "chat_lock": "ChatLockMixin",
    "account_link": "AccountLinkMixin",
    "chats_store": "ChatsStoreMixin",
    "groups": "GroupsMixin",
    "contacts": "ContactsMixin",
    "backfill": "BackfillMixin",
    "conversation_sync": "ConversationSyncMixin",
    "media": "MediaMixin",
    "chat_events": "ChatEventsMixin",
    "history": "HistoryMixin",
    "read_state": "ReadStateMixin",
    "chat_actions": "ChatActionsMixin",
    "message_actions": "MessageActionsMixin",
}
MIXIN_ORDER = list(MIXIN_NAMES)

MIXIN_DOCS = {
    "window_chrome": "Menu bar, window title, accounts menu, IPC between account processes, bookmark/global hotkeys and the offline toggle.",
    "connection": "WhatsApp connection state: suspend/resume, zombie-session restarts, _set_wa_connected, the WebSocket client, reachability probes and check_wa_connection_http.",
    "sync": "Full account sync: prepare_sync, _run_sync, start/trigger gates, the resync menu actions and the per-chat sync planning (see docs/traps/sync-completion.md).",
    "updates": "App and WPPConnect Server update checks triggered from the menu or the background checkers.",
    "window_lifecycle": "Window activation, presence heartbeat, tray, close/hide/restore, focus and the shutdown path.",
    "chat_list": "The chat list: navigation to a JID, computing and applying the chat lists, scheduled refreshes, last-message previews, archived list and row rendering.",
    "calls": "Voice and video calls: incoming-call alerts, call audio/camera, the call bar, call control requests and the call-log watcher.",
    "identity": "JID identity: normalization, @lid <-> phone bridging, LID mapping caches, contact-name resolution and remote profile lookups.",
    "message_events": "Live and historical message ingestion (on_new_message / on_historical_message), revokes, edits, undecrypted placeholders and reaction notifications.",
    "wpp_server": "The local WPPConnect Server process: browser payload, npm modules, version pin, ports, background start, stop and ensure_wpp_running.",
    "sending": "Sending messages: text, audio, media, contacts, reactions, pins; send capability checks, Meta AI terms and the message-queue callbacks.",
    "session_lifecycle": "Session teardown and profile health: shutdown audit, Windows end-session handling, unattended QR guard, profile recovery and live snapshots (see docs/traps/profile-recovery.md).",
    "shortcuts": "Accelerator table, Alt+N navigation, settings/language entry points and the output() speech funnel.",
    "settings": "First-run checks, settings load/save/migrate, settings export/import, live settings application and sounds.",
    "session_tokens": "WA_token vault access, the session store and cleanup of abandoned sessions.",
    "chat_lock": "The locked-chats vault: PIN, reveal code, timeout and the locked conversations panel.",
    "account_link": "Periodic connection health check and the 'another number was linked' detection and local-data wipe.",
    "chats_store": "Local chat storage: clearing local data, chat getters, remote chat fetch, deduplication, status updates and saving.",
    "groups": "Group metadata: names, send permissions, admin/settings/subject changes and group management actions.",
    "contacts": "Local and remote contacts, self-reference detection and chat list computation inputs.",
    "backfill": "Background history backfill of empty or incomplete chats, history-sync status and deferred media sync.",
    "conversation_sync": "Per-conversation message sync (sync_chat_messages), remote message windows and remote deletion/rollback reconciliation.",
    "media": "Media download: size/age limits, failed-id bookkeeping, sync_if_media, base64 fetch, video duration probing and local audio saving.",
    "chat_events": "Chat-level server events: message status (acks), presence, unread counters, archive and pin updates.",
    "history": "On-demand older history: deep backfill, fetch_older_messages and the exhaustion bookkeeping.",
    "read_state": "Read/unread state: marking conversations read or unread and keeping the local-read anchor.",
    "chat_actions": "Chat actions: block, mute, archive, delete, clear, typing/recording status and pin.",
    "message_actions": "Message actions: edit, delete for everyone/me, forward, resend with caption and mark-played.",
}

MIXIN_FILE_DOCS = {m: f"{MIXIN_NAMES[m]} — part of MainWindow (see main_window/__init__.py).\n\nMoved verbatim out of main.py. Methods run with ``self`` bound to the\nMainWindow instance, so every attribute set in MainWindow.__init__ is\navailable here.\n" for m in MIXIN_NAMES}

FILE_FIX = {}

for n in ("_http_session", "_orig_get", "_orig_post", "_patched_get", "_patched_post"):
    MODULE_DEFS[n] = "http_pool"
HELPER_DOCS["http_pool"] = "Process-wide pooled HTTP session (Keep-Alive) behind requests.get/post.\n\nmain.py installs _patched_get/_patched_post over requests.get/post at\nimport time; the objects live here so the mixins can reach the session.\n"


def _sending_post(text):
    # _find_api_ffmpeg() resolved its search paths from main.py's own
    # location; keep them anchored there rather than at this package.
    assert text.count("__file__") == 5
    text = text.replace("__file__", "_MAIN_PY")
    marker = "\n\n\nclass SendingMixin:"
    return text.replace(marker, "\n\n# The directory layout _find_api_ffmpeg() searches is relative to main.py.\n"
                        "_MAIN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), \"main.py\")\n"
                        + marker, 1)


POST = {"sending": _sending_post}


def _lazy_mixin(attr, mixin, module):
    def fix(text):
        old = f"MainWindow.{attr}("
        # The code occurrence is the last one (earlier ones sit in docstrings).
        idx = text.rindex(old)
        line_start = text.rindex("\n", 0, idx) + 1
        line = text[line_start:text.index("\n", idx)]
        indent = line[:len(line) - len(line.lstrip())]
        new_line = line.replace(old, f"{mixin}.{attr}(")
        # Imported at call time: the mixin module imports this helper module,
        # so a top-level import here would be circular.
        return (text[:line_start] + f"{indent}from main_window.{module} import {mixin}\n"
                + new_line + text[line_start + len(line):])
    return fix


POST["identity_rules"] = _lazy_mixin("_phone_digits_equivalent", "ContactsMixin", "contacts")
POST["message_rules"] = _lazy_mixin("_counts_as_last_message", "ChatListMixin", "chat_list")
_prev_rs = POST.get("read_state")


def _read_state_post(text):
    # _send_seen()'s return annotation names requests.Response.
    return text.replace("\n\n\nclass ReadStateMixin:", "\nimport requests\n\n\nclass ReadStateMixin:", 1) if "\nimport requests\n" not in text else text


POST["read_state"] = _read_state_post
