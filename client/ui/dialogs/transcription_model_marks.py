"""Marking models in the Transcription tab's list: the selection mode.

The same scheme as the lists of chats and messages (ChatListSelectionMixin):

* **Ctrl+Space** marks or unmarks the model the list is on, with the sound and
  the "Selecionado"/"Desmarcado" announcement the other lists give.
* **Space** does the same while a model is marked, if Settings > User
  Interface > "Usar Espaço para marcar/desmarcar enquanto houver algo marcado"
  is on; with nothing marked it stays the list's own key.
* **Ctrl+Shift+Space** marks every model, or unmarks them all when they all are.
* **Esc** unmarks everything, if "Esc desmarca…" is on — and only then: with
  nothing marked, or the setting off, Esc is the dialog's.

The selection mode is derived, never stored: it is on while a marked model is
among the rows listed, and the announcements say when it turns on or off. What
is marked is the download queue (core/transcription/model_queue.py); the row
the list is on is still the chosen model, as it was when this was a drop-down.
Only catalogue models can be marked: "Automatic" and the models in other
folders have nothing to download.
"""

import logging
import os

import wx

from core.sound_system import load_sound
from core.transcription import errors as transcription_errors
from core.transcription import model_queue
from core.transcription import preferences as transcription_preferences
from ui.shortcut_bindings import command_key_event


class TranscriptionModelMarksMixin:
    """The marks of the model list, for `SettingsDialog`."""

    def _init_transcription_model_marks(self) -> None:
        #: Ids of the models marked for download, in no order: the queue is
        #: taken in the order the list shows them.
        self._transcription_model_marks = set()
        #: The rows as populate wrote them, before any mark was drawn on them.
        self._transcription_model_base_labels = []
        self._transcription_mark_sound = None
        self._transcription_model_list.Bind(
            wx.EVT_KEY_DOWN, self._on_transcription_model_key_down
        )
        # Esc is the dialog's Cancel before it is anything else, and the
        # dialog sees it as a char hook: only a hook on the list, which does
        # not pass it on, can keep it for "unmark everything".
        self._transcription_model_list.Bind(
            wx.EVT_CHAR_HOOK, self._on_transcription_model_char_hook
        )

    # ── Settings (Settings > User Interface), shared with the other lists ────

    def _transcription_ui_setting(self, name, default=True):
        return self.main_window.settings.get("user_interface", {}).get(name, default)

    def _model_space_selects(self) -> bool:
        return bool(self._transcription_ui_setting("space_selects_in_selection_mode"))

    def _model_escape_clears(self) -> bool:
        return bool(self._transcription_ui_setting("escape_clears_selection"))

    # ── What is markable, and what a row says ────────────────────────────────

    def _markable_model_id(self, index):
        """The catalogue model at `index`, or None for the rows with no download."""
        ids = self._transcription_model_ids
        if not 0 <= index < len(ids):
            return None
        model_id = ids[index]
        if model_id == transcription_preferences.AUTO:
            return None
        return model_id if model_id in self._transcription_model_states else None

    def _marked_model_labels(self, labels, model_ids):
        """`labels` with the "selected" word on the marked rows.

        Also where marks of models the list no longer offers are forgotten:
        the list is rebuilt whenever the backend or the folder changes.
        """
        model_queue.prune(self._transcription_model_marks, model_ids)
        position = self._transcription_ui_setting("selected_announcement_position", "end")
        word = self.main_window.i18n.t("selected_suffix")
        return [
            model_queue.row_label(
                label, model_id in self._transcription_model_marks, word, position
            )
            for label, model_id in zip(labels, model_ids)
        ]

    def _marked_models_visible(self) -> bool:
        return model_queue.visible_marked(
            self._transcription_model_marks, self._transcription_model_ids
        )

    def _repaint_model_marks(self) -> None:
        """Redraw only the rows whose text changed, so the reader hears none of
        the rows that did not. The unmarked texts are kept by the populate that
        wrote them: redrawing from them beats parsing the suffix back off."""
        listbox = self._transcription_model_list
        fresh = self._marked_model_labels(
            self._transcription_model_base_labels, self._transcription_model_ids
        )
        listbox.Freeze()
        try:
            for index, (old, new) in enumerate(
                    zip(self._transcription_model_labels, fresh)):
                if old != new:
                    listbox.SetString(index, new)
        finally:
            listbox.Thaw()
        self._transcription_model_labels = fresh
        self._sync_transcription_action_buttons()

    # ── Announcements ────────────────────────────────────────────────────────

    def _announce_model_marks(self, key, was_active, sound=False) -> None:
        i18n = self.main_window.i18n
        text = i18n.t(key)
        if self._model_space_selects():
            is_active = self._marked_models_visible()
            if is_active and not was_active:
                text = f"{text}. {i18n.t('selection_mode_on')}"
            elif was_active and not is_active:
                text = f"{text}. {i18n.t('selection_mode_off')}"
        if sound:
            self._play_model_mark_sound()
        self.main_window.speak_output.output(text, interrupt=True)

    def _play_model_mark_sound(self) -> None:
        """The "selected" cue the other lists play. Guarded: a sound that cannot
        load must not cost the announcement (docs/traps/audio-devices.md)."""
        try:
            if self._transcription_mark_sound is None:
                self._transcription_mark_sound = load_sound(
                    self.main_window.sound_system,
                    os.path.join("default", "selected.ogg"),
                )
            self._transcription_mark_sound.play()
        except Exception as exc:
            # The report, not the exception's text: it can quote a path that
            # names the Windows user.
            logging.warning("[transcription] could not play the selection sound: %s",
                            transcription_errors.exception_report(exc))

    # ── Marking ──────────────────────────────────────────────────────────────

    def _toggle_model_mark(self, index) -> bool:
        """Mark or unmark the model at `index`. False when the row has none."""
        model_id = self._markable_model_id(index)
        if model_id is None:
            return False
        was_active = self._marked_models_visible()
        now_marked = model_queue.toggle(self._transcription_model_marks, model_id)
        self._repaint_model_marks()
        self._announce_model_marks(
            "selected" if now_marked else "unselected", was_active, sound=now_marked
        )
        return True

    def _toggle_all_model_marks(self) -> bool:
        markable = [
            model_id for index in range(len(self._transcription_model_ids))
            if (model_id := self._markable_model_id(index)) is not None
        ]
        if not markable:
            return False
        was_active = self._marked_models_visible()
        everything = all(model_id in self._transcription_model_marks for model_id in markable)
        if everything:
            self._transcription_model_marks.difference_update(markable)
        else:
            self._transcription_model_marks.update(markable)
        self._repaint_model_marks()
        self._announce_model_marks(
            "all_unselected" if everything else "all_selected",
            was_active, sound=not everything,
        )
        return True

    def _clear_model_marks(self) -> bool:
        """Unmark everything. False when nothing was marked."""
        if not self._transcription_model_marks:
            return False
        was_active = self._marked_models_visible()
        self._transcription_model_marks.clear()
        self._repaint_model_marks()
        self._announce_model_marks("all_unselected", was_active)
        return True

    # ── Keys ─────────────────────────────────────────────────────────────────

    def _handle_model_mark_key(self, key, ctrl, shift) -> bool:
        """The selection keys of the model list. True when one was dealt with."""
        focus = self._transcription_model_list.GetSelection()
        if ctrl and shift and key == wx.WXK_SPACE:
            self._toggle_all_model_marks()
            return True
        if ctrl and not shift and key == wx.WXK_SPACE:
            # Swallowed even on a row with nothing to mark, as in the other
            # lists: Ctrl+Space is never a character here.
            self._toggle_model_mark(focus)
            return True
        if (key == wx.WXK_SPACE and not ctrl and not shift
                and self._model_space_selects() and self._marked_models_visible()):
            return self._toggle_model_mark(focus)
        return False

    def _on_transcription_model_key_down(self, event) -> None:
        event = command_key_event(self, "chat_selection", event)
        if not self._handle_model_mark_key(
                event.GetKeyCode(), event.ControlDown(), event.ShiftDown()):
            event.Skip()

    def _on_transcription_model_char_hook(self, event) -> None:
        if (event.GetKeyCode() == wx.WXK_ESCAPE
                and self._model_escape_clears()
                and self._marked_models_visible()
                and self._clear_model_marks()):
            return
        event.Skip()
