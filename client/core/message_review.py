"""Reviewing a recent message by its position from the newest (issue #462).

The pure half of the ten "review" shortcuts (ui/conversation_panel/
message_accels.py): which row is the Nth newest message, and whether a key press
repeats the last one. No wx, so both are tested without a list control.
"""

#: How long after a review key the same key counts as "again" and copies.
REVIEW_REPEAT_SECONDS = 1.0


def recent_message_index(messages, position, is_separator):
    """Row of the *position*-th newest real message (1 is the newest), or -1.

    Separator rows (the unread marker, the empty placeholder) are not messages
    and are skipped; the typing row is not in the list at all. Pure, so the
    counting is tested without a list control.
    """
    seen = 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or is_separator(message):
            continue
        seen += 1
        if seen == position:
            return index
    return -1


def is_repeated_review(last, digit, msg_id, now, window=REVIEW_REPEAT_SECONDS):
    """Whether this press repeats the previous one: same key, same message,
    within *window* seconds. *last* is (digit, time, message id) or None."""
    return (last is not None and last[0] == digit and last[2] == msg_id
            and now - last[1] <= window)
