"""A rotated pairing code / QR must always reach the dialog.

Both refresh paths briefly carried a 15-second time cooldown, added to stop
"rapid, flickering updates". Suppressing by elapsed time is the wrong axis for
this particular screen, and it recreated the exact bug the code path exists to
prevent:

  * WhatsApp invalidates the previous pairing code (and the previous QR) the
    moment it issues a new one. A refresh dropped for arriving too soon leaves
    an expired credential on screen. update_pairing_code()'s own docstring
    spells out where that ends: the user types a stale code, pairing fails,
    they request another, and WhatsApp's anti-abuse eventually blocks the
    account.

  * The timestamps lived on the Connect instance, which outlives the dialog.
    Closing pairing and reopening it inside the cooldown meant the freshly
    built dialog got no code and no QR at all — an empty field and an empty
    image box, with a log line as the only clue.

Deduplicating on the *payload* removes the flicker with none of that: a
re-emitted identical code/QR is the only thing that can actually flicker, and a
genuinely new one is never withheld.
"""

import pytest

from ui.dialogs.connect import Connect


class _Field:
    """Stands in for the wx.TextCtrl holding the pairing code."""

    def __init__(self, value=""):
        self._value = value
        self.writes = []

    def GetValue(self):
        return self._value

    def ChangeValue(self, v):
        self._value = v
        self.writes.append(v)


class _Dial:
    def __init__(self, shown=True):
        self._shown = shown

    def __bool__(self):
        # A destroyed wx.Dialog is falsy; mirror that.
        return True

    def IsShown(self):
        return self._shown


class _Sound:
    def __init__(self):
        self.plays = 0

    def play(self):
        self.plays += 1


class _I18n:
    def t(self, key):
        return key


class _MainWindow:
    def __init__(self):
        self.pairing_code_updated_sound = _Sound()
        # What the screen reader actually speaks.
        self.spoken = []

    def output(self, text):
        self.spoken.append(text)


class _Stub:
    """Connect is not a wx window, but its collaborators are — bind only the
    method under test onto a plain object carrying what it touches."""

    update_pairing_code = Connect.update_pairing_code

    def __init__(self, current="", shown=True):
        self.pairing_dial = _Dial(shown)
        self.pairing_code_field = _Field(current)
        self.main_window = _MainWindow()
        self.i18n = _I18n()

    @property
    def sound_plays(self):
        return self.main_window.pairing_code_updated_sound.plays


class TestPairingCodeRefresh:
    def test_a_rotated_code_replaces_the_stale_one(self):
        s = _Stub(current="ABCD-1234")
        s.update_pairing_code("WXYZ-9876")
        assert s.pairing_code_field.GetValue() == "WXYZ-9876"

    def test_two_rotations_in_quick_succession_both_land(self):
        """The regression: the second was dropped for arriving inside the
        cooldown, leaving a code WhatsApp had already invalidated on screen."""
        s = _Stub(current="AAAA-1111")
        s.update_pairing_code("BBBB-2222")
        s.update_pairing_code("CCCC-3333")
        assert s.pairing_code_field.writes == ["BBBB-2222", "CCCC-3333"]

    def test_a_reopened_dialog_still_receives_a_code(self):
        """Nothing that decides this may outlive the dialog — a fresh dialog
        starts with an empty field and must be filled regardless of how
        recently the previous one was."""
        first = _Stub(current="")
        first.update_pairing_code("AAAA-1111")
        reopened = _Stub(current="")
        reopened.update_pairing_code("AAAA-1111")
        assert reopened.pairing_code_field.GetValue() == "AAAA-1111"

    def test_an_identical_re_emit_is_ignored(self):
        """The flicker this is allowed to suppress — and the screen-reader
        user hears no second announcement for a code that did not change."""
        s = _Stub(current="AAAA-1111")
        s.update_pairing_code("AAAA-1111")
        assert s.pairing_code_field.writes == []
        assert s.sound_plays == 0

    def test_a_real_rotation_is_announced(self):
        """The new code has to be spoken, not just written into a field the
        user is not focused on."""
        s = _Stub(current="AAAA-1111")
        s.update_pairing_code("BBBB-2222")
        assert s.sound_plays == 1
        assert any("BBBB-2222" in line for line in s.main_window.spoken)

    def test_an_empty_code_is_ignored(self):
        s = _Stub(current="AAAA-1111")
        s.update_pairing_code("")
        s.update_pairing_code(None)
        assert s.pairing_code_field.writes == []

    def test_nothing_is_written_when_there_is_no_dialog(self):
        s = _Stub(current="")
        s.pairing_dial = None
        s.update_pairing_code("AAAA-1111")
        assert s.pairing_code_field.writes == []

    def test_a_hidden_dialog_is_not_written_to(self):
        s = _Stub(current="", shown=False)
        s.update_pairing_code("AAAA-1111")
        assert s.pairing_code_field.writes == []


def test_neither_refresh_path_suppresses_by_elapsed_time():
    """Guard on the source itself, because the failure is invisible at runtime
    — a dropped rotation looks exactly like WhatsApp not having sent one."""
    import inspect

    src = inspect.getsource(Connect)
    for name in ("_last_qr_code_update_ts", "_last_phone_code_update_ts"):
        assert name not in src, (
            f"{name} is a time-based cooldown on a credential that expires when "
            f"it is replaced — dedupe on the payload instead (see this module's "
            f"docstring)"
        )
