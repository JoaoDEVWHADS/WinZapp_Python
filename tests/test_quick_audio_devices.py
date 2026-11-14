"""Quick switch between audio devices: Ctrl+Alt+Shift+H (playback) and
Ctrl+Alt+Shift+G (recording), then a digit.

Win+digit combinations were ruled out first: every Win / Win+Alt / Win+Ctrl /
Win+Shift + 1..0 is registered by Explorer for the taskbar (RegisterHotKey
answers 1409, ERROR_HOTKEY_ALREADY_REGISTERED). Alt+8/Alt+9 are kept for
communities and channels. The switch lasts this session only (nothing is
saved), covers the general and the call devices, and is passed on to every
other open account over IPC. Nothing here opens a window.
"""

import copy
import inspect
import json
import types

import pytest
import wx

import ipc
import main_window.quick_audio_devices as quick_mod
from core.quick_audio_devices import (
    DIGIT_SLOTS,
    KIND_INPUT,
    KIND_OUTPUT,
    digit_for_slot,
    quick_device_rows,
    slot_for_digit,
)
from main import MainWindow
from tests.god_modules import main_window_method_source
from ui.dialogs.quick_audio_device_dialog import QuickAudioDeviceDialog, typed_digit


# ── The list ──────────────────────────────────────────────────────────────────


def test_digits_follow_the_keyboard_row():
    assert [digit_for_slot(s) for s in range(10)] == list("1234567890")
    assert [slot_for_digit(d) for d in "1234567890"] == list(range(10))
    assert slot_for_digit("x") is None
    assert slot_for_digit("12") is None


def test_rows_number_ten_devices_then_the_default():
    names = [f"Dev {i}" for i in range(12)]
    rows, focus = quick_device_rows(names, "Dev 2", "Padrão", "(em uso)")
    labels = [label for label, _ in rows]
    assert labels[0] == "1. Dev 0"
    assert labels[2] == "3. Dev 2 (em uso)"
    assert labels[9] == "0. Dev 9"
    assert labels[10] == "Dev 10"          # past the tenth: no digit
    assert rows[-1] == ("Padrão", "")       # default last, value ""
    assert focus == 2
    assert DIGIT_SLOTS == 10


def test_the_default_is_marked_when_it_is_in_use():
    rows, focus = quick_device_rows(["A", "B"], "", "Padrão", "(em uso)")
    assert rows[-1] == ("Padrão (em uso)", "")
    assert focus == len(rows) - 1


def test_a_saved_device_that_is_unplugged_reads_as_the_default():
    """WinZapp is on the system default then, so that is what is in use."""
    rows, focus = quick_device_rows(["A", "B"], "Fone USB", "Padrão", "(em uso)")
    assert not any("(em uso)" in label for label, _ in rows[:-1])
    assert rows[focus] == ("Padrão (em uso)", "")


# ── The dialog's keys (a stub, never a window) ─────────────────────────────────


def test_typed_digit_reads_top_row_and_keypad():
    assert typed_digit(ord("3")) == "3"
    assert typed_digit(ord("0")) == "0"
    assert typed_digit(wx.WXK_NUMPAD7) == "7"
    assert typed_digit(ord("A")) is None


class _DialogStub:
    _on_char_hook = QuickAudioDeviceDialog._on_char_hook

    def __init__(self, rows, selected=0):
        self._rows = rows
        self.picked = []
        self.list = types.SimpleNamespace(GetSelection=lambda: selected)

    def _pick(self, index):
        self.picked.append(index)


def _key(code, modifiers=False):
    ev = types.SimpleNamespace(skipped=False)
    ev.GetKeyCode = lambda: code
    ev.HasAnyModifiers = lambda: modifiers
    ev.Skip = lambda: setattr(ev, "skipped", True)
    return ev


class TestDialogKeys:
    ROWS, _ = quick_device_rows(["A", "B", "C"], "A", "Padrão", "(em uso)")

    def test_a_digit_picks_its_device_at_once(self):
        d = _DialogStub(self.ROWS)
        d._on_char_hook(_key(ord("2")))
        assert d.picked == [1]

    def test_a_digit_with_no_device_behind_it_does_nothing(self):
        """"4" would land on the default row, which has no digit."""
        d = _DialogStub(self.ROWS)
        ev = _key(ord("4"))
        d._on_char_hook(ev)
        assert d.picked == [] and ev.skipped

    def test_enter_picks_the_focused_row(self):
        d = _DialogStub(self.ROWS, selected=3)
        d._on_char_hook(_key(wx.WXK_RETURN))
        assert d.picked == [3]

    def test_modified_keys_and_arrows_pass_through(self):
        d = _DialogStub(self.ROWS)
        for ev in (_key(ord("2"), modifiers=True), _key(wx.WXK_DOWN)):
            d._on_char_hook(ev)
            assert ev.skipped
        assert d.picked == []


# ── Applying the choice: this session only, every open account ─────────────


class _SoundSystem:
    def __init__(self, ok=True):
        self.ok = ok
        self.applied = []

    def apply_output_device(self, name, warn_on_failure=False):
        self.applied.append(name)
        return self.ok if name == "Novo" else True

    def apply_effects_device(self, name, warn_on_failure=False):
        self.applied.append(("effects", name))
        return True


SAVED = {"audio_devices": {"output_device_name": "Antigo", "input_device_name": "Mic antigo"},
         "call_audio_devices": {"output_device_name": "Fone de ligação",
                                "input_device_name": "Mic de ligação"}}


class _Stub:
    apply_quick_audio_device = MainWindow.apply_quick_audio_device
    open_quick_audio_devices = MainWindow.open_quick_audio_devices
    current_audio_device = MainWindow.current_audio_device
    call_audio_device = MainWindow.call_audio_device
    _session_audio_device = MainWindow._session_audio_device
    _session_call_audio_device = MainWindow._session_call_audio_device
    end_session_audio_devices = MainWindow.end_session_audio_devices
    _ipc_audio_device = MainWindow._ipc_audio_device

    def __init__(self, sound_ok=True, in_call=False):
        self.settings = copy.deepcopy(SAVED)
        self.i18n = types.SimpleNamespace(
            t=lambda k: {"audio_device_default": "Padrão"}.get(k, k + "{device}"))
        self.sound_system = _SoundSystem(sound_ok)
        self._call_audio_session = object() if in_call else None
        self.events = []
        self.passed_on = []

    def load_sounds(self):
        self.events.append("load_sounds")

    def save_settings(self):
        self.events.append("save")

    def _restart_active_voice_call_audio(self):
        self.events.append("restart_call")

    def output(self, text, interrupt=False):
        self.events.append(("say", text))

    def _pass_audio_device_to_other_accounts(self, kind, name):
        self.passed_on.append((kind, name))


class TestSessionOnly:
    def test_output_switches_live_and_reloads_sounds(self):
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_OUTPUT, "Novo") is True
        assert s.sound_system.applied == ["Novo", ("effects", "Novo")]
        assert "load_sounds" in s.events      # docs/traps/audio-devices.md
        assert ("say", "quick_audio_output_setNovo") in s.events

    def test_effect_sounds_follow_unless_a_device_was_chosen_for_them(self):
        """Effects are pinned to a device of their own; set to follow the
        system default they follow the switch, chosen on purpose they stay."""
        s = _Stub()
        s.settings["audio_devices"]["effects_output_device_name"] = "Caixa de som"
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert s.sound_system.applied == ["Novo"]

    def test_nothing_is_saved(self):
        """The next launch starts on Settings' choice again."""
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert s.settings == SAVED
        assert "save" not in s.events

    def test_the_session_choice_is_what_is_in_use_and_what_calls_open(self):
        s = _Stub()
        assert s.current_audio_device(KIND_OUTPUT) == "Antigo"
        assert s.call_audio_device(KIND_OUTPUT) == "Fone de ligação"
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert s.current_audio_device(KIND_OUTPUT) == "Novo"
        assert s.call_audio_device(KIND_OUTPUT) == "Novo"
        # The other kind still follows the saved settings.
        assert s.call_audio_device(KIND_INPUT) == "Mic de ligação"

    def test_the_system_default_is_a_real_override(self):
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "")
        assert s.current_audio_device(KIND_OUTPUT) == ""
        assert s.call_audio_device(KIND_OUTPUT) == ""

    def test_an_output_that_will_not_open_changes_nothing(self):
        s = _Stub(sound_ok=False)
        assert s.apply_quick_audio_device(KIND_OUTPUT, "Novo") is False
        assert s.sound_system.applied == ["Novo", "Antigo"]   # put back, effects untouched
        assert s.current_audio_device(KIND_OUTPUT) == "Antigo"
        assert s.passed_on == []
        assert ("say", "quick_audio_device_failedNovo") in s.events

    def test_input_is_tested_then_used_for_recording_and_calls(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index", lambda name: 4)
        monkeypatch.setattr(quick_mod, "test_input_device", lambda idx: True)
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "Mic novo") is True
        assert s.effective_input_device_name == "Mic novo"
        assert s.call_audio_device(KIND_INPUT) == "Mic novo"
        assert s.settings == SAVED
        assert "load_sounds" not in s.events

    def test_an_input_that_will_not_open_changes_nothing(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index", lambda name: 4)
        monkeypatch.setattr(quick_mod, "test_input_device", lambda idx: False)
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "Mic novo") is False
        assert s.current_audio_device(KIND_INPUT) == "Mic antigo"
        assert s.passed_on == []

    def test_the_default_input_needs_no_test(self, monkeypatch):
        monkeypatch.setattr(quick_mod, "find_input_device_index",
                            lambda name: pytest.fail("the default was probed"))
        s = _Stub()
        assert s.apply_quick_audio_device(KIND_INPUT, "") is True
        assert ("say", "quick_audio_input_setPadrão") in s.events

    def test_a_call_in_progress_moves_without_being_dropped(self):
        s = _Stub(in_call=True)
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert "restart_call" in s.events


class TestAnExplicitChoiceEndsTheSwitch:
    """Found in review: the override was only ever set, so a device chosen in
    Settings or in the call's audio settings afterwards kept losing to it."""

    def test_saving_settings_ends_the_general_override_only(self):
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        s.end_session_audio_devices(general=True)
        assert s.current_audio_device(KIND_OUTPUT) == "Antigo"
        assert s.call_audio_device(KIND_OUTPUT) == "Novo"

    def test_applying_call_settings_ends_the_call_override_only(self):
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        s.end_session_audio_devices(call=True)
        assert s.call_audio_device(KIND_OUTPUT) == "Fone de ligação"
        assert s.current_audio_device(KIND_OUTPUT) == "Novo"

    def test_the_settings_dialog_ends_it_when_it_applies_the_devices(self):
        from ui.dialogs.settings_dialog import SettingsDialog
        src = inspect.getsource(SettingsDialog).replace("\r\n", "\n")
        at = src.index("self.main_window.effective_input_device_name = input_name")
        assert "end_session(general=True)" in src[at:at + 600]

    def test_only_the_kinds_named_are_ended(self):
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        s._session_call_audio_devices[KIND_INPUT] = "Microfone novo"
        s.end_session_audio_devices(call=True, kinds=(KIND_OUTPUT,))
        assert s.call_audio_device(KIND_OUTPUT) == "Fone de ligação"
        assert s.call_audio_device(KIND_INPUT) == "Microfone novo"

    def test_ending_before_any_switch_is_harmless(self):
        s = _Stub()
        s.end_session_audio_devices(general=True, call=True)
        assert s.current_audio_device(KIND_OUTPUT) == "Antigo"

    def test_the_call_dialog_ends_it_only_for_a_box_the_user_changed(self):
        """Found in the second review: OK pressed mid-call to turn on echo
        cancellation moved the call off the quick-switched headset, because the
        boxes show the saved devices, not the one in use."""
        from tests.god_modules import main_window_source
        full = main_window_source()
        at = full.index("shown_devices = (")
        block = full[at:at + 2600]
        assert '"input": input_combo.GetSelection()' in block
        assert "combo.GetSelection() != shown_devices[kind]" in block
        assert "if changed:" in block
        assert "self.end_session_audio_devices(call=True, kinds=changed)" in block
        assert "self.end_session_audio_devices(call=True)" not in full

    def test_a_settings_import_ends_both(self):
        from tests.god_modules import main_window_source
        full = main_window_source()
        at = full.index('_step("audio devices", self._apply_configured_audio_devices)')
        assert "self.end_session_audio_devices(general=True, call=True)" in full[at - 300:at]
        # ...and a call in progress moves to the imported devices.
        after = full[at:at + 700]
        assert '_step("call audio", _move_active_call)' in after
        assert "self._restart_active_voice_call_audio()" in after


class TestEveryOpenAccount:
    def test_the_choice_is_passed_on(self):
        s = _Stub()
        s.apply_quick_audio_device(KIND_OUTPUT, "Novo")
        assert s.passed_on == [(KIND_OUTPUT, "Novo")]

    def test_an_account_that_was_passed_the_choice_follows_quietly(self):
        """No speech (the user is in another window, which already spoke) and
        no passing it on again (it would bounce between processes)."""
        s = _Stub()
        s._ipc_audio_device(KIND_OUTPUT, "Novo")
        assert s.current_audio_device(KIND_OUTPUT) == "Novo"
        assert s.passed_on == []
        assert not any(isinstance(e, tuple) and e[0] == "say" for e in s.events)

    def test_a_malformed_request_is_ignored(self):
        s = _Stub()
        s._ipc_audio_device("speakers", "Novo")
        s._ipc_audio_device(KIND_OUTPUT, None)
        assert s.sound_system.applied == []

    def test_passing_on_asks_each_other_running_account(self, monkeypatch):
        asked = []
        monkeypatch.setattr(ipc, "request_audio_device",
                            lambda gd, acc, kind, name: asked.append((gd, acc, kind, name)) or True)

        class _Thread:
            def __init__(self, target=None, **kw):
                self.target = target

            def start(self):
                self.target()
        monkeypatch.setattr(quick_mod.threading, "Thread", _Thread)

        class _S:
            _pass_audio_device_to_other_accounts = MainWindow._pass_audio_device_to_other_accounts
            global_dir = "G"

            def _other_running_account_ids(self):
                return ["b", "c"]

        _S()._pass_audio_device_to_other_accounts(KIND_INPUT, "Mic novo")
        assert asked == [("G", "b", KIND_INPUT, "Mic novo"), ("G", "c", KIND_INPUT, "Mic novo")]


class TestIpc:
    @staticmethod
    def _listener(received):
        return ipc.IpcListener("G", "acc", on_activate=lambda s: None, on_quit=lambda: None,
                               on_audio_device=lambda kind, name: received.append((kind, name)))

    def test_the_listener_hands_the_device_over_and_acknowledges(self):
        received = []
        replies = self._listener(received)._handle_message(json.dumps(
            {"cmd": "audio_device", "request_id": "r1", "kind": "output", "name": "Novo"}))
        assert received == [("output", "Novo")]
        assert json.loads(replies[0]) == {"request_id": "r1", "ack": True}

    def test_a_bad_payload_is_not_acknowledged(self):
        received = []
        replies = self._listener(received)._handle_message(json.dumps(
            {"cmd": "audio_device", "request_id": "r1", "kind": "output", "name": 3}))
        assert received == [] and replies == []

    def test_a_listener_without_the_callback_ignores_it(self):
        listener = ipc.IpcListener("G", "acc", on_activate=lambda s: None, on_quit=lambda: None)
        assert listener._handle_message(json.dumps(
            {"cmd": "audio_device", "request_id": "r", "kind": "output", "name": ""})) == []

    def test_request_audio_device_sends_kind_and_name(self, monkeypatch):
        sent = []
        monkeypatch.setattr(ipc, "_send",
                            lambda gd, acc, req, timeout: sent.append(req) or [{"ack": True}])
        assert ipc.request_audio_device("G", "acc", "input", "Mic") is True
        assert (sent[0]["cmd"], sent[0]["kind"], sent[0]["name"]) == ("audio_device", "input", "Mic")
        monkeypatch.setattr(ipc, "_send", lambda *a, **k: None)
        assert ipc.request_audio_device("G", "acc", "input", "Mic") is False


def test_calls_open_the_session_device():
    src = main_window_method_source("_build_call_audio_session")
    assert 'input_name = self.call_audio_device("input")' in src
    assert 'output_name = self.call_audio_device("output")' in src


def test_the_listener_is_wired():
    src = main_window_method_source("_start_ipc_listener")
    assert "on_audio_device=lambda kind, name: wx.CallAfter(" in src
    assert "self._ipc_audio_device, kind, name)" in src


# ── Opening the list ──────────────────────────────────────────────────────────


class _FakeDialog:
    answer = None

    def __init__(self, parent, title, rows, focus):
        type(self).seen = (title, rows, focus)
        self.chosen = type(self).answer

    def ShowModal(self):
        return wx.ID_OK if self.chosen is not None else wx.ID_CANCEL

    def Destroy(self):
        pass


class TestOpen:
    @pytest.fixture(autouse=True)
    def _fakes(self, monkeypatch):
        import ui.dialogs.quick_audio_device_dialog as dlg_mod
        monkeypatch.setattr(dlg_mod, "QuickAudioDeviceDialog", _FakeDialog)

    def test_the_pick_is_applied(self):
        s = _Stub()
        s._quick_device_names = lambda kind: ["Antigo", "Novo"]
        applied = []
        s.apply_quick_audio_device = lambda kind, name: applied.append((kind, name))
        _FakeDialog.answer = "Novo"

        s.open_quick_audio_devices(KIND_OUTPUT)

        assert applied == [(KIND_OUTPUT, "Novo")]
        title, rows, focus = _FakeDialog.seen
        assert title == "quick_audio_output_title{device}"
        assert rows[focus][1] == "Antigo"      # opens on the device in use

    def test_it_opens_on_this_sessions_choice(self):
        s = _Stub()
        s._session_audio_devices = {KIND_OUTPUT: "Novo"}
        s._quick_device_names = lambda kind: ["Antigo", "Novo"]
        s.apply_quick_audio_device = lambda *a: None
        _FakeDialog.answer = None
        s.open_quick_audio_devices(KIND_OUTPUT)
        _, rows, focus = _FakeDialog.seen
        assert rows[focus][1] == "Novo"

    def test_cancel_changes_nothing(self):
        s = _Stub()
        s._quick_device_names = lambda kind: ["Antigo"]
        s.apply_quick_audio_device = lambda *a: pytest.fail("applied on cancel")
        _FakeDialog.answer = None
        s.open_quick_audio_devices(KIND_INPUT)


def test_the_shortcuts_are_in_the_frame_table():
    src = inspect.getsource(MainWindow.create_accelerator_table)
    assert "ord('H'), self.ID_CTRL_ALT_SHIFT_H" in src
    assert "ord('G'), self.ID_CTRL_ALT_SHIFT_G" in src
    assert "self._on_quick_output_devices, id=self.ID_CTRL_ALT_SHIFT_H" in src
    assert "self._on_quick_input_devices, id=self.ID_CTRL_ALT_SHIFT_G" in src
