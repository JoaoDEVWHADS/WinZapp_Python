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


def normalize_group_call_participants(
    participants: list[str] | tuple[str, ...] | None,
    lid_to_phone: dict[str, str] | None = None,
) -> list[str]:
    """Return unique individual phone JIDs accepted by the group-call runtime."""
    mapping = lid_to_phone or {}
    normalized: list[str] = []
    seen: set[str] = set()
    for value in participants or []:
        jid = str(value or "").strip()
        if not jid:
            continue
        if jid.endswith("@lid"):
            jid = str(mapping.get(jid) or "").strip()
            if not jid:
                continue
        if "@" not in jid and jid.isdigit():
            jid = f"{jid}@c.us"
        elif jid.endswith("@s.whatsapp.net"):
            jid = jid[: -len("@s.whatsapp.net")] + "@c.us"
        if not jid.endswith("@c.us") or jid in seen:
            continue
        seen.add(jid)
        normalized.append(jid)
    return normalized
