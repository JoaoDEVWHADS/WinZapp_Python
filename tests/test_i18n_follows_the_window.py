"""Every I18n instance speaks the language the window shows.

The language setting is install-wide: another account changing it reaches this
window's settings copy on its next save, while the window keeps the language it
shows until the user applies one (MainWindow._apply_pulled_global_settings()).
The tray, the notification manager, the WebSocket client and a few dialogs keep
I18n instances of their own and refresh them with get_language(), which read
the settings -- so they switched by themselves: toasts and tray menus in the
new language over a window still in the old one. The updater did the same on
the window's own instance, switching every string drawn after it -- and so
did the AI result dialog, asking it which language the answer should be in.
"""

import ast
import collections
import os
import pathlib

from core.i18n import I18n

_CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"

# Top-level folders of client/ that are not WinZapp's own Python: the venv
# route's virtualenv, the vendored WPPConnect Server clone and the portable
# Node runtime (all git-ignored; any of them may be absent).
_NOT_OUR_SOURCE = {"venv", "api", "node"}

# Every place in client/ that names get_language(), as
# {file: {enclosing function: how many}}. Nothing in the source tells the
# window's own instance from a helper's (dialogs keep `main_window.i18n` under
# their own `self.i18n`), so the whole list is closed: a new one fails
# test_nobody_else_asks_it_behind_the_windows_back() until somebody has decided
# which of the two below it is.

# On the window's own instance (`main_window.i18n`), where the call reads the
# settings: only where a language is being applied to the whole window, each
# one followed by apply_language_changes() -- or, at startup, by the UI being
# built in it.
_APPLIES_A_LANGUAGE = {
    "main.py": {"MainWindow.__init__": 1},
    "main_window/settings.py": {
        # A language another account chose, once the window may repaint.
        "SettingsMixin._apply_pending_language_switch": 1,
        # A settings import that carried a language.
        "SettingsMixin.apply_settings_live._reload_language": 1,
    },
    # The Settings dialog's OK, when its language choice changed.
    "ui/dialogs/settings_dialog.py": {"SettingsDialog._apply_values": 1},
}

# On an I18n the caller built for itself, where the call follows the window
# (or, before MainWindow.i18n exists, reads the settings there are).
_ON_ITS_OWN_INSTANCE = {
    "core/i18n.py": {"I18n.t": 1},  # not the window's instance once it was read
    "core/notification_manager.py": {
        "NotificationManager.__init__": 1,
        "NotificationManager._announce_unshown": 1,
        "NotificationManager._dispatch": 1,
        "NotificationManager.refresh_language": 1,
    },
    "core/tray_manager.py": {
        "TrayIcon.__init__": 1,
        "TrayIcon.refresh_labels": 1,
        "TrayIcon.update_tooltip": 1,
    },
    "core/websocket_client.py": {"WebSocketClient.__init__": 1},
    # No window at all: the messages shown before MainWindow exists.
    "startup_i18n.py": {"startup_i18n": 1},
    "ui/dialogs/api_startup.py": {"ApiStartupDialog.__init__": 1},
    # Built by MainWindow.__init__ one line before MainWindow.i18n.
    "ui/dialogs/connect.py": {"Connect.__init__": 1},
}


def _get_language_references():
    """{file: {enclosing function: how many}} for every `<x>.get_language` in
    client/ -- a call, or the method handed around to be called later."""
    found = {}
    for root, dirs, files in os.walk(_CLIENT):
        if pathlib.Path(root) == _CLIENT:
            # Pruned, not filtered: api/ and node/ hold node_modules.
            dirs[:] = [name for name in dirs if name not in _NOT_OUR_SOURCE]
        for name in files:
            if not name.endswith((".py", ".pyw")):
                continue
            path = pathlib.Path(root, name)
            text = path.read_text(encoding="utf-8")
            if "get_language" not in text:
                continue  # parsing all of client/ is what would cost time
            references = collections.Counter()
            pending = [(ast.parse(text, filename=str(path)), ())]
            while pending:
                node, scope = pending.pop()
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = scope + (node.name,)
                elif isinstance(node, ast.Attribute) and node.attr == "get_language":
                    references[".".join(scope) or "<module>"] += 1
                pending.extend((child, scope) for child in ast.iter_child_nodes(node))
            if references:
                found[path.relative_to(_CLIENT).as_posix()] = dict(references)
    return found


class _Window:
    def __init__(self, language):
        self.settings = {"general": {"language": language}}


def _window_showing(language):
    window = _Window(language)
    window.i18n = I18n(window)
    window.i18n.get_language()
    return window


class TestAHelperFollowsTheWindow:
    def test_not_the_settings_another_account_changed(self):
        window = _window_showing("pt-BR")
        window.settings["general"]["language"] = "en-US"  # pulled

        helper = I18n(window)

        assert helper.get_language() == "pt-BR"
        assert helper.language == "pt-BR"

    def test_and_moves_when_the_window_applies_a_language(self):
        window = _window_showing("pt-BR")
        helper = I18n(window)
        helper.get_language()

        window.settings["general"]["language"] = "es-ES"
        window.i18n.get_language()  # the Settings dialog's OK, an import

        assert helper.get_language() == "es-ES"

    def test_before_the_window_has_one_it_reads_the_settings(self):
        """Early startup: Connect is built before MainWindow.i18n exists."""
        window = _Window("pl")

        assert I18n(window).get_language() == "pl"


class TestAHelperLookup:
    """t() refreshes the language itself (an I18n starts at pt-BR and used to
    stay there until someone called get_language()). For a helper, refreshing
    is following the window."""

    def test_is_in_the_windows_language_without_anyone_asking(self):
        window = _window_showing("en-US")
        helper = I18n(window)  # still at its pt-BR default

        assert helper.t("no_pairing_code_received").startswith("Could not connect")

    def test_and_not_in_a_language_the_window_has_not_applied(self):
        window = _window_showing("en-US")
        helper = I18n(window)
        english = helper.t("no_pairing_code_received")
        window.settings["general"]["language"] = "pt-BR"  # pulled

        assert helper.t("no_pairing_code_received") == english


class TestTheWindowsOwnInstance:
    def test_reads_the_settings_when_asked(self):
        window = _window_showing("pt-BR")
        window.settings["general"]["language"] = "en-US"

        assert window.i18n.get_language() == "en-US"

    def test_a_lookup_is_not_asking(self):
        """Or the window's strings switch one at a time, each as it is drawn,
        and MainWindow._apply_pending_language_switch() finds the language
        "already applied" and never repaints the rest."""
        window = _window_showing("pt-BR")
        portuguese = window.i18n.t("no_pairing_code_received")
        window.settings["general"]["language"] = "en-US"  # pulled

        assert window.i18n.t("no_pairing_code_received") == portuguese
        assert window.i18n.language == "pt-BR"

    def test_a_lookup_before_it_was_ever_asked_reads_the_settings(self):
        """The one lookup that does: nobody called get_language() yet, and
        the alternative is the pt-BR default on an English install."""
        window = _Window("en-US")
        window.i18n = I18n(window)

        assert window.i18n.t("no_pairing_code_received").startswith("Could not connect")
        assert window.i18n.language == "en-US"

    def test_nobody_else_asks_it_behind_the_windows_back(self):
        """The updater did, for the changelog's language, and the AI result
        dialog, for the answer's: both hold `main_window.i18n` itself, and what
        they wanted is its `language` attribute -- the one the window shows.
        Structural, with no behaviour to call: the next caller does not exist
        yet. A failure here means deciding which list the new call belongs to,
        or reading `.language` instead."""
        assert not set(_APPLIES_A_LANGUAGE) & set(_ON_ITS_OWN_INSTANCE)

        assert _get_language_references() == {**_APPLIES_A_LANGUAGE, **_ON_ITS_OWN_INSTANCE}
