"""Locale-aware formatting for copied message blocks."""

from datetime import datetime


def format_copied_message(timestamp, sender: str, text: str,
                          datetime_format: str) -> str:
    """Return one WhatsApp-export-style line in the active app locale."""
    if not timestamp:
        return f"{sender}: {text}"
    stamp = datetime.fromtimestamp(timestamp).strftime(datetime_format)
    return f"{stamp} - {sender}: {text}"
