"""WinZapp's global show/hide hotkey on macOS (Carbon RegisterEventHotKey).

On Windows the hotkey is a RegisterHotKey() owned by a thread with its own
message loop (main_window/win32_helpers._HotkeyManager). macOS's equivalent
system-wide hotkey API is Carbon's RegisterEventHotKey — still the
supported way to do this, and unlike a global key monitor it needs no
Accessibility permission. Callbacks arrive on the main run loop, which wx
already runs.

Settings keep WinZapp's (vk, mod) format: the capture field sees keys
after keymap_mac has turned the Mac combo into WinZapp's Windows combo
(Cmd-Option-W arrives as Alt+W), so what is stored is exactly what a
Windows install would store; registering applies the same rule back
(Alt+W -> Cmd-Option-W). The field reads the combo back in Mac terms.
"""

import ctypes
import ctypes.util
import logging

import wx

from . import keymap_mac as km

_MOD_ALT, _MOD_CONTROL, _MOD_SHIFT, _MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008

# Carbon modifier bits
_CMD, _SHIFT, _OPTION, _CONTROL = 0x0100, 0x0200, 0x0800, 0x1000

# Windows virtual-key -> macOS virtual keycode (kVK_*), for the keys a
# hotkey can use.
_ANSI = {"A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06,
         "X": 0x07, "C": 0x08, "V": 0x09, "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E,
         "R": 0x0F, "Y": 0x10, "T": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
         "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D, "O": 0x1F,
         "U": 0x20, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "K": 0x28, "N": 0x2D,
         "M": 0x2E}
_NAMED = {"SPACE": 0x31, "RETURN": 0x24, "TAB": 0x30, "ESCAPE": 0x35, "BACK": 0x33,
          "DELETE": 0x75, "HOME": 0x73, "END": 0x77, "PAGEUP": 0x74, "PAGEDOWN": 0x79,
          "LEFT": 0x7B, "RIGHT": 0x7C, "DOWN": 0x7D, "UP": 0x7E,
          "F1": 0x7A, "F2": 0x78, "F3": 0x63, "F4": 0x76, "F5": 0x60, "F6": 0x61,
          "F7": 0x62, "F8": 0x64, "F9": 0x65, "F10": 0x6D, "F11": 0x67, "F12": 0x6F}
_VK_NAMES = {0x08: "BACK", 0x09: "TAB", 0x0D: "RETURN", 0x1B: "ESCAPE", 0x20: "SPACE",
             0x21: "PAGEUP", 0x22: "PAGEDOWN", 0x23: "END", 0x24: "HOME", 0x25: "LEFT",
             0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN", 0x2E: "DELETE"}
_WXK_TO_VK = {wx.WXK_BACK: 0x08, wx.WXK_TAB: 0x09, wx.WXK_RETURN: 0x0D, wx.WXK_ESCAPE: 0x1B,
              wx.WXK_SPACE: 0x20, wx.WXK_PAGEUP: 0x21, wx.WXK_PAGEDOWN: 0x22, wx.WXK_END: 0x23,
              wx.WXK_HOME: 0x24, wx.WXK_LEFT: 0x25, wx.WXK_UP: 0x26, wx.WXK_RIGHT: 0x27,
              wx.WXK_DOWN: 0x28, wx.WXK_DELETE: 0x2E}


def vk_key_name(vk):
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x70 <= vk <= 0x7B:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return None


def wx_keycode_to_vk(code):
    """The Windows virtual key for a wx key code (what RegisterHotKey stores)."""
    if code in _WXK_TO_VK:
        return _WXK_TO_VK[code]
    if wx.WXK_F1 <= code <= wx.WXK_F12:
        return 0x70 + (code - wx.WXK_F1)
    if 32 < code < 127:
        ch = chr(code).upper()
        if ch.isalnum():
            return ord(ch)
    return 0


def mac_combo(vk, mod):
    """(vk, mod) as stored by WinZapp -> (Carbon keycode, Carbon modifiers)."""
    key = vk_key_name(vk)
    if key is None:
        return None
    win = set()
    if mod & _MOD_CONTROL:
        win.add(km.W_CTRL)
    if mod & _MOD_ALT:
        win.add(km.W_ALT)
    if mod & _MOD_SHIFT:
        win.add(km.W_SHIFT)
    mac_mods, mac_key = km.win_to_mac(frozenset(win), key)
    code = _ANSI.get(mac_key) if len(mac_key) == 1 else _NAMED.get(mac_key)
    if code is None:
        return None
    carbon = 0
    if km.M_CMD in mac_mods:
        carbon |= _CMD
    if km.M_OPT in mac_mods:
        carbon |= _OPTION
    if km.M_SHIFT in mac_mods:
        carbon |= _SHIFT
    if km.M_CTRL in mac_mods:
        carbon |= _CONTROL
    return code, carbon


def vk_mod_to_str(vk, mod):
    orig = _orig_vk_mod_to_str
    if orig is None:
        from main_window import win32_helpers
        orig = win32_helpers._vk_mod_to_str
        if orig is vk_mod_to_str:
            return ""
    return km.mac_shortcut_text(orig(vk, mod))


# --------------------------------------------------------------- Carbon ----

class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_carbon = None
_handler_ref = None
_callbacks = {}
_next_id = [1]
_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_kEventClassKeyboard = int.from_bytes(b"keyb", "big")
_kEventHotKeyPressed = 5
_kEventParamDirectObject = int.from_bytes(b"----", "big")
_typeEventHotKeyID = int.from_bytes(b"hkid", "big")
_SIGNATURE = int.from_bytes(b"WZap", "big")


def _on_hotkey(_next, event, _data):
    hk = _EventHotKeyID()
    _carbon.GetEventParameter(event, _kEventParamDirectObject, _typeEventHotKeyID, None,
                              ctypes.sizeof(hk), None, ctypes.byref(hk))
    cb = _callbacks.get(hk.id)
    if cb is not None:
        wx.CallAfter(cb)
    return 0


_on_hotkey_c = _HANDLER(_on_hotkey)


def _carbon_lib():
    global _carbon, _handler_ref
    if _carbon is None:
        _carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))
        _carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        _carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
                                                ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p)]
        _carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                                ctypes.c_void_p, ctypes.c_uint32,
                                                ctypes.POINTER(ctypes.c_void_p)]
        _carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        _carbon.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                              ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                                              ctypes.c_void_p]
        spec = _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed)
        ref = ctypes.c_void_p()
        _carbon.InstallEventHandler(_carbon.GetApplicationEventTarget(), _on_hotkey_c, 1,
                                    ctypes.byref(spec), None, ctypes.byref(ref))
        _handler_ref = ref
    return _carbon


class MacHotkeyManager:
    """Drop-in for win32_helpers._HotkeyManager(vk, mod, callback)."""

    def __init__(self, vk, mod, callback):
        self._ref = None
        combo = mac_combo(vk, mod)
        if combo is None:
            logging.error("[hotkey_mac] no Mac key for vk=%#x mod=%#x", vk, mod)
            return
        code, carbon_mods = combo
        self._id = _next_id[0]
        _next_id[0] += 1
        _callbacks[self._id] = callback
        ref = ctypes.c_void_p()
        status = _carbon_lib().RegisterEventHotKey(
            code, carbon_mods, _EventHotKeyID(_SIGNATURE, self._id),
            _carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if status != 0:
            logging.error("[hotkey_mac] RegisterEventHotKey failed (%s) — the combination "
                          "may belong to another app", status)
            _callbacks.pop(self._id, None)
            return
        self._ref = ref
        logging.info("[hotkey_mac] registered %s", vk_mod_to_str(vk, mod))

    def stop(self):
        if self._ref is not None:
            _carbon.UnregisterEventHotKey(self._ref)
            self._ref = None
            _callbacks.pop(self._id, None)


# ------------------------------------------------------- capture + toggle --

def _capture_key_down(self, event):
    code = event.GetKeyCode()
    if code == wx.WXK_TAB:
        event.Skip()
        return
    if code in (wx.WXK_SHIFT, wx.WXK_ALT, wx.WXK_CONTROL, wx.WXK_RAW_CONTROL,
                wx.WXK_COMMAND, wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT):
        event.Skip()
        return
    if code in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasAnyModifiers():
        self._vk = 0
        self._mod = 0
        self.SetValue("")
        return
    mod = 0
    if event.ControlDown():
        mod |= _MOD_CONTROL
    if event.AltDown():
        mod |= _MOD_ALT
    if event.ShiftDown():
        mod |= _MOD_SHIFT
    if not (mod & (_MOD_CONTROL | _MOD_ALT)):
        return
    vk = wx_keycode_to_vk(code)
    if not vk or mac_combo(vk, mod) is None:
        return
    self._vk, self._mod = vk, mod
    self.SetValue(vk_mod_to_str(vk, mod))


def toggle_window_from_hotkey(self):
    """Show WinZapp, or hide it when its window is the one in front."""
    try:
        from AppKit import NSApp
        in_front = bool(NSApp().isActive()) and self.IsShown() and self.IsActive()
    except Exception:
        in_front = False
    if in_front:
        self.hide_to_tray()
    else:
        self.restore_window()


_orig_vk_mod_to_str = None


def install():
    global _orig_vk_mod_to_str
    from main_window import win32_helpers, window_chrome, window_lifecycle
    _orig_vk_mod_to_str = win32_helpers._vk_mod_to_str
    win32_helpers._HotkeyManager = MacHotkeyManager
    window_chrome._HotkeyManager = MacHotkeyManager
    win32_helpers._vk_mod_to_str = vk_mod_to_str
    window_lifecycle.WindowLifecycleMixin.toggle_window_from_hotkey = toggle_window_from_hotkey
    from ui.dialogs import settings_dialog
    settings_dialog._HotkeyCapture._on_key_down = _capture_key_down
