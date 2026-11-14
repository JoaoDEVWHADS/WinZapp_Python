"""Delete one of the account's own statuses, for everyone who received it.

The route is WinZapp's own (client/api_patches/src/controller/statusDeleteController.ts):
it does what WhatsApp Web's "Delete" in the status player does. Sent once and
never retried here: a delete that timed out may already have reached everyone.
"""

from core.api_client import api_post

#: The status is not among the account's own any more (expired, or deleted
#: already, here or on the phone): nothing is left to delete.
NOT_FOUND = "not_found"


def plain_key_id(status_id):
    """The id part of *status_id*: a stored key.id is sometimes the whole
    serialized id (fromMe_remote_id[_participant]), which the route refuses
    as invalid_request, and the user heard "could not confirm" for it."""
    if isinstance(status_id, str):
        parts = status_id.split("_")
        if len(parts) >= 3 and parts[0] in ("true", "false") and parts[2]:
            return parts[2]
    return status_id


def delete_own_status(connection, status_id) -> None:
    """Delete *status_id* (the key.id of one of the account's own statuses).
    Returns on success; ValueError with the server's code otherwise
    ("unavailable" when there was none)."""
    status_id = plain_key_id(status_id)
    server, port, token = connection
    url = f"{server}:{port}/api/{token}/status/{status_id}/delete"
    try:
        response = api_post(url, json={}, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        body = response.json()
    except Exception:
        raise ValueError("unavailable") from None
    if response.status_code == 200 and isinstance(body, dict) and body.get("status") == "success":
        return
    code = body.get("code") if isinstance(body, dict) else None
    raise ValueError(code if isinstance(code, str) and code else "unavailable")
