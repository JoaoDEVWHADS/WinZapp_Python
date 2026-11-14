"""Per-account quick-chat slots, stored without contact names."""

def slots_from_settings(settings):
    slots = settings.get("quick_chats", {}) if isinstance(settings, dict) else {}
    if not isinstance(slots, dict):
        return {}
    return {str(d): jid for d in range(10)
            if isinstance((jid := slots.get(str(d))), str) and jid}
