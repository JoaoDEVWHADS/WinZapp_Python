"""A name learned from a chat listing or a nickname never replaces the name an
address book gives the person.

Measured on a real Neonize account before the fix, with the real client code
over the real contact data: after the 60 s conversation-list poll, 70 of the 103
saved contacts showed a nickname (or the phone's old conversation name) instead
of the name the user gave them, until the next all-contacts poll put it back.

No window is created: the module's functions, the unbound `on_contacts_update`
and the unbound `_store_resolved_name` run on plain stubs.
"""
from types import SimpleNamespace

from core import chat_contact_names as ccn
from core.websocket_client import WebSocketClient
from main import MainWindow

PHONE = "5511999990000@s.whatsapp.net"
TWIN = "551199990000@s.whatsapp.net"          # the same number without the 9th digit
LID = "123456789012345@lid"


def saved(name, **extra):
    return {"id": PHONE, "remoteJid": PHONE, "name": name, "pushName": name,
            "isMyContact": True, "syncToAddressbook": True, "type": "contact", **extra}


# -- find_contact_key / has_address_book_name ---------------------------------

def test_a_record_is_found_under_either_form_of_a_brazilian_number():
    assert ccn.find_contact_key({PHONE: {}}, PHONE) == PHONE
    assert ccn.find_contact_key({TWIN: {}}, PHONE) == TWIN
    assert ccn.find_contact_key({PHONE: {}}, TWIN) == PHONE
    assert ccn.find_contact_key({}, PHONE) == ""
    assert ccn.find_contact_key({"14155550123@s.whatsapp.net": {}}, "14155550123@s.whatsapp.net")


def test_only_a_record_with_a_name_in_an_address_book_counts():
    assert ccn.has_address_book_name({PHONE: saved("Ana Silva")}, PHONE)
    assert ccn.has_address_book_name({TWIN: saved("Ana Silva")}, PHONE)
    assert not ccn.has_address_book_name({PHONE: {"name": "aninha", "pushName": "aninha"}}, PHONE)
    assert not ccn.has_address_book_name({PHONE: saved("")}, PHONE)
    assert not ccn.has_address_book_name({}, PHONE)


# -- learn_chat_names ----------------------------------------------------------

def test_the_listings_name_does_not_replace_a_saved_name():
    contacts = {PHONE: saved("Ana Silva")}

    ccn.learn_chat_names(contacts, LID, "aninha", "aninha", linked=(PHONE,))

    assert contacts[PHONE]["name"] == "Ana Silva"
    assert contacts[PHONE]["pushName"] == "aninha"      # the nickname goes beside it
    assert "name" not in contacts[LID] or contacts[LID]["name"] != "aninha"


def test_the_saved_name_is_kept_when_the_record_sits_under_the_other_digit_form():
    contacts = {TWIN: saved("Bia Lima", id=TWIN, remoteJid=TWIN)}

    ccn.learn_chat_names(contacts, PHONE, "bia", "bia")

    assert contacts[TWIN]["name"] == "Bia Lima"
    assert PHONE not in contacts                          # no second record beside it


def test_an_unsaved_person_still_gets_the_name_the_listing_carries():
    contacts = {}

    ccn.learn_chat_names(contacts, PHONE, "Maria", "", linked=(LID,))

    assert contacts[PHONE]["name"] == "Maria" and contacts[LID]["name"] == "Maria"


def test_a_record_that_is_not_in_an_address_book_is_renamed_as_before():
    contacts = {PHONE: {"name": "old", "pushName": "old"}}

    ccn.learn_chat_names(contacts, PHONE, "new", "newer")

    assert contacts[PHONE]["name"] == "new" and contacts[PHONE]["pushName"] == "newer"


# -- contacts.update -----------------------------------------------------------

class _Window:
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self, contacts, lid_to_phone=None):
        self.contacts = contacts
        self._lid_to_phone = lid_to_phone or {}
        self.db = SimpleNamespace(upsert_contact=lambda jid, record: self.upserted.append(jid))
        self.upserted = []
        self._schedule_set_chats = lambda: None


class _Socket:
    on_contacts_update = WebSocketClient.on_contacts_update

    def __init__(self, window):
        self.main_window = window

    def _belongs_to_this_session(self, info):
        return True


def announce(window, jid, nickname):
    _Socket(window).on_contacts_update(
        {"session": "s", "data": [{"remoteJid": jid, "pushName": nickname}]})


def test_a_nickname_announcement_keeps_the_saved_name(monkeypatch):
    monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda f, *a: f(*a))
    window = _Window({PHONE: saved("Ana Silva")})

    announce(window, PHONE.replace("@s.whatsapp.net", "@c.us"), "aninha")

    assert window.contacts[PHONE]["name"] == "Ana Silva"
    assert window.contacts[PHONE]["pushName"] == "aninha"


def test_a_nickname_announcement_does_not_open_a_record_beside_the_saved_twin(monkeypatch):
    monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda f, *a: f(*a))
    window = _Window({TWIN: saved("Bia Lima", id=TWIN, remoteJid=TWIN)})

    announce(window, PHONE.replace("@s.whatsapp.net", "@c.us"), "bia")

    assert list(window.contacts) == [TWIN]
    assert window.contacts[TWIN]["name"] == "Bia Lima"
    assert window.upserted == [TWIN]


def test_a_nickname_announcement_for_an_unknown_person_still_creates_the_record(monkeypatch):
    monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda f, *a: f(*a))
    window = _Window({})

    announce(window, PHONE.replace("@s.whatsapp.net", "@c.us"), "Maria")

    assert window.contacts[PHONE]["pushName"] == "Maria"


# -- the @lid resolution -------------------------------------------------------

def test_the_lid_resolution_does_not_write_a_nickname_over_a_saved_name():
    window = SimpleNamespace(contacts={PHONE: saved("Ana Silva")})
    updated = {}

    MainWindow._store_resolved_name(window, PHONE, "aninha", updated)

    assert window.contacts[PHONE]["name"] == "Ana Silva" and updated == {}


def test_the_lid_resolution_respects_the_saved_twin_too():
    window = SimpleNamespace(contacts={TWIN: saved("Bia Lima", id=TWIN, remoteJid=TWIN)})
    updated = {}

    MainWindow._store_resolved_name(window, PHONE, "bia", updated)

    assert PHONE not in window.contacts and updated == {}


def test_the_lid_resolution_still_names_an_unsaved_person():
    window = SimpleNamespace(contacts={})
    updated = {}

    MainWindow._store_resolved_name(window, LID, "Maria", updated)

    assert window.contacts[LID]["name"] == "Maria" and LID in updated
