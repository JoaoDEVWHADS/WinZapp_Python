"""The sender prefix of a message row, and the setting that drops it for the
user's own messages (Settings > User Interface,
``user_interface.hide_own_sender_in_message_list``, off by default).

Only the lead of the row changes. The self-reference word of "How should I be
referred to?" is still used by reactions, mentions, quoted replies and group
notices, so hiding it here is a separate switch rather than an empty custom
word.
"""
from core.call_log import is_call_log


def hide_own_sender_enabled(settings) -> bool:
    """True only when the setting is explicitly on; a missing or malformed
    settings dict counts as off, like the shipped default."""
    ui = settings.get("user_interface") if isinstance(settings, dict) else None
    if not isinstance(ui, dict):
        return False
    return ui.get("hide_own_sender_in_message_list", False) is True


def should_hide_sender(msg, settings) -> bool:
    """Whether this row leaves out its sender: the setting is on and the message
    is the user's own. A call record keeps its sender, because its sentence
    does not say who called."""
    if not isinstance(msg, dict) or not hide_own_sender_enabled(settings):
        return False
    return bool((msg.get("key") or {}).get("fromMe")) and not is_call_log(msg)


def row_lead(sender: str, replying_to: str, body: str, hide_sender: bool = False) -> str:
    """Sender, optional "replying to X" clause and body, as a row starts:
    ``Sender, replying to X: body``. Without its sender the row starts with the
    clause, or with the body itself when it is not a reply."""
    if hide_sender:
        return f"{replying_to}: {body}" if replying_to else body
    header = f"{sender}, {replying_to}" if replying_to else sender
    return f"{header}: {body}"
