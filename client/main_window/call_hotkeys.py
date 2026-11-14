"""CallHotkeysMixin — part of MainWindow (see main_window/__init__.py).

Answer, reject or hang up a call from any window. Two system-wide keys,
changeable in Settings > Keyboard shortcuts (shipped as Ctrl+Alt+Shift+Enter
and Ctrl+Alt+Shift+Backspace):

* answer: answers the call that is ringing, brings the call window forward and
  puts the focus in it. A video call is answered the way its Answer button
  does, with the camera on.
* end: rejects the call that is ringing -- a group offer too, which can be
  rejected though not answered; with no call ringing, hangs up the one in
  progress.

WinZapp used to need its own window in front (or the global "show WinZapp" key
first) before a call could be answered, which for a screen-reader user means
leaving what they are doing.

The keys are registered with Windows only while they can do something --
``answer`` while a call that can be answered rings, ``end`` while any call
rings or a call is in progress -- so they are free for every other program the
rest of the time. With several accounts open, a press of the end key that
reaches an account with nothing ringing first offers the reject to the other
running accounts (``_hang_up_unless_another_account_rings``): the account
ringing could not take the key from the one holding it for its call.

Every change of the incoming-call state and of the call in
progress asks for a sync (``_request_call_hotkey_sync``); the sync itself runs
once the event that changed things is over, so it never sees the moment
between "the alert stopped" and "the call was answered" as "no call at all".
"""

import logging
import threading

import wx

from core.call_logic import (
    call_hotkey_setting,
    first_answerable_call,
)
from core.dialog_foreground import force_foreground
from main_window.win32_helpers import _HotkeyManager

# A call key exists only while a call rings, so a key another account has
# just let go of is retried every second, not on the 15 s of the show key.
_CALL_KEY_RETRY_SECONDS = 1.0


class CallHotkeysMixin:
    def _wanted_call_hotkeys(self) -> dict:
        """name -> ((vk, mod), callback) for the keys that can act right now."""
        if getattr(self, "_shutting_down", False):
            return {}
        answerable = self._has_answerable_incoming_call()
        ringing = bool(getattr(self, "_active_incoming_calls", None))
        in_call = bool(getattr(self, "_active_voice_call", None))
        general = getattr(self, "settings", {}).get("general", {})
        wanted = {}
        if answerable:
            key = call_hotkey_setting(general, "call_answer_hotkey")
            if key:
                wanted["answer"] = (key, self._answer_call_from_hotkey)
        if ringing or in_call:
            key = call_hotkey_setting(general, "call_end_hotkey")
            if key:
                wanted["end"] = (key, self._end_call_from_hotkey)
        return wanted

    def _request_call_hotkey_sync(self):
        """Sync the keys once the current event is over; repeated asks before
        then cost one sync.

        Answering stops the alert (nothing rings any more) a moment before it
        records the call in progress. Synced in between, the end key was
        released and registered again on every answer, holding up the UI
        thread while the key's thread let go of it.
        """
        if getattr(self, "_call_hotkey_sync_pending", False):
            return
        self._call_hotkey_sync_pending = True
        wx.CallAfter(self._run_requested_call_hotkey_sync)

    def _run_requested_call_hotkey_sync(self):
        self._call_hotkey_sync_pending = False
        self._sync_call_hotkeys()

    def _sync_call_hotkeys(self):
        """Hold exactly the keys that can act now, on the keys set in Settings."""
        managers = getattr(self, "_call_hotkey_managers", None)
        if managers is None:
            managers = self._call_hotkey_managers = {}
        wanted = self._wanted_call_hotkeys()
        for name in list(managers):
            manager, key = managers[name]
            if name not in wanted or wanted[name][0] != key:
                manager.stop(wait=True)
                del managers[name]
        for name, (key, callback) in wanted.items():
            if name in managers:
                continue
            try:
                managers[name] = (
                    _HotkeyManager(key[0], key[1], callback,
                                   retry_seconds=_CALL_KEY_RETRY_SECONDS),
                    key)
            except Exception:
                logging.exception("[call_hotkeys] could not register the %s key", name)

    def _release_call_hotkeys(self):
        """Let go of every call key now (shutdown): a key pressed while the
        session is being stopped must not answer a call into a closing app."""
        managers = getattr(self, "_call_hotkey_managers", None) or {}
        self._call_hotkey_managers = {}
        for manager, _key in managers.values():
            try:
                manager.stop()
            except Exception:
                logging.exception("[call_hotkeys] could not release a call key")

    def _ringing_call_for_hotkey(self):
        identity = first_answerable_call(
            getattr(self, "_active_incoming_calls", {}),
            getattr(self, "_incoming_call_details", {}),
        )
        details = getattr(self, "_incoming_call_details", {}).get(identity, {})
        return identity, details

    def _answer_call_from_hotkey(self):
        if getattr(self, "_shutting_down", False):
            return
        identity, details = self._ringing_call_for_hotkey()
        if not identity:
            return
        logging.info("[call_hotkeys] answer key pressed video=%s", bool(details.get("is_video")))
        self.accept_incoming_call(identity)
        # After accept_incoming_call's own queued refresh of the call window,
        # so the window is on screen by the time it is brought forward.
        wx.CallAfter(self._focus_call_window)

    def _end_call_from_hotkey(self):
        if getattr(self, "_shutting_down", False):
            return
        if self._reject_ringing_call_from_hotkey():
            return
        if getattr(self, "_active_voice_call", None):
            self._hang_up_unless_another_account_rings()

    def _reject_ringing_call_from_hotkey(self) -> bool:
        """Reject the first ringing offer, a group one included: the user
        pressed "reject" because something rings, and hanging up the call they
        are on instead would lose it."""
        identity = self._first_incoming_call_identity()
        if not identity:
            return False
        logging.info("[call_hotkeys] end key pressed: rejecting the ringing call")
        self.reject_incoming_call(identity)
        self.output(self.i18n.t("incoming_call_rejected"), interrupt=True)
        return True

    def _hang_up_unless_another_account_rings(self):
        """Hang up the call in progress, unless the key was meant for another
        account's ringing call.

        Each account is its own process, and Windows gives a key combination
        to one registration: while this account holds the end key for its
        call, another account that starts ringing cannot take it, and the
        press meant to reject that call arrives here. So every other running
        account is asked first (an IPC round trip each, off the wx thread);
        only when none of them had a call ringing is this call hung up.
        """
        gd = getattr(self, "global_dir", None)
        if not (gd and getattr(self, "account_id", None)):
            self._hang_up_from_hotkey(self._active_voice_call.get("call_id"))
            return
        call_id = self._active_voice_call.get("call_id")

        def _worker():
            import ipc
            try:
                others = self._other_running_account_ids()
            except Exception:
                logging.exception("[call_hotkeys] listing running accounts failed")
                others = []
            for account_id in others:
                try:
                    if ipc.request_reject_ringing_call(gd, account_id):
                        logging.info("[call_hotkeys] end key passed to another account's ringing call")
                        return
                except Exception:
                    logging.exception("[call_hotkeys] asking another account to reject failed")
            wx.CallAfter(self._hang_up_from_hotkey, call_id)

        threading.Thread(target=_worker, daemon=True, name="winzapp-call-end-key").start()

    def _hang_up_from_hotkey(self, call_id):
        active = getattr(self, "_active_voice_call", None)
        if getattr(self, "_shutting_down", False) or not active:
            return
        if active.get("call_id") != call_id:
            return  # that call ended while the other accounts were asked
        logging.info("[call_hotkeys] end key pressed: hanging up the call")
        self.end_active_call()

    def _ipc_reject_ringing_call(self) -> bool:
        """Another account's end key, pressed while a call rings here. Runs on
        the IPC thread: whether something rings is answered now, the reject
        itself happens on the wx thread."""
        if getattr(self, "_shutting_down", False):
            return False
        if not getattr(self, "_active_incoming_calls", None):
            return False
        wx.CallAfter(self._reject_ringing_call_from_hotkey)
        return True

    def _focus_call_window(self):
        """Bring the call window in front of any program and focus its first button."""
        window = getattr(self, "voice_call_window", None)
        if window is None or not window.IsShown():
            return
        try:
            force_foreground(window.GetHandle(), topmost=True)
        except Exception:
            logging.exception("[call_hotkeys] could not bring the call window forward")
            window.Raise()
        button = getattr(self, "voice_call_window_mute_button", None)
        if button is not None:
            button.SetFocus()
