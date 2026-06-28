# Changelog (WinZapp Fork)

All notable changes to this fork of WinZapp are documented in this file.

# v0.16.0.0beta

## Delete, Clearing, Hotkey & Conversation Data
* **Delete for everyone still left the message for the group:** The revoke hardcoded a `true_` prefix and ignored the participant, so `WPP.chat.deleteMessage` either failed to find the message or fell back to a local-only delete (revoke only fires when the message resolves and is yours or you're a group admin). It now builds the correct serialized id (via the same serializer reactions use), checks the API result, and warns if the revoke truly failed.
* **Clearing a conversation now updates the list immediately:** The now-empty chat is removed from the conversations list right away (its stale last-message/unread are cleared too), and keyboard focus lands on the neighbouring conversation instead of being lost.
* **Global hotkey getting "stuck":** `restore_window` relied on a bare `SetForegroundWindow`, which silently fails under Windows' foreground-lock — the window stayed hidden and the hotkey seemed dead until a restart. Restore now uses the `AttachThreadInput` technique for a reliable bring-to-front, and the hotkey registers with `MOD_NOREPEAT`.
* **Conversation data dialog showed "success":** It displayed the API result word as the contact's About text. About now comes from the dedicated `profile-status` endpoint, and **last seen** is fetched directly from `last-seen` (with the live presence cache as the primary source) so it actually appears in both the dialog and the data-button note.
* **pt-PT:** "Biografia" → "Sobre".

## Reaction Notifications & More
* **No notification when someone reacts to your message:** The client never subscribed to the WPPConnect `onreactionmessage` event (and the API had it disabled), so reactions to your messages were silently dropped. Now subscribed and enabled (`config.json` `onReactionMessage: true`); reactions to *your* messages produce a notification like "Name (in Group): reacted with 👍 to: your message text". Only your own messages trigger it — never reactions to others' messages, nor your own reactions.
* **NVDA repeating the focused conversation name while idle:** Presence bursts (online/offline toggles that don't change the row) rewrote the focused chat-list row's text unconditionally, making NVDA re-announce the conversation name over and over. The row is now only updated when its visible text actually changes.
* **Audio/media bytes never bloat messages.dat:** Confirmed voice notes live only in `voice_messages/`; additionally, never-read media fields (urls, mediaKey, directPath, file hashes, waveform, `body`) are now stripped from every stored message — media is always re-fetched by message id. Combined with the quoted-message slimming this trims the real cache by ~24%.

## Bug Fixes
* **Reactions not sent:** `send_reaction` sent only the bare `key.id`, which `WPP.chat.getMessageById` cannot resolve. It now builds the full serialized id (`<fromMe>_<chatId>_<id>`, plus `_<participant>` for group/status messages), mirroring how deletes work.
* **Delete for everyone:** Normalized the `phone` field to `@c.us` (it previously stayed `@s.whatsapp.net`, so `WPP.chat.deleteMessage` could not resolve the chat and the revoke silently no-opped). Also fixed the `delete-message` controller, which sent a `200` and then fell through to a `401` (missing `return` → `ERR_HTTP_HEADERS_SENT`, masking real failures).
* **Document send fails with HTTP 500:** Transient `5xx` responses (notably WPPConnect's `ProtocolError: Promise was collected` on large uploads) and network/timeout errors are now retried by the message queue instead of being abandoned after a single attempt.
* **Clear conversation did nothing:** The `cleared_chats` cutoff timestamp was written but never read, so the next history sync repopulated the chat. Cleared messages are now filtered out on both history sync and live re-delivery.
* **Muted/pinned groups missing after pairing:** Switched chat collection from the deprecated `all-chats` (`WAPI.getAllChats`, which omits some chats) to the modern `list-chats` (`WPP.chat.list`), and now sync pin state from the server into `pinned_chats`.
* **Garbage IDs in chat list:** Base64 thumbnail/binary blobs (e.g. `+0 /9j/4AAQSkZJRg...`) leaking from business-account name fields are now rejected at ingestion and display via `looks_like_binary_blob`.
* **App freezing during sync / media download:** The bulk media pre-fetch fired a `wx.CallAfter` per 64 KB chunk per file across 6 workers (each an O(n) scan of the open conversation), flooding the UI thread. Bulk downloads no longer stream per-chunk progress, and the single completion refresh only fires for the conversation currently on screen.
* **Long messages truncated in the message list:** Added a custom `wx.Accessible` for the messages list so screen readers receive the full message text, bypassing the native Win32 ListView ~259-char limit (previously only Alt+C revealed the full text / trailing links).
* **Choppy voice recording:** Increased the PyAudio capture buffer (1024 → 4096 frames, ~85 ms) so the callback tolerates scheduling delays from background threads without PortAudio dropping samples; input-overflow status is now logged.
* **Unread separator:** Removed the guard that cancelled the separator-dismiss timer when focus moved back above the counter — the separator now always disappears after the unread region is reached.
* **Deleted messages:** Removed the 🚫 emoji prefix from deleted-message text inside conversations.

## Performance & Storage
* **Slow conversation open / messages.dat bloat:** WPPConnect stored the *entire* quoted message under `contextInfo.quotedMessage` (base64 thumbnail, mediaKey, directPath, deprecatedMms3Url, file hashes), none of which the UI reads — it dominated `messages.dat` and slowed every chat with replies. Quoted messages are now slimmed to a capped text preview + type marker at ingestion, with a one-time startup migration that prunes already-stored data (~23% smaller on a real cache).

## Additional Bug Fixes
* **@lid shown as a phone number:** When a name was unavailable, the chat list and conversation header fell back to `format_number(jid)` on a `@lid`, displaying the raw internal identifier as a wall of digits. A new `_format_jid_for_display` resolves `@lid → phone` when known and otherwise yields a generic placeholder — the raw `@lid` is never shown.
* **Image/video caption showing raw base64:** The websocket normalizer fell back to `wpp_msg["body"]` for the caption, but for media messages `body` holds the base64 JPEG thumbnail. Captions now come only from the real caption field, with a binary-blob guard.
* **"Sync contact to phone" did nothing:** Adding a contact only set a local `isSaved` flag and never called any API. Added an `add-new-contact` endpoint (`WPP.contact.save(..., {syncAddressBook})`) and wired the checkbox to it.

---

# V2026.06.26.0000

## Database Migration (JSON → SQLite)
* **DatabaseManager (core/database.py):** Replaced the monolithic encrypted `messages.dat` JSON blob with a transactional SQLite database (6 tables: chats, messages, contacts, lid_mappings, unresolvable_lids, status_updates). WAL mode for concurrent access. Payload columns encrypted with Fernet per-field. All CRUD operations are async via aiosqlite + AnyIO. 45 tests.
* **MigrationEngine (core/migration.py):** Seamless one-time migration from `messages.dat` → SQLite on startup. Reads and decrypts legacy data, populates SQLite, renames `messages.dat` → `messages.dat.bak`. Full rollback support (`rollback()` restores `.bak`). 16 tests.
* **DatabaseBridge (core/database_bridge.py):** Sync↔async bridge running an asyncio event loop in a background daemon thread. All DatabaseManager calls dispatched via `asyncio.run_coroutine_threadsafe()`. Provides `save_full_state()`, `clear_all()`, `run_migration()`, and all CRUD methods as sync wrappers for wxPython compatibility.
* **Incremental saves:** `save_data()` now uses upsert-only (`clear_first=False`) — the database is never truncated during normal saves. Full-clear is only used by `clear_local_data()` for account reset. Prevents the database from being wiped and re-synced on every startup.
* **62 tests covering database, migration, and bridge:** All passing.

## Bug Fixes (28 corrigidos)

### Conversation & Message Display
* **Group names showing participant name:** `_compute_chat_lists()` no longer uses `pushName` for groups (WPPConnect returns last sender's name in pushName for groups). `on_new_message()` skips pushName for new group chats. `get_remote_chats()` doesn't overwrite pushName for existing groups.
* **Group names showing raw numbers (88605561233607):** `navigate_to_conversation()` now has a separate name resolution chain for groups (ignores pushName, uses `unknown_group` as fallback). `_format_jid_for_display()` returns empty string for `@g.us` JIDs. `get_remote_chats()` checks `subject` field when `name` is empty. New `_fill_group_name()` lazily fetches group names via API.
* **"Contato sem nome" persisting:** `get_remote_contacts()` no longer stores placeholder "Contato sem nome" — uses empty string instead. New `_clean_contacts_cached()` + `_is_bad_contact_name()` sanitizes existing cache at startup. `_compute_chat_lists()` fallback displays formatted JID number instead of `unknown_contact` when no name or phone mapping exists.
* **Unsupported message types:** Added handlers for `interactiveMessage`, `buttonsResponseMessage`, `listResponseMessage` in `_get_message_content()` with i18n keys (`interactive_reply`, `list_reply`, `interactive_message`) in all 4 languages.
* **Document attachment duplicating in message list:** `_on_send_attachment()` now appends `virtual_msg` to conversation `records` (not just `_sorted_messages`). Fixed `send_media_attachment()` return values to properly report ID extraction failures.
* **Star/favorites feature not working:** `_on_menu_star()` was a no-op (`pass`). Now toggles `msg["starred"]` flag, persists via `_schedule_save()`, shows "★" indicator in message list, and menu alternates between "Favoritar"/"Desfavoritar".
* **Read status not syncing to standard WhatsApp:** Fixed JID format — removed `_phone_to_lid` lookup that returned `@lid` (not accepted by `sendSeen` API). Now always converts `@s.whatsapp.net` → `@c.us`. Added early return for `@g.us` (groups don't support `sendSeen`).
* **Pin not syncing to standard WhatsApp:** `_sync_pin_to_server()` now converts JID from `@s.whatsapp.net` → `@c.us` before sending to pin-chat API.
* **Mute sync deleting local mutes:** `get_remote_chats()` now checks `"muteExpiration" in chat` instead of `chat.get("muteExpiration", 0)` — when the server omits the field, local mute is preserved.
* **UnreadCount resurrecting after being cleared:** `on_chat_unread_update()` now guards against server-stale counts overwriting local `unreadCount: 0`.
* **Channels showing as "Contato sem nome":** Fixed name resolution for `@lid` JIDs with no phone mapping — displays formatted raw digits instead of placeholder text.
* **Chats without new messages appearing at top:** `_chat_last_ts()` returns `1` (epoch+1) instead of `0` for chats with no timestamp, sorting them to the bottom of the list.

### Chat List & Sync
* **Old deleted conversations reappearing:** `deleted_chats` filter now checks both `@lid` and `@s.whatsapp.net` aliases. `cleared_chats` cutoff also filters re-sync. `delete_chat_local()` saves both JID formats.
* **Ghost contacts at top (days/weeks old):** `_chat_last_ts()` guard for zero timestamps — now returns `1` instead of `0`, preventing `-0 = 0` from sorting to top.
* **Contact from other country jumping to top:** Fallback name resolution now handles all JID formats correctly — shows phone number instead of unknown_contact.
* **sync_chat_messages identity bug:** Line 4202 condition `if api_ok or not records` wiped cached records when API returned `200 OK` with empty response. Now only replaces records when `api_ok AND all_messages has content`.
* **sync_chat_messages retry loop (14s freeze):** Added `_wa_connected` guard — skips API call entirely when disconnected. Reduced retries from 3 to 2, removed blocking `time.sleep()`.
* **save_data crash (dictionary changed size during iteration):** All mutable dicts (chats, contacts, lid_to_phone, status_updates) are now deep-copied via `dict()`/`list()` before passing to bridge.

### Media & Attachments
* **Attachments HTTP 400 ("não existe"):** `send_media_attachment()` now sends `phone` as array `[remote_jid]` (server iterates with `for...of`) and includes `isGroup` flag.
* **send_media for groups HTTP 400:** Strips `@g.us` suffix from remote JID (server expects bare group ID) and sets `isGroup=true`.
* **send_contact_attachment for groups:** Strips `@g.us` from remote JID + adds `isGroup` flag. Removed `_phone_to_lid` lookup that could return invalid `@lid` JIDs.

### WebSocket & Performance
* **WebSocket messages.update event not registered:** `websocket_client.py` now subscribes to `"messages.update"` events — the existing `on_messages_update()` handler was defined but never bound.
* **Performance freeze entering conversation:** `preselect_messages()` used to call `Focus(0)/Select(0)` on an empty `wx.ListCtrl` from the main thread. Now uses `wx.CallAfter()` + `GetItemCount() > 0` guard, deferring execution until `populate_messages()` fills the list.

### Database & Startup
* **DB clearing on every startup (resyncing):** `save_data()` used `clear_first=True` based on `_initial_sync_running` — which was only `True` inside `start_sync()`. Every save outside the sync window truncated the database. Fixed: always `clear_first=False` (incremental upsert). Only `clear_local_data()` (account reset) uses full clear.
* **Datas na lista pegando conversas antigas e jogando pra cima:** `_chat_last_ts()` retornava `0` para chats sem timestamp → `sort key -0 = 0` ordenava no topo. Fix: `return ts if ts else 1` (epoch+1 = mais antigo).

## Features
* **Node.js auto-download:** New `NodeDownloadDialog` (`ui/dialogs/node_download.py`) downloads Node.js v18.20.4-win-x64.zip from `nodejs.org` and extracts to `client/node/` with progress bar. Shown automatically when `node.exe` is missing, replacing the fatal error message.
* **Star/favorites on messages:** Context menu toggles star on any message. Starred messages show "★" indicator. State persisted across restarts.
* **PyInstaller --onefile build option:** `build.py --onefile` compiles a single-file `.exe` with all Python deps and external resources (node/, api/, lib/, sounds/, languages/, data/, .env) embedded. Resources extracted to temp directory at runtime via `sys._MEIPASS`.
* **Incremental database saves:** Normal `save_data()` calls now perform upsert-only writes. The database is only fully cleared during explicit account reset (`clear_local_data()`), preventing unnecessary re-syncs.

---

# V2026.06.21.1555

## Bug Fixes
* **Auto-Updater Path Warning:** Fixed the incorrect warning log statement indentation in `updater.py` so it only runs on unsupported platforms.
* **Process Tree Cleanup:** Modified `real_exit()` and `_stop_evolution()` to explicitly kill the entire WPPConnect Server Node.js/Chromium process tree on Windows using `taskkill /F /T`, preventing orphaned processes and releasing all file locks for auto-updater overwrites.
* **PTT Audio Playback (Opus):** Loaded the `bassopus` and `bass_aac` plugins during BASS startup in `sound_system.py` to support playing WhatsApp Opus-encoded voice notes (`.ogg`) and AAC attachments.
* **Message Status Filtering:** Fixed `_map_status()` to display status ticks (sent, delivered, read) only on messages sent by you (`fromMe`). Incoming received messages will no longer display these ticks (unless the audio was played).

---

# V2026.06.21.1450

## Upstream Synchronization & Merge
* **PyQt/wxPython Upstream Enhancements:** Merged Gabriel's PyQt/wx client UI enhancements, including the new playing voice note audio controls visualization in the conversations list.
* **WPPConnect Mentions Integration:** Integrated the new upstream `@mention` suggestion panel and `mentioned_jids` arguments in `send_text_message` with WPPConnect Server's `/api/:session/send-mentioned` routing (with robust fallback to standard sending on failure).
* **Silent Disconnection Handling:** Replaced blocking error popups during transient network disconnections with silent status bar notifications and automatic Socket.IO reconnection loops to prevent UI freezes.
* **Debounced Data Saves:** Coalesced rapid message writes using a thread-safe `_save_lock` and a `150ms` debounced timer (`_schedule_save`) to prevent `messages.dat` file corruption during bulk syncs.
* **Accessibility Overrides (NVDA):** Preserved local list focus and selection guards (e.g. clearing focus state before DeleteAllItems) to prevent stuttering and COM errors on screen readers.

---

# V2026.06.20.0312

## Port Refactor
* **Port Uniformity:** Changed the default local API port from `3417` to `6300` in client configurators, settings menus, and startup launchers to align with local WPPConnect Server setups.

---

# V2026.06.18.1742

## @lid JID Name Resolution & Caching
* **Background LID to Phone Resolution:** Implemented background queries utilizing `/contact/fetchProfile` to map linked device JIDs (`@lid`) to real phone numbers and contact names, resolving blank contacts.
* **Local Mapping Cache:** Added a local JID mapper cache (`_lid_to_phone` and `_phone_to_lid`) that is encrypted and stored in `messages.dat` on shutdown.
* **Real-time Chat Merging:** Implemented real-time message merging and unread count accumulation, deduplicating and merging `@lid` chats directly into `@s.whatsapp.net` entries at startup and on incoming events.
* **Placeholder Name Filtering:** Prevented resolved placeholders (e.g. "Contato sem nome") from overwriting valid contact names.
* **Brazilian 9-Digit Interchangeability:** Added support for matching phone numbers with and without the 9th digit interchangeably.

## Contact Synchronization Overhaul
* **Contact Update Merging:** Replaced raw contact overwrites with safe merging (`self.contacts.update`) to prevent active background syncs from wiping out previously resolved contact names.
* **Selective Contact Queries:** Reverted the contact download endpoint to GET `/contact/findContacts` and integrated selective incremental updates to minimize API overhead.
* **Contact Type Filtering:** Explicitly filtered contact list data by `type == contact` to keep parity with the original codebase.

## Startup & WebSocket Stability
* **Connection State Verification:** Implemented a direct HTTP connection query during client initialization to resolve startup race conditions and prevent redundant websocket connections.
* **Registry Autostart Synchronization:** Synced the Windows registry autostart keys with client configuration options on startup to prevent duplicate prompts during reinstallations.
* **Archived Status Sync:** Synchronized chat archives status changes via websocket `chats.update` events and local settings during normalization.
* **Log Redirection:** Redirected all evolution logs to the client logs directory.
* **Platform Guards:** Guarded Windows-specific `ctypes` and subprocess flags behind platform checks to support safer multi-platform script execution.

---

# V2026.06.17.2340

## WebSocket & API Connection
* **Evolution API WebSocket Activation:** Configured `WEBSOCKET_ENABLED=true` and `WEBSOCKET_GLOBAL_EVENTS=true` in the local launcher (`start.js`) to ensure the Socket.IO server initializes correctly, resolving `404 Not Found` connection failures during client startup.

## Maximum Verbosity Logging ("logs no talo")
* **Deep Level Logging (DEBUG):** Upgraded the entire Python client log level to `DEBUG` and redirected all standard output (`sys.stdout`) to `logging.DEBUG` to capture every print.
* **Network & WebSocket Tracing:** Explicitly forced all HTTP (`requests`, `urllib3`) and Socket.IO/Engine.IO loggers to `DEBUG` level.
* **Full Socket.IO Packet Logging:** Enabled `logger=True` and `engineio_logger=True` on the Socket.IO client constructor to record all incoming/outgoing websocket packets, events, payload contents, and keep-alive heartbeats.

---

# V2026.06.17.2228

## Critical App Bug Fixes
* **Connection Initialization Crash:** Resolved a startup crash (`TypeError: Cannot read properties of undefined (reading 'state')`) by applying a defensive patch to the Baileys auth state and enabling PostgreSQL local database persistence by default.
* **Force Update Feedback:** Fixed silent failures during manual update checks (Help > Force Update) to display a dialog explaining the network error or GitHub rate limits.

## Database & API Integration
* **Local Database Persistence:** Enabled database saving by default in the API boot script (`start.js`) so that instance credentials and chat history persist correctly in PostgreSQL (`DATABASE_SAVE_DATA_INSTANCE=true`).
* **Automated Patching:** Integrated all Baileys and Evolution API patch scripts (quoted context, pairing time, mark read, auth state) into the automated GitHub Actions release workflow.

## Client Logging System
* **Persistent Logs:** Added a client logging module writing to `logs/log.log` to track runtime traces, request errors, and detailed updater exception tracebacks for troubleshooting.

## CI/CD & Automation
* **Workflow Concurrency Control:** Added concurrency settings in GitHub Actions to automatically cancel any in-progress runs when a new push is received, preventing duplicate builds and race conditions.

---

# V2026.06.17.2208

## CI/CD & Automation
* **Automated Release Pipeline:** Implemented a full GitHub Actions workflow (`release.yml`) running on Windows Server to compile and publish ready-to-run releases on every push to the `main` branch.
* **Date-Based Versioning:** Switched to automatic UTC date/time versioning (`YYYY.MM.DD.HHMM`, e.g., `2026.06.17.2208`) to prevent loop updates.
* **Structured Action Caches:** Added cache scopes for MSYS2, Python pip dependencies, Node.js binaries, and `node_modules` to speed up remote compilation.

## User Interface
* **Interface Cleanup:** Removed the "What's New" dialog (`WhatsNewDialog`) and changelog buttons from the updater interface to streamline startup.

---

# V0.11.0.1

## Auto-Updater System
* **GitHub Release Integration:** Re-engineered the updater to query GitHub Releases API directly, fetching tags and release notes natively without needing extra files.
* **File Lock Resolution:** Added dynamic process termination routines in the updater script to close PostgreSQL (port 5433) and Evolution API (port 6300) connections, preventing "Access Denied" errors during files overwrite.

## Compilation & Packaging
* **PyInstaller Migration:** Replaced the legacy Nuitka compiler with PyInstaller (`build.py`) for builds packaging.
* **Library DLL Bundling:** Restructured packaging of critical dynamic sound DLLs (BASS) and screen readers (`accessible-output2`) to prevent runtime crashes.
* **Custom Installer Stub:** Optimized the C stub installer (`installer.c`) to extract payload files and register uninstallation entries on Windows.

## Development Setup
* **Dependencies Preservation:** Updated `setup_api.py` to preserve the `node_modules` folder, maintaining a local NPM cache during checkout operations.

---

# V0.10.0.0

## Client Stabilization
* **Dialogue Error Fix:** Fixed an `AttributeError` in the connection dialog (`connection_dial`) occurring during WebSocket disconnections.
* **LID JID Compatibility:** Added support for linked device JIDs (`@lid`), resolving blank contact and conversation names.
* **Group Formatting:** Prevented group JIDs from being incorrectly parsed as standard phone numbers.
* **Updater Redirection:** Updated all download endpoints to target `JoaoDEVWHADS/WinZapp_Python`.
