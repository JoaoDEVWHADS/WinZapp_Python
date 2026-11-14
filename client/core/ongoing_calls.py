"""Native joinable calls are live state, never inferred from stored history."""
import re

from core.call_matching import is_placeholder_call_id

_CHAT = re.compile(r"\d+(?:-\d+)?@(?:g\.us|lid|s\.whatsapp\.net|c\.us)")


def ongoing_entries(body):
    rows = body.get("response") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Invalid ongoing calls response")
    result, seen = [], set()
    for row in rows[:500]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or not isinstance(row.get("chatJid"), str) or not _CHAT.fullmatch(row["chatJid"])
                or type(row.get("isVideo")) is not bool or row["id"] in seen):
            continue
        seen.add(row["id"])
        # Canonical form, so lock checks and name lookups match the stored
        # chat; the runtime treats both phone forms as the same chat.
        chat = re.sub(r"@c\.us$", "@s.whatsapp.net", row["chatJid"])
        result.append({"jid": chat, "ongoing": {
            "id": row["id"], "chatJid": chat, "isVideo": row["isVideo"]}})
    return result


def include_current_call(entries, active, state):
    """An established local 1:1 call is current even without a native join log."""
    rows = list(entries)
    if not isinstance(active, dict) or state not in ("ACTIVE", "REJOINING"):
        return rows
    call_id = active.get("call_id")
    if not isinstance(call_id, str) or is_placeholder_call_id(call_id):
        return rows
    if any(entry["ongoing"]["id"] == call_id for entry in rows):
        return rows
    current = ongoing_entries({"response": [{"id": call_id,
        "chatJid": active.get("peer_jid"), "isVideo": bool(active.get("is_video"))}]})
    return current + rows
