"""Downloading the marked models of the Transcription tab, one after another.

The marks are made with Ctrl+Space (transcription_model_marks.py); "Download"
with something marked fetches every marked model that is not complete yet
instead of only the one the list is on (core/transcription/model_queue.py).

One question covers the queue, sized as the sum, and then the models go in the
order the list shows them:

* **Behind the progress dialog** each model gets the dialog it always had, one
  after the other, and the first failure or cancellation ends the run: a
  download that failed for lack of disk would fail again for each of the rest.
* **In the background** the whole queue is handed to the main window as one run
  (main_window/transcription_background.py), which says each model as it ends.

A model that arrives is unmarked; the ones that did not stay marked, so pressing
Download again resumes the queue where it stopped.
"""

import wx

from core.transcription import management as transcription_management
from core.transcription import model_names, model_queue, model_store
from core.transcription import preferences as transcription_preferences
from ui.dialogs.transcription_tab import (
    _format_transcription_size,
)


def queue_confirmation_text(i18n, summary) -> str:
    """Everything the user is agreeing to for the whole queue. Pure."""
    lines = [
        i18n.t("transcription_confirm_queue").format(
            count=len(summary.model_ids),
            models=model_names.display_list(i18n, summary.model_ids),
        ),
        i18n.t("transcription_confirm_download_size").format(
            size=_format_transcription_size(i18n, summary.download_bytes)
        ),
        i18n.t("transcription_confirm_required_space").format(
            size=_format_transcription_size(i18n, summary.required_free_bytes)
        ),
    ]
    if summary.enough_space is None:
        lines.append(i18n.t("transcription_confirm_space_unknown"))
    elif summary.enough_space:
        lines.append(i18n.t("transcription_confirm_free_space").format(
            size=_format_transcription_size(i18n, summary.free_bytes)
        ))
    else:
        lines.append(i18n.t("transcription_confirm_not_enough_space").format(
            required=_format_transcription_size(i18n, summary.required_free_bytes),
            free=_format_transcription_size(i18n, summary.free_bytes),
        ))
    lines.append(i18n.t("transcription_confirm_destination").format(
        folder=summary.destination
    ))
    if summary.not_fitting:
        lines.append(i18n.t("transcription_confirm_queue_does_not_fit").format(
            models=model_names.display_list(i18n, summary.not_fitting)
        ))
    return "\n".join(lines)


class TranscriptionQueueMixin:
    """The queue of marked models, for `SettingsDialog`."""

    def _transcription_queue_to_download(self) -> list:
        """The marked models a Download would fetch, in list order."""
        return model_queue.queue_for(
            self._transcription_model_marks,
            self._transcription_model_ids,
            self._transcription_model_states,
        )

    def _start_transcription_queue(self) -> bool:
        """Begin a download of the marked models. False: nothing to queue."""
        queue = self._transcription_queue_to_download()
        if not queue:
            return False
        self._set_transcription_job_running(True)
        models_root = transcription_preferences.resolve_models_dir(
            self._transcription_models_dir
        )

        def _measured(probe):
            # On the probe's own thread: the disk query belongs there too.
            free = model_store.free_bytes(models_root)
            wx.CallAfter(self._confirm_transcription_queue, queue, probe, free)

        transcription_management.probe_in_background(_measured)
        return True

    def _confirm_transcription_queue(self, queue, probe, free_bytes) -> None:
        """Back on the wx thread with the measurements: ask once, then run."""
        if not self:
            return
        self._adopt_transcription_probe(probe)
        self._set_transcription_job_running(False)
        summary = model_queue.queue_download_summary(
            queue,
            transcription_preferences.resolve_models_dir(self._transcription_models_dir),
            probe, free_bytes, self._selected_transcription_device_preference(),
            whisper_cpp_cuda_installed=self._whisper_cpp_cuda_installed(),
            compute_type_preference=self._selected_transcription_precision()
            or transcription_preferences.AUTO,
        )
        if summary is None or not self._ask_transcription_queue(summary):
            return
        self._run_transcription_queue(list(summary.model_ids))

    def _ask_transcription_queue(self, summary) -> bool:
        i18n = self.main_window.i18n
        text = queue_confirmation_text(i18n, summary)
        title = i18n.t("transcription_download_confirm_title")
        if summary.enough_space is False:
            # Not a question, for the reason _ask_transcription_download() gives.
            wx.MessageBox(text, title, wx.OK | wx.ICON_ERROR, self)
            return False
        return wx.MessageBox(text, title, wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES

    def _run_transcription_queue(self, model_ids) -> None:
        action = transcription_management.ACTION_DOWNLOAD_MODEL
        if self._transcription_background_wanted(action):
            self._start_transcription_queue_in_background(model_ids)
            return
        done = 0
        for position, model_id in enumerate(model_ids):
            job, result, error = self._run_transcription_job(action, model_id=model_id)
            remaining = len(model_ids) - position - 1
            extra = ("transcription_queue_stopped",) if error is not None and remaining else ()
            self._after_transcription_job(job, result, error, extra_keys=extra,
                                          action=action, model_id=model_id)
            if error is not None:
                return
            done += 1
        if done > 1:
            self.main_window.speak_output.output(
                self.main_window.i18n.t("transcription_queue_done").format(count=done)
            )

    def _start_transcription_queue_in_background(self, model_ids) -> None:
        action = transcription_management.ACTION_DOWNLOAD_MODEL
        items = [
            (self._transcription_job_factory(action, model_id=model_id),
             self._transcription_status_text(action, model_id))
            for model_id in model_ids
        ]
        if not self.main_window.start_transcription_background_jobs(items):
            return
        self._enter_transcription_background_run()
