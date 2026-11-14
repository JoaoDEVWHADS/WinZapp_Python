"""Marking models in the picker, and downloading the marked ones in sequence.

The model list of the Transcription tab has a selection mode like the lists of
chats and messages: Ctrl+Space marks the focused model, Space marks while
something is marked, Esc clears (the two settings under Settings > User
Interface that steer those lists steer this one). What is marked is a queue:
"Download" fetches every marked model that is not complete yet, one after the
other, instead of only the model the list is on.

Pure, no wx — the marks are a set of model ids the tab holds, and everything
the tab has to decide about them is here, where it can be tested without a
window: which marks still mean something, what the queue is, what the user is
agreeing to, and how a row says it is marked.

Two decisions carry the weight:

* **Only what is missing is queued.** A marked model that is already complete
  is skipped, not re-downloaded and not an error: marking "everything" and
  pressing Download must fetch what is absent. Repair stays a single-model
  action — it deletes before it fetches, and doing that to a list of models
  because they happened to be marked would be a destructive surprise.
* **One question for the whole queue, sized as the sum.** The disk gate runs
  per model, as each starts, against what is free by then; quoting the total
  up front is the same arithmetic done once, and refusing at the top beats
  discovering at the fourth model that the third filled the disk.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import utils
from core.transcription import management, model_store

#: Model states a queued download can act on; the rest are skipped.
DOWNLOADABLE_STATES = (model_store.STATE_ABSENT, model_store.STATE_INCOMPLETE)


def toggle(marks, model_id) -> bool:
    """Flip `model_id` in `marks`. Returns whether it is marked now."""
    if model_id in marks:
        marks.discard(model_id)
        return False
    marks.add(model_id)
    return True


def visible_marked(marks, listed_ids) -> bool:
    """Whether any marked model is among the ones listed right now.

    The selection mode's gate, as for the chat lists: switching to the other
    backend lists other models, and a mark nobody can see must not make Space
    keep marking.
    """
    return any(model_id in marks for model_id in listed_ids)


def prune(marks, listed_ids) -> None:
    """Forget marks of models that are no longer offered."""
    marks.intersection_update(listed_ids)


def queue_for(marks, listed_ids, states) -> list:
    """The marked models to download, in the order the list shows them.

    `states` is {model id: model_store state}. A model whose state is unknown
    (not measured yet) is not queued: guessing would download over a model that
    may be complete.
    """
    return [
        model_id for model_id in listed_ids
        if model_id in marks and states.get(model_id) in DOWNLOADABLE_STATES
    ]


def row_label(label, marked, word, position) -> str:
    """The row as it is read: with the localized "selected" word when marked."""
    return utils.append_selected_marker(label, word, position, marked)


@dataclass(frozen=True)
class QueueSummary:
    """What the user is told before agreeing to the queue. Data, not text."""

    model_ids: tuple
    download_bytes: int
    required_free_bytes: int
    free_bytes: int | None
    enough_space: bool | None
    destination: str
    #: Models that will not fit the memory of the device they would run on.
    not_fitting: tuple


def queue_download_summary(model_ids, models_root, probe, free_bytes, device_preference,
                           whisper_cpp_cuda_installed=False,
                           compute_type_preference=None):
    """The summary for downloading `model_ids` in sequence, or None.

    Built from each model's own `management.model_download_summary()`, so a
    resumed download is quoted at what it will fetch and a GGML model brings
    the voice-activity model it needs. None when no id is known to the
    catalogue (nothing to quote and nothing to fetch).
    """
    kwargs = {"whisper_cpp_cuda_installed": whisper_cpp_cuda_installed}
    if compute_type_preference is not None:
        kwargs["compute_type_preference"] = compute_type_preference
    summaries = [
        management.model_download_summary(
            model_id, models_root, probe, free_bytes, device_preference, **kwargs
        )
        for model_id in model_ids
    ]
    summaries = [summary for summary in summaries if summary is not None]
    if not summaries:
        return None
    total = sum(summary.download_bytes for summary in summaries)
    required = model_store.required_free_bytes(total)
    return QueueSummary(
        model_ids=tuple(summary.model_id for summary in summaries),
        download_bytes=total,
        required_free_bytes=required,
        free_bytes=free_bytes,
        enough_space=None if free_bytes is None else int(free_bytes) >= required,
        destination=models_root,
        not_fitting=tuple(
            summary.model_id for summary in summaries if summary.fits_memory is False
        ),
    )
