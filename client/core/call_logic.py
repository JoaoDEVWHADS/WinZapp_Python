"""Pure call-state helpers shared by the wx UI and headless tests."""


def incoming_call_can_answer(details: dict | None) -> bool:
    """Voice calls are answerable whether direct or group; video is not."""
    return not bool((details or {}).get("is_video"))


def active_call_label_key(active: dict | None) -> str:
    """Return the translation key that matches direct vs group voice calls."""
    return (
        "voice_group_call_active_label"
        if bool((active or {}).get("is_group"))
        else "voice_call_active_label"
    )
