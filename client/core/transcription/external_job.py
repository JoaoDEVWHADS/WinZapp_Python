"""Checking a folder of the user's on its own thread, and what to say about it.

`external_models.accept_catalogue_folder()` hashes up to 3 GB and
`accept_custom_folder()` loads a model for tens of seconds: neither may run on
the wx thread, and both want the progress dialog and its Cancel that downloads
already have. `ExternalModelJob` has the shape `TranscriptionProgressDialog`
drives (`start()`, `cancel()`, `on_progress(tick)`, `on_finished(result,
error)` exactly once) and borrows `management`'s throttle and `Announcement`,
rather than adding two more actions to `ManagementJob`: that one is "act on a
model WinZapp owns" down to its remove button, and this is the opposite — a
folder WinZapp never writes to.

Nothing here imports wx. Like management.py, every callback runs on the worker
thread and the tab crosses to the wx thread through the progress dialog.

**What is said, and why it is not the stock sentences.** The stock
MODEL_CORRUPTED sentence says "download the model again", which for a folder of
somebody else's is both impossible and 3 GB of wrong advice, so a failure to
read or load such a folder has two sentences of its own (one per kind of
check). Every other code keeps its stock sentence: "the folder is not there"
and "not enough video memory" are true wherever the model lives. The log keeps
the technical line (`TranscriptionError.log_line`), as everywhere in this
package.
"""

from __future__ import annotations

import logging
import threading
import time

from coord_locks import LockTimeout
from core.transcription import (
    backend as backend_module,
    device,
    errors,
    external_ggml,
    external_models,
    external_view,
    management,
    precision,
)

#: Hash the folder as one of the catalogue's models, and remember it as that.
KIND_VERIFY = "verify"
#: Load the folder once with the backend, and remember it as a custom model.
KIND_CUSTOM = "custom"

KINDS = (KIND_VERIFY, KIND_CUSTOM)

ADDED_I18N_KEY = "transcription_external_added"
CHECKED_I18N_KEY = "transcription_external_checked"
CUSTOM_ADDED_I18N_KEY = "transcription_external_custom_added"
CUSTOM_CHECKED_I18N_KEY = "transcription_external_custom_checked"
CHANGED_WHILE_CHECKED_I18N_KEY = "transcription_external_changed_while_checked"
REFUSED_UNREACHABLE_I18N_KEY = "transcription_external_refused_unreachable"
REFUSED_NOT_A_MODEL_I18N_KEY = "transcription_external_refused_not_a_model"
REFUSED_BAD_CONFIG_I18N_KEY = "transcription_external_refused_bad_config"
REFUSED_INSIDE_ROOT_I18N_KEY = "transcription_external_refused_inside_root"
REFUSED_NOT_GGML_I18N_KEY = "transcription_external_refused_not_ggml"
READ_FAILED_I18N_KEY = "transcription_external_read_failed"
LOAD_FAILED_I18N_KEY = "transcription_external_load_failed"
NOT_ADDED_I18N_KEY = "transcription_external_not_added"

#: Every key `announcement()` can answer with, besides the error codes' own.
ANNOUNCEMENT_I18N_KEYS = (
    ADDED_I18N_KEY,
    CHECKED_I18N_KEY,
    CUSTOM_ADDED_I18N_KEY,
    CUSTOM_CHECKED_I18N_KEY,
    CHANGED_WHILE_CHECKED_I18N_KEY,
    REFUSED_UNREACHABLE_I18N_KEY,
    REFUSED_NOT_A_MODEL_I18N_KEY,
    REFUSED_BAD_CONFIG_I18N_KEY,
    REFUSED_INSIDE_ROOT_I18N_KEY,
    REFUSED_NOT_GGML_I18N_KEY,
    READ_FAILED_I18N_KEY,
    LOAD_FAILED_I18N_KEY,
    NOT_ADDED_I18N_KEY,
    management.CANCELLED_I18N_KEY,
)

#: The line the progress dialog shows (and speaks) while each kind runs.
STATUS_I18N_KEYS = {
    KIND_VERIFY: "transcription_external_progress_verify",
    KIND_CUSTOM: "transcription_external_progress_custom",
}

# What a refusal of the folder's shape is told as: four sentences, not six —
# a folder that is missing, is a file, or cannot be listed is "could not be
# opened" to somebody who has to act on it. Files that are missing are named;
# a config.json that is there and is not a model's configuration has its own
# sentence, since "missing: config.json" would send the user looking for a
# file they can see.
_REFUSAL_I18N_KEYS = {
    external_models.REFUSED_FOLDER_MISSING: REFUSED_UNREACHABLE_I18N_KEY,
    external_models.REFUSED_NOT_A_FOLDER: REFUSED_UNREACHABLE_I18N_KEY,
    external_models.REFUSED_UNREADABLE: REFUSED_UNREACHABLE_I18N_KEY,
    external_models.REFUSED_FILES_MISSING: REFUSED_NOT_A_MODEL_I18N_KEY,
    external_models.REFUSED_BAD_CONFIG: REFUSED_BAD_CONFIG_I18N_KEY,
    external_models.REFUSED_INSIDE_MODELS_ROOT: REFUSED_INSIDE_ROOT_I18N_KEY,
    # A file (whisper.cpp): one that is there and is empty cannot be a model.
    external_ggml.REFUSED_NOT_GGML: REFUSED_NOT_GGML_I18N_KEY,
}


class ExternalModelJob:
    """One check of one folder, on its own thread. Started once, never reused.

    `result` is the `external_models.AcceptOutcome`; `error` a
    `TranscriptionError`. `backend_id` is which kind of model `path` is for:
    whisper.cpp means a GGML *file*, checked by external_ggml; anything else a
    faster-whisper *folder*, as before part 9b. `device_preference` only
    matters to a faster-whisper KIND_CUSTOM, whose trial load has to run on
    the device the model will run on (see external_models.trial_load()) —
    decided here, on the worker, the way TranscriptionJob decides them;
    whisper.cpp's trial load always runs on its processor build.
    `compute_type_preference` is the precision chosen for faster-whisper
    (part 11), for the same reason: the trial loads the folder the way the
    run will, so a precision the folder cannot be loaded in is found here.
    `other_roots` is a models folder that is chosen in the settings dialog and
    not applied yet, refused like the one in force (see
    external_models.accept_catalogue_folder()).
    """

    def __init__(self, kind, app_settings, path, models_root,
                 device_preference=device.PREFERENCE_AUTO, backend_id=None,
                 on_progress=None, on_finished=None, throttle=None, clock=None,
                 other_roots=(), compute_type_preference=precision.AUTO):
        if kind not in KINDS:
            raise ValueError(f"unknown external model check: {kind!r}")
        self.kind = kind
        self.path = str(path)
        self._app_settings = app_settings
        self._models_root = models_root
        self._other_roots = tuple(other_roots)
        self._device_preference = device_preference
        self._compute_type_preference = compute_type_preference
        self._backend_id = backend_id
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._throttle = throttle or management.ProgressThrottle()
        self._clock = clock or time.monotonic
        self._cancelled = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="winzapp-transcription-external"
        )

    # ── Control ──────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        return self

    def cancel(self):
        """Ask the check to stop. Cooperative: it stops at the next check."""
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def announcement(self, result, error):
        """`announcement()` for this job's own kind and folder."""
        return announcement(
            self.kind, self.path, result, error,
            is_file=self._backend_id == backend_module.BACKEND_WHISPER_CPP,
        )

    # ── Worker ───────────────────────────────────────────────────────────────

    def _run(self):
        started = time.monotonic()
        try:
            result = self._perform()
        except errors.TranscriptionError as exc:
            self._finish(None, exc, started)
        except LockTimeout as exc:
            # app.json held by another account's process for the whole wait. The
            # sentence of "another window is busy, wait and try again" is the
            # true one; its code is about the models folder, but the answer to
            # both is the same and nothing is wrong with either.
            self._finish(
                None,
                errors.TranscriptionError(errors.MODELS_BUSY, f"app.json: {exc}"),
                started,
            )
        except Exception as exc:
            # Nothing above a worker thread catches anything, and the tab is
            # holding a progress dialog open until it hears back.
            logging.error(
                "[transcription] checking an external model failed unexpectedly: %s",
                errors.exception_report(exc),
            )
            self._finish(
                None,
                errors.TranscriptionError(
                    errors.BACKEND_ERROR, f"{type(exc).__name__}: {exc}"
                ),
                started,
            )
        else:
            self._finish(result, None, started)

    def _perform(self):
        # A cancel that arrived before the thread ran touches nothing.
        self._check_cancel()
        if self._backend_id == backend_module.BACKEND_WHISPER_CPP:
            if self.kind == KIND_VERIFY:
                return external_ggml.accept_ggml_file(
                    self._app_settings, self.path, self._models_root,
                    progress=self._report_progress, should_cancel=self._should_cancel,
                    other_roots=self._other_roots,
                )
            return external_ggml.accept_custom_ggml_file(
                self._app_settings, self.path, self._models_root,
                # get_backend(), not resolve_backend(): falling through to
                # faster-whisper would hand it a file it cannot read. Without
                # the program the trial says WHISPER_CPP_NOT_INSTALLED, which
                # is the sentence the user needs.
                backend_module.get_backend(self._backend_id),
                should_cancel=self._should_cancel, other_roots=self._other_roots,
            )
        if self.kind == KIND_VERIFY:
            return external_models.accept_catalogue_folder(
                self._app_settings, self.path, self._models_root,
                progress=self._report_progress, should_cancel=self._should_cancel,
                other_roots=self._other_roots,
            )
        # A folder is faster-whisper's whatever backend is selected: falling
        # through to another (resolve_backend()) would hand whisper-cli a
        # folder it cannot read and blame the folder. Then the decisions
        # TranscriptionJob._decode() makes before it loads: the device and
        # compute type against a fresh probe.
        backend = backend_module.get_backend(backend_module.BACKEND_FASTER_WHISPER)
        if backend is None or not backend.is_available():
            raise errors.TranscriptionError(
                errors.BACKEND_MISSING, "faster-whisper is not available for the trial load"
            )
        probe = device.probe_hardware()
        device_id, _reason = device.resolve_device(self._device_preference, probe)
        compute_type = backend.resolve_compute_type(
            self._compute_type_preference, device_id, probe
        ).compute_type
        return external_models.accept_custom_folder(
            self._app_settings, self.path, self._models_root, backend, device_id,
            compute_type, should_cancel=self._should_cancel,
            other_roots=self._other_roots,
        )

    def _finish(self, result, error, started):
        if error is None:
            outcome = getattr(result, "code", "done")
        elif error.code == errors.CANCELLED:
            outcome = "cancelled"
        else:
            outcome = "failed"
        logging.info(
            "[transcription] external model %s %s took=%.1fs%s",
            self.kind, outcome, time.monotonic() - started,
            f" — {error.log_line}" if error is not None else "",
        )
        self._call(self._on_finished, result, error)

    # ── Plumbing ─────────────────────────────────────────────────────────────

    def _report_progress(self, done, total):
        tick = self._throttle.update(done, total, self._clock())
        if tick.update_bar or tick.speak:
            self._call(self._on_progress, tick)

    def _call(self, callback, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            logging.error("[transcription] an external model callback raised: %s",
                          errors.exception_report(exc))

    def _should_cancel(self) -> bool:
        return self._cancelled.is_set()

    def _check_cancel(self):
        if self._cancelled.is_set():
            raise errors.TranscriptionError(errors.CANCELLED, "cancelled by the user")


# ── Outcome to sentence ──────────────────────────────────────────────────────


def announcement(kind, path, result=None, error=None,
                 is_file=False) -> management.Announcement:
    """What to tell the user once a check of `path` has finished.

    `result` is the AcceptOutcome and `error` the TranscriptionError of the
    job. The two outcomes that are neither success nor failure of the check —
    a folder no catalogue entry claims, and one with a catalogue model's sizes
    and other weights — come back as NOT_ADDED: the tab asks the question that
    follows them (use it as a custom model?) before saying anything, and this
    is what it says when the answer is no. `is_file` picks the sentences that
    say "file" (a whisper.cpp model) over the ones that say "folder".
    """
    said = _announcement(kind, path, result, error)
    return management.Announcement(
        external_view.for_reference(said.i18n_key, is_file), said.outcome,
        said.values,
    )


def _announcement(kind, path, result, error) -> management.Announcement:
    name = external_models.folder_name(path)
    if error is not None:
        return _error_announcement(kind, name, error)

    code = getattr(result, "code", None)
    reference = getattr(result, "reference", None)
    values = {"name": name, "model": getattr(reference, "model_id", None) or ""}
    refreshed = code == external_models.ACCEPT_UPDATED
    if code in (external_models.ACCEPT_ADDED, external_models.ACCEPT_UPDATED):
        if kind == KIND_CUSTOM:
            key = CUSTOM_CHECKED_I18N_KEY if refreshed else CUSTOM_ADDED_I18N_KEY
        else:
            key = CHECKED_I18N_KEY if refreshed else ADDED_I18N_KEY
        return management.Announcement(key, management.OUTCOME_DONE, values)
    if code == external_models.ACCEPT_CHANGED_WHILE_CHECKED:
        return management.Announcement(
            CHANGED_WHILE_CHECKED_I18N_KEY, management.OUTCOME_WARNING, values
        )
    if code in _REFUSAL_I18N_KEYS:
        shape = getattr(result, "shape", None)
        values["files"] = ", ".join(getattr(shape, "missing", ()) or ()) or "config.json"
        return management.Announcement(
            _REFUSAL_I18N_KEYS[code], management.OUTCOME_WARNING, values
        )
    return management.Announcement(NOT_ADDED_I18N_KEY, management.OUTCOME_WARNING, values)


def _error_announcement(kind, name, error) -> management.Announcement:
    code = getattr(error, "code", None)
    values = {"name": name}
    if code == errors.CANCELLED:
        return management.Announcement(
            management.CANCELLED_I18N_KEY, management.OUTCOME_CANCELLED
        )
    if code in (errors.MODEL_CORRUPTED, errors.BACKEND_ERROR) or code not in errors.ERROR_CODES:
        key = LOAD_FAILED_I18N_KEY if kind == KIND_CUSTOM else READ_FAILED_I18N_KEY
        return management.Announcement(key, management.OUTCOME_FAILED, values)
    return management.Announcement(
        errors.error_i18n_key(code), management.OUTCOME_FAILED,
        errors.error_i18n_values(code),
    )
