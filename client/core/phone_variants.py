"""The Brazilian 8/9-digit mobile pair of a phone JID.

A Brazilian mobile can be written with or without its 9th digit
(55DD9XXXXXXXX / 55DDXXXXXXXX) and WhatsApp may store the same person under
either. "Nova conversa" creates the chat under the form the user typed; the
chat WhatsApp generates on the first message can use the other one.
"""

PHONE_JID_SUFFIX = "@s.whatsapp.net"


def other_brazilian_mobile_jid(jid: str) -> str:
    """The other 8/9-digit form of a Brazilian phone JID, or "" when it has none."""
    if not jid or not jid.endswith(PHONE_JID_SUFFIX):
        return ""
    digits = jid[: -len(PHONE_JID_SUFFIX)]
    if not digits.isdigit() or not digits.startswith("55"):
        return ""
    if len(digits) == 13 and digits[4] == "9":
        return digits[:4] + digits[5:] + PHONE_JID_SUFFIX
    if len(digits) == 12 and digits[4] in "6789":  # landlines start with 2-5
        return digits[:4] + "9" + digits[4:] + PHONE_JID_SUFFIX
    return ""


def brazilian_variant_chat_jid(chats, jid: str) -> str:
    """The key of an existing chat under the other 8/9-digit form of *jid*, or ""."""
    other = other_brazilian_mobile_jid(jid)
    if other and other in chats:
        return other
    return ""
