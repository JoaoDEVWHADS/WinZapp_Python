"""Recognising the echo of a reaction WinZapp itself just sent.

A reaction sent from WinZapp is drawn at once (the optimistic row update in
ui/conversation_panel/reactions.py), and WhatsApp then echoes it back over the
WebSocket as a `fromMe` reaction — twice, through received-message and through
onreactionmessage. That echo must be dropped, or the reaction is counted
again. A `fromMe` reaction made on the phone or another linked device looks
exactly the same and must NOT be dropped, so a send leaves a short-lived
marker (`MainWindow._pending_own_reactions`) and only an echo matching it is
suppressed.

What it matches on is the whole point. The marker used to be (message id,
emoji), with no chat: a message id is only unique within its chat, so a
reaction made on the phone to another chat's message with the same id and the
same emoji, within the window, was swallowed as if it were WinZapp's echo.
The chat is part of the key now, and because one chat reaches here under
several spellings — send_reaction() swaps a phone JID for its @lid before
sending, and the echo comes back as @lid, @c.us or @s.whatsapp.net — every
spelling known for it counts as the same chat.

Pure: no wx, no MainWindow. The callers pass the @lid/phone maps in.
"""

#: How long a sent reaction waits for its echo. An echo later than this is
#: treated as a reaction made elsewhere, which is the safe direction: at
#: worst it is counted twice, never lost.
ECHO_WINDOW_SECONDS = 60


def _canonical(jid) -> str:
    """Device suffix stripped and @c.us folded to @s.whatsapp.net — the same
    reduction as MainWindow._normalize_jid."""
    jid = str(jid or "").strip()
    if not jid:
        return ""
    if ":" in jid and "@" in jid:
        user, domain = jid.split("@", 1)
        jid = f"{user.split(':', 1)[0]}@{domain}"
    if jid.endswith("@c.us"):
        jid = jid[:-len("@c.us")] + "@s.whatsapp.net"
    return jid


def _chat_spellings(jid):
    """Phone aliases include Brazil's optional ninth digit, never LID/group IDs."""
    jid = _canonical(jid)
    if not jid:
        return set()
    forms = {jid}
    if jid.endswith("@s.whatsapp.net"):
        digits = jid.split("@", 1)[0]
        if digits.isdigit() and digits.startswith("55"):
            if len(digits) == 13 and digits[4] == "9":
                forms.add(f"{digits[:4]}{digits[5:]}@s.whatsapp.net")
            elif len(digits) == 12:
                forms.add(f"{digits[:4]}9{digits[4:]}@s.whatsapp.net")
    return forms


def reaction_echo_keys(chats, target_id, emoji, lid_to_phone=None, phone_to_lid=None):
    """Every (chat, message id, emoji) a reaction can be recognised by.

    *chats* are whichever spellings of the conversation the caller has (the
    sender: the chat it was asked for and the one it sent to; the receiver:
    both keys of the echo). Each is canonicalised and bridged through the
    @lid/phone maps both ways, so a send and its echo share a key whatever
    form each side happened to use. Empty when there is no message id.
    """
    target_id = str(target_id or "")
    if not target_id:
        return frozenset()
    emoji = str(emoji or "").strip()
    lid_to_phone = lid_to_phone or {}
    phone_to_lid = phone_to_lid or {}
    forms = set()
    remaining = set()
    for chat in chats:
        remaining.update(_chat_spellings(chat))
    # A LID can map to either phone spelling; expand the phone before looking
    # up its inverse bridge so the other digit count can reach the same LID.
    while remaining:
        chat = remaining.pop()
        if chat in forms:
            continue
        forms.add(chat)
        for bridge in (lid_to_phone, phone_to_lid):
            remaining.update(_chat_spellings(bridge.get(chat, "")) - forms)
    return frozenset((chat, target_id, emoji) for chat in forms)


def prune_expired(pending: dict, now: float) -> None:
    """Drop markers whose echo window has passed. *pending* maps a send's
    token to ``(created_at, keys)``."""
    for token, (created_at, _keys) in list(pending.items()):
        if now - created_at > ECHO_WINDOW_SECONDS:
            pending.pop(token, None)


def take_matching_send(pending: dict, keys, now: float):
    """Remove and return the token of the send *keys* echo, or None.

    A send is removed whole, every spelling of its chat with it: a spelling
    left behind would go on to swallow a genuine reaction made on the phone
    to that same message with that same emoji.
    """
    prune_expired(pending, now)
    if not keys:
        return None
    for token, (_created_at, send_keys) in list(pending.items()):
        if send_keys & keys:
            pending.pop(token, None)
            return token
    return None


def stored_reaction_chat(chats, jid, lid_to_phone=None, phone_to_lid=None) -> str:
    """The key under which *jid*'s conversation is stored in *chats*.

    Reported (Neonize): a reaction to the user's message showed in the chat
    list's preview in one conversation and not in another. A reaction reaches
    on_new_message() before the @lid/phone resolution every other message
    goes through, so it looked the chat up under the address it came with: a
    private chat's reaction arrives as its @lid, and a chat stored under the
    number was not found, so nothing was updated. Looked up here under every
    spelling of the same chat (number <-> @lid, Brazil's ninth digit); *jid*
    itself when none is stored."""
    jid = _canonical(jid)
    if not jid or jid in chats:
        return jid
    lid_to_phone = lid_to_phone or {}
    phone_to_lid = phone_to_lid or {}
    candidates = []
    if jid.endswith("@lid"):
        candidates.append(lid_to_phone.get(jid, ""))
    else:
        candidates.append(phone_to_lid.get(jid, ""))
    for form in _chat_spellings(jid):
        candidates.append(form)
        candidates.append(phone_to_lid.get(form, ""))
    for phone in list(candidates):
        candidates.extend(_chat_spellings(phone))
    for candidate in candidates:
        if candidate and candidate in chats:
            return candidate
    return jid
