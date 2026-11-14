"""QuickAudioDevicesMixin — part of MainWindow (see main_window/__init__.py).

Ctrl+Alt+Shift+H opens the list of playback devices, Ctrl+Alt+Shift+G the
list of recording devices; a digit (or arrows + Enter) switches at once.

The switch is for this session only. Nothing is saved: Settings > Audio
devices and the call device settings keep their choice, and the next launch
starts on it again. An explicit choice made afterwards ends it: saving
Settings or importing settings ends the general override (both re-apply the
saved devices), and changing a device box in the call's own audio settings
ends the call override for that device.

It covers everything that uses a device — sounds and playback, voice-message
recording, calls (a call in progress moves without being dropped) — and every
account open right now: each one is its own process with its own audio, so
the account that got the keystroke passes the choice on over IPC
(ipc.request_audio_device) and the others apply it quietly.

Output goes through SoundSystem.apply_output_device() and then load_sounds(),
exactly as the Settings dialog does it: switching the one BASS device
invalidates every stream created before (docs/traps/audio-devices.md).
"""

import logging
import threading

import wx

from core.audio_devices import (
    enumerate_input_devices,
    enumerate_output_devices,
    find_input_device_index,
    test_input_device,
)
from core.quick_audio_devices import KIND_INPUT, KIND_OUTPUT, quick_device_rows

_SETTING_KEY = {KIND_OUTPUT: "output_device_name", KIND_INPUT: "input_device_name"}


class QuickAudioDevicesMixin:
    """Session-only quick switch between playback and recording devices."""

    def _on_quick_output_devices(self, event=None):
        self.open_quick_audio_devices(KIND_OUTPUT)

    def _on_quick_input_devices(self, event=None):
        self.open_quick_audio_devices(KIND_INPUT)

    def _quick_device_names(self, kind: str) -> list:
        devices = enumerate_output_devices() if kind == KIND_OUTPUT else enumerate_input_devices()
        return [name for _, name in devices]

    def _session_audio_device(self, kind: str):
        """This session's general override for *kind*: a device name ("" =
        system default), or None when the saved setting still applies."""
        return (getattr(self, "_session_audio_devices", None) or {}).get(kind)

    def _session_call_audio_device(self, kind: str):
        """This session's override for the device a call opens for *kind*."""
        return (getattr(self, "_session_call_audio_devices", None) or {}).get(kind)

    def end_session_audio_devices(self, *, general: bool = False, call: bool = False,
                                  kinds=(KIND_OUTPUT, KIND_INPUT)):
        """Drop the quick-switch override for *kinds*, because the user just
        chose devices explicitly: in Settings (``general``) or in the call's
        audio settings (``call``). Left in place, the override would keep
        winning over the choice the user just made."""
        for wanted, attr in ((general, "_session_audio_devices"),
                             (call, "_session_call_audio_devices")):
            overrides = getattr(self, attr, None)
            if wanted and overrides:
                for kind in kinds:
                    overrides.pop(kind, None)

    def current_audio_device(self, kind: str) -> str:
        """The general device *kind* is on: the session override, else the saved one."""
        override = self._session_audio_device(kind)
        if override is not None:
            return override
        return self.settings.get("audio_devices", {}).get(_SETTING_KEY[kind], "")

    def call_audio_device(self, kind: str) -> str:
        """The device a call opens for *kind*: the session override when there
        is one, else the call device settings (which may differ from the
        general ones on purpose)."""
        override = self._session_call_audio_device(kind)
        if override is not None:
            return override
        return self.settings.get("call_audio_devices", {}).get(_SETTING_KEY[kind], "")

    def open_quick_audio_devices(self, kind: str):
        """Show the quick list for *kind* and apply what the user picks."""
        from ui.dialogs.quick_audio_device_dialog import QuickAudioDeviceDialog

        t = self.i18n.t
        try:
            names = self._quick_device_names(kind)
        except Exception:
            logging.exception("[quick-audio] listing %s devices failed", kind)
            names = []
        rows, focus = quick_device_rows(
            names, self.current_audio_device(kind),
            t("audio_device_default"), t("quick_audio_device_current"))
        title = t("quick_audio_output_title" if kind == KIND_OUTPUT else "quick_audio_input_title")
        dialog = QuickAudioDeviceDialog(self, title, rows, focus)
        try:
            if dialog.ShowModal() != wx.ID_OK or dialog.chosen is None:
                return
            chosen = dialog.chosen
        finally:
            dialog.Destroy()
        self.apply_quick_audio_device(kind, chosen)

    def apply_quick_audio_device(self, kind: str, name: str, *,
                                 announce: bool = True, broadcast: bool = True) -> bool:
        """Switch *kind* to device *name* ("" = system default) for the rest
        of this session. A device that will not open changes nothing.

        ``announce``/``broadcast`` are off when another account passed the
        choice on: the one the user is in already spoke, and passing it on
        again would bounce between processes."""
        t = self.i18n.t
        shown = name or t("audio_device_default")

        if kind == KIND_OUTPUT:
            previous = self.current_audio_device(KIND_OUTPUT)
            if not self.sound_system.apply_output_device(name):
                # apply_output_device() already fell back to the system
                # default; put the device that was working back.
                self.sound_system.apply_output_device(previous)
                self.load_sounds()
                if announce:
                    self.output(t("quick_audio_device_failed").format(device=shown), interrupt=True)
                return False
            # Effect sounds (message received/sent...) are pinned to a device
            # of their own. Set to follow the system default, they follow the
            # switch too; a device chosen for them on purpose is left alone.
            if not self.settings.get("audio_devices", {}).get("effects_output_device_name", ""):
                self.sound_system.apply_effects_device(name)
            self.load_sounds()
        elif name:
            idx = find_input_device_index(name)
            if idx is None or not test_input_device(idx):
                if announce:
                    self.output(t("quick_audio_device_failed").format(device=shown), interrupt=True)
                return False

        if getattr(self, "_session_audio_devices", None) is None:
            self._session_audio_devices = {}
        if getattr(self, "_session_call_audio_devices", None) is None:
            self._session_call_audio_devices = {}
        self._session_audio_devices[kind] = name
        self._session_call_audio_devices[kind] = name
        if kind == KIND_INPUT:
            self.effective_input_device_name = name
        logging.info("[quick-audio] %s device set to %r for this session", kind, name or "(default)")

        if getattr(self, "_call_audio_session", None) is not None:
            self._restart_active_voice_call_audio()

        if announce:
            self.output(
                t("quick_audio_output_set" if kind == KIND_OUTPUT else "quick_audio_input_set")
                .format(device=shown),
                interrupt=True,
            )
        if broadcast:
            self._pass_audio_device_to_other_accounts(kind, name)
        return True

    def _pass_audio_device_to_other_accounts(self, kind: str, name: str):
        """Hand the choice to every other account running now, off the wx
        thread: each is an IPC round trip to another process."""
        gd = getattr(self, "global_dir", None)
        if not gd:
            return

        def _worker():
            try:
                others = self._other_running_account_ids()
            except Exception:
                logging.exception("[quick-audio] listing running accounts failed")
                return
            import ipc
            for account_id in others:
                try:
                    if not ipc.request_audio_device(gd, account_id, kind, name):
                        logging.warning("[quick-audio] account %s did not take the %s device",
                                        account_id, kind)
                except Exception:
                    logging.exception("[quick-audio] passing the %s device to %s failed",
                                      kind, account_id)

        threading.Thread(target=_worker, daemon=True, name="winzapp-quick-audio").start()

    def _ipc_audio_device(self, kind: str, name: str):
        """Another account switched a device: follow it, quietly."""
        if kind not in _SETTING_KEY or not isinstance(name, str):
            return
        self.apply_quick_audio_device(kind, name, announce=False, broadcast=False)
