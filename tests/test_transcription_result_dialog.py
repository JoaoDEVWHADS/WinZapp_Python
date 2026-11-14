"""The window a transcription is read in — its buttons, and what it says.

`TranscriptionResultDialog` is a wx.Dialog, which this suite may not put on the
desktop (tests/test_no_desktop_visible_windows.py), so its methods are bound
onto a stub carrying what they touch — the house pattern. The construction
itself is covered by tests/test_transcription_result_dialog_gui.py, which only
runs where a real dialog is allowed (CI).

What is pinned here is what a sighted tester would not notice:

* **The spoken sentence is queued before the dialog runs, not said before it
  appears** — said first, the screen reader's own announcement of the new
  window cancels it, and the voice-filter warning inside it is lost.
* **A failed save says so, once, without the path.** The folder the user
  picked may be named after the contact.
* **The saved file reads correctly in Notepad**: UTF-8 with a BOM and Windows
  line endings, for a text in whatever language was spoken.
* **The default file name is one Windows accepts** whatever the contact is
  called.
"""

import logging

from tests.locales import load_strings, registered_locale_codes
import pytest

from core.transcription import errors
from ui.dialogs import transcription_result
from ui.dialogs.transcription_result import TranscriptionResultDialog


class _I18n:
    def t(self, key):
        return {
            "transcription_save_default_name": "Transcrição - {name}",
        }.get(key, key)


class _Speech:
    def __init__(self):
        self.spoken = []

    def output(self, text, interrupt=False):
        assert not interrupt
        self.spoken.append(text)


class _MainWindow:
    def __init__(self):
        self.i18n = _I18n()
        self.speak_output = _Speech()
        self.settings = {}
        self.remembered = []
        self.error_sound = type("S", (), {"played": 0, "play": lambda s: setattr(s, "played", s.played + 1)})()

    def remember_save_folder(self, path):
        self.remembered.append(path)


class _Dialog:
    """TranscriptionResultDialog's methods over plain attributes."""

    def __init__(self, text="olá, mundo\nsegunda linha", spoken="dito"):
        self._main_window = _MainWindow()
        self._i18n = self._main_window.i18n
        self._text = text
        self._spoken = spoken
        self.insert_requested = False
        self.ended = None
        self.events = []
        self.alive = True

    def __bool__(self):
        return self.alive

    def ShowModal(self):
        self.events.append("ShowModal")
        return 5101

    def EndModal(self, code):
        self.ended = code

    run = TranscriptionResultDialog.run
    _announce = TranscriptionResultDialog._announce
    _on_copy = TranscriptionResultDialog._on_copy
    _save_to = TranscriptionResultDialog._save_to
    _on_insert = TranscriptionResultDialog._on_insert


@pytest.fixture
def posted(monkeypatch):
    calls = []
    monkeypatch.setattr(transcription_result.wx, "CallAfter",
                        lambda func, *a, **k: calls.append(func))
    return calls


class TestWhatIsSpoken:
    def test_it_is_queued_before_the_dialog_runs_and_said_from_inside_it(self, posted):
        dialog = _Dialog()
        dialog._main_window.speak_output.output = (
            lambda text, interrupt=False: dialog.events.append(("spoken", text)))
        assert dialog.run() == 5101
        # Queued, not said: nothing reached the screen reader before the window.
        assert dialog.events == ["ShowModal"]
        assert posted == [dialog._announce]
        posted[0]()
        assert dialog.events == ["ShowModal", ("spoken", "dito")]

    def test_nothing_is_queued_when_there_is_nothing_to_say(self, posted):
        dialog = _Dialog(spoken="")
        dialog.run()
        assert posted == []

    def test_a_dialog_already_gone_says_nothing(self):
        dialog = _Dialog()
        dialog.alive = False
        dialog._announce()
        assert dialog._main_window.speak_output.spoken == []


class TestTheButtons:
    def test_copy_puts_the_text_on_the_clipboard_and_says_so(self, monkeypatch):
        copied = []
        monkeypatch.setattr(transcription_result.pyperclip, "copy", copied.append)
        dialog = _Dialog()
        dialog._on_copy()
        assert copied == [dialog._text]
        assert dialog._main_window.speak_output.spoken == ["transcription_result_copied"]

    def test_a_clipboard_that_refuses_is_said(self, monkeypatch):
        def _refuse(text):
            raise RuntimeError("clipboard locked by another program")

        monkeypatch.setattr(transcription_result.pyperclip, "copy", _refuse)
        dialog = _Dialog()
        dialog._on_copy()
        assert dialog._main_window.speak_output.spoken == ["transcription_result_copy_failed"]

    def test_insert_ends_the_dialog_and_leaves_the_writing_to_the_caller(self):
        dialog = _Dialog()
        dialog._on_insert()
        assert dialog.insert_requested is True
        assert dialog.ended == transcription_result.wx.ID_OK


class TestSaving:
    def test_the_file_reads_right_in_notepad(self, tmp_path):
        dialog = _Dialog(text="Zażółć gęślą jaźń\nsegunda linha")
        target = tmp_path / "t.txt"
        assert dialog._save_to(str(target)) is True
        raw = target.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" in raw
        assert raw.decode("utf-8-sig").replace("\r\n", "\n") == dialog._text
        assert dialog._main_window.remembered == [str(target)]
        assert dialog._main_window.speak_output.spoken == ["transcription_result_saved"]

    def test_a_save_that_fails_is_said_once_and_names_no_path(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG)
        folder = tmp_path / "Ana Souza"
        folder.mkdir()
        dialog = _Dialog()
        # A directory where the file should go: open() refuses it.
        assert dialog._save_to(str(folder)) is False
        assert dialog._main_window.speak_output.spoken == [
            errors.error_i18n_key(errors.SAVE_FAILED)]
        assert dialog._main_window.error_sound.played == 1
        assert dialog._main_window.remembered == []
        assert "Ana Souza" not in caplog.text
        assert str(tmp_path) not in caplog.text

    def test_a_sound_that_raises_does_not_cost_the_sentence(self, tmp_path, caplog):
        """docs/traps/audio-devices.md: the output device may be gone, and
        the sentence is the only thing that says the file was not written."""
        caplog.set_level(logging.DEBUG)
        folder = tmp_path / "Ana Souza"
        folder.mkdir()
        dialog = _Dialog()

        class _Raising:
            def play(self):
                raise RuntimeError("5, invalid handle")

        dialog._main_window.error_sound = _Raising()
        assert dialog._save_to(str(folder)) is False
        assert dialog._main_window.speak_output.spoken == [
            errors.error_i18n_key(errors.SAVE_FAILED)]
        assert "could not play the error sound" in caplog.text
        # Raised inside the OSError's handler, the sound's exception carries
        # that OSError — and the chosen path — as its __context__.
        assert "Ana Souza" not in caplog.text
        assert str(tmp_path) not in caplog.text


class TestFileNames:
    @pytest.mark.parametrize("name", ['Ana / trabalho', 'a:b*c?"d<e>f|g', "   ", "x" * 300])
    def test_the_default_name_is_one_windows_accepts(self, name):
        result = transcription_result.default_file_name(_I18n(), name)
        stem = result[:-4]
        assert result.endswith(".txt")
        assert not set('<>:"/\\|?*') & set(stem)
        assert stem == stem.strip(" .")
        assert len(stem) <= 80

    @pytest.mark.parametrize("locale", registered_locale_codes())
    def test_no_name_is_the_word_alone_not_a_dangling_dash(self, locale):
        """A message whose sender resolves to nothing readable: the pattern's
        separator has nothing after it, and "Transcrição -.txt" is both an
        odd file name and an odd thing to hear."""
        table = load_strings(locale)

        class _Locale:
            def t(self, key):
                return table.get(key, key)

        word = table["transcription_save_default_name"].split("{name}")[0].strip(" -")
        assert transcription_result.default_file_name(_Locale(), "") == f"{word}.txt"

    def test_a_pattern_with_nothing_usable_falls_back_to_the_translated_word(self):
        """Never an English literal: a Polish user would be offered a file
        named in a language they did not choose."""
        class _Odd:
            def t(self, key):
                return {"transcription_save_default_name": "// {name} ??",
                        "transcription_progress_title": "Transkrypcja"}[key]

        assert transcription_result.default_file_name(_Odd(), "") == "Transkrypcja.txt"

    def test_two_sentences_with_nothing_usable_still_give_a_name(self):
        """".txt" alone is a nameless hidden file, read out as "dot t x t"."""
        class _Blank:
            def t(self, key):
                return {"transcription_save_default_name": "// {name} ??",
                        "transcription_progress_title": " ... "}[key]

        assert transcription_result.default_file_name(_Blank(), "") == "WinZapp.txt"

    def test_a_typed_name_without_an_extension_gets_txt(self):
        assert transcription_result.with_txt_extension(r"C:\x\nota") == r"C:\x\nota.txt"
        assert transcription_result.with_txt_extension(r"C:\x\nota.md") == r"C:\x\nota.md"
