"""Global hotkey on macOS (hotkey_mac)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import wx  # noqa: E402

from winzapp_mac import hotkey_mac as hk  # noqa: E402

CTRL, ALT, SHIFT = 0x0002, 0x0001, 0x0004


@pytest.mark.parametrize("vk, mod, want", [
    (ord("W"), ALT, (0x0D, hk._CMD | hk._OPTION)),               # Alt+W -> Cmd-Opt-W
    (ord("W"), CTRL | SHIFT, (0x0D, hk._CMD | hk._SHIFT)),        # Ctrl+Shift+W -> Shift-Cmd-W
    (ord("Z"), CTRL | ALT, (0x06, hk._CMD | hk._CONTROL)),        # Ctrl+Alt+Z -> Ctrl-Cmd-Z
    (0x70 + 4, CTRL | ALT, (0x60, hk._CMD | hk._CONTROL)),        # Ctrl+Alt+F5
])
def test_stored_windows_combo_registers_the_mac_keys(vk, mod, want):
    assert hk.mac_combo(vk, mod) == want


def test_wx_keys_become_windows_virtual_keys():
    assert hk.wx_keycode_to_vk(ord("w")) == ord("W")
    assert hk.wx_keycode_to_vk(wx.WXK_F5) == 0x74
    assert hk.wx_keycode_to_vk(wx.WXK_SPACE) == 0x20


def test_field_reads_the_combo_in_mac_terms(monkeypatch):
    from main_window import win32_helpers
    monkeypatch.setattr(hk, "_orig_vk_mod_to_str", win32_helpers._vk_mod_to_str)
    assert hk.vk_mod_to_str(ord("W"), ALT) == "Option-Command-W"


def test_registering_and_releasing_a_system_hotkey():
    fired = []
    mgr = hk.MacHotkeyManager(0x7B, CTRL | ALT | SHIFT, lambda: fired.append(1))  # Ctrl+Alt+Shift+F12
    try:
        assert mgr._ref is not None, "RegisterEventHotKey refused the combination"
    finally:
        mgr.stop()
    assert mgr._ref is None
