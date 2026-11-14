"""Companion-device suffix handling for JIDs."""


def strip_device_suffix(jid: str) -> str:
    """Drop the ":NN" companion-device part ("123:56@lid" -> "123@lid")."""
    if not jid or ":" not in jid or "@" not in jid:
        return jid
    user, server = jid.split("@", 1)
    return f"{user.split(':', 1)[0]}@{server}"
