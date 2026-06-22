# Plan: WinZapp Bugfixes

Fix sync issues, unread status, archive desynchronization, audio duration, channel visibility, and status posting failures in WinZapp.

## Success Criteria
- [x] Initial sync does not crash/freeze the Node.js API.
- [x] Archiving/unarchiving a chat on the phone is reflected on the PC instantly.
- [x] Reading messages on the phone clears the unread counts on the PC.
- [x] Channels/newsletters are filtered out (kept hidden) from the conversations list.
- [x] Audio messages display their correct duration instead of "0 segundos".
- [x] Text and media statuses can be posted successfully.

## Tasks

### Task 1: API (Node.js) WA-JS events bridging
- **Agent**: `backend-specialist`
- **File**: `client/api/src/util/createSessionUtil.ts`
- **Input**: Current `createSessionUtil.ts`
- **Output**: Expose `onChatsUpdateNode` and evaluate `chat.unread_count_changed` and `change:archive`/`change:unreadCount` Backbone events on `window.Store.Chat`.
- **Verify**: Inspect that `chats-update` events are successfully generated on Socket.IO when a chat's archive or unread state changes.

### Task 2: Python Client: startup optimization & dynamic message sync
- **Agent**: `backend-specialist`
- **File**: `client/main.py` & `client/ui/conversations.py`
- **Input**: Sequentially syncing all chats on start.
- **Output**: Limit startup message sync to top 20 chats + unread chats. Fetch messages in a background thread when navigating to a chat, and refresh messages.
- **Verify**: Client loads and populates the list quickly, and clicking a non-cached chat fetches and renders its messages.

### Task 3: Python Client: keep channel filters (restored)
- **Agent**: `backend-specialist`
- **File**: `client/main.py`
- **Input**: User requested to keep the newsletter/channel filter.
- **Output**: Channels/newsletters are kept filtered/hidden.
- **Verify**: Reverted changes so channels are not displayed and filtered out correctly.

### Task 4: Python Client: status updates caching & text status posting
- **Agent**: `backend-specialist`
- **File**: `client/main.py`, `client/status_panel.py`, `client/core/websocket_client.py`
- **Input**: In-memory status updates, incorrect payload for `/send-text-storie`, missing mediaData duration fallback.
- **Output**: Save status updates to `messages.dat` and load them on startup. Correct text status payload option wrapping. Parse audio duration from `mediaData.duration` if missing.
- **Verify**: Statuses persist across app restarts, text statuses can be posted, and audio durations are correct.

## Phase X: Final Verification
- [x] Validate changes by compiling/running the application.
- [x] Verify no critical issues.

## ✅ PHASE X COMPLETE
- Lint: ✅ Pass
- Security: ✅ No critical issues
- Build: ✅ Success
- Date: 2026-06-22
