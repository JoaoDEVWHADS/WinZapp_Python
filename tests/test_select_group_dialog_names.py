"""Tests for SelectGroupDialog._populate_groups() (ui/dialogs/add_member_dialog.py).

Reported live: opening a private conversation's data and clicking "add to
group" showed every group in the picker as a raw number instead of its
name. _resolve_contact_name() always returns None for a group — it's
address-book lookup, and groups have no such entry (see its own docstring)
— so the old fallback chain (_resolve_contact_name -> find_name_through_
messages -> pushName -> bare JID) never had anything useful to try before
the group JID and fell straight to that last resort every time. A group's
real name lives under groupMetadata.subject in the raw chat dict, resolved
everywhere else via MainWindow._group_name_from_chat_dict() — this dialog
just never called it.

SelectGroupDialog is a wx.Dialog and can't be instantiated without a
running wx.App; _populate_groups() is bound onto a plain stub carrying fake
_list/_ok_btn widgets, same approach used throughout this suite.
"""

from ui.dialogs.add_member_dialog import SelectGroupDialog


class _FakeList:
    def __init__(self):
        self.items = []

    def GetItemCount(self):
        return len(self.items)

    def InsertItem(self, idx, text):
        self.items.insert(idx, text)


class _FakeButton:
    def __init__(self):
        self.enabled = True

    def Disable(self):
        self.enabled = False

    def Enable(self):
        self.enabled = True


class _FakeI18n:
    def t(self, key):
        return f"[{key}]"


class _FakeMainWindow:
    _group_name_from_chat_dict = staticmethod(
        __import__("main").MainWindow._group_name_from_chat_dict
    )

    def __init__(self, chats, group_name_cache=None):
        self.chats = chats
        self.settings = {}
        self._group_name_cache = group_name_cache or {}

    def _resolve_contact_name(self, chat):
        # Real implementation always returns None for a group — reproduced
        # here rather than importing MainWindow's, since that one needs a
        # live main-window instance for its @lid/contact lookups.
        return None

    def find_name_through_messages(self, chat):
        return chat.get("_messages_derived_name", "")


class _Stub:
    _populate_groups = SelectGroupDialog._populate_groups

    def __init__(self, mw):
        self._mw = mw
        self._i18n = _FakeI18n()
        self._list = _FakeList()
        self._ok_btn = _FakeButton()


class TestSelectGroupDialogNameResolution:
    def test_group_with_metadata_subject_shows_its_real_name(self):
        chat = {
            "remoteJid": "123456789@g.us",
            "groupMetadata": {"subject": "Familia"},
        }
        mw = _FakeMainWindow({"123456789@g.us": chat})
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["Familia"]
        assert stub._group_jids == ["123456789@g.us"]

    def test_group_with_flat_name_field_shows_its_real_name(self):
        chat = {"remoteJid": "123456789@g.us", "name": "Trabalho"}
        mw = _FakeMainWindow({"123456789@g.us": chat})
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["Trabalho"]

    def test_group_never_falls_back_to_the_raw_jid_when_metadata_available(self):
        """The bug: every group used to render as its bare numeric JID."""
        chat = {
            "remoteJid": "551199999999-1234567890@g.us",
            "groupMetadata": {"subject": "Amigos do Trabalho"},
        }
        mw = _FakeMainWindow({"551199999999-1234567890@g.us": chat})
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["Amigos do Trabalho"]
        assert stub._list.items != ["551199999999-1234567890"]

    def test_falls_back_to_the_group_name_cache_when_no_metadata_present(self):
        chat = {"remoteJid": "123456789@g.us"}
        mw = _FakeMainWindow(
            {"123456789@g.us": chat},
            group_name_cache={"123456789@g.us": "Cached Group"},
        )
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["Cached Group"]

    def test_falls_back_to_bare_jid_only_as_a_last_resort(self):
        chat = {"remoteJid": "123456789@g.us"}
        mw = _FakeMainWindow({"123456789@g.us": chat})
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["123456789"]

    def test_non_group_chats_are_excluded(self):
        chats = {
            "5511999999999@s.whatsapp.net": {"remoteJid": "5511999999999@s.whatsapp.net", "name": "Fulano"},
            "123456789@g.us": {"remoteJid": "123456789@g.us", "name": "Grupo"},
        }
        mw = _FakeMainWindow(chats)
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["Grupo"]
        assert stub._group_jids == ["123456789@g.us"]

    def test_deleted_groups_are_excluded(self):
        chat = {"remoteJid": "123456789@g.us", "name": "Grupo Apagado"}
        mw = _FakeMainWindow({"123456789@g.us": chat})
        mw.settings = {"deleted_chats": ["123456789@g.us"]}
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._group_jids == []
        assert stub._list.items == ["[no_groups_available]"]

    def test_no_groups_at_all_shows_placeholder_and_disables_ok(self):
        mw = _FakeMainWindow({})
        stub = _Stub(mw)

        stub._populate_groups()

        assert stub._list.items == ["[no_groups_available]"]
        assert stub._ok_btn.enabled is False
