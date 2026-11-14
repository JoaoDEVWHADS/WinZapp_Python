"""Pure rules for the multi-selection of chats in the conversation list.

Moved verbatim out of ui/conversations.py, which re-exports every name.
"""




def toggle_jid_selection(selected: set, jid: str) -> "tuple[bool, bool]":
    """Add/remove *jid* in *selected* and return (now_selected, was_active).

    The pure half of the forward dialog's Ctrl+Space/Space toggle, which lives
    inside a closure in _on_menu_forward() (its selection set is local to the
    dialog, not a panel attribute) and was therefore the one selection-mode
    surface no test could reach. The caller keeps the wx work — the row
    repaint, the sound, the announcement — since none of that is decidable
    from the set alone.

    *was_active* is the state BEFORE the toggle, i.e. whether anything at all
    was selected. That is deliberately NOT what names the mode in the forward
    dialog: its list is filtered by its own search box, and a selection the
    filter hides is not a mode the user is in, so the caller derives both
    booleans from visible_jid_selected() and ignores this one. It stays part of
    the answer because it is the whole-set reading the caller is choosing
    against, and because getting the two confused is the bug this pair of
    helpers exists to keep apart.
    """
    was_active = bool(selected)
    now_selected = jid not in selected
    if now_selected:
        selected.add(jid)
    else:
        selected.discard(jid)
    return now_selected, was_active


def visible_jid_selected(selected: set, listed_jids) -> bool:
    """Whether any of *listed_jids* is in *selected*.

    The forward dialog's equivalent of
    ConversationsPanel._chat_selection_visible(), and it exists for the same
    reason: that dialog has its own search box, which rebuilds the rows while
    selected_jids survives untouched. Gating plain Space on the raw set let a
    user select a contact, type a query that hides it, press Space on another
    one, and forward the message to both — including one they could not see
    they had picked. This surface is the one that actually sends, so it is the
    one where an invisible selection costs most.

    *listed_jids* is any iterable (the dialog passes a generator over the rows
    currently in the ListBox), and the scan short-circuits on the first hit.
    """
    if not selected:
        return False
    return any(jid in selected for jid in listed_jids)
