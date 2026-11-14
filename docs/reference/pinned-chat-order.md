# Optional fixed order for pinned chats

Settings > User Interface > "Keep pinned chats in a fixed order" is per-account
and off by default. Off preserves the existing recent-message ordering.
On keeps pinned chats in their saved relative order while messages change
their previews. Unpinned chats retain recent-message ordering in both modes.
Apply/OK and settings import request a list recompute without a restart.

The sort key in `main_window/chat_list.py` is shared by main, archived and
locked lists. A fixed-order pinned chat's live message path repaints only
that row; active searches, filters and custom WhatsApp lists retain their
existing full-sort fallback. Names and message times are never rank inputs.

`core/pinned_chat_order.py` keeps an ordered list in account DB metadata
`pinned_chat_order`, independently of the legacy `pinned_chats` membership
set. Only known `_lid_to_phone` mappings bridge identities (a reverse-only
`_phone_to_lid` entry is a leftover of identity cleanup and is never used);
legacy phone JIDs and device suffixes use the existing normalizer. A mapping learned later folds
the aliases into one retained position.

On the first load, numeric server pin timestamps seed the order, newest pin
first. Boolean-only pins use the already displayed order where available;
remaining ties use a deterministic identity order. Old unordered membership
metadata cannot reconstruct an unavailable original pin order. The initial
fallback is saved, so subsequent messages, polls and reloads do not change it.
This is a local display preference, not a claim that every client exposes the
same relative order.

Newly pinned chats go before retained pins. Unpinning removes a rank;
repinning assigns a new place. Local actions, phone-side pin events and polls
maintain the saved order. A definite API rejection restores the previous
relative order without removing unrelated pins added during the request.
No retries or changes to ambiguous API-failure handling are introduced.

F5 preserves metadata and the rank cache. An account wipe retires the cache
under its lock before clearing DB metadata, so an old worker cannot persist
the previous account's ranks afterward. The wipe also replaces the pinned
set, and a list build that captured the old set before that saves nothing.
Reads are cached per window, writes only occur when the order changes, and a
failed write can be retried. A pin event that arrives before the account DB
opens (a reused pairing socket) is not cached, so it cannot hide the saved
order once the DB is there. Server times and the visible order are only read
when a chat was newly pinned.

`tests/test_pinned_chat_order.py` calls real methods on plain stubs and tests
the pure reconciliation logic. Remote-poll, settings-import and account-wipe
integration cases accompany the existing tests in those areas. The existing
Settings checkbox wiring and CI roundtrip tests discover the new checkbox.
Local verification never constructs a wx window, opens an audio device or
contacts WhatsApp.
