"""Issue #70: the "attach a contact" picker iterated main_window.contacts
directly, but that dict intentionally holds more than one entry per real
person — the same contact bridged under @lid, @c.us and/or @s.whatsapp.net,
and Brazilian numbers additionally under both their 8- and 9-digit mobile
form (see core.utils.contact_dedup_key()). Every contact showed up twice,
once per JID variant with a different phone-number format, and in
dict-insertion order rather than sorted.

AttachContactDialog is a wx.Dialog and can't be instantiated without a
running wx.App, so the population logic is reimplemented against a stub in
the same shape as tests/test_new_conversation_empty_list.py, exercising the
real contact_dedup_key() the dialog now uses.
"""

from core.utils import contact_dedup_key, format_number


class _FakeMw:
    def __init__(self, contacts=None, lid_to_phone=None):
        self.contacts = dict(contacts or {})
        self._lid_to_phone = dict(lid_to_phone or {})

    def _normalize_jid(self, jid):
        if not jid:
            return jid
        if jid.endswith("@c.us"):
            return jid[:-5] + "@s.whatsapp.net"
        return jid


def _contact(name=""):
    return {"name": name}


def _build_rows(mw):
    """Mirrors AttachContactDialog._build_ui()'s population logic."""
    best_by_key = {}
    for jid, contact in mw.contacts.items():
        if not jid or jid.endswith("@g.us"):
            continue
        key = contact_dedup_key(mw, jid)
        entry = {**contact, "remoteJid": jid}
        existing = best_by_key.get(key)
        if existing is None or (
            existing["remoteJid"].endswith("@lid") and not jid.endswith("@lid")
        ):
            best_by_key[key] = entry

    rows = [
        (
            entry.get("name") or entry.get("pushName") or format_number(entry["remoteJid"]),
            entry,
        )
        for entry in best_by_key.values()
    ]
    rows.sort(key=lambda r: r[0].lower())
    return rows


class TestAttachContactDedup:
    def test_brazilian_8_vs_9_digit_forms_are_not_duplicated(self):
        mw = _FakeMw(contacts={
            "551199999999@s.whatsapp.net": _contact("Carla"),
            "5511999999999@s.whatsapp.net": _contact("Carla"),
        })

        rows = _build_rows(mw)

        assert [name for name, _ in rows] == ["Carla"]

    def test_lid_and_phone_forms_are_not_duplicated(self):
        lid = "10000000000001@lid"
        phone = "5511999999999@s.whatsapp.net"
        mw = _FakeMw(
            contacts={lid: _contact("Duda"), phone: _contact("Duda")},
            lid_to_phone={lid: phone},
        )

        rows = _build_rows(mw)

        assert [name for name, _ in rows] == ["Duda"]
        # The phone JID is kept (usable for the vCard), not the @lid one.
        assert rows[0][1]["remoteJid"] == phone

    def test_cus_and_net_forms_are_not_duplicated(self):
        mw = _FakeMw(contacts={
            "5511999999999@c.us": _contact("Bia"),
            "5511999999999@s.whatsapp.net": _contact("Bia"),
        })

        rows = _build_rows(mw)

        assert [name for name, _ in rows] == ["Bia"]

    def test_rows_are_sorted_alphabetically_case_insensitively(self):
        mw = _FakeMw(contacts={
            "3@s.whatsapp.net": _contact("carlos"),
            "1@s.whatsapp.net": _contact("Ana"),
            "2@s.whatsapp.net": _contact("Bia"),
        })

        rows = _build_rows(mw)

        assert [name for name, _ in rows] == ["Ana", "Bia", "carlos"]

    def test_groups_are_excluded(self):
        mw = _FakeMw(contacts={
            "120363000000000001@g.us": _contact("Grupo"),
            "1@s.whatsapp.net": _contact("Ana"),
        })

        rows = _build_rows(mw)

        assert [name for name, _ in rows] == ["Ana"]
