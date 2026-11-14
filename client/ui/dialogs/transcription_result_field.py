"""The Transcription tab's result field: where the focus goes, and when it empties.

The tab has one read-only field for everything it has to tell the user (see
`_render_transcription_substitutions()`): the outcome of the action they just
took first, then the notices about their choices. Two things about it live
here, apart from the 1,900-line tab that owns the field:

* **Verifying lands on it.** A check is a question, and its answer is the
  field. Leaving the focus on the button that was pressed (or, for the check of
  a model in another folder, sending it to the list) puts the answer one Tab
  away from a user who has just been told it exists. The other actions keep
  the rule of `_restore_transcription_focus()`: only a button that the action
  switched off loses the focus, since what they changed is the row, not a
  verdict.

* **An outcome expires with the thing it was about.** "The model is intact"
  said about Small is not about Large, and it stays on screen, in a field that
  is otherwise hidden, until something replaces it. Choosing another model,
  backend, build or folder reference drops it, which hides the field again
  when nothing else has anything to say.
"""

import wx

from core.transcription import management as transcription_management

#: The three management verifications. The check of a folder in another
#: section is a fourth, reached through `_restore_external_focus()`.
VERIFY_ACTIONS = (
    transcription_management.ACTION_VERIFY_MODEL,
    transcription_management.ACTION_VERIFY_CUDA_RUNTIME,
    transcription_management.ACTION_VERIFY_WHISPER_CPP,
)


def shares_window(control, other) -> bool:
    """Whether two controls are in the same top-level window.

    The CUDA, whisper.cpp and external-model checks run from windows of their
    own (transcription_windows.py) while the result field stays on the tab:
    focusing it from there put the focus in the Settings dialog, disabled
    behind the modal window, and the user lost their place. The answer is
    spoken either way (_announce_transcription_result())."""
    if control is None or other is None:
        return False
    try:
        return control.GetTopLevelParent() is other.GetTopLevelParent()
    except RuntimeError:  # a window already destroyed
        return False


class TranscriptionResultFieldMixin:
    """Focus and expiry of the result field, for `SettingsDialog`."""

    def _focus_transcription_result(self, pressed=None) -> bool:
        """Move the focus to the result field. False when it is not showing.

        The field is hidden while it has nothing to say, and a hidden control
        cannot take the focus — the caller then keeps whatever rule it had.

        *pressed* is the button the check was started from; its window, not
        wherever the focus is now, decides (FindFocus() is None while WinZapp
        is not the foreground app, and a long check can end then).
        """
        field = self._transcription_substituted_field
        if not field.IsShown():
            return False
        if not shares_window(field, pressed if pressed is not None else wx.Window.FindFocus()):
            # The check ran in another window (see shares_window()): the focus
            # stays there, under the caller's own rule.
            return False
        field.SetFocus()
        return True

    def _forget_transcription_outcome(self) -> None:
        """Drop the last action's outcome, because the user moved on from it."""
        if self._transcription_last_outcome is None:
            return
        self._transcription_last_outcome = None
        self._transcription_last_outcome_extra = ()
        self._render_transcription_substitutions()
