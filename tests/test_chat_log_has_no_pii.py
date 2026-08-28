"""Tests that the @lid chat diagnostic logs shape, not content.

`get_remote_chats()` carried a leftover diagnostic that logged the whole first
@lid chat object it saw. A WPPConnect chat object contains the contact's name
and pushname, their LID, and signed profile-photo URLs — and it landed in
`log.log` 42 times in one ordinary session.

That matters more than its size (134 KB of a 5 MB log): CLAUDE.md instructs
anyone diagnosing a startup or pairing problem to ask the user for that exact
file. Every such request was therefore also asking them to hand over a slice of
their address book, to whoever was helping.

The shape — key names and value types — is the part that was ever useful for
debugging LID handling, and it carries nothing personal.
"""

import inspect

from main import MainWindow


def _source():
    return inspect.getsource(MainWindow.get_remote_chats)


class TestNoRawChatObjectIsLogged:
    def test_the_raw_dump_is_gone(self):
        assert "RAW LID CHAT DATA" not in _source()

    def test_no_log_call_interpolates_a_whole_chat(self):
        """`lid_chats[0]` is the object itself. Formatting it into a log line
        in any form — %s, f-string, or str() — puts the whole thing on disk."""
        source = _source()
        for line in source.splitlines():
            if "logging." not in line:
                continue
            assert "lid_chats[0]}" not in line, line
            assert "lid_chats[0])" not in line, line
            assert ", lid_chats[0]" not in line, line

    def test_the_shape_is_still_logged(self):
        """The diagnostic keeps its value: this exists so a future change to
        WPPConnect's @lid chat payload is visible in a user's log."""
        source = _source()
        assert "@lid chat shape" in source
        assert "type(v).__name__" in source


class TestTheShapeItselfCarriesNothingPersonal:
    def test_it_maps_keys_to_type_names_only(self):
        """Reproduces what the logged expression builds, to prove no value
        survives into it."""
        chat = {
            "remoteJid": "20791953461282@lid",
            "name": "Bruna",
            "pushName": "Bruna 🧜",
            "contact": {"formattedName": "Bruna"},
            "profilePicThumbObj": {"eurl": "https://pps.whatsapp.net/v/t61..."},
            "t": 1787852459,
            "isGroup": False,
        }

        shape = {k: type(v).__name__ for k, v in chat.items()}

        assert shape == {
            "remoteJid": "str",
            "name": "str",
            "pushName": "str",
            "contact": "dict",
            "profilePicThumbObj": "dict",
            "t": "int",
            "isGroup": "bool",
        }

        rendered = str(shape)
        for secret in ("Bruna", "20791953461282", "pps.whatsapp.net", "1787852459"):
            assert secret not in rendered

    def test_the_shape_is_built_from_the_chats_own_keys(self):
        """The fix rests on the keys being WPPConnect's fixed field
        vocabulary rather than user data. Building the map from .items() is
        what keeps it that way; anything deriving entries from values would
        put content back in the log."""
        shape_line = next(
            line for line in _source().splitlines() if "type(v).__name__" in line
        )
        assert ".items()" in shape_line
