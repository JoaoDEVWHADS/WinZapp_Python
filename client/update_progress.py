"""UI lifetime of a WinZapp installer handoff; no blocking joins on wx's loop."""

import threading
import logging

import wx

from ui.modal_utils import end_modal_if_running


def update_control_if_alive(callback, value):
    """A queued progress callback may outlive an unexpectedly closed dialog."""
    try:
        callback(value)
    except RuntimeError:
        pass


class UpdateProgressLifecycle:
    """Used by UpdateProgressDialog; its worker owns completion and cleanup."""

    def _on_cancel(self, event):
        if self._handoff.cancel():
            self._cancelled = True
            end_modal_if_running(self, wx.ID_CANCEL)

    def _on_close(self, event):
        if self._handoff.cancel():
            self._cancelled = True
            end_modal_if_running(self, wx.ID_CANCEL)
        elif event.CanVeto():
            event.Veto()
        else:
            # A forced close cannot be vetoed. The caller retains this object
            # until the worker settles and honours an already-launched installer.
            event.Skip()

    def _on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(event)
        else:
            event.Skip()

    def _start_worker(self):
        if self._thread is not None or self._handoff.settled.is_set():
            return
        try:
            if not self.IsModal() or self._handoff.cancelled.is_set():
                self._handoff.cancel()
                self._handoff.settled.set()
                return
            self._thread = threading.Thread(target=self._worker, daemon=True,
                                            name="winzapp-update-install")
            self._thread.start()
        except Exception as exc:
            logging.exception("Auto-updater: could not start the update worker")
            self._error_msg = str(exc)
            self._handoff.cancel()
            self._handoff.settled.set()
            end_modal_if_running(self, wx.ID_ABORT)

    def run(self):
        # CallAfter runs inside ShowModal: a fast prepared package cannot ask
        # to commit before the modal loop exists.
        try:
            wx.CallAfter(self._start_worker)
            return self.ShowModal()
        finally:
            self._handoff.cancel()
            if self._thread is None:
                self._handoff.settled.set()

    def _grant_install_handoff(self):
        try:
            modal = self.IsModal() and not getattr(self._main_window, "_shutting_down", False)
            if self._handoff.begin(modal):
                self._cancel_btn.Disable()
        except RuntimeError:
            self._handoff.cancel()

    def _request_install_handoff(self) -> bool:
        wx.CallAfter(self._grant_install_handoff)
        self._handoff.decided.wait()
        return self._handoff.may_spawn()

    def defer_until_settled(self, callback) -> bool:
        """Keep the dialog alive after an unexpected early ShowModal return.

        A download or a peer's IPC shutdown can still be running. Do not destroy
        controls, discard its package or read _install_ok while that is true.
        """
        if self._handoff.settled.is_set():
            return False

        def poll():
            if self._handoff.settled.is_set():
                callback()
            else:
                wx.CallLater(50, poll)

        wx.CallLater(50, poll)
        return True
