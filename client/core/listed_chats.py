"""Which entries of the server's chat list are conversations WinZapp lists.

Statuses (@broadcast) go to the Status tab. Channels (@newsletter) are not
conversations, and the Neonize bridge lists them without a name, so they stay out
of the conversation list unless Settings > Interface > Chats asks for them
("Show channels in the chat list": a tab of their own is planned, and WhatsApp
itself is trying channels in the chat list).
"""

_STATUS = "@broadcast"
_CHANNEL = "@newsletter"


def channels_listed(settings) -> bool:
    """Whether the user asked for the channels in the conversation list (off by default)."""
    ui = settings.get("user_interface") if isinstance(settings, dict) else None
    return isinstance(ui, dict) and ui.get("show_channels_in_chat_list") is True


def is_listed_chat(jid, show_channels: bool = False) -> bool:
    if not isinstance(jid, str) or not jid or jid.endswith(_STATUS):
        return False
    return show_channels or not jid.endswith(_CHANNEL)
