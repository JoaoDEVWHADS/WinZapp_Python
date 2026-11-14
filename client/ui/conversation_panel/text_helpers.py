"""Small pure text helpers shared by ConversationsPanel's mixins.

Moved verbatim out of ui/conversations.py, which re-exports every name.
"""

import re
from core.locale_format import (
    get_date_format,
    get_time_format,
)


# Compiled URL regex used for link extraction from message text
_URL_RE = re.compile(r'https?://\S+|www\.\S+')


def message_caption(msg) -> str:
    """The caption carried by an image/video/document message, '' otherwise.

    Forwarding preserves captions through a different server call than a
    plain forward (resend_media_message_with_caption), so "does this message
    have a caption?" has to be answered per message — a mass forward mixes
    captioned media with plain text, and sending a text message down the
    media path is not a no-op.
    """
    if not isinstance(msg, dict):
        return ""
    inner = msg.get("message", {})
    if isinstance(inner, str):
        import json
        try:
            inner = json.loads(inner)
        except Exception:
            return ""
    if not isinstance(inner, dict):
        return ""
    for key in ("imageMessage", "videoMessage", "documentMessage"):
        media = inner.get(key)
        if isinstance(media, dict):
            return (media.get("caption") or "").strip()
    return ""


def _fmt_last_seen(ts, i18n) -> str:
    """Format a Unix timestamp as a localized last-seen string."""
    if not ts:
        return ""
    try:
        from datetime import datetime as _dt, timedelta as _td
        ts_val = int(ts)
        if ts_val > 1_000_000_000_000:
            ts_val //= 1000
        dt       = _dt.fromtimestamp(ts_val)
        now      = _dt.now()
        time_str = dt.strftime(get_time_format(i18n.t("time_fmt")))
        if dt.date() == now.date():
            return i18n.t("last_seen_today").format(time=time_str)
        if dt.date() == (now - _td(days=1)).date():
            return i18n.t("last_seen_yesterday").format(time=time_str)
        date_str = dt.strftime(get_date_format(i18n.t("date_fmt")))
        return i18n.t("last_seen_date").format(date=date_str, time=time_str)
    except Exception:
        return ""
