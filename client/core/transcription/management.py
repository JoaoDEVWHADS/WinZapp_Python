"""The settings tab's management actions, as logic the tab only has to wire.

Downloading, repairing, verifying and removing a model, moving the models
folder, and installing, repairing, verifying and removing the CUDA libraries:
model_store and cuda_runtime already do every one of these correctly. What
they cannot do is be *called from a settings tab* as they stand, and the gap
is four problems that each look small and each have a user on the other end:

* **They report progress per megabyte.** ~3000 calls for large-v3. One
  `wx.CallAfter` per call floods the UI thread, and one spoken percentage per
  call has the screen reader read numbers for the whole download. So progress
  goes through `ProgressThrottle`, which answers two questions separately —
  "is it time to move the bar?" and "is this worth saying out loud?" — because
  they have very different budgets.

* **The user has to know what they are agreeing to before the bytes start.**
  The issue asks for the model's name, the download size, the disk it needs,
  where it goes and whether it will run on the processor or the card — *before*
  a multi-gigabyte download. `model_download_summary()` and
  `cuda_runtime_download_summary()` put that together as data; the tab owns
  the wording.

* **They block, and some of them block for half an hour.** `ManagementJob` runs
  one action on its own thread in the shape `job.TranscriptionJob` already
  set: cooperative cancel, callbacks through a guard, and exactly one finished
  report whatever happens.

* **Their outcomes are not sentences, and several are not failures.** A removal
  that leaves the libraries behind because a transcription mapped them, an
  install whose card still cannot use what is on disk, a folder move that got
  three models across and not the other two, a cancellation: none of these is
  the error message the code would suggest. `announcement()` decides which
  sentence each one gets.

Nothing here imports wx — every callback runs on a worker thread and part 5c-2
wraps it in `wx.CallAfter`, the split core/message_queue.py and job.py make —
and nothing here retries on its own. The CUDA download cannot resume, so a
second attempt on a bad line is another 553 MB; whether that is worth it is
the user's call, not this module's.

What is whisper.cpp's own — its program's four actions, the voice-activity
model a GGML model brings, the figures of a program install and the sentences
about it — is in management_whisper_cpp.py, which `ManagementJob._perform()`
dispatches to.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time
from dataclasses import dataclass, field

# management_whisper_cpp imports this module too; neither reads the other's
# names before a function runs, which is what keeps the cycle harmless.
from core.transcription import (
    cuda_runtime,
    device,
    errors,
    management_whisper_cpp,
    model_store,
    precision,
    whisper_cpp_catalog,
)

# ── Actions ──────────────────────────────────────────────────────────────────

ACTION_DOWNLOAD_MODEL = "download_model"
ACTION_REPAIR_MODEL = "repair_model"
ACTION_VERIFY_MODEL = "verify_model"
ACTION_REMOVE_MODEL = "remove_model"
ACTION_MOVE_MODELS = "move_models"
ACTION_INSTALL_CUDA_RUNTIME = "install_cuda_runtime"
ACTION_REPAIR_CUDA_RUNTIME = "repair_cuda_runtime"
ACTION_VERIFY_CUDA_RUNTIME = "verify_cuda_runtime"
ACTION_REMOVE_CUDA_RUNTIME = "remove_cuda_runtime"
# The whisper.cpp program, one build at a time (`ManagementJob.build_id`).
ACTION_INSTALL_WHISPER_CPP = "install_whisper_cpp"
ACTION_REPAIR_WHISPER_CPP = "repair_whisper_cpp"
ACTION_VERIFY_WHISPER_CPP = "verify_whisper_cpp"
ACTION_REMOVE_WHISPER_CPP = "remove_whisper_cpp"

ACTIONS = (
    ACTION_DOWNLOAD_MODEL,
    ACTION_REPAIR_MODEL,
    ACTION_VERIFY_MODEL,
    ACTION_REMOVE_MODEL,
    ACTION_MOVE_MODELS,
    ACTION_INSTALL_CUDA_RUNTIME,
    ACTION_REPAIR_CUDA_RUNTIME,
    ACTION_VERIFY_CUDA_RUNTIME,
    ACTION_REMOVE_CUDA_RUNTIME,
    ACTION_INSTALL_WHISPER_CPP,
    ACTION_REPAIR_WHISPER_CPP,
    ACTION_VERIFY_WHISPER_CPP,
    ACTION_REMOVE_WHISPER_CPP,
)

WHISPER_CPP_ACTIONS = (
    ACTION_INSTALL_WHISPER_CPP,
    ACTION_REPAIR_WHISPER_CPP,
    ACTION_VERIFY_WHISPER_CPP,
    ACTION_REMOVE_WHISPER_CPP,
)

MODEL_ACTIONS = (
    ACTION_DOWNLOAD_MODEL,
    ACTION_REPAIR_MODEL,
    ACTION_VERIFY_MODEL,
    ACTION_REMOVE_MODEL,
)

# The code a failure nobody classified becomes, per action. Chosen for the
# sentence the user will hear, not for where the exception came from:
#
# * a download or repair that broke is "the download did not get through",
#   whichever of the two layers it broke in;
# * a move keeps MODEL_MOVE_FAILED, whose sentence ("the models are still in
#   the previous folder") is the true one — move_models() copies and verifies
#   before it deletes;
# * verifying and removing get BACKEND_ERROR, deliberately *not*
#   MODEL_CORRUPTED / CUDA_RUNTIME_CORRUPTED. Those say "your files are
#   damaged, download them again", and after a bug in a check that never
#   finished that advice costs up to 3 GB for nothing. announcement() gives
#   BACKEND_ERROR a management sentence of its own, since the stock one says
#   "during the transcription".
_FALLBACK_CODES = {
    ACTION_DOWNLOAD_MODEL: errors.MODEL_DOWNLOAD_FAILED,
    ACTION_REPAIR_MODEL: errors.MODEL_DOWNLOAD_FAILED,
    ACTION_VERIFY_MODEL: errors.BACKEND_ERROR,
    ACTION_REMOVE_MODEL: errors.BACKEND_ERROR,
    ACTION_MOVE_MODELS: errors.MODEL_MOVE_FAILED,
    ACTION_INSTALL_CUDA_RUNTIME: errors.CUDA_RUNTIME_DOWNLOAD_FAILED,
    ACTION_REPAIR_CUDA_RUNTIME: errors.CUDA_RUNTIME_DOWNLOAD_FAILED,
    ACTION_VERIFY_CUDA_RUNTIME: errors.BACKEND_ERROR,
    ACTION_REMOVE_CUDA_RUNTIME: errors.BACKEND_ERROR,
    ACTION_INSTALL_WHISPER_CPP: errors.WHISPER_CPP_DOWNLOAD_FAILED,
    ACTION_REPAIR_WHISPER_CPP: errors.WHISPER_CPP_DOWNLOAD_FAILED,
    ACTION_VERIFY_WHISPER_CPP: errors.BACKEND_ERROR,
    ACTION_REMOVE_WHISPER_CPP: errors.BACKEND_ERROR,
}

# ── Progress ─────────────────────────────────────────────────────────────────

#: The percentages worth saying out loud: the quarters, and deliberately not
#: the end.
#:
#: Every 1% is a hundred interruptions of whatever the user is reading, and
#: every 10% is still ten announcements in the few seconds a tiny model takes
#: on a fast line, each one talking over the last. Quarters are three: enough
#: to tell a working download from a stalled one on a 3 GB model (minutes
#: apart on a slow line), few enough to stay out of the way on a small one.
#: Anything finer is one keystroke away — the gauge is a normal control, NVDA
#: reads its value on demand and beeps as it moves.
#:
#: 100 is not a milestone because the last progress report is not the end.
#: The CUDA install reports INSTALL_BYTES/INSTALL_BYTES and only *then*
#: registers the directory and loads cuBLAS to find out whether the card can
#: use it — a user told "100%" there reaches for the next thing and is then
#: told, mid-probe, that the card still cannot. On every other action "100%"
#: lands on top of the finished sentence. The finished report is the
#: announcement of the end; the bar still goes to 100.
SPEECH_MILESTONES = (25, 50, 75)

#: How often the gauge may move. A `wx.CallAfter` every half second is nothing
#: to the UI thread, and it is still fine-grained enough that NVDA's
#: progress-bar beeps sound continuous rather than stuck.
BAR_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class ProgressTick:
    """One progress report that got past the throttle.

    `percent` is None when the total is unknown, and is never 100 before `done`
    has actually reached `total`. A tick at 100 moves the bar and is never
    spoken — see SPEECH_MILESTONES for why the end belongs to the finished
    report instead.
    """

    done: int
    total: int | None
    percent: int | None
    update_bar: bool
    speak: bool


def progress_percent(done, total):
    """Whole percent of `done` over `total`, rounded down; None if unknowable.

    Down, never to the nearest: 99.95% is 99, so "100" can only mean done.
    """
    try:
        done = int(done)
        total = int(total)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    if done <= 0:
        return 0
    return min(100, done * 100 // total)


class ProgressThrottle:
    """Decides which of thousands of progress reports reach the UI, and which
    of those reach the user's ears.

    Pure: the clock is an argument, which is what makes the interval testable
    without sleeping. One instance per action, used from one thread.

    **A milestone is said once, however the progress moves afterwards.**
    `done` can go backwards — model_store starts a file over when a server
    ignores the byte range, and a repair deletes before it downloads — and a
    user who has heard "75%" and then hears "25%" will reasonably conclude that
    something broke. So a regression moves the bar at once (the bar should show
    the truth) and says nothing; speech resumes only once progress passes the
    highest milestone already spoken.
    """

    def __init__(self, bar_interval=BAR_INTERVAL_SECONDS, milestones=SPEECH_MILESTONES):
        self._bar_interval = float(bar_interval)
        self._milestones = tuple(sorted({int(m) for m in milestones}))
        self._last_bar_at = None
        self._last_bar_percent = None
        self._last_done = None
        self._spoken = 0

    def update(self, done, total, now) -> ProgressTick:
        try:
            done = max(0, int(done))
        except (TypeError, ValueError):
            done = 0
        percent = progress_percent(done, total)
        known_total = int(total) if percent is not None else None

        regressed = self._last_done is not None and done < self._last_done
        self._last_done = done

        speak = False
        if percent is not None:
            crossed = [m for m in self._milestones if self._spoken < m <= percent]
            if crossed:
                # A jump over several milestones — a same-volume move is one
                # rename, 0% to 100% in a single report — is said once, at the
                # real figure, never as a string of numbers in a row. And not
                # at all when the jump lands on the end: that is the finished
                # report's to say, even for a caller that passed 100 in.
                self._spoken = crossed[-1]
                speak = percent < 100

        # The bar has to *reach* 100 even inside the interval: the last report
        # of an action is usually its only one at 100, and a gauge left at 97%
        # beside the sentence "downloaded" contradicts it.
        reached_end = percent == 100 and self._last_bar_percent != 100
        update_bar = (
            self._last_bar_at is None
            or now - self._last_bar_at >= self._bar_interval
            # A spoken number the gauge disagrees with is worse than an extra
            # repaint.
            or speak
            or regressed
            or reached_end
        )
        if update_bar:
            self._last_bar_at = now
            self._last_bar_percent = percent
        return ProgressTick(done, known_total, percent, update_bar, speak)


# ── The summary before a download ────────────────────────────────────────────

SUBJECT_MODEL = "model"
SUBJECT_CUDA_RUNTIME = "cuda_runtime"
SUBJECT_WHISPER_CPP = "whisper_cpp"


@dataclass(frozen=True)
class DownloadSummary:
    """What the user is told before agreeing to a download. Data, not text.

    `required_free_bytes` is what the free-space gate will actually demand
    (`model_store.required_free_bytes()`, slack included) and not the bare file
    sizes: quoting 3.0 GB to a user with 3.1 GB free and then refusing with "no
    disk space" is a contradiction they have no way to resolve.

    `enough_space` is None when the free space could not be measured, and the
    gate lets that through (see `model_store.ensure_free_space()`); the tab
    should say "unknown", not "enough".
    """

    subject: str
    model_id: str | None
    download_bytes: int
    #: What stays on disk once it is done.
    installed_bytes: int
    required_free_bytes: int
    free_bytes: int | None
    enough_space: bool | None
    destination: str
    #: Where a transcription would run once this is installed, and why.
    device: str
    device_reason: str
    #: False for the CUDA libraries: a cancelled or dropped transfer starts from
    #: zero next time, which is 553 MB the user should know about beforehand.
    resumable: bool
    #: Whether the model fits the memory of that device, headroom included.
    #: None when unmeasured, and always None for the CUDA libraries.
    fits_memory: bool | None = None
    #: For a repair: what the removal frees before the gate is asked, and
    #: therefore already counted in `enough_space`. 0 otherwise.
    freed_bytes: int = 0
    #: SUBJECT_WHISPER_CPP: the build being installed (`RuntimeBuild.id`).
    build_id: str | None = None
    #: SUBJECT_WHISPER_CPP: the processor build comes first, in the same
    #: action, because the graphics build is never installed without it (see
    #: `management_whisper_cpp.perform_program()`); its download is counted
    #: in the figures.
    includes_cpu_build: bool = False


def model_download_summary(model_id, models_root, probe, free_bytes,
                           device_preference=device.PREFERENCE_AUTO,
                           repair=False, whisper_cpp_cuda_installed=False,
                           compute_type_preference=precision.AUTO):
    """The summary for downloading (or repairing) `model_id`, or None.

    `probe` is a `device.HardwareProbe` and `free_bytes` is
    `model_store.free_bytes(models_root)`; both are taken by the caller —
    the probe through `probe_in_background()` — because measuring either here
    would put driver and disk-query I/O back on the UI thread. What *is* read
    here is the size of the model's own few files, through
    `model_store.remaining_download_bytes()`: the same call the gate makes, so
    a resumed download is quoted at what it will actually fetch.

    `repair=True` quotes `repair_model()` instead, which is a different
    transfer: it deletes everything and fetches the whole model, so nothing on
    disk is discounted from the download — a model with every file present and
    the wrong digest would otherwise be quoted at 0 bytes — and the gate runs
    *after* the removal, so what the removal frees counts towards the space.
    That freed figure is the files at their catalogued size only, a lower bound
    (a half-written file frees something too), which errs toward "not enough"
    by at most the leftovers of an interrupted download.

    None for an id the catalogue does not know, the same answer
    `model_catalog.get_model()` gives. A GGML id of whisper.cpp's is known
    too: its figures include the voice-activity model when that is not on disk
    yet, and its device is whisper.cpp's (`whisper_cpp_cuda_installed` is
    whether that program's graphics-card build is installed).

    `compute_type_preference` is the precision chosen for faster-whisper
    (part 11): "does it fit" is measured in the precision the model will load
    with, which is not the catalogue's when the user chose one.
    """
    model = _model_entry(model_id)
    if model is None:
        return None
    if repair:
        download = model.download_bytes
        freed = model_store.installation_state(models_root, model).present_bytes
    else:
        download = model_store.remaining_download_bytes(models_root, model)
        freed = 0
    compute_type = None
    if management_whisper_cpp.is_ggml(model):
        extra, device_id, reason = management_whisper_cpp.ggml_download_figures(
            models_root, probe, device_preference, repair, whisper_cpp_cuda_installed
        )
        download += extra
    else:
        device_id, reason = device.resolve_device(device_preference, probe)
        compute_type = precision.memory_compute_type(
            compute_type_preference, device_id, probe
        )
    budget = device.available_memory_mb(probe, device_id)
    required = model_store.required_free_bytes(download)
    return DownloadSummary(
        subject=SUBJECT_MODEL,
        model_id=model.id,
        download_bytes=download,
        installed_bytes=model.disk_bytes,
        required_free_bytes=required,
        free_bytes=free_bytes,
        enough_space=_enough_space(free_bytes, freed, required),
        destination=model_store.model_dir(models_root, model.id),
        device=device_id,
        device_reason=reason,
        resumable=True,
        fits_memory=(None if budget is None
                     else device.model_fits(model, budget, device_id, compute_type)),
        freed_bytes=freed,
    )


def cuda_runtime_download_summary(probe, free_bytes, directory=None,
                                  device_preference=device.PREFERENCE_AUTO,
                                  repair=False):
    """The summary for installing (or repairing) the CUDA libraries.

    The device is the answer *after* the install, which is the one the user is
    deciding about: the same probe with the libraries assumed loadable. On a
    machine with no card that is still the processor, and with the preference
    set to the processor it is the processor too — both worth hearing before
    553 MB, not after.

    `repair=True` counts what `repair_cuda_runtime()` removes before its gate
    runs — the sizes of `cuda_runtime.INSTALLED_FILES` on disk — as free.
    """
    destination = directory or cuda_runtime.default_cuda_runtime_dir()
    device_id, reason = device.resolve_device(
        device_preference, dataclasses.replace(probe, cuda_libraries_ok=True)
    )
    freed = _sizes_on_disk(destination, cuda_runtime.INSTALLED_FILES) if repair else 0
    # The peak, not the final size: the wheel is still on disk while the
    # libraries are unpacked out of it, which is what the install's own gate
    # measures against.
    required = model_store.required_free_bytes(cuda_runtime.INSTALL_BYTES)
    return DownloadSummary(
        subject=SUBJECT_CUDA_RUNTIME,
        model_id=None,
        download_bytes=cuda_runtime.WHEEL_BYTES,
        installed_bytes=cuda_runtime.EXTRACTED_BYTES,
        required_free_bytes=required,
        free_bytes=free_bytes,
        enough_space=_enough_space(free_bytes, freed, required),
        destination=destination,
        device=device_id,
        device_reason=reason,
        resumable=False,
        freed_bytes=freed,
    )


def _model_entry(model_id):
    """A transcription model of either catalogue (never the VAD), or None."""
    entry = model_store.find_entry(model_id)
    if entry is whisper_cpp_catalog.VAD_MODEL:
        return None
    return entry


def _enough_space(free_bytes, freed_bytes, required_bytes):
    if free_bytes is None:
        return None
    return int(free_bytes) + int(freed_bytes) >= required_bytes


def _sizes_on_disk(directory, names) -> int:
    total = 0
    for name in names:
        try:
            total += os.path.getsize(os.path.join(directory, name))
        except OSError:
            continue
    return total


# ── Running one action ───────────────────────────────────────────────────────


class ManagementJob:
    """One management action on its own thread. Started once, never reused.

    `on_progress(tick)` receives only the `ProgressTick`s the throttle let
    through, and `on_finished(result, error)` is called exactly once: `result`
    is what the model_store / cuda_runtime function returned, `error` a
    `TranscriptionError` — never both, and never neither.
    """

    def __init__(self, action, models_root=None, model_id=None,
                 new_models_root=None, cuda_directory=None, session=None,
                 on_progress=None, on_finished=None, throttle=None, clock=None,
                 build_id=None, runtime_root=None, compute_capability=None):
        if action not in ACTIONS:
            # A caller bug, raised on the caller's thread where it is seen at
            # once — not a report the user would have to sit through.
            raise ValueError(f"unknown management action: {action!r}")
        self.action = action
        self.model_id = model_id
        self._models_root = models_root
        self._new_models_root = new_models_root
        self._cuda_directory = cuda_directory
        #: For the whisper.cpp actions: which build, where the builds live
        #: (None: whisper_cpp_runtime's own folder) and the card's compute
        #: capability, which the install refuses the graphics build without.
        self.build_id = build_id
        self._runtime_root = runtime_root
        self._compute_capability = compute_capability
        # A test's fake HTTP session; production leaves it None and the store
        # opens its own through tls_trust.
        self._session = session
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._throttle = throttle or ProgressThrottle()
        self._clock = clock or time.monotonic

        self._cancelled = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="winzapp-transcription-manage"
        )

        #: For ACTION_MOVE_MODELS: every model with anything in the old folder
        #: just before the move began. `exc.moved` says which crossed; this is
        #: what lets announcement() also say which stayed behind — after a
        #: failed or cancelled move the models are split across two folders,
        #: and the user has to be told where each one is.
        #:
        #: Read *before* move_models() takes the models lock, and that window
        #: is accepted rather than closed: holding the lock from here would
        #: mean reaching into model_store's private lock helper. What it can
        #: cost is bounded — another account's process adding or removing a
        #: model in the old folder in those few milliseconds leaves that one
        #: model missing from, or wrongly named in, the "still in the previous
        #: folder" list. The models themselves are moved or kept correctly
        #: either way; move_models() plans under its own lock.
        self.models_before_move = ()

    # ── Control ──────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        return self

    def cancel(self):
        """Ask the action to stop. Cooperative: it stops at the next check."""
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def announcement(self, result, error):
        """`announcement()` for this job's own action and context."""
        return announcement(
            self.action, result, error,
            model_id=self.model_id,
            models_before_move=self.models_before_move,
            build_id=self.build_id,
        )

    # ── Worker ───────────────────────────────────────────────────────────────

    def _run(self):
        started = time.monotonic()
        try:
            result = self._perform()
        except errors.TranscriptionError as exc:
            self._finish(None, exc, started)
        except Exception as exc:
            # Nothing above a worker thread catches anything, and the tab is
            # holding a progress dialog open until it hears back.
            # The report, not logging.exception(): the same chain and frames,
            # through the one funnel every module of the issue logs an
            # exception by, so what may not reach the log (a media file name,
            # the message id) is decided in one place — errors.py.
            logging.error(
                "[transcription] management action %s failed unexpectedly: %s",
                self.action, errors.exception_report(exc),
            )
            self._finish(
                None,
                errors.TranscriptionError(
                    _FALLBACK_CODES[self.action], f"{type(exc).__name__}: {exc}"
                ),
                started,
            )
        else:
            self._finish(result, None, started)

    def _perform(self):
        # A cancel that arrived before the thread ran must not touch the disk
        # at all — least of all start a removal.
        self._check_cancel()
        action = self.action
        progress = self._report_progress
        cancel = self._should_cancel

        if action == ACTION_REMOVE_MODEL:
            # By id, not by catalogue entry: remove_model() itself answers an
            # id the catalogue dropped with "nothing removed", which is true.
            return model_store.remove_model(
                self._models_root, self.model_id, should_cancel=cancel
            )
        if action in WHISPER_CPP_ACTIONS:
            return management_whisper_cpp.perform_program(
                action, self.build_id, self._runtime_root, self._models_root,
                self._compute_capability, self._session, progress, cancel,
            )
        if action in MODEL_ACTIONS:
            model = _model_entry(self.model_id)
            if model is None:
                # Not the action's fallback: for a download that is "check
                # your connection", and nothing was ever sent over it. A
                # settings file naming a model this version dropped is what
                # this is, and "not installed" is the sentence
                # model_store.ensure_ready() already gives that case.
                raise errors.TranscriptionError(
                    errors.MODEL_NOT_INSTALLED, f"unknown model id {self.model_id}"
                )
            if management_whisper_cpp.is_ggml(model):
                return management_whisper_cpp.perform_ggml(
                    action, model, self._models_root, self._session, progress, cancel
                )
            if action == ACTION_DOWNLOAD_MODEL:
                return model_store.download_model(
                    model, self._models_root, progress=progress,
                    should_cancel=cancel, session=self._session,
                )
            if action == ACTION_REPAIR_MODEL:
                return model_store.repair_model(
                    model, self._models_root, progress=progress,
                    should_cancel=cancel, session=self._session,
                )
            return model_store.verify_model(
                self._models_root, model, progress=progress, should_cancel=cancel
            )

        if action == ACTION_MOVE_MODELS:
            self.models_before_move = _models_present(self._models_root)
            return model_store.move_models(
                self._models_root, self._new_models_root,
                progress=progress, should_cancel=cancel,
            )

        if action == ACTION_INSTALL_CUDA_RUNTIME:
            return cuda_runtime.install_cuda_runtime(
                self._cuda_directory, progress=progress,
                should_cancel=cancel, session=self._session,
            )
        if action == ACTION_REPAIR_CUDA_RUNTIME:
            return cuda_runtime.repair_cuda_runtime(
                self._cuda_directory, progress=progress,
                should_cancel=cancel, session=self._session,
            )
        if action == ACTION_VERIFY_CUDA_RUNTIME:
            return cuda_runtime.verify_installation(
                self._cuda_directory, progress=progress, should_cancel=cancel
            )
        return cuda_runtime.remove_cuda_runtime(
            self._cuda_directory, should_cancel=cancel
        )

    def _finish(self, result, error, started):
        if error is None:
            outcome = "done"
        elif error.code == errors.CANCELLED:
            outcome = "cancelled"
        else:
            outcome = "failed"
        logging.info(
            "[transcription] management %s %s model=%s took=%.1fs%s",
            self.action,
            outcome,
            self.model_id or self.build_id,
            time.monotonic() - started,
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
            # A callback that raises must cost neither the rest of the action
            # nor the finished report the tab is waiting on.
            logging.error("[transcription] a management callback raised: %s",
                          errors.exception_report(exc))

    def _should_cancel(self) -> bool:
        return self._cancelled.is_set()

    def _check_cancel(self):
        if self._cancelled.is_set():
            raise errors.TranscriptionError(errors.CANCELLED, "cancelled by the user")


def _models_present(root):
    """Ids with anything of theirs under `root`, in catalogue order."""
    return tuple(
        model.id
        for model in model_store.all_entries()
        if model_store.installation_state(root, model).state != model_store.STATE_ABSENT
    )


# ── Probing off the UI thread ────────────────────────────────────────────────


def probe_in_background(on_done, probe=None) -> threading.Thread:
    """Run the hardware probe on its own thread; hand the answer to `on_done`.

    The first `device.probe_hardware()` of a process was measured at 0.67 s on a
    machine with *no* graphics card — the ctranslate2 import alone — and on the
    UI thread that is 0.67 s in which NVDA cannot query the tab control the user
    just switched to. The tab wraps `on_done` in `wx.CallAfter`.

    `on_done(probe)` is called exactly once. `probe_hardware()` promises never
    to raise, but a probe that did would otherwise leave the tab waiting for
    an answer forever, so a failure delivers an empty `HardwareProbe` — every
    field unknown, which is the honest answer and one every decision function
    already handles.
    """
    measure = probe or device.probe_hardware

    def _run():
        try:
            answer = measure()
        except Exception as exc:
            logging.error("[transcription] the background hardware probe raised: %s",
                          errors.exception_report(exc))
            answer = device.HardwareProbe(
                driver_error=f"probe: {errors.scrub_media_names(str(exc))}"
            )
        try:
            on_done(answer)
        except Exception as exc:
            logging.error("[transcription] the probe callback raised: %s",
                          errors.exception_report(exc))

    thread = threading.Thread(target=_run, daemon=True, name="winzapp-transcription-probe")
    thread.start()
    return thread


# ── Outcome to sentence ──────────────────────────────────────────────────────

OUTCOME_DONE = "done"
# Finished without an error, and still not what the user asked for: the
# libraries that stayed behind, the card that still cannot use what was
# installed. The tab should not play the success sound for these.
OUTCOME_WARNING = "warning"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_FAILED = "failed"

CANCELLED_I18N_KEY = "transcription_manage_cancelled"
FAILED_I18N_KEY = "transcription_manage_failed"
MODEL_DOWNLOADED_I18N_KEY = "transcription_manage_model_downloaded"
MODEL_REPAIRED_I18N_KEY = "transcription_manage_model_repaired"
MODEL_VERIFIED_I18N_KEY = "transcription_manage_model_verified"
MODEL_REMOVED_I18N_KEY = "transcription_manage_model_removed"
MODEL_NOTHING_TO_REMOVE_I18N_KEY = "transcription_manage_model_nothing_to_remove"
MODELS_MOVED_I18N_KEY = "transcription_manage_models_moved"
MODELS_NOTHING_TO_MOVE_I18N_KEY = "transcription_manage_models_nothing_to_move"
MODELS_MOVE_PARTIAL_I18N_KEY = "transcription_manage_models_move_partial"
MODELS_MOVE_CANCELLED_PARTIAL_I18N_KEY = "transcription_manage_models_move_cancelled_partial"
MODELS_MOVE_NO_SPACE_I18N_KEY = "transcription_manage_models_move_no_space"
MODELS_MOVE_PARTIAL_NO_SPACE_I18N_KEY = "transcription_manage_models_move_partial_no_space"
CUDA_INSTALLED_I18N_KEY = "transcription_manage_cuda_installed"
CUDA_INSTALLED_UNVERIFIED_I18N_KEY = "transcription_manage_cuda_installed_unverified"
CUDA_INSTALLED_NOT_USABLE_I18N_KEY = "transcription_manage_cuda_installed_not_usable"
CUDA_VERIFIED_I18N_KEY = "transcription_manage_cuda_verified"
CUDA_REMOVED_I18N_KEY = "transcription_manage_cuda_removed"
CUDA_REMOVE_NEEDS_RESTART_I18N_KEY = "transcription_manage_cuda_remove_needs_restart"
#: Every key announcement() can answer with, besides the error codes' own and
#: management_whisper_cpp.ANNOUNCEMENT_I18N_KEYS.
ANNOUNCEMENT_I18N_KEYS = (
    CANCELLED_I18N_KEY,
    FAILED_I18N_KEY,
    MODEL_DOWNLOADED_I18N_KEY,
    MODEL_REPAIRED_I18N_KEY,
    MODEL_VERIFIED_I18N_KEY,
    MODEL_REMOVED_I18N_KEY,
    MODEL_NOTHING_TO_REMOVE_I18N_KEY,
    MODELS_MOVED_I18N_KEY,
    MODELS_NOTHING_TO_MOVE_I18N_KEY,
    MODELS_MOVE_PARTIAL_I18N_KEY,
    MODELS_MOVE_CANCELLED_PARTIAL_I18N_KEY,
    MODELS_MOVE_NO_SPACE_I18N_KEY,
    MODELS_MOVE_PARTIAL_NO_SPACE_I18N_KEY,
    CUDA_INSTALLED_I18N_KEY,
    CUDA_INSTALLED_UNVERIFIED_I18N_KEY,
    CUDA_INSTALLED_NOT_USABLE_I18N_KEY,
    CUDA_VERIFIED_I18N_KEY,
    CUDA_REMOVED_I18N_KEY,
    CUDA_REMOVE_NEEDS_RESTART_I18N_KEY,
)

#: What joins the model ids of a move's sentence. Ids, not names: this module
#: does not format text, and a GGML id is no name ("ggml-small-q5_1"). The tab
#: splits on it and says each id as the picker names it
#: (model_names.display_list()); an id never contains it.
LIST_SEPARATOR = ", "


@dataclass(frozen=True)
class Announcement:
    """The sentence for a finished action: `i18n.t(key).format(**values)`."""

    i18n_key: str
    outcome: str
    values: dict = field(default_factory=dict)


def announcement(action, result=None, error=None, model_id=None,
                 models_before_move=(), build_id=None) -> Announcement:
    """What to tell the user once `action` has finished.

    `result` and `error` are exactly what `ManagementJob`'s `on_finished`
    received; `models_before_move` is that job's attribute of the same name,
    and `ManagementJob.announcement()` passes both for you. For the
    whisper.cpp actions the values carry `build`: the build's *i18n key*
    (management_whisper_cpp.WHISPER_CPP_BUILD_I18N_KEYS), which the UI
    translates before formatting — this module does not format text.
    """
    if error is not None:
        return _error_announcement(action, error, models_before_move)

    model_values = {"model": str(model_id or "")}

    if action == ACTION_DOWNLOAD_MODEL:
        return Announcement(MODEL_DOWNLOADED_I18N_KEY, OUTCOME_DONE, model_values)
    if action == ACTION_REPAIR_MODEL:
        return Announcement(MODEL_REPAIRED_I18N_KEY, OUTCOME_DONE, model_values)
    if action == ACTION_VERIFY_MODEL:
        return Announcement(MODEL_VERIFIED_I18N_KEY, OUTCOME_DONE, model_values)
    if action == ACTION_REMOVE_MODEL:
        # remove_model()'s False is "there was nothing to delete" and nothing
        # else — a busy folder raises — so it is safe to say so.
        key = MODEL_REMOVED_I18N_KEY if result else MODEL_NOTHING_TO_REMOVE_I18N_KEY
        return Announcement(key, OUTCOME_DONE, model_values)

    if action == ACTION_MOVE_MODELS:
        moved = _listed(result)
        if not moved:
            return Announcement(MODELS_NOTHING_TO_MOVE_I18N_KEY, OUTCOME_DONE)
        return Announcement(
            MODELS_MOVED_I18N_KEY, OUTCOME_DONE,
            {"models": LIST_SEPARATOR.join(moved)},
        )

    if action in (ACTION_INSTALL_CUDA_RUNTIME, ACTION_REPAIR_CUDA_RUNTIME):
        ok = result[0] if isinstance(result, (tuple, list)) and result else None
        if ok is True:
            return Announcement(CUDA_INSTALLED_I18N_KEY, OUTCOME_DONE)
        if ok is False:
            # The libraries are on disk and verified — freshly downloaded, or
            # already there, in which case install_cuda_runtime() fetched
            # nothing — and the loader still says no. So the sentence says
            # "installed", never "downloaded"; not "check your connection",
            # since this is not a transfer failure; and not "download them in
            # the settings", which is the screen the user is already on and
            # the button they just pressed. What is left that they can act on
            # is the driver: cuBLAS 12.9 refuses a driver too old for it.
            return Announcement(CUDA_INSTALLED_NOT_USABLE_I18N_KEY, OUTCOME_WARNING)
        # The loader could not be asked at all (probe_cuda_libraries()'s None).
        # Claiming the card works now would be inventing an answer.
        return Announcement(CUDA_INSTALLED_UNVERIFIED_I18N_KEY, OUTCOME_WARNING)

    if action == ACTION_VERIFY_CUDA_RUNTIME:
        return Announcement(CUDA_VERIFIED_I18N_KEY, OUTCOME_DONE)

    if action in WHISPER_CPP_ACTIONS:
        return management_whisper_cpp.announcement(action, result, build_id)

    if action == ACTION_REMOVE_CUDA_RUNTIME:
        if result:
            # The expected result after any transcription ran on the card:
            # Windows does not unlink a DLL mapped into this process. And
            # nothing finishes the removal on its own at the next launch —
            # cuda_runtime explains why a startup sweep cannot tell a leftover
            # from an install — so the sentence has to ask for the button
            # again after the restart, not promise the restart does it.
            return Announcement(CUDA_REMOVE_NEEDS_RESTART_I18N_KEY, OUTCOME_WARNING)
        return Announcement(CUDA_REMOVED_I18N_KEY, OUTCOME_DONE)

    # An action this function was never taught. Saying "done" about something
    # we cannot describe would be a guess.
    return Announcement(FAILED_I18N_KEY, OUTCOME_FAILED)


def _listed(model_ids):
    """The ids a move's sentence names: every one but the voice-activity
    model's, which moves with the models and is nobody's choice — a folder
    holding nothing else had no models to move, as far as the user knows."""
    return tuple(
        model_id for model_id in (model_ids or ())
        if model_id != whisper_cpp_catalog.VAD_MODEL.id
    )


def _error_announcement(action, error, models_before_move):
    code = getattr(error, "code", None)

    if action == ACTION_MOVE_MODELS:
        moved = _listed(getattr(error, "moved", ()))
        remaining = tuple(m for m in _listed(models_before_move) if m not in moved)
        if moved and remaining:
            # Cancelled or failed, the models are now split across two folders
            # and only one of them is the folder the setting names. Which ones
            # are where is the one thing the user needs, and it outranks
            # "cancelled" as much as it outranks the error code — though a
            # full disk, the one reason the user can act on, is repeated.
            values = {
                "moved": LIST_SEPARATOR.join(moved),
                "remaining": LIST_SEPARATOR.join(remaining),
            }
            if code == errors.CANCELLED:
                return Announcement(
                    MODELS_MOVE_CANCELLED_PARTIAL_I18N_KEY, OUTCOME_CANCELLED, values
                )
            if code == errors.NO_DISK_SPACE:
                return Announcement(
                    MODELS_MOVE_PARTIAL_NO_SPACE_I18N_KEY, OUTCOME_FAILED, values
                )
            return Announcement(MODELS_MOVE_PARTIAL_I18N_KEY, OUTCOME_FAILED, values)
        if moved:
            # Everything that was there crossed and the move still raised. Not
            # a path move_models() has — a model is appended only after its
            # source is gone — but MODEL_MOVE_FAILED's own sentence ("the
            # models are still in the previous folder") would be false here, so
            # it does not get it.
            if code == errors.CANCELLED:
                return Announcement(CANCELLED_I18N_KEY, OUTCOME_CANCELLED)
            return Announcement(FAILED_I18N_KEY, OUTCOME_FAILED)
        if code == errors.NO_DISK_SPACE:
            # The stock sentence says "for this download", spoken right after
            # the user asked to move a folder.
            return Announcement(MODELS_MOVE_NO_SPACE_I18N_KEY, OUTCOME_FAILED)

    if code == errors.CANCELLED:
        # Its own key: transcription_error_cancelled says "transcription
        # cancelled", and nothing was being transcribed.
        return Announcement(CANCELLED_I18N_KEY, OUTCOME_CANCELLED)
    if code == errors.BACKEND_ERROR or code not in errors.ERROR_CODES:
        # The stock BACKEND_ERROR sentence says "during the transcription".
        return Announcement(FAILED_I18N_KEY, OUTCOME_FAILED)
    # Everything else already has the right sentence, CUDA_RUNTIME_IN_USE's
    # "close and reopen WinZapp" among them.
    return Announcement(errors.error_i18n_key(code), OUTCOME_FAILED,
                        errors.error_i18n_values(code))
