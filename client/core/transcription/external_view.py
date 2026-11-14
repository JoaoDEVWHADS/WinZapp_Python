"""What the Transcription tab says and offers about models in other folders.

The decisions of `ui/dialogs/transcription_external.py`, as plain functions
with no wx: which sentence a row is, which buttons can be pressed for it, which
catalogue models count as "available" once an external folder is counted, and
what the question about a folder no catalogue entry claims says. The dialog is
a wx.Dialog the suite may not open (tests/test_no_desktop_visible_windows.py),
so everything that can be decided without one is decided here and tested
directly.

A reference's *state* (`external_models.reference_state()`) touches the disk,
and the disk may be an unplugged drive or a share that is down — so none of
these functions measures it: they take the states the tab collected on a worker
thread, and `None` for "not measured yet".
"""

from __future__ import annotations

from dataclasses import dataclass

from core.transcription import (
    backend as backend_module,
    errors,
    external_models,
    model_catalog,
    model_names,
    model_store,
    whisper_cpp_catalog,
)

# What a reference is right now, as a word to put in its row. `None` is "the
# worker has not answered yet", which is a state of the screen and not of the
# folder, and is said as such rather than as a guess.
STATE_I18N_KEYS = {
    external_models.REF_READY: "transcription_external_state_ready",
    external_models.REF_FOLDER_MISSING: "transcription_external_state_missing",
    external_models.REF_CHANGED: "transcription_external_state_changed",
    external_models.REF_UNVERIFIED: "transcription_external_state_unverified",
    None: "transcription_external_state_checking",
}

ROW_CATALOGUE_I18N_KEY = "transcription_external_row_catalogue"
ROW_CUSTOM_I18N_KEY = "transcription_external_row_custom"
# The model picker's two lines for what lives in another folder. Two sentences
# for the reason model_choice_label() gives: the figure means something
# different in each.
CHOICE_EXTERNAL_I18N_KEY = "transcription_model_choice_external"
CHOICE_CUSTOM_I18N_KEY = "transcription_model_choice_custom"

SNAPSHOT_RECOGNISED_I18N_KEY = "transcription_external_find_item_recognised"
NOT_IDENTIFIED_QUESTION_I18N_KEY = "transcription_external_not_identified_question"
DIGEST_MISMATCH_QUESTION_I18N_KEY = "transcription_external_digest_mismatch_question"

FORGET_QUESTION_I18N_KEY = "transcription_external_forget_question"
FORGOTTEN_I18N_KEY = "transcription_external_forgotten"
FORGOTTEN_RESET_I18N_KEY = "transcription_external_forgotten_reset"
USE_DONE_I18N_KEY = "transcription_external_use_done"
SEARCHING_I18N_KEY = "transcription_external_find_searching"
FIND_NONE_I18N_KEY = "transcription_external_find_none"

#: The sentences that say "folder", and the ones that say "file" instead for a
#: whisper.cpp model, which is one GGML file (external_ggml): the same news,
#: and a blind user told "the folder ggml-small.bin" goes looking for a folder.
FILE_I18N_KEYS = {
    key: f"{key}_file"
    for key in (
        "transcription_external_added",
        "transcription_external_checked",
        "transcription_external_custom_added",
        "transcription_external_custom_checked",
        "transcription_external_changed_while_checked",
        "transcription_external_refused_unreachable",
        "transcription_external_refused_inside_root",
        "transcription_external_read_failed",
        "transcription_external_load_failed",
        "transcription_external_not_added",
        "transcription_external_progress_verify",
        "transcription_external_progress_custom",
        NOT_IDENTIFIED_QUESTION_I18N_KEY,
        DIGEST_MISMATCH_QUESTION_I18N_KEY,
        FORGET_QUESTION_I18N_KEY,
        FORGOTTEN_I18N_KEY,
        STATE_I18N_KEYS[external_models.REF_FOLDER_MISSING],
        STATE_I18N_KEYS[external_models.REF_CHANGED],
        # The run's own two sentences about a model somewhere else, said by
        # the flow and by a check that found the model gone.
        errors.error_i18n_key(errors.EXTERNAL_MODEL_MISSING),
        errors.error_i18n_key(errors.EXTERNAL_MODEL_CHANGED),
    )
}

#: The file chooser of "Add..." when whisper.cpp is the backend.
BROWSE_FILE_TITLE_I18N_KEY = "transcription_external_browse_file_dialog_title"
BROWSE_FILE_WILDCARD_I18N_KEY = "transcription_external_file_wildcard"


#: Every key this module and the tab's external section ask for besides the
#: ones external_job and the error codes own. The i18n test reads this rather
#: than a list of its own.
VIEW_I18N_KEYS = (
    tuple(STATE_I18N_KEYS.values())
    + (
        ROW_CATALOGUE_I18N_KEY,
        ROW_CUSTOM_I18N_KEY,
        CHOICE_EXTERNAL_I18N_KEY,
        CHOICE_CUSTOM_I18N_KEY,
        SNAPSHOT_RECOGNISED_I18N_KEY,
        NOT_IDENTIFIED_QUESTION_I18N_KEY,
        DIGEST_MISMATCH_QUESTION_I18N_KEY,
        FORGET_QUESTION_I18N_KEY,
        FORGOTTEN_I18N_KEY,
        FORGOTTEN_RESET_I18N_KEY,
        USE_DONE_I18N_KEY,
        SEARCHING_I18N_KEY,
        FIND_NONE_I18N_KEY,
        "transcription_external_label",
        "transcription_external_actions_group",
        "transcription_external_add_btn",
        "transcription_external_find_btn",
        "transcription_external_use_btn",
        "transcription_external_check_btn",
        "transcription_external_forget_btn",
        "transcription_external_browse_dialog_title",
        "transcription_external_pick_title",
        "transcription_external_pick_prompt",
        "transcription_external_question_title",
        BROWSE_FILE_TITLE_I18N_KEY,
        BROWSE_FILE_WILDCARD_I18N_KEY,
    )
    + tuple(FILE_I18N_KEYS.values())
)


def for_reference(key, is_file) -> str:
    """`key`, or its "file" sentence when the model is a whisper.cpp file."""
    return FILE_I18N_KEYS.get(key, key) if is_file else key


@dataclass(frozen=True)
class Candidate:
    """A folder the user may mean, as the pick list shows it.

    The three fields `snapshot_label()` reads, which a
    `external_models.CacheSnapshot` has too: the two are listed the same way.
    """

    path: str
    revision: str = ""
    model_id: str | None = None


def row_label(i18n, reference, state) -> str:
    """One line of the list of references, written as a sentence.

    A list row is read whole and nothing else is, so the folder, what it holds
    and whether it can be used all have to be inside it. `state` is
    `reference_state()`'s answer, or None while it is being measured.
    """
    key = ROW_CUSTOM_I18N_KEY if reference.is_custom else ROW_CATALOGUE_I18N_KEY
    return i18n.t(key).format(
        name=external_models.display_name(reference),
        # "small, 5 bits" for a whisper.cpp file, "small.en, English only"
        # for an English-only model: the name the picker uses for it.
        model=model_names.display_name(i18n, reference.model_id) or "",
        state=i18n.t(for_reference(
            STATE_I18N_KEYS.get(state, STATE_I18N_KEYS[None]), reference.is_file
        )),
    )


def button_states(reference, state, job_running) -> dict:
    """Which of the five buttons may be pressed.

    Everything is off while something runs, as on the model row: two jobs on
    the same list would serialize behind a bar that does not move for the
    second. "Use" needs a model that can be used *now* — choosing one whose
    folder is gone only moves the failure from here to the first transcription
    — and the two that act on a row need one to be selected.
    """
    if job_running:
        return {"add": False, "find": False, "use": False, "check": False,
                "forget": False}
    selected = reference is not None
    return {
        "add": True,
        "find": True,
        "use": selected and state == external_models.REF_READY,
        "check": selected,
        "forget": selected,
    }


def ready_model_ids(references, states) -> frozenset:
    """Catalogue ids a verified external folder holds right now.

    From the states already measured: a reference whose state is not known yet
    does not count, which is the cautious answer (the picker would otherwise
    call a model available that the run may not find).
    """
    return frozenset(
        reference.model_id
        for reference in references
        if not reference.is_custom
        and states.get(reference.id) == external_models.REF_READY
    )


def custom_choices(i18n, references, backend_id=None) -> list:
    """[(model setting value, picker line)] for the custom models.

    Listed whatever their folder's state: the stored choice has to have an
    entry to be selected, and a model whose disk is unplugged is still the one
    the user picked (a run says so with EXTERNAL_MODEL_MISSING). Only the ones
    `backend_id` can load when it is given — a whisper.cpp file in
    faster-whisper's list would be a choice the run can only refuse.
    """
    return [
        (
            external_models.custom_choice(reference),
            i18n.t(CHOICE_CUSTOM_I18N_KEY).format(
                name=external_models.display_name(reference)
            ),
        )
        for reference in references
        if reference.is_custom and _for_backend(reference, backend_id)
    ]


def _for_backend(reference, backend_id) -> bool:
    if backend_id is None:
        return True
    if backend_id == backend_module.BACKEND_WHISPER_CPP:
        return reference.is_file
    return not reference.is_file


def usable_ids(root_ids, references, states) -> tuple:
    """The catalogue ids that are complete in the models folder or ready in an
    external one, in the catalogue's order — what preferences.resolve() takes
    as `installed_ids`, from states the tab already holds (the run itself asks
    `external_models.usable_catalogue_ids()`, which measures)."""
    wanted = set(root_ids) | ready_model_ids(references, states)
    return tuple(
        model.id
        for model in model_catalog.list_models() + whisper_cpp_catalog.list_models()
        if model.id in wanted
    )


def choice_is_external(model, root_state, external_ready) -> bool:
    """Whether the picker line for `model` is the "in another folder" one:
    nothing complete in WinZapp's own folder, and a verified copy elsewhere."""
    return model.id in external_ready and root_state != model_store.STATE_INSTALLED


def snapshot_label(i18n, snapshot) -> str:
    """One entry of the list of models found in the Hugging Face cache.

    The repository's name and a slice of the commit, which is what tells two
    revisions of the same repository apart; and, for one the catalogue
    recognises by name and size, which model it looks like. Nothing here is a
    verdict — only hashing says "verified", and that happens after the user
    picks.
    """
    name = external_models.folder_name(snapshot.path)
    revision = (snapshot.revision or "")[:8]
    if snapshot.model_id:
        return i18n.t(SNAPSHOT_RECOGNISED_I18N_KEY).format(
            name=name, revision=revision,
            model=model_names.display_name(i18n, snapshot.model_id),
        )
    return f"{name} ({revision})" if revision else name


def custom_question(i18n, folder, code, model_id, is_file=False) -> str:
    """The question asked about a folder that is a valid model and not one the
    catalogue vouches for: use it as a custom model, after a trial load?

    `code` is the ACCEPT_* the verification came back with, because the two
    cases say different true things: nobody claims the folder, or it has the
    sizes of `model_id` and other weights — which is not "model_id" and the
    user must not be allowed to believe it is.
    """
    name = external_models.folder_name(folder)
    if code == external_models.ACCEPT_DIGEST_MISMATCH:
        return i18n.t(for_reference(DIGEST_MISMATCH_QUESTION_I18N_KEY, is_file)).format(
            name=name, model=model_names.display_name(i18n, model_id) or ""
        )
    return i18n.t(for_reference(NOT_IDENTIFIED_QUESTION_I18N_KEY, is_file)).format(name=name)


def folder_candidates(path) -> tuple:
    """The `Candidate`s a picked folder stands for.

    Only folders shaped like a model; with none, the picked folder itself —
    so that the check that follows says why it is not one. Reads names and
    sizes (never model.bin) and may touch a share that is down: on a worker.
    """
    usable = []
    for folder in external_models.candidate_folders(path):
        identification = external_models.identify_quick(folder)
        if identification.shape is None or not identification.shape.ok:
            continue
        coordinates = external_models.hf_cache_coordinates(folder)
        usable.append(Candidate(
            folder,
            coordinates[1] if coordinates is not None else "",
            identification.model_id
            if identification.match == external_models.MATCH_CANDIDATE else None,
        ))
    return tuple(usable) or (Candidate(str(path)),)


def new_snapshots(snapshots, references) -> tuple:
    """The discovered snapshots that no reference already points at.

    Resolves each folder to compare it (`reference_for_path()`), which is disk
    I/O: on a worker.
    """
    return tuple(
        snapshot for snapshot in snapshots
        if external_models.reference_for_path(references, snapshot.path) is None
    )
