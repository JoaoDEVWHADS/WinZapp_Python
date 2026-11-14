"""whisper.cpp models the user already has: one GGML file, anywhere on disk.

external_models' counterpart for the second backend, and deliberately not a
second mechanism: the references are the same records in the same app.json
list (`ExternalReference` with `backend` set to whisper.cpp), stored and
forgotten by the same locked `_store()` / `forget_reference()`, measured into
the same REF_* states and accepted with the same ACCEPT_* outcomes, so the tab,
the job and the run treat both kinds alike. What differs is only what a model
*is* — a file, where faster-whisper's is a folder — and every rule of
external_models carries over to it unchanged:

* **The user's file is never copied, moved or deleted.** Forgetting it removes
  the record; a file inside WinZapp's own models folder is refused, as a
  folder there is.
* **Only the digest makes a file "the catalogue's model X".** Every GGML file
  of the catalogue has a size and a sha256 (whisper_cpp_catalog), so a file
  whose size is one of them is a candidate and is hashed; it is stored as that
  model only when the digest matches. The size alone would not even pick the
  entry: ggml-large-v1.bin and ggml-large-v2.bin have exactly the same size.
* **Anything else is custom only because the user said so**, after the check
  that says what it is, and only once whisper-cli has loaded it
  (`WhisperCppBackend.trial_load()`, on the processor build). Nothing here reads
  the file's header to guess: a header that looks right says nothing about
  whether this release can load it, and the trial load is the one answer that
  does.
* **The identity mark is the file's own** (size, st_mtime_ns), taken before the
  hash or the trial load and compared after: a file rewritten meanwhile stores
  nothing (ACCEPT_CHANGED_WHILE_CHECKED), and one rewritten later is
  REF_CHANGED.

Hashing a 3 GB file and loading a model both take long: everything here runs
on a worker thread (external_job.py), never on the wx thread. The log gets
paths and ids, as in external_models — never anything of a message.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from core.transcription import (
    backend as backend_module,
    errors,
    external_models,
    model_store,
    whisper_cpp_catalog,
    whisper_cpp_store,
)

WHISPER_CPP = backend_module.BACKEND_WHISPER_CPP

#: A file that cannot be a model at all: empty. Its own code, because
#: "missing: config.json" (a folder's sentence) says nothing about a file.
REFUSED_NOT_GGML = "not_ggml"


def inspect_file(path):
    """None when `path` is a non-empty regular file, else a REFUSED_* code."""
    path = str(path)
    if not os.path.exists(path):
        return external_models.REFUSED_FOLDER_MISSING
    if os.path.isdir(path):
        return external_models.REFUSED_NOT_A_FOLDER
    mark = external_models.file_mark(path)
    if mark is None:
        return external_models.REFUSED_UNREADABLE
    if mark[0] <= 0:
        return REFUSED_NOT_GGML
    return None


def identify_file(path, progress=None, should_cancel=None, known_id=None):
    """(match, model_id) for `path`: MATCH_VERIFIED, MATCH_DIGEST_MISMATCH or
    MATCH_NONE, hashing the file only when its size is a catalogue file's.

    A mismatch names `known_id` — the model the file was stored as — when it
    is one of the entries of that size, and the first of them otherwise:
    several weigh exactly the same (distil-large-v3, distil-large-v3.5 and
    both kotoba files), and a file that was distil-large-v3 must not be said
    to be a damaged distil-large-v3.5.
    """
    mark = external_models.file_mark(path)
    size = mark[0] if mark is not None else None
    candidates = [entry for entry in whisper_cpp_catalog.MODELS if entry.size_bytes == size]
    if not candidates:
        return external_models.MATCH_NONE, None
    started = time.monotonic()
    digest = _hash(path, size, progress, should_cancel)
    for entry in candidates:
        if digest == entry.sha256:
            logging.info("[transcription] %s verified as %s in %.1fs",
                         os.path.basename(path), entry.id, time.monotonic() - started)
            return external_models.MATCH_VERIFIED, entry.id
    logging.info(
        "[transcription] %s has the size of %s and not its contents: sha256 %s",
        os.path.basename(path), ", ".join(entry.id for entry in candidates), digest,
    )
    named = next((entry for entry in candidates if entry.id == known_id), candidates[0])
    return external_models.MATCH_DIGEST_MISMATCH, named.id


def accept_ggml_file(app_settings, path, models_root, progress=None,
                     should_cancel=None, other_roots=()):
    """Verify `path` as a catalogue GGML file and, only if it is one, remember it.

    external_models.accept_catalogue_folder() for a file: the same outcomes,
    the hash in the same call as the write, a digest mismatch that marks an
    existing record unverified, and nothing stored for a file rewritten while
    it was hashed.
    """
    path = str(path)
    refusal = inspect_file(path)
    if refusal is not None:
        return external_models.AcceptOutcome(refusal)
    if external_models._inside_any(path, models_root, other_roots):
        return external_models.AcceptOutcome(external_models.REFUSED_INSIDE_MODELS_ROOT)

    # The model this file is already stored as, if any: a check that now finds
    # other contents marks that record unverified and leaves its id alone.
    known = external_models.reference_for_path(
        external_models.load_references(app_settings), path)
    known_id = known.model_id if known is not None and known.is_file else None
    before = external_models.file_mark(path)
    match, model_id = identify_file(path, progress, should_cancel, known_id)
    mark = external_models.file_mark(path)
    identification = external_models.Identification(path, match, model_id)
    if mark is None or mark != before:
        return external_models._changed_while_checked(path, before, mark, identification, None)
    if match == external_models.MATCH_VERIFIED:
        code, reference = external_models._store(
            app_settings, path, model_id, True, mark, backend=WHISPER_CPP
        )
        return external_models.AcceptOutcome(code, reference, identification)
    if match == external_models.MATCH_DIGEST_MISMATCH:
        external_models._store(app_settings, path, known_id or model_id, False, mark,
                               only_if_present=True, backend=WHISPER_CPP)
        return external_models.AcceptOutcome(
            external_models.ACCEPT_DIGEST_MISMATCH, None, identification
        )
    return external_models.AcceptOutcome(
        external_models.ACCEPT_NOT_IDENTIFIED, None, identification
    )


def accept_custom_ggml_file(app_settings, path, models_root, backend,
                            should_cancel=None, other_roots=()):
    """Trial-load `path` with whisper.cpp and, if it loaded, remember it as custom.

    Called only after the user chose to use a file the catalogue does not
    vouch for. The trial runs on the processor build whatever the device
    preference (see WhisperCppBackend.trial_load()), and its failure is raised
    as it came and stores nothing.
    """
    path = str(path)
    refusal = inspect_file(path)
    if refusal is not None:
        return external_models.AcceptOutcome(refusal)
    if external_models._inside_any(path, models_root, other_roots):
        return external_models.AcceptOutcome(external_models.REFUSED_INSIDE_MODELS_ROOT)

    before = external_models.file_mark(path)
    backend.trial_load(path, "cpu", "", should_cancel=should_cancel)
    if should_cancel is not None and should_cancel():
        raise errors.TranscriptionError(errors.CANCELLED, "cancelled by the user")
    mark = external_models.file_mark(path)
    if mark is None or mark != before:
        return external_models._changed_while_checked(path, before, mark, None, None)
    code, reference = external_models._store(
        app_settings, path, None, True, mark, backend=WHISPER_CPP
    )
    return external_models.AcceptOutcome(code, reference)


def usable_ggml_ids(models_root, references=()) -> tuple[str, ...]:
    """GGML ids a run could load now: complete in the models folder, or held by
    a whisper.cpp reference that is REF_READY. external_models.
    usable_catalogue_ids()'s counterpart; never a custom file."""
    ready = {
        reference.model_id
        for reference in references
        if reference.is_file and not reference.is_custom
        and external_models.reference_state(reference) == external_models.REF_READY
    }
    in_root = set(whisper_cpp_store.list_installed(models_root))
    return tuple(
        entry.id for entry in whisper_cpp_catalog.list_models()
        if entry.id in ready or entry.id in in_root
    )


def model_file(models_root, choice, references=()) -> str:
    """The GGML file to hand whisper-cli for `choice`, or the right error.

    external_models.model_directory() for whisper.cpp, with its order and its
    codes: WinZapp's own complete copy wins, then a REF_READY reference to the
    same file elsewhere; MODEL_CORRUPTED for an incomplete copy of WinZapp's,
    EXTERNAL_MODEL_MISSING / EXTERNAL_MODEL_CHANGED for a reference that is
    gone or changed, MODEL_NOT_INSTALLED otherwise. A custom choice resolves
    only to a whisper.cpp reference.
    """
    reference_id = external_models.custom_reference_id(choice)
    if reference_id is not None:
        reference = external_models.find_reference(references, reference_id)
        if reference is None or not reference.is_custom or not reference.is_file:
            raise errors.TranscriptionError(errors.MODEL_NOT_INSTALLED, str(choice))
        return _ready_path(reference, str(choice))

    entry = whisper_cpp_catalog.get_model(choice)
    if entry is None or entry not in whisper_cpp_catalog.MODELS:
        return whisper_cpp_store.ensure_ready(models_root, choice)
    if model_store.is_installed(models_root, entry):
        return whisper_cpp_store.model_path(models_root, entry)

    states = []
    for reference in references:
        if not reference.is_file or reference.model_id != entry.id:
            continue
        state = external_models.reference_state(reference)
        if state == external_models.REF_READY:
            logging.info("[transcription] model %s is loaded from the external file %s",
                         entry.id, os.path.basename(reference.path))
            return reference.path
        states.append(state)

    if model_store.installation_state(models_root, entry).state != model_store.STATE_ABSENT:
        return whisper_cpp_store.ensure_ready(models_root, entry.id)
    if external_models.REF_FOLDER_MISSING in states:
        raise errors.TranscriptionError(errors.EXTERNAL_MODEL_MISSING, entry.id)
    if external_models.REF_CHANGED in states:
        raise errors.TranscriptionError(
            errors.EXTERNAL_MODEL_CHANGED, f"{entry.id}: changed since it was verified"
        )
    return whisper_cpp_store.ensure_ready(models_root, entry.id)


@dataclass(frozen=True)
class CacheFile:
    """One GGML file found in the Hugging Face cache — the three fields the
    tab's pick list reads, as external_models.CacheSnapshot has them."""

    path: str
    revision: str
    #: The catalogue file of that name *and* size, or None. A candidate, never
    #: a verdict: only the digest, after the user picks, says "verified".
    model_id: str | None = None


def discover_hf_cache(cache_dir=None) -> tuple[CacheFile, ...]:
    """Every GGML model file in the Hugging Face cache, cheaply.

    Names and sizes only — nothing is hashed — in the snapshots of a repository
    with "whisper" in its name (ggerganov/whisper.cpp is where the files the
    whisper.cpp scripts download come from). The voice-activity model is not a
    transcription model and is left out.
    """
    root = cache_dir or external_models.hf_cache_dir()
    vad_name = whisper_cpp_catalog.VAD_MODEL.filename
    found = []
    for folder in external_models._sorted_dirs(root):
        repo = external_models._repo_of_cache_folder(folder)
        if repo is None or "whisper" not in repo.casefold():
            continue
        snapshots = os.path.join(root, folder, "snapshots")
        for revision in external_models._sorted_dirs(snapshots):
            snapshot = os.path.join(snapshots, revision)
            try:
                names = sorted(os.listdir(snapshot))
            except OSError:
                continue
            for name in names:
                if not (name.startswith("ggml-") and name.endswith(".bin")) or name == vad_name:
                    continue
                path = os.path.join(snapshot, name)
                mark = external_models.file_mark(path)
                if mark is None or mark[0] <= 0:
                    continue
                # The repository too: `ggml-model.bin` at 3,095,033,483 bytes
                # is the file of three different third-party models.
                entry = next((e for e in whisper_cpp_catalog.MODELS
                              if e.filename == name and e.size_bytes == mark[0]
                              and e.repo.casefold() == repo.casefold()), None)
                found.append(CacheFile(path, revision, entry.id if entry else None))
    logging.info("[transcription] Hugging Face cache %s: %d GGML file(s), %d recognised",
                 root, len(found), sum(1 for item in found if item.model_id))
    return tuple(found)


def _ready_path(reference, choice) -> str:
    state = external_models.reference_state(reference)
    if state == external_models.REF_READY:
        return reference.path
    if state == external_models.REF_FOLDER_MISSING:
        raise errors.TranscriptionError(errors.EXTERNAL_MODEL_MISSING, reference.path)
    # Changed or unverified: the same answer external_models gives a custom
    # folder — check it again, or choose another model.
    raise errors.TranscriptionError(
        errors.EXTERNAL_MODEL_CHANGED, f"{choice}: {reference.path} is not as it was checked"
    )


def _hash(path, size, progress, should_cancel) -> str:
    """sha256 of the file, through external_models' reader, so a file that
    vanishes while it is read is EXTERNAL_MODEL_MISSING there too."""
    if not os.path.exists(path):
        raise errors.TranscriptionError(errors.EXTERNAL_MODEL_MISSING, path)
    return external_models._hash_file(
        path, size, progress, should_cancel, os.path.dirname(path) or "."
    )
