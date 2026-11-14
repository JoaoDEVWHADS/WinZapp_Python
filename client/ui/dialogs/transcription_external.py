"""The part of the Transcription tab that points WinZapp at models the user
already has in other folders, split out of transcription_tab.py.

A user who already transcribes with a model from another program — in the
Hugging Face cache, or wherever their script put it — does not have to
download it again: they add the folder, WinZapp checks it (the digest for one
of its catalogue models, a trial load for any other), and it appears in the
model picker. The decisions are in `core/transcription/external_models.py`
(what a folder is, what is stored) and `external_view.py` (what the tab says);
this module is the wx half and `ExternalModelsMixin` is mixed into
`SettingsDialog` beside `TranscriptionTabMixin`, whose own state (job flag,
announcement field, model picker) it shares.

What matters to the person using it:

* **Nothing here copies, moves or deletes a file of theirs.** "Forget" removes
  the reference and says so; the folder is never touched.
* **The slow parts never run on the wx thread.** Hashing 3 GB, loading a model
  and even *looking* at a folder on a drive that may be unplugged happen on
  worker threads, behind the same progress dialog and Cancel the model
  download has, and every result is spoken through `speak_output`.
* **References are written when they are checked, not on OK.** They are
  install-wide and describe the machine (the model files themselves do not
  wait for OK either); only *which model to use* is a setting of the dialog,
  and choosing one marks the dialog dirty like any other control does.
* **A whisper.cpp model is a file, not a folder** (external_ggml). "Add..."
  and "Find..." look for the kind the backend picker is on — a GGML file for
  whisper.cpp, a folder otherwise — and every sentence about a file says
  "file" (external_view.for_reference()). Both kinds share the one list.
"""

import logging
import threading

import wx

from core.transcription import (
    backend as transcription_backend,
    external_ggml,
    external_job,
    external_models,
    external_view,
    management,
    preferences as transcription_preferences,
)
from ui.dialogs.transcription_progress import TranscriptionProgressDialog

# The five buttons, in the order they are offered and tabbed: (name, label key).
# `external_view.button_states()` answers for the same names.
_EXTERNAL_BUTTONS = (
    ("add", "transcription_external_add_btn"),
    ("find", "transcription_external_find_btn"),
    ("use", "transcription_external_use_btn"),
    ("check", "transcription_external_check_btn"),
    ("forget", "transcription_external_forget_btn"),
)

#: The name of the group box around them. Without a mnemonic, for the reason
#: the model and CUDA groups give: a static box is not a tab stop.
_EXTERNAL_ACTIONS_GROUP = "transcription_external_actions_group"


class _Said:
    """Stands where a job stands for `_announce_transcription_result()`: it
    answers one fixed sentence. That method already speaks once through the
    app's funnel, plays the error sound for a failure and leaves the sentence
    in the tab's read-only field, which is everything these results need too."""

    def __init__(self, announcement):
        self._announcement = announcement

    def announcement(self, _result, _error):
        return self._announcement


class ExternalModelsMixin:
    """The "models in other folders" section of `SettingsDialog`'s tab."""

    def _build_external_models_group(self, page, sizer):
        """The list of references and its five buttons, laid out in `page`.

        Directly under the model picker and its actions, since "add a model
        I already have" is the other half of "download one". A plain
        wx.ListBox, which every screen reader reads row by row, and the
        buttons in a named group like the other two rows.
        """
        i18n = self.main_window.i18n
        self._transcription_external_label = wx.StaticText(
            page, label=i18n.t("transcription_external_label")
        )
        sizer.Add(self._transcription_external_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        # Rows are sentences, so the list is as wide as the page and as tall as
        # five lines of the font in use — never a pixel count, which crops at
        # the scaling a low-vision user runs.
        self._transcription_external_list = wx.ListBox(
            page, style=wx.LB_SINGLE,
            size=(-1, page.GetTextExtent("Xg").GetHeight() * 5),
        )
        sizer.Add(self._transcription_external_list, 0, wx.EXPAND | wx.ALL, 8)
        self._transcription_external_list.Bind(
            wx.EVT_LISTBOX, self._on_external_selection
        )
        #: Parallel to the rows: the reference id each one stands for, and the
        #: text each shows, so a redraw that would say the same thing says
        #: nothing (a screen reader re-reads a list that was rewritten).
        self._transcription_external_row_ids = []
        self._transcription_external_row_labels = []

        # Kept on its own: `_transcription_action_groups` is the model row, the
        # CUDA row and the whisper.cpp row, the buttons of management actions.
        box = self._transcription_external_box = wx.StaticBox(
            page, label=i18n.t(_EXTERNAL_ACTIONS_GROUP)
        )
        group = wx.StaticBoxSizer(box, wx.VERTICAL)
        row = wx.WrapSizer(wx.HORIZONTAL)
        handlers = {
            "add": self._on_external_add,
            "find": self._on_external_find,
            "use": self._on_external_use,
            "check": self._on_external_check,
            "forget": self._on_external_forget,
        }
        self._transcription_external_buttons = {}
        for name, label_key in _EXTERNAL_BUTTONS:
            button = wx.Button(box, label=i18n.t(label_key))
            button.Bind(wx.EVT_BUTTON, handlers[name])
            self._transcription_external_buttons[name] = button
            row.Add(button, 0, wx.RIGHT, 8)
        group.Add(row, 1, wx.EXPAND | wx.ALL, 4)
        sizer.Add(group, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._redraw_external_list()

    def _refresh_external_labels(self):
        """Retranslate this section after a language change."""
        i18n = self.main_window.i18n
        self._transcription_external_label.SetLabel(
            i18n.t("transcription_external_label")
        )
        self._transcription_external_box.SetLabel(i18n.t(_EXTERNAL_ACTIONS_GROUP))
        for name, label_key in _EXTERNAL_BUTTONS:
            self._transcription_external_buttons[name].SetLabel(i18n.t(label_key))
        # The rows are sentences in the old language: forced past the "nothing
        # changed" check of a redraw.
        self._transcription_external_row_labels = []
        self._redraw_external_list()

    # ── The list ─────────────────────────────────────────────────────────────

    def _selected_external_reference(self):
        """The reference the list is on, or None."""
        index = self._transcription_external_list.GetSelection()
        ids = self._transcription_external_row_ids
        if index == wx.NOT_FOUND or not 0 <= index < len(ids):
            return None
        return external_models.find_reference(
            self._transcription_external_references, ids[index]
        )

    def _redraw_external_list(self, keep_id=None):
        """Show the references as they are now, keeping the same one selected.

        Rewritten only when what it would say changed, and inside
        Freeze()/Thaw() like every list mutation in the app.
        """
        i18n = self.main_window.i18n
        references = self._transcription_external_references
        states = self._transcription_external_states
        if keep_id is None:
            selected = self._selected_external_reference()
            keep_id = selected.id if selected is not None else None
        ids = [reference.id for reference in references]
        labels = [
            external_view.row_label(i18n, reference, states.get(reference.id))
            for reference in references
        ]
        listbox = self._transcription_external_list
        if ids != self._transcription_external_row_ids or labels != (
                self._transcription_external_row_labels):
            listbox.Freeze()
            try:
                listbox.Set(labels)
                self._transcription_external_row_ids = ids
                self._transcription_external_row_labels = labels
            finally:
                listbox.Thaw()
        if ids:
            wanted = ids.index(keep_id) if keep_id in ids else 0
            if listbox.GetSelection() != wanted:
                listbox.SetSelection(wanted)
        self._sync_external_buttons()

    def _sync_external_buttons(self):
        """Enable exactly the buttons that can act on what is selected now.

        The focus is left where it is: while something runs every button is
        off, and moving the user off the one they pressed in the middle of it
        would announce the list over "Searching…" and the progress dialog.
        `_restore_external_focus()` finds them a place once it is over.
        """
        reference = self._selected_external_reference()
        state = (None if reference is None
                 else self._transcription_external_states.get(reference.id))
        allowed = external_view.button_states(
            reference, state, self._transcription_job_running
        )
        for name, button in self._transcription_external_buttons.items():
            button.Enable(allowed[name])

    def _restore_external_focus(self, pressed):
        """Never leave the focus on a button the action just switched off.

        The rule `_restore_transcription_focus()` follows for the model row:
        a disabled button answers nothing to a screen reader. The list, when
        it has rows, is what the buttons act on; with none (the last
        reference was just forgotten), the first button that can still be
        pressed.
        """
        if pressed == "check" and self._focus_transcription_result(
                self._transcription_external_buttons.get(pressed)):
            return
        button = self._transcription_external_buttons.get(pressed)
        if button is None or button.IsEnabled():
            return
        if self._transcription_external_list.GetCount():
            self._transcription_external_list.SetFocus()
            return
        for name, _label_key in _EXTERNAL_BUTTONS:
            candidate = self._transcription_external_buttons[name]
            if candidate.IsEnabled():
                candidate.SetFocus()
                return

    def _on_external_selection(self, event):
        self._forget_transcription_outcome()
        self._sync_external_buttons()
        event.Skip()

    # ── Measuring, off the wx thread ─────────────────────────────────────────

    def _external_in_background(self, work, then, fallback=None):
        """Run `work()` on a worker and hand its answer to `then` on the wx thread.

        Everything that touches a folder of the user's goes through here: it
        may be on an unplugged drive or a share that is down, where one stat
        waits out a network timeout and would freeze the window — and the
        screen reader with it. A `work` that raises answers `fallback`.
        """
        def _run():
            try:
                answer = work()
            except Exception as exc:
                logging.warning(
                    "[transcription] looking at an external model folder failed: %s",
                    type(exc).__name__,
                )
                answer = fallback
            wx.CallAfter(self._external_deliver, then, answer)

        threading.Thread(
            target=_run, daemon=True, name="winzapp-transcription-external-probe"
        ).start()

    def _external_deliver(self, then, answer):
        if not self:
            # Configurações was closed while the worker ran.
            return
        then(answer)

    def _refresh_external_models(self, select_id=None):
        """Re-read the references and measure each one's folder.

        The list and the model picker are redrawn at once with what is known
        (a reference not measured yet says "checking"), and again when the
        worker answers. With nothing referenced — nearly everybody — there is
        nothing to measure, and no worker is started.
        """
        references, known = external_models.read_references(
            self._install_wide_settings()
        )
        self._transcription_external_known = known
        if known:
            self._transcription_external_references = references
        else:
            # app.json unreadable for now: keep showing what was read last
            # rather than an empty list the user would take for "forgotten".
            references = self._transcription_external_references
        self._transcription_external_generation += 1
        generation = self._transcription_external_generation
        listed = {r.id for r in references}
        self._transcription_external_states = {
            reference_id: state
            for reference_id, state in self._transcription_external_states.items()
            if reference_id in listed
        }
        self._redraw_external_list(keep_id=select_id)
        self._populate_transcription_model_choices()
        self._show_transcription_hardware_notices()
        if not references:
            return
        self._external_in_background(
            lambda: {r.id: external_models.reference_state(r) for r in references},
            lambda states: self._external_states_measured(generation, states),
        )

    def _external_states_measured(self, generation, states):
        if generation != self._transcription_external_generation or states is None:
            # A newer refresh is on its way, or the measuring failed (and was
            # logged): the rows keep saying "checking" rather than guessing.
            return
        self._transcription_external_states = states
        self._redraw_external_list()
        self._populate_transcription_model_choices()
        self._show_transcription_hardware_notices()

    # ── The buttons ──────────────────────────────────────────────────────────

    def _external_looks_for_files(self) -> bool:
        """Whether "Add..." and "Find..." look for whisper.cpp's GGML files —
        when the backend picker is on whisper.cpp — rather than folders."""
        return (self._transcription_picker_backend()
                == transcription_backend.BACKEND_WHISPER_CPP)

    def _on_external_add(self, _event):
        """Choose a folder (or a whisper.cpp file), then check it."""
        if self._transcription_job_running:
            return
        i18n = self.main_window.i18n
        if self._external_looks_for_files():
            with wx.FileDialog(
                self,
                message=i18n.t(external_view.BROWSE_FILE_TITLE_I18N_KEY),
                wildcard=i18n.t(external_view.BROWSE_FILE_WILDCARD_I18N_KEY),
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            ) as dlg:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                chosen = dlg.GetPath()
            # One file is one model: nothing to pick between, and the check
            # that follows says what it is.
            self._check_external_folder(
                chosen, backend_id=transcription_backend.BACKEND_WHISPER_CPP
            )
            self._restore_external_focus("add")
            return
        with wx.DirDialog(
            self,
            message=i18n.t("transcription_external_browse_dialog_title"),
            style=wx.DD_DEFAULT_STYLE,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            chosen = dlg.GetPath()
        self._set_transcription_job_running(True)
        self._external_in_background(
            lambda: external_view.folder_candidates(chosen),
            self._external_candidates_found,
            fallback=(external_view.Candidate(chosen),),
        )

    def _external_candidates_found(self, candidates):
        self._set_transcription_job_running(False)
        folder = self._external_pick(candidates)
        if folder is not None:
            # Said, not left to the default: a folder is faster-whisper's.
            self._check_external_folder(
                folder, backend_id=transcription_backend.BACKEND_FASTER_WHISPER
            )
        self._restore_external_focus("add")

    def _on_external_find(self, _event):
        """List the Whisper models in the Hugging Face cache not added yet."""
        if self._transcription_job_running:
            return
        self._set_transcription_job_running(True)
        self.main_window.speak_output.output(
            self.main_window.i18n.t(external_view.SEARCHING_I18N_KEY)
        )
        references = self._transcription_external_references
        files = self._external_looks_for_files()
        discover = (external_ggml.discover_hf_cache if files
                    else external_models.discover_hf_cache)
        self._external_in_background(
            lambda: external_view.new_snapshots(discover(), references),
            lambda snapshots: self._external_snapshots_found(snapshots, files),
            fallback=(),
        )

    def _external_snapshots_found(self, snapshots, files=False):
        self._set_transcription_job_running(False)
        if not snapshots:
            self._say_external(external_view.FIND_NONE_I18N_KEY)
            self._restore_external_focus("find")
            return
        folder = self._external_pick(snapshots, always_ask=True)
        if folder is not None:
            self._check_external_folder(
                folder, backend_id=(transcription_backend.BACKEND_WHISPER_CPP if files
                                    else transcription_backend.BACKEND_FASTER_WHISPER),
            )
        self._restore_external_focus("find")

    def _external_pick(self, candidates, always_ask=False):
        """The folder to check out of `candidates`, or None if the user cancels.

        A folder the user browsed to that is one model is not a question.
        Several (every revision in a Hugging Face repository's folder) are a
        plain single-choice dialog, a list a screen reader reads row by row —
        and so is whatever "find" lists, even a single entry: the user asked to
        see what is there, and the check that follows hashes gigabytes.
        """
        if len(candidates) == 1 and not always_ask:
            return candidates[0].path
        i18n = self.main_window.i18n
        labels = [external_view.snapshot_label(i18n, c) for c in candidates]
        with wx.SingleChoiceDialog(
            self,
            i18n.t("transcription_external_pick_prompt"),
            i18n.t("transcription_external_pick_title"),
            labels,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return candidates[dlg.GetSelection()].path

    def _on_external_use(self, _event):
        """Make the selected model the one transcriptions use."""
        reference = self._selected_external_reference()
        if reference is None or self._transcription_job_running:
            return
        # The button is off for a folder that is not ready; the handler says
        # the same so that nothing but that button's rule can choose it.
        if self._transcription_external_states.get(reference.id) != external_models.REF_READY:
            return
        choice = (external_models.custom_choice(reference) if reference.is_custom
                  else reference.model_id)
        if reference.backend != self._transcription_picker_backend():
            # The model is another backend's: its entry is only in that
            # backend's list, and choosing the model chooses the backend.
            self._select_transcription_backend(reference.backend)
            self._populate_transcription_model_choices()
        self._select_transcription_model(choice)
        # SetSelection() fires no event, and an unchanged-looking dialog would
        # not offer Apply for a choice the user has just made.
        self._mark_dirty()
        self._sync_transcription_action_buttons()
        self._show_transcription_hardware_notices()
        self._say_external(
            external_view.USE_DONE_I18N_KEY,
            {"name": external_models.display_name(reference)},
        )

    def _on_external_check(self, _event):
        """Check the selected folder again — the way out of "changed"."""
        reference = self._selected_external_reference()
        if reference is None or self._transcription_job_running:
            return
        self._check_external_folder(reference.path, reference)
        self._restore_external_focus("check")

    def _on_external_forget(self, _event):
        """Drop the reference, after asking. The folder is not touched."""
        reference = self._selected_external_reference()
        if reference is None or self._transcription_job_running:
            return
        i18n = self.main_window.i18n
        name = external_models.display_name(reference)
        if wx.MessageBox(
            i18n.t(external_view.for_reference(
                external_view.FORGET_QUESTION_I18N_KEY, reference.is_file
            )).format(name=name),
            i18n.t("transcription_remove_confirm_title"),
            wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        choice = (external_models.custom_choice(reference) if reference.is_custom
                  else None)
        was_selected = (choice is not None
                        and self._selected_transcription_model() == choice)
        app_settings = self._install_wide_settings()
        self._set_transcription_job_running(True)
        self._external_in_background(
            lambda: external_models.forget_reference(app_settings, reference.id),
            lambda done: self._external_forgotten(
                name, was_selected, done, reference.is_file
            ),
        )

    def _external_forgotten(self, name, was_selected, done, is_file=False):
        self._set_transcription_job_running(False)
        if done is None:
            # The write failed (another window held app.json) and was logged.
            self._refresh_external_models()
            self._restore_external_focus("forget")
            self._say_external(
                management.FAILED_I18N_KEY, outcome=management.OUTCOME_FAILED
            )
            return
        extra = ()
        if was_selected:
            # The picker falls back to "automatic" by itself once the entry is
            # gone; the dialog has to be told its choice changed, and the user
            # has to be told too.
            self._mark_dirty()
            extra = (external_view.FORGOTTEN_RESET_I18N_KEY,)
        self._refresh_external_models()
        self._restore_external_focus("forget")
        self._say_external(
            external_view.for_reference(external_view.FORGOTTEN_I18N_KEY, is_file),
            {"name": name}, extra,
        )

    # ── Checking a folder ────────────────────────────────────────────────────

    def _check_external_folder(self, folder, reference=None, backend_id=None):
        """Verify (or trial-load) `folder`, ask about a custom model if need be,
        say what came of it, and redraw.

        A catalogue model is verified by its digest. A folder nobody claims —
        or one with a catalogue model's sizes and other weights — is only ever
        used because the user said so: the question comes after the check that
        says what it is, and the trial load after the "yes".

        `backend_id` is the kind of model looked for: a reference's own, or
        the one "Add..." and "Find..." looked for.
        """
        if reference is not None:
            backend_id = reference.backend
        kind = (external_job.KIND_CUSTOM
                if reference is not None and reference.is_custom
                else external_job.KIND_VERIFY)
        job, result, error = self._run_external_job(kind, folder, backend_id)
        code = getattr(result, "code", None)
        if (kind == external_job.KIND_VERIFY and error is None and code in (
                external_models.ACCEPT_NOT_IDENTIFIED,
                external_models.ACCEPT_DIGEST_MISMATCH)):
            if self._ask_external_custom(folder, result, backend_id):
                job, result, error = self._run_external_job(
                    external_job.KIND_CUSTOM, folder, backend_id
                )
        self._announce_transcription_result(job, result, error)
        stored = getattr(result, "reference", None)
        self._refresh_external_models(
            select_id=stored.id if stored is not None else None
        )

    def _ask_external_custom(self, folder, outcome, backend_id=None) -> bool:
        identification = getattr(outcome, "identification", None)
        text = external_view.custom_question(
            self.main_window.i18n, folder, outcome.code,
            getattr(identification, "model_id", None),
            is_file=backend_id == transcription_backend.BACKEND_WHISPER_CPP,
        )
        return wx.MessageBox(
            text,
            self.main_window.i18n.t("transcription_external_question_title"),
            wx.YES_NO | wx.ICON_QUESTION, self,
        ) == wx.YES

    def _run_external_job(self, kind, folder, backend_id=None):
        """Run one check behind the progress dialog; (job, result, error).

        `backend_id` is the kind of model `folder` is checked as: whisper.cpp
        for a GGML file, anything else for a faster-whisper folder.
        """
        i18n = self.main_window.i18n
        app_settings = self._install_wide_settings()
        # The folder in force, never one that is only chosen: the same rule as
        # _run_transcription_job(), and what the "inside the models folder"
        # refusal is measured against.
        models_root = transcription_preferences.resolve_models_dir(
            self._stored_transcription_models_dir()
        )
        # ...and the folder that is chosen and not applied yet is refused
        # too: OK would move WinZapp's models into it, on top of this folder.
        pending = transcription_preferences.resolve_models_dir(
            self._transcription_models_dir
        )
        other_roots = (pending,) if pending != models_root else ()
        preference = self._selected_transcription_device_preference()
        # The trial loads a folder the way the run will (part 11).
        compute_preference = (self._selected_transcription_precision()
                              or transcription_preferences.AUTO)
        is_file = backend_id == transcription_backend.BACKEND_WHISPER_CPP

        def _make_job(on_progress, on_finished):
            return external_job.ExternalModelJob(
                kind, app_settings, folder, models_root,
                device_preference=preference, backend_id=backend_id,
                on_progress=on_progress, on_finished=on_finished,
                other_roots=other_roots,
                compute_type_preference=compute_preference,
            )

        dialog = TranscriptionProgressDialog(
            self,
            i18n,
            self.main_window.speak_output,
            _make_job,
            i18n.t(external_view.for_reference(
                external_job.STATUS_I18N_KEYS[kind], is_file
            )).format(
                name=external_models.folder_name(folder)
            ),
        )
        self._set_transcription_job_running(True)
        try:
            dialog.run()
            return dialog.job, dialog.result, dialog.error
        finally:
            dialog.Destroy()
            self._set_transcription_job_running(False)

    def _say_external(self, key, values=None, extra_keys=(),
                      outcome=management.OUTCOME_DONE):
        """Say one sentence of this section: spoken once, and left on screen."""
        self._announce_transcription_result(
            _Said(management.Announcement(key, outcome, values or {})),
            None, None, extra_keys,
        )
