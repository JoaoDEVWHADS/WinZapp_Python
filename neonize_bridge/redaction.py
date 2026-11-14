"""No JID, phone number or full session name in the bridge's log.

The user's log.log gets passed around (bug reports, issues). `redact` keeps just
enough to tell one chat from another in the same log: the end of the user part
and the server (`g.us`, `lid`, `s.whatsapp.net`), which identifies nobody. Pure
function, tested in test_redaction.py.
"""
import logging
import re


def redact(value) -> str:
    """`5511999998888@s.whatsapp.net` -> `...88@s.whatsapp.net`; `account1` -> `...t1`."""
    text = str(value or "").strip()
    if not text:
        return "?"
    user, at_sign, server = text.partition("@")
    return f"...{user[-2:]}{at_sign}{server}"


_JID = re.compile(r"(\d{4,})(:\d+)?(@(?:s\.whatsapp\.net|c\.us|lid|g\.us|newsletter|broadcast))")
_NUMBER = re.compile(r"(?<![\w.])\+?\d{9,}(?![\w])")


def mask_text(text) -> str:
    """Hides JIDs and long numbers in a log text (the one of a whatsmeow
    exception can carry the phone). Same cut as `redact`."""
    text = _JID.sub(lambda m: f"...{m.group(1)[-2:]}{m.group(3)}", str(text))
    return _NUMBER.sub(lambda m: "..." + m.group(0)[-2:], text)


class RedactionFilter(logging.Filter):
    """Passes the message and the traceback of each record through `mask_text`."""

    def filter(self, record):
        record.msg = mask_text(record.getMessage())
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_text(record.exc_text)
        return True
