"""The Transcription tab's side of a download that runs without a window.

`_start_transcription_job()` is the one place the tab starts a model, CUDA or
whisper.cpp action. It runs it behind the progress dialog, as before, unless
the user turned on Settings > General > "download updates in the background"
and the action is a download (core/transcription/background.py): then the main
window runs it (main_window/transcription_background.py), the tab goes back to
being usable, and `_transcription_background_ended()` finishes the job when
the window says it is over.

Two things are deliberate:

* **The tab never owns the job.** Settings is modal, the user leaves it, and the
  job goes on. If the dialog is closed the window says the outcome alone; if a
  new dialog is opened meanwhile it adopts the running job
  (`_watch_transcription_background()`), with its buttons off, so a second
  action cannot queue behind the first on the models lock.

* **Finishing in the background never moves the focus** — the user is in
  another tab or another window by then — except off a control of this tab
  that can no longer answer (Cancel, now hidden, or a switched-off button),
  where it would otherwise be stranded. Starting a run moves it to Cancel, for
  the same reason: the button pressed is switched off.
"""

import wx

from core.transcription import background as transcription_background
from core.transcription import management as transcription_management
from update_background import background_downloads_enabled


class TranscriptionBackgroundTabMixin:
    """Starts and finishes the tab's actions, in a dialog or in the background."""

    def _transcription_background_wanted(self, action) -> bool:
        """Whether `action` goes to the main window instead of the dialog."""
        return transcription_background.runs_in_background(
            action,
            background_downloads_enabled(getattr(self.main_window, "settings", None)),
        )

    def _start_transcription_job(self, action, model_id=None, build_id=None,
                                 compute_capability=None):
        """Run one action, then say it. In the background when the user asked."""
        if self._transcription_background_wanted(action):
            self._start_transcription_in_background(
                action, model_id, build_id, compute_capability
            )
            return
        if action in transcription_management.WHISPER_CPP_ACTIONS:
            # As before the background mode: a program action names its build
            # (and the card it was offered for), a model action its model.
            job, result, error = self._run_transcription_job(
                action, build_id=build_id, compute_capability=compute_capability,
            )
        else:
            job, result, error = self._run_transcription_job(action, model_id=model_id)
        self._after_transcription_job(job, result, error, action=action,
                                      model_id=model_id, build_id=build_id)

    def _start_transcription_in_background(self, action, model_id, build_id,
                                           compute_capability):
        make_job = self._transcription_job_factory(
            action, model_id=model_id, build_id=build_id,
            compute_capability=compute_capability,
        )
        started = self.main_window.start_transcription_background_job(
            make_job, self._transcription_status_text(action, model_id, build_id)
        )
        if not started:
            # Another download is already running: the buttons are off while
            # one is, so this is a press that got through, and it changes
            # nothing.
            return
        self._enter_transcription_background_run(focus_cancel=True)

    def _enter_transcription_background_run(self, focus_cancel=False) -> None:
        """The tab goes quiet and offers Cancel while the window runs the job.

        `focus_cancel` when the user has just started it: the button they
        pressed is switched off with every other one, and a disabled control
        says nothing to a screen reader, so the focus moves to the one control
        that does something now. A tab adopting a run already under way leaves
        the focus where the user put it.
        """
        self._set_transcription_job_running(True)
        self._show_transcription_cancel(True)
        if focus_cancel:
            button = getattr(self, "_transcription_cancel_btn", None)
            if button is not None:
                button.SetFocus()
        self.main_window.watch_transcription_background(
            self._transcription_background_ended
        )

    def _transcription_background_ended(self, job, result, error, last=True) -> bool:
        """The window's call when a job of the background run is over.

        True: said here. `last` is False between the jobs of a queue, when the
        tab stays busy and Cancel stays offered. `job` None: the run ended
        without a job of its own to report (the next one of a queue could not
        start) — the tab only comes back to life; the window says why.
        """
        if not self:
            # Settings was closed meanwhile; the window says it.
            return False
        if job is None:
            self._set_transcription_job_running(False)
            self._show_transcription_cancel(False)
            if self._transcription_focus_stranded():
                self._transcription_model_list.SetFocus()
            return True
        stranded = False
        if last:
            # Asked before Cancel is hidden: whatever wx does with the focus of
            # a control it hides, the answer is about where the user was.
            stranded = self._transcription_focus_stranded()
            self._set_transcription_job_running(False)
            self._show_transcription_cancel(False)
        self._after_transcription_job(job, result, error, restore_focus=False)
        if stranded:
            self._rescue_transcription_focus(job.action)
        return True

    def _transcription_focus_stranded(self) -> bool:
        """Whether the focus is on a control of this window that can no longer
        answer: Cancel, now hidden, or a button switched off. Focus anywhere
        else — another window included — is the user's and is left alone."""
        focused = wx.Window.FindFocus()
        if focused is None or wx.GetTopLevelParent(focused) is not self:
            return False
        return (focused is getattr(self, "_transcription_cancel_btn", None)
                or not focused.IsEnabled() or not focused.IsShown())

    def _rescue_transcription_focus(self, action) -> None:
        """The button of the action that ran when it can be pressed again,
        else the nearest control of its row that can."""
        button = self._transcription_action_buttons.get(action)
        if button is not None and button.IsEnabled() and button.IsShown():
            button.SetFocus()
        elif action in transcription_management.WHISPER_CPP_ACTIONS:
            self._restore_whisper_cpp_focus(action)
        else:
            self._restore_transcription_focus(action)

    def _after_transcription_job(self, job, result, error, restore_focus=True,
                                 extra_keys=(), action=None, model_id=None,
                                 build_id=None):
        """Report a finished job by whichever family its action belongs to.

        `action`, `model_id` and `build_id` are what the caller asked for. They
        are given where it knows them, because the progress dialog can answer
        with no job at all (one that never started), and the report still has
        to name the action, as it did before the background mode existed.
        """
        action = action if action is not None else getattr(job, "action", None)
        if model_id is None:
            model_id = getattr(job, "model_id", None)
        if build_id is None:
            build_id = getattr(job, "build_id", None)
        if action in transcription_management.WHISPER_CPP_ACTIONS:
            self._finish_whisper_cpp_job(
                action, build_id, job, result, error,
                restore_focus=restore_focus,
            )
            return
        if (error is None and job is not None
                and action == transcription_management.ACTION_DOWNLOAD_MODEL):
            # It arrived: it is no longer waiting in the queue. (No job: nothing
            # ran, so nothing arrived.)
            self._transcription_model_marks.discard(model_id)
        self._report_transcription_job(
            action, model_id, job, result, error,
            extra_keys=extra_keys, restore_focus=restore_focus,
        )

    def _watch_transcription_background(self) -> None:
        """A tab opened while a download runs in the background adopts it."""
        running = getattr(self.main_window, "transcription_background_running", None)
        if not callable(running) or not running():
            return
        self._enter_transcription_background_run()

    # ── Cancel ───────────────────────────────────────────────────────────────

    def _show_transcription_cancel(self, shown) -> None:
        """Offer Cancel only while there is something to cancel.

        Hidden rather than disabled: it is a stop in the tab order that answers
        nothing the rest of the time. Never disabled while shown: it may hold
        the focus, and a disabled control says nothing to a screen reader.
        """
        button = getattr(self, "_transcription_cancel_btn", None)
        if button is None:
            return
        self._transcription_cancel_requested = False
        button.Enable(True)
        button.Show(bool(shown))
        button.GetParent().Layout()

    def _on_transcription_cancel_background(self, event) -> None:
        """Stop the running download and whatever was queued behind it."""
        if getattr(self, "_transcription_cancel_requested", False):
            # Asked already: say it again rather than nothing.
            self.main_window.speak_output.output(
                self.main_window.i18n.t("transcription_progress_cancelling"))
            return
        if not self.main_window.cancel_transcription_background():
            return
        self._transcription_cancel_requested = True
        self.main_window.speak_output.output(
            self.main_window.i18n.t("transcription_progress_cancelling")
        )
