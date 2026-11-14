---
paths:
  - "client/core/websocket_client.py"
  - "client/core/message_queue.py"
  - "client/core/database.py"
  - "client/core/database_bridge.py"
  - "client/main_window/message_events.py"
  - "client/main_window/message_rules.py"
  - "client/main_window/sending.py"
  - "client/ui/conversation_panel/text_sending.py"
---

# Message pipeline

**Read `docs/reference/message-pipeline.md` before changing these files.** Short form:

1. `client/core/websocket_client.py` normalizes WPPConnect events into the canonical dict `{"key": {"remoteJid","fromMe","id","participant"?}, "message", "messageType", "messageTimestamp", "pushName"}`.
2. `MainWindow.on_new_message()` (live) and `on_historical_message()` (history) are the two funnels, both gated by `_live_events_ready()`. `is_countable_message()` keeps system events out of badges/sort/notify. `_is_undecrypted_placeholder()` drops a live `ciphertext`; one a sync stored is shown and later replaced by its decrypted copy. An edit arrives under the *original* `key.id` and goes to `_apply_possible_edit()`.
3. Sends: `client/ui/conversation_panel/text_sending.py` shows a virtual pending message (`_local_pending`, `_local_id`), `client/core/message_queue.py` calls `MainWindow.send_*`; the echo comes back through `on_new_message` and is matched to the pending message **by type**. Ambiguous failures (timeout, 5xx) are never resent.
4. `client/core/database.py` is async aiosqlite (payloads Fernet-encrypted with `data/secret.key`); `client/core/database_bridge.py` is the sync façade with a timeout so a stuck coroutine cannot freeze the app.
