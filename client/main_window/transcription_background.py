"""TranscriptionBackgroundMixin — part of MainWindow (see main_window/__init__.py).

A transcription download (a model, the CUDA libraries, the whisper.cpp
program) that the user chose to run in the background — Settings > General,
"download updates in the background", the option the updater and the WPPConnect
Server update already follow (core/transcription/background.py).

**It lives here and not in the Settings dialog because it outlives it.** The
dialog is modal and the point of the option is that the user goes back to the
app; a job owned by the dialog would have to be cancelled with it, or finish
into a window that no longer exists. So the window starts the job and says how
it ended, and the dialog — when one is open — only asks to be told.

**A run is a queue of jobs, usually of one.** The models the user marked in the
tab are downloaded one after the other, never at once (the models folder is
install-wide and ManagementJob serialises on its lock, so a second job would
wait silently behind the first, which is the one thing a background job must
never do). The first failure or cancellation ends the run: what was queued
behind it is dropped and said to be, because a download that failed for lack of
disk would fail again for each of the others.

**Cancelling** is the user's button in the tab and the app quitting
(`cancel_transcription_background()`, called from the shutdown); the job stops
at its next check and reports CANCELLED like any other end.
"""

import logging

import wx

from core.transcription import errors as transcription_errors
from core.transcription import management, management_text


class TranscriptionBackgroundMixin:
    """MainWindow's half of a transcription download that runs without a window."""

    def transcription_background_running(self) -> bool:
        return getattr(self, "_transcription_background_job", None) is not None

    def watch_transcription_background(self, listener) -> None:
        """Be told, on the wx thread, how each job of the running run ended.

        `listener(job, result, error, last)` returns True when it said the
        outcome itself (the Settings tab does, on screen and aloud); otherwise
        the window says it. `last` is True for the job that ends the run, and
        a listener is forgotten after it, so a dialog that was closed meanwhile
        is not kept alive by this list — it only has to ignore the call
        (`if not self`).
        """
        listeners = self.__dict__.setdefault("_transcription_background_listeners", [])
        listeners.append(listener)

    def start_transcription_background_job(self, make_job, status_text) -> bool:
        """Start one management job with no window; False if a run is going."""
        return self.start_transcription_background_jobs([(make_job, status_text)])

    def start_transcription_background_jobs(self, items) -> bool:
        """Start a run of jobs with no window; False if one is running.

        `items` is [(make_job, status_text)], `make_job(on_progress, on_finished)`
        being the factory the progress dialog takes, so the same job is built
        either way. Progress is not reported: a percentage read out every few
        seconds for half an hour is the noise the option exists to remove, and
        the start and the end of each job are the news.
        """
        if self.transcription_background_running() or not items:
            return False
        self._transcription_background_queue = list(items)
        self._transcription_background_total = len(items)
        self._transcription_background_done = 0
        if not self._start_next_transcription_background_job(first=True):
            self._transcription_background_queue = []
            return False
        return True

    def cancel_transcription_background(self) -> bool:
        """Stop the running job and drop what was queued behind it.

        True when there was a run to stop. Cooperative: the job stops at its
        next check and reports CANCELLED through the usual path, which is what
        frees the buttons. Safe on the shutdown thread: it only sets flags.
        """
        job = getattr(self, "_transcription_background_job", None)
        if job is None:
            return False
        self._transcription_background_queue = []
        try:
            job.cancel()
        except Exception as exc:
            logging.error("[transcription] could not cancel the background job: %s",
                          transcription_errors.exception_report(exc))
        return True

    def _start_next_transcription_background_job(self, first=False) -> bool:
        make_job, status_text = self._transcription_background_queue.pop(0)
        try:
            job = make_job(None, self._post_transcription_background_finished)
            self._transcription_background_job = job
            job.start()
        except Exception as exc:
            logging.error("[transcription] the background job could not start: %s",
                          transcription_errors.exception_report(exc))
            self._transcription_background_job = None
            return False
        if first:
            status_text = f"{status_text} {self.i18n.t('transcription_background_started')}"
        self.output(status_text)
        return True

    def _post_transcription_background_finished(self, result, error) -> None:
        """On the job's thread: hop to the wx thread, touch nothing else."""
        wx.CallAfter(self._transcription_background_finished, result, error)

    def _transcription_background_finished(self, result, error) -> None:
        job = getattr(self, "_transcription_background_job", None)
        if job is None:
            return
        queue = self._transcription_background_queue
        if error is None:
            self._transcription_background_done += 1
        # Failure and cancellation both end the run.
        dropped = len(queue) if error is not None else 0
        if error is not None:
            del queue[:]
        last = not queue

        listeners = self.__dict__.get("_transcription_background_listeners", [])
        if last:
            self.__dict__.pop("_transcription_background_listeners", None)
            self._transcription_background_job = None
        said = False
        for listener in listeners:
            try:
                said = bool(listener(job, result, error, last)) or said
            except Exception as exc:
                logging.error("[transcription] a background listener raised: %s",
                              transcription_errors.exception_report(exc))
        if not said:
            self._say_transcription_background_outcome(job, result, error)

        if dropped:
            self.output(self.i18n.t("transcription_queue_stopped"))
        if last:
            if error is None and self._transcription_background_total > 1:
                self.output(self.i18n.t("transcription_queue_done").format(
                    count=self._transcription_background_done))
            return
        if not self._start_next_transcription_background_job():
            # The next job could not even be built: end the run like a failure.
            # The listeners were told "more to come" above, so they are told
            # it is over now (job None: no outcome of its own to report), or a
            # Settings tab would stay with every button off and a Cancel that
            # cancels nothing.
            self._transcription_background_queue = []
            ended = self.__dict__.pop("_transcription_background_listeners", [])
            for listener in ended:
                try:
                    listener(None, None, None, True)
                except Exception as exc:
                    logging.error("[transcription] a background listener raised: %s",
                                  transcription_errors.exception_report(exc))
            self.output(self.i18n.t("transcription_queue_stopped"))

    def _say_transcription_background_outcome(self, job, result, error) -> None:
        announcement = job.announcement(result, error)
        if announcement.outcome == management.OUTCOME_FAILED:
            try:
                self.error_sound.play()
            except Exception as exc:
                logging.warning("[transcription] could not play the error sound: %s",
                                transcription_errors.exception_report(exc))
        self.output(management_text.announcement_text(self.i18n, announcement))
