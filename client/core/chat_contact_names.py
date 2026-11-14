"""Where a name learned from a chat listing or a nickname announcement may land.

The conversation list and ``contacts.update`` both carry a name for a person, and
that name is not always the one the user's address book gives them: the Neonize
bridge only knows a public nickname for many people, and WhatsApp itself sends a
nickname with every first message. A record that is in an address book keeps its
name, whatever else arrives; the nickname goes beside it (``pushName``), where the
name shown prefers ``name`` anyway (``MainWindow._resolve_contact_name``).

A Brazilian mobile is stored with or without its 9th digit depending on where it
came from (``phone_contacts.other_digit_form``), so a record is looked for under
both forms before another one is created beside it.
"""
from core.phone_contacts import other_digit_form
from core.unsaved_contact_marker import contact_is_saved


def find_contact_key(contacts: dict, jid: str) -> str:
    """The key *jid*'s record sits under in *contacts*: the JID itself, else its
    Brazilian 8/9-digit twin; "" when the person has no record yet."""
    if jid in contacts:
        return jid
    twin = other_digit_form(jid)
    return twin if twin and twin in contacts else ""


def has_address_book_name(contacts: dict, jid: str) -> bool:
    """True when *jid* (either form of its number) is in an address book under a
    name, so no other name may replace it."""
    key = find_contact_key(contacts, jid)
    record = contacts.get(key) if key else None
    return bool(record) and contact_is_saved(record) and bool((record.get("name") or "").strip())


def learn_chat_names(contacts: dict, jid: str, name: str, push_name: str, linked=()) -> None:
    """Files the *name* and profile name (*push_name*) a chat listing carries
    for *jid* and the other addresses of the same person (*linked*: its phone
    JID, its @lid).

    The profile name is always filed. The name is withheld from every address of
    a person who is in an address book under a name already."""
    targets = [jid] + [other for other in linked if other]
    keep_name = any(has_address_book_name(contacts, target) for target in targets)
    for target in targets:
        record = contacts.get(find_contact_key(contacts, target) or target)
        if record is None:
            record = contacts[target] = {"id": target, "remoteJid": target}
        if name and not keep_name:
            record["name"] = name
        if push_name:
            record["pushName"] = push_name
