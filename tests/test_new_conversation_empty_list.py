"""Tests for the New Conversation dialog listing contacts without typing.

The dialog used to open with an empty list and only populate once the user
typed something in the search field, because _do_search() returned early on
an empty query and nothing populated the list at construction time. For a
screen-reader user that meant: Ctrl+N opens a dialog, focus lands on an
empty list, and there is no way to know which contacts exist without
guessing a name to type.

The fix makes an empty query list everything (chats first, then the
remaining contacts), and the dialog populates the list at construction so
the full contact list is visible immediately.

NewConversationDialog is a wx.Dialog and can't be instantiated without a
running wx.App, so _do_search is exercised against a stub carrying a fake
results list — same approach as the rest of the UI-logic tests.
"""

from ui.dialogs.new_conversation import NewConversationDialog


class _FakeResultsList:
    def __init__(self):
        self.items = []
        self.focus_calls = []
        self.select_calls = []

    def DeleteAllItems(self):
        self.items = []

    def Append(self, row):
        self.items.append(row[0])

    def Focus(self, idx):
        self.focus_calls.append(idx)

    def Select(self, idx, on=True):
        self.select_calls.append(idx)


class _FakeI18n:
    def t(self, key):
        return {"no_results": "Sem resultados"}.get(key, key)


class _FakeMw:
    def __init__(self, chats=None, contacts=None, lid_to_phone=None):
        self.chats = dict(chats or {})
        self.contacts = dict(contacts or {})
        self._lid_to_phone = dict(lid_to_phone or {})
        self.i18n = _FakeI18n()

    def _normalize_jid(self, jid):
        if not jid:
            return jid
        if ":" in jid and "@" in jid:
            parts = jid.split("@", 1)
            base = parts[0].split(":", 1)[0]
            jid = f"{base}@{parts[1]}"
        if jid.endswith("@c.us"):
            return jid[:-5] + "@s.whatsapp.net"
        return jid

    def _resolve_contact_name(self, chat):
        return chat.get("name", "")

    def find_name_through_messages(self, chat):
        return ""

    def find_jid_through_messages(self, chat):
        return ""

    @staticmethod
    def _group_name_from_chat_dict(chat):
        name = (chat.get("name") or "").strip()
        if name:
            return name
        subject = (chat.get("subject") or "").strip()
        if subject:
            return subject
        group_meta = chat.get("groupMetadata")
        if isinstance(group_meta, dict):
            gm_subject = (group_meta.get("subject") or "").strip()
            if gm_subject:
                return gm_subject
        return ""

    def _is_bad_contact_name(self, name):
        from core.utils import is_phone_like, looks_like_binary_blob
        if not name or not isinstance(name, str):
            return True
        name = name.strip()
        return (
            not name
            or name.isdigit()
            or is_phone_like(name)
            or looks_like_binary_blob(name)
            or "sem nome" in name.lower()
            or "unknown" in name.lower()
            or name.lower() in ("no name", "desconhecido")
        )


class _Stub:
    _do_search = NewConversationDialog._do_search
    _name_is_usable = NewConversationDialog._name_is_usable
    _dedup_key = NewConversationDialog._dedup_key

    def __init__(self, mw):
        self._mw = mw
        self._results = []
        self._results_list = _FakeResultsList()


def _chat(jid, name):
    return {"remoteJid": jid, "name": name}


def _contact(jid, name):
    return {"id": jid, "remoteJid": jid, "name": name}


class TestEmptyQueryListsEverything:
    def test_empty_query_lists_all_contacts(self):
        mw = _FakeMw(
            contacts={"1@s.whatsapp.net": _contact("1@s.whatsapp.net", "Ana")}
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Ana"]
        assert stub._results_list.items == ["Ana"]

    def test_chats_and_contacts_are_all_sorted_together(self):
        mw = _FakeMw(
            chats={"9@s.whatsapp.net": _chat("9@s.whatsapp.net", "Grupo Família")},
            contacts={
                "1@s.whatsapp.net": _contact("1@s.whatsapp.net", "Ana"),
                "2@s.whatsapp.net": _contact("2@s.whatsapp.net", "Bia"),
            },
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Ana", "Bia", "Grupo Família"]

    def test_results_are_sorted_alphabetically(self):
        mw = _FakeMw(
            contacts={
                "3@s.whatsapp.net": _contact("3@s.whatsapp.net", "carlos"),
                "1@s.whatsapp.net": _contact("1@s.whatsapp.net", "Ana"),
                "2@s.whatsapp.net": _contact("2@s.whatsapp.net", "Bia"),
            }
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Ana", "Bia", "carlos"]

    def test_nameless_group_jid_is_filtered_out(self):
        """The reported bug: a group with no name resolved to its raw
        18-digit JID (e.g. 120363426112908706) via format_number()."""
        mw = _FakeMw(
            chats={
                "120363426112908706@g.us": _chat("120363426112908706@g.us", ""),
                "5@s.whatsapp.net": _chat("5@s.whatsapp.net", "Zé"),
            }
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Zé"]

    def test_named_group_shows_its_name_not_the_raw_jid(self):
        """A group WITH a name (name/subject/groupMetadata.subject) must
        appear under that name, sorted with the rest — not fall through to
        its raw 18-digit id."""
        jid = "120363000000000001@g.us"
        mw = _FakeMw(
            chats={
                jid: _chat(jid, "Família"),
                "1@s.whatsapp.net": _chat("1@s.whatsapp.net", "Ana"),
            }
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Ana", "Família"]

    def test_contact_with_only_a_phone_number_is_filtered_out(self):
        mw = _FakeMw(
            contacts={"5511999999999@s.whatsapp.net": _contact("5511999999999@s.whatsapp.net", "")}
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert stub._results == []
        assert stub._results_list.items == ["Sem resultados"]

    def test_contact_already_in_chats_is_not_duplicated(self):
        jid = "1@s.whatsapp.net"
        mw = _FakeMw(
            chats={jid: _chat(jid, "Ana")},
            contacts={jid: _contact(jid, "Ana")},
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Ana"]

    def test_cus_and_net_forms_of_the_same_contact_are_not_duplicated(self):
        """Same phone stored once as @c.us (chat) and once as @s.whatsapp.net
        (contact) must appear once — the raw JIDs differ but they're the
        same person."""
        mw = _FakeMw(
            chats={"5511999999999@c.us": _chat("5511999999999@c.us", "Bia")},
            contacts={"5511999999999@s.whatsapp.net": _contact("5511999999999@s.whatsapp.net", "Bia")},
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Bia"]

    def test_brazilian_8_vs_9_digit_forms_are_not_duplicated(self):
        """551199999999 vs 5511999999999 (the 9th-digit variant) identify the
        same number; both being present must yield a single row."""
        mw = _FakeMw(
            contacts={
                "551199999999@s.whatsapp.net": _contact("551199999999@s.whatsapp.net", "Carla"),
                "5511999999999@s.whatsapp.net": _contact("5511999999999@s.whatsapp.net", "Carla"),
            }
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Carla"]

    def test_lid_chat_and_phone_contact_are_not_duplicated(self):
        """A chat stored under @lid whose bridge maps back to a phone number
        that's also in contacts must not show up twice."""
        lid = "10000000000001@lid"
        phone = "5511999999999@s.whatsapp.net"
        mw = _FakeMw(
            chats={lid: _chat(lid, "Duda")},
            contacts={phone: _contact(phone, "Duda")},
            lid_to_phone={lid: phone},
        )
        stub = _Stub(mw)

        stub._do_search("")

        assert [n for n, _, _ in stub._results] == ["Duda"]

    def test_nothing_at_all_apends_no_results_row(self):
        stub = _Stub(_FakeMw())

        stub._do_search("")

        assert stub._results == []
        assert stub._results_list.items == ["Sem resultados"]


class TestFirstRowIsFocusedAndSelectedByDefault:
    """Reported live: the New Conversation dialog's results list opened with
    nothing focused/selected, unlike every other list in the app
    (conversations, messages), where the first row is always focused and
    selected by default. This is NOT about moving keyboard focus to the
    list — the search field keeps that, so typing isn't interrupted — only
    about the list's own internal focused/selected row state, so Tab-ing or
    arrowing into the list (or pressing Enter) immediately acts on row 0
    instead of nothing being highlighted at all."""

    def test_row_0_is_focused_and_selected_when_results_exist(self):
        mw = _FakeMw(contacts={"1@s.whatsapp.net": _contact("1@s.whatsapp.net", "Ana")})
        stub = _Stub(mw)

        stub._do_search("")

        assert stub._results_list.focus_calls == [0]
        assert stub._results_list.select_calls == [0]

    def test_nothing_is_focused_when_the_list_is_a_single_no_results_row(self):
        stub = _Stub(_FakeMw())

        stub._do_search("")

        assert stub._results_list.focus_calls == []
        assert stub._results_list.select_calls == []

    def test_row_0_is_refocused_after_typing_narrows_the_results(self):
        mw = _FakeMw(
            contacts={
                "1@s.whatsapp.net": _contact("1@s.whatsapp.net", "Ana"),
                "2@s.whatsapp.net": _contact("2@s.whatsapp.net", "Bia"),
            }
        )
        stub = _Stub(mw)

        stub._do_search("")
        stub._do_search("bia")

        assert stub._results_list.focus_calls == [0, 0]
        assert stub._results_list.select_calls == [0, 0]


class TestTypedQueryStillFilters:
    def test_typed_query_only_lists_matches(self):
        mw = _FakeMw(
            chats={"1@s.whatsapp.net": _chat("1@s.whatsapp.net", "Ana")},
            contacts={
                "2@s.whatsapp.net": _contact("2@s.whatsapp.net", "Bia"),
                "3@s.whatsapp.net": _contact("3@s.whatsapp.net", "Ana Paula"),
            },
        )
        stub = _Stub(mw)

        stub._do_search("ana")

        assert [n for n, _, _ in stub._results] == ["Ana", "Ana Paula"]

    def test_typed_query_excludes_non_matches(self):
        mw = _FakeMw(
            contacts={"2@s.whatsapp.net": _contact("2@s.whatsapp.net", "Bia")}
        )
        stub = _Stub(mw)

        stub._do_search("ana")

        assert stub._results == []
        assert stub._results_list.items == ["Sem resultados"]
