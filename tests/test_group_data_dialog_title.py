"""The group-data dialog's title follows a rename made from inside it.

The title is built once, in __init__, from the name the chat had when the
dialog opened. Renaming the group from that very dialog's "edit group name"
action left the title still announcing the old name for as long as the dialog
stayed open — and a screen reader re-reads the window title on every focus
change, so the stale name is heard again and again while the field right below
it already shows the new one.

The retitle is applied from _populate_group_unsafe() rather than from the edit
handler, for two reasons: every refresh passes through there (including the
one _run_group_edit() fires after a successful save), and the value available
there is the subject the server just confirmed rather than whatever was typed
into the prompt.

ConversationDataDialog is a wx.Dialog and cannot be instantiated without a
running wx.App, so the two title methods are bound to a stub — the same
approach as tests/test_message_bookmarks.py. The call site inside
_populate_group_unsafe() (which builds real wx widgets) is checked
structurally instead, as tests/test_group_data_dialog_admin_ui.py already does
for that method.
"""

import inspect

import pytest

from ui.dialogs.conversation_data_dialog import ConversationDataDialog


class _FakeI18n:
    _STRINGS = {
        "group_data": "Dados do grupo",
        "conversation_data": "Dados da conversa",
    }

    def t(self, key):
        return self._STRINGS[key]


class _Dialog:
    _dialog_title = ConversationDataDialog._dialog_title
    _apply_subject_to_title = ConversationDataDialog._apply_subject_to_title

    def __init__(self, name, is_group=True):
        self._i18n = _FakeI18n()
        self._is_group = is_group
        self._name = name
        self.titles = []

    def SetTitle(self, title):
        self.titles.append(title)


class TestTheTitleFormat:
    def test_a_group_puts_the_name_before_the_boilerplate(self):
        """NVDA announces the title on every focus change — whose data this
        is has to come first, or the user hears "Dados do grupo" repeatedly
        before ever reaching the part that differs."""
        assert _Dialog("Equipe")._dialog_title("Equipe") == "Equipe | Dados do grupo"

    def test_a_one_to_one_chat_uses_the_conversation_wording(self):
        dlg = _Dialog("Fulano", is_group=False)
        assert dlg._dialog_title("Fulano") == "Fulano | Dados da conversa"


class TestRetitlingAfterARename:
    def test_a_new_subject_retitles_the_dialog(self):
        dlg = _Dialog("Nome Antigo")
        dlg._apply_subject_to_title("Nome Novo")
        assert dlg.titles == ["Nome Novo | Dados do grupo"]

    def test_the_tracked_name_is_updated_too(self):
        """_name backs the next title build; leaving it stale would make a
        second rename in the same session compare against the wrong value."""
        dlg = _Dialog("Nome Antigo")
        dlg._apply_subject_to_title("Nome Novo")
        assert dlg._name == "Nome Novo"

    def test_two_renames_in_a_row_both_land(self):
        dlg = _Dialog("A")
        dlg._apply_subject_to_title("B")
        dlg._apply_subject_to_title("C")
        assert dlg.titles == ["B | Dados do grupo", "C | Dados do grupo"]

    def test_the_same_subject_does_not_retitle(self):
        """Every data refresh calls this, not just the ones after a rename —
        re-setting an identical title would make some screen readers announce
        the window again for no reason."""
        dlg = _Dialog("Equipe")
        dlg._apply_subject_to_title("Equipe")
        assert dlg.titles == []

    @pytest.mark.parametrize("empty", ["", None])
    def test_an_empty_subject_never_blanks_the_title(self, empty):
        """get_group_info() can answer without a subject; falling back to a
        bare " | Dados do grupo" would leave the dialog unidentifiable."""
        dlg = _Dialog("Equipe")
        dlg._apply_subject_to_title(empty)
        assert dlg.titles == []
        assert dlg._name == "Equipe"


class TestItIsWiredIntoTheRefresh:
    """_populate_group_unsafe() builds real wx widgets, so the wiring is
    checked by inspection — same convention as the admin-UI tests."""

    def test_the_refresh_applies_the_subject_to_the_title(self):
        src = inspect.getsource(ConversationDataDialog._populate_group_unsafe)
        assert "self._apply_subject_to_title(subject)" in src

    def test_it_uses_the_subject_the_server_confirmed(self):
        """Not the string typed into the rename prompt: a save that the
        server silently altered (trimmed, length-capped) would otherwise put
        a name in the title that the group does not actually have."""
        src = inspect.getsource(ConversationDataDialog._populate_group_unsafe)
        assert 'subject  = data.get("subject") or self._name' in src

    def test_a_successful_rename_triggers_that_refresh(self):
        src = inspect.getsource(ConversationDataDialog._run_group_edit)
        assert "self._fetch_data" in src

    def test_the_title_is_built_through_the_shared_helper(self):
        """__init__ and the retitle must not drift into two formats."""
        src = inspect.getsource(ConversationDataDialog.__init__)
        assert "self._dialog_title(name)" in src
