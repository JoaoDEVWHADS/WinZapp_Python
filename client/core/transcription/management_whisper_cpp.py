"""The whisper.cpp half of the settings tab's management actions (part 9b).

`management.ManagementJob` runs every action on its own thread, throttles its
progress and reports it once; what is whisper.cpp's own is decided here, and
`ManagementJob._perform()` dispatches to it:

* **The program, one build at a time.** The processor build is the floor
  everything else stands on (WhisperCppBackend.is_available()), so the
  graphics build is never left on the machine without it: installing it
  installs the processor build first when that is missing, and removing the
  processor build removes the graphics one with it.
* **A GGML model brings the voice-activity model with it.** The filter's model
  (885 KB, whisper_cpp_catalog.VAD_MODEL) is what keeps whisper.cpp from
  inventing a last sentence in the silence a voice note ends with. It is
  shared by every GGML model, never removed with one — and installing the
  program fetches it too, once the program is in, since a user who only points
  WinZapp at a GGML file of their own would otherwise never get it. A check or
  a repair fetches it when an earlier install did not.
* **The sentences and the figures**: what is said once an action on the
  program finished, and what an install costs before it starts.

The two modules import each other, and that is safe for one reason that must
stay true: neither reads the other's names at import time, only inside
functions.
"""

from __future__ import annotations

import logging

from core.transcription import (
    device,
    errors,
    management,
    model_store,
    whisper_cpp_builds,
    whisper_cpp_catalog,
    whisper_cpp_runtime,
)

WHISPER_CPP_INSTALLED_I18N_KEY = "transcription_manage_whisper_cpp_installed"
WHISPER_CPP_VERIFIED_I18N_KEY = "transcription_manage_whisper_cpp_verified"
WHISPER_CPP_REMOVED_I18N_KEY = "transcription_manage_whisper_cpp_removed"
WHISPER_CPP_REMOVE_IN_USE_I18N_KEY = "transcription_manage_whisper_cpp_remove_in_use"

#: How each build is named inside those sentences ("{build}"): "for the
#: processor" / "for the graphics card", in each locale's own word order.
WHISPER_CPP_BUILD_I18N_KEYS = {
    whisper_cpp_builds.BUILD_CPU.id: "transcription_whisper_cpp_build_cpu",
    whisper_cpp_builds.BUILD_CUDA.id: "transcription_whisper_cpp_build_cuda",
}

#: Every key announcement() can answer with.
ANNOUNCEMENT_I18N_KEYS = (
    WHISPER_CPP_INSTALLED_I18N_KEY,
    WHISPER_CPP_VERIFIED_I18N_KEY,
    WHISPER_CPP_REMOVED_I18N_KEY,
    WHISPER_CPP_REMOVE_IN_USE_I18N_KEY,
)


def build(build_id):
    """The `RuntimeBuild` with this id, or None."""
    for candidate in whisper_cpp_builds.BUILDS:
        if candidate.id == build_id:
            return candidate
    return None


def is_ggml(model) -> bool:
    """Whether a catalogue entry is one of whisper.cpp's GGML model files."""
    return model in whisper_cpp_catalog.MODELS


# ── What it costs ────────────────────────────────────────────────────────────


def ggml_download_figures(models_root, probe, device_preference, repair,
                          cuda_build_installed):
    """(extra download bytes, device, reason) of a GGML model's summary.

    The voice-activity model comes with a GGML model (see perform_ggml()), so
    what it costs is quoted with it; and the device is whisper.cpp's
    (`device.resolve_whisper_cpp_device()`).
    """
    vad = whisper_cpp_catalog.VAD_MODEL
    extra = (vad.download_bytes if repair
             else model_store.remaining_download_bytes(models_root, vad))
    device_id, reason = device.resolve_whisper_cpp_device(
        device_preference, probe, cuda_build_installed
    )
    return extra, device_id, reason


def whisper_cpp_download_summary(build_id, probe, free_bytes, installed_build_ids=(),
                                 device_preference=device.PREFERENCE_AUTO,
                                 repair=False, directory=None):
    """The summary for installing (or repairing) one whisper.cpp build, or None.

    `installed_build_ids` are the builds already installed. Installing the
    graphics-card build without the processor one installs both, and both are
    quoted. The free space is the install's own gate — the zip plus up to three
    times that unpacked (whisper_cpp_runtime) — which errs high, the safe side
    for a gate; a repair counts nothing as freed, since the build's folder is
    only emptied once the new one is in place. Nothing resumes: an interrupted
    download starts over, which the user hears before agreeing. The device is
    the one a transcription would use once this is installed. The
    voice-activity model the install also fetches (885 KB) is not quoted: it
    goes to the models folder, maybe on another drive, which this gate does
    not measure — and the install does not depend on it (perform_program()).
    """
    chosen = build(build_id)
    if chosen is None:
        return None
    installed = set(installed_build_ids)
    with_cpu = chosen.uses_cuda and whisper_cpp_builds.BUILD_CPU.id not in installed
    download = chosen.archive_bytes + (
        whisper_cpp_builds.BUILD_CPU.archive_bytes if with_cpu else 0
    )
    required = model_store.required_free_bytes(
        download * whisper_cpp_runtime.INSTALL_SPACE_FACTOR
    )
    cuda_after = chosen.uses_cuda or whisper_cpp_builds.BUILD_CUDA.id in installed
    device_id, reason = device.resolve_whisper_cpp_device(device_preference, probe, cuda_after)
    root = directory or whisper_cpp_runtime.default_runtime_dir()
    return management.DownloadSummary(
        subject=management.SUBJECT_WHISPER_CPP,
        model_id=None,
        download_bytes=download,
        installed_bytes=download,
        required_free_bytes=required,
        free_bytes=free_bytes,
        enough_space=None if free_bytes is None else int(free_bytes) >= required,
        destination=whisper_cpp_runtime.build_dir(root, chosen),
        device=device_id,
        device_reason=reason,
        resumable=False,
        build_id=chosen.id,
        includes_cpu_build=with_cpu,
    )


# ── Running them ─────────────────────────────────────────────────────────────


def perform_ggml(action, model, models_root, session, progress, cancel):
    """A GGML model's download, repair or check — with its filter's model.

    The voice-activity model comes first on a download or a repair: it is
    small, and a failure there is better heard before the 3 GB than after. A
    check checks it too, and fetches or mends it on the side — a damaged
    filter is not the model the user is checking being damaged, and without
    the filter a run still works and says so.
    """
    if action == management.ACTION_VERIFY_MODEL:
        model_store.verify_model(models_root, model, progress=progress, should_cancel=cancel)
        ensure_vad(models_root, session, cancel, check=True, strict=False)
        return None
    if action == management.ACTION_REPAIR_MODEL:
        model_store.repair_model(whisper_cpp_catalog.VAD_MODEL, models_root,
                                 should_cancel=cancel, session=session)
        return model_store.repair_model(
            model, models_root, progress=progress, should_cancel=cancel, session=session,
        )
    ensure_vad(models_root, session, cancel)
    return model_store.download_model(
        model, models_root, progress=progress, should_cancel=cancel, session=session,
    )


def perform_program(action, build_id, runtime_root, models_root, compute_capability,
                    session, progress, cancel):
    """Install, repair, check or remove one build of the whisper.cpp program.

    Returns what the runtime answered — for a removal, the files still open (a
    whisper-cli running). An install, a repair or a check also makes sure the
    voice-activity model is in `models_root` (None: not asked) — afterwards, and
    best-effort: the program comes from GitHub and the filter from Hugging
    Face, and a user whose network blocks the second, and who brings a GGML
    file of their own, must still be able to install the first. A run without
    the filter works and says so.
    """
    chosen = build(build_id)
    if chosen is None:
        raise errors.TranscriptionError(
            errors.WHISPER_CPP_NOT_INSTALLED, f"unknown build {build_id}"
        )
    cpu = whisper_cpp_builds.BUILD_CPU
    if action == management.ACTION_VERIFY_WHISPER_CPP:
        whisper_cpp_runtime.verify_build(chosen, runtime_root, progress=progress,
                                         should_cancel=cancel)
        ensure_vad(models_root, session, cancel, check=True, strict=False)
        return None
    if action == management.ACTION_REMOVE_WHISPER_CPP:
        remaining = ()
        if chosen is cpu:
            remaining += whisper_cpp_runtime.remove_build(
                whisper_cpp_builds.BUILD_CUDA, runtime_root, should_cancel=cancel
            )
        return remaining + whisper_cpp_runtime.remove_build(
            chosen, runtime_root, should_cancel=cancel
        )
    steps = [chosen]
    if (chosen is not cpu and whisper_cpp_runtime.installation_state(cpu, runtime_root).state
            != whisper_cpp_runtime.STATE_INSTALLED):
        steps.insert(0, cpu)
    total = sum(step.archive_bytes * 2 for step in steps)
    offset = 0
    for step in steps:
        def _progress(done, _total, base=offset):
            progress(base + done, total)

        run = (whisper_cpp_runtime.repair_build
               if action == management.ACTION_REPAIR_WHISPER_CPP and step is chosen
               else whisper_cpp_runtime.install_build)
        run(step, runtime_root, progress=_progress, should_cancel=cancel,
            session=session, compute_capability=compute_capability)
        offset += step.archive_bytes * 2
    ensure_vad(models_root, session, cancel,
               check=action == management.ACTION_REPAIR_WHISPER_CPP, strict=False)
    return None


def ensure_vad(models_root, session, cancel, check=False, strict=True):
    """Put the voice-activity model in `models_root` if it is not there.

    `check` hashes one that is there and mends it if it is damaged. `strict`
    False is for the checks and the program's own actions: a filter that could
    not be fetched (offline, Hugging Face blocked) is logged and left for later
    rather than turned into their failure — the run works without it and says
    so. A cancel is always a cancel. Does
    nothing without a models folder.
    """
    if not models_root:
        return
    vad = whisper_cpp_catalog.VAD_MODEL
    try:
        if model_store.installation_state(models_root, vad).state != model_store.STATE_INSTALLED:
            model_store.download_model(vad, models_root, should_cancel=cancel, session=session)
            return
        if not check:
            return
        try:
            model_store.verify_model(models_root, vad, should_cancel=cancel)
        except errors.TranscriptionError as exc:
            if exc.code != errors.MODEL_CORRUPTED:
                raise
            logging.info("[transcription] the voice-activity model was damaged; fetching it again")
            model_store.repair_model(vad, models_root, should_cancel=cancel, session=session)
    except errors.TranscriptionError as exc:
        if strict or exc.code == errors.CANCELLED:
            raise
        logging.warning("[transcription] the voice-activity model was left as it is: %s",
                        exc.log_line)


# ── What is said ─────────────────────────────────────────────────────────────


def announcement(action, result, build_id) -> management.Announcement:
    """management.announcement() for a finished action on the program.

    The values carry `build`: the build's *i18n key*
    (WHISPER_CPP_BUILD_I18N_KEYS), which the UI translates before formatting.
    """
    values = {"build": WHISPER_CPP_BUILD_I18N_KEYS.get(build_id, "")}
    if action == management.ACTION_VERIFY_WHISPER_CPP:
        return management.Announcement(
            WHISPER_CPP_VERIFIED_I18N_KEY, management.OUTCOME_DONE, values)
    if action == management.ACTION_REMOVE_WHISPER_CPP:
        if result:
            # A whisper-cli still running holds its own files open; the rest
            # went. Removing again once it has finished takes them.
            return management.Announcement(
                WHISPER_CPP_REMOVE_IN_USE_I18N_KEY, management.OUTCOME_WARNING, values)
        return management.Announcement(
            WHISPER_CPP_REMOVED_I18N_KEY, management.OUTCOME_DONE, values)
    return management.Announcement(
        WHISPER_CPP_INSTALLED_I18N_KEY, management.OUTCOME_DONE, values)
