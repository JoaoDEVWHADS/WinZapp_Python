"""Log every message box WinZapp shows, with its text and caller.

Several dialogs have appeared that nothing in log.log accounts for (a
Portuguese pairing error on an English, already-paired install). WinZapp
calls wx.MessageBox directly in many places; logging each one with its text
and the call stack makes the next occurrence traceable.

A message box can quote a contact's name or number, and only numbers are
masked (core/pii_redaction.py), so neither log records the message text:
the caption, the text's length and the call stack identify the dialog.
The persistent file is capped at MAX_BYTES (one older copy is kept).
"""

import logging
import os
import time
import traceback

import wx

_orig_message_box = wx.MessageBox
LOG_DIR = os.path.expanduser("~/Library/Logs/WinZapp")
MAX_BYTES = 256 * 1024


def persistent_entry(caption, message, stack, when=None):
    """The message-boxes.log entry: caption, text length and caller, never
    the text itself."""
    from core.pii_redaction import redact_phone
    when = when or time.strftime("%Y-%m-%d %H:%M:%S")
    return redact_phone(f"{when} {caption!r} | {len(str(message))} characters\n{stack}\n")


def _rotate(path, max_bytes=MAX_BYTES):
    """Keep the file under max_bytes by moving it aside to <path>.1."""
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except OSError:
        pass


def _logged_message_box(message, caption=wx.MessageBoxCaptionStr, style=wx.OK | wx.CENTRE,
                        parent=None, x=wx.DefaultCoord, y=wx.DefaultCoord):
    try:
        stack = "".join(traceback.format_stack(limit=8)[:-1])
        logging.warning("[message-box] %r | %d characters\n%s", caption, len(str(message)), stack)
        # log.log is truncated at every launch; keep these across restarts.
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "message-boxes.log")
        _rotate(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(persistent_entry(caption, message, stack))
    except Exception:
        pass
    return _orig_message_box(message, caption, style, parent, x, y)


def install():
    wx.MessageBox = _logged_message_box
