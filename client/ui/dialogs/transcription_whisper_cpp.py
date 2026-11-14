"""The whisper.cpp part of the Transcription tab, split out of transcription_tab.py.

Two things the second backend (part 9b) adds to the tab, and only those:

* **The backend picker decides what the model picker lists.** Each backend
  loads its own files — faster-whisper a CTranslate2 folder, whisper.cpp one
  GGML file per quantization — so the model list is the catalogue of the
  backend selected *now* (`preferences.catalogue_models()`), redrawn as the
  backend changes. "Automatic" lists faster-whisper's, which is what it
  resolves to.
* **The whisper.cpp program.** whisper-cli is a download of its own: a build
  for the processor, and one for NVIDIA cards where the card can run it
  (`whisper_cpp_builds.builds_offered()` for its compute capability). It goes
  into a WinZapp-owned install-wide folder that the models-folder setting
  never moves (`whisper_cpp_runtime.default_runtime_dir()`). A read-only
  combobox lists the builds — the processor one always, and first — each item
  one sentence with its state and size, and four buttons under it act on the
  selected one, in a named group like the model and CUDA rows. They are
  management actions: asked about the same way, run behind the same progress
  dialog and said through the same funnel as the model downloads.

`WhisperCppMixin` is mixed into `SettingsDialog` beside `TranscriptionTabMixin`,
whose state it shares (job flag, action-button registry, probe, announcement
field). Nothing here is measured on opening the dialog beyond what the CUDA
line already reads: a manifest and the sizes of the files it lists.
"""

import wx

from core.transcription import (
    backend as transcription_backend,
    errors as transcription_errors,
    management as transcription_management,
    management_whisper_cpp,
    model_store,
    whisper_cpp_builds,
    whisper_cpp_runtime,
)
from ui.dialogs.transcription_tab import (
    _TRANSCRIPTION_STATE_CORRUPTED,
    _format_transcription_size,
    _transcription_action_states,
    _whisper_cpp_build_name,
)

# The four buttons, (action, label key, state key) as in the tab's two rows.
_WHISPER_CPP_ACTION_BUTTONS = (
    (transcription_management.ACTION_INSTALL_WHISPER_CPP,
     "transcription_whisper_cpp_install_btn", "download"),
    (transcription_management.ACTION_VERIFY_WHISPER_CPP,
     "transcription_whisper_cpp_verify_btn", "verify"),
    (transcription_management.ACTION_REPAIR_WHISPER_CPP,
     "transcription_whisper_cpp_repair_btn", "repair"),
    (transcription_management.ACTION_REMOVE_WHISPER_CPP,
     "transcription_whisper_cpp_remove_btn", "remove"),
)

#: The group's name, without a mnemonic for the reason the other groups give.
_WHISPER_CPP_ACTIONS_GROUP = "transcription_whisper_cpp_actions_group"

#: One line of the builds combobox, by what is on disk. An install of an
#: earlier release is INCOMPLETE too, and "Repair" replaces it either way.
_BUILD_CHOICE_I18N_KEYS = {
    whisper_cpp_runtime.STATE_INSTALLED: "transcription_whisper_cpp_choice_installed",
    whisper_cpp_runtime.STATE_INCOMPLETE: "transcription_whisper_cpp_choice_incomplete",
    whisper_cpp_runtime.STATE_ABSENT: "transcription_whisper_cpp_choice_absent",
}


def whisper_cpp_build_label(i18n, build, state, reused=False) -> str:
    """One line of the builds combobox, written as a sentence.

    Which build, whether it is here, and the download it costs — the whole of
    what the user chooses on, since a combobox item is read whole and nothing
    else is. An unknown state reads as "not installed", as on the model list.
    `reused`: not installed in WinZapp's own folder, but in use from the folder
    the user asked to reuse (transcription_reuse.py) — said, or the line would
    offer to download what is already being used.
    """
    key = _BUILD_CHOICE_I18N_KEYS.get(
        state, _BUILD_CHOICE_I18N_KEYS[whisper_cpp_runtime.STATE_ABSENT]
    )
    text = i18n.t(key).format(
        build=_whisper_cpp_build_name(i18n, build.id),
        size=_format_transcription_size(i18n, build.archive_bytes),
    )
    if reused and state != whisper_cpp_runtime.STATE_INSTALLED:
        text = f"{text} {i18n.t('transcription_reuse_in_use_note')}"
    return text


def listed_builds(compute_capability, states) -> tuple:
    """The builds the combobox lists: the ones offered to this card, plus any
    already on disk — a graphics build installed before the card was swapped
    must still be reachable by "Remove"."""
    offered = whisper_cpp_builds.builds_offered(compute_capability)
    return tuple(
        build for build in whisper_cpp_builds.BUILDS
        if build in offered
        or states.get(build.id, whisper_cpp_runtime.STATE_ABSENT)
        != whisper_cpp_runtime.STATE_ABSENT
    )


class WhisperCppMixin:
    """The whisper.cpp half of `SettingsDialog`'s Transcription tab."""

    # ── The backend picker ───────────────────────────────────────────────────

    def _transcription_picker_backend(self):
        """The backend whose catalogue the model picker lists.

        The selected one, or the first of BACKEND_IDS for "automatic" (and
        while the picker does not exist yet) — what _resolve_backend() falls
        back to when nobody measured which backends run here.
        """
        selected = self._selected_transcription_backend()
        if selected in transcription_backend.BACKEND_IDS:
            return selected
        return transcription_backend.BACKEND_IDS[0]

    def _on_transcription_backend_change(self, event):
        """Another backend, another list of models.

        A model of the other backend's list is no choice for this one: the
        picker falls back to "automatic" by itself (`_select_id()`), which is
        also what the run would do with it.
        """
        self._forget_transcription_outcome()
        self._populate_transcription_model_choices()
        self._show_transcription_hardware_notices()
        # Skip(): the dialog-level handler is what shows Apply.
        event.Skip()

    # ── The program ──────────────────────────────────────────────────────────

    def _build_whisper_cpp_section(self, page, sizer):
        """The builds combobox and its four buttons, laid out in `page`."""
        i18n = self.main_window.i18n
        #: whisper_cpp_runtime.installation_state()'s state per build id, as
        #: last measured; empty until then, which disables every button.
        self._whisper_cpp_states = {}
        #: Builds a check found damaged — the state only a hash can see, kept
        #: for the reason _TRANSCRIPTION_STATE_CORRUPTED gives.
        self._whisper_cpp_corrupted = set()
        #: Parallel to the combobox items, and the items as last set, so a
        #: redraw that would say the same thing leaves the list alone.
        self._whisper_cpp_build_ids = []
        self._whisper_cpp_build_labels = []

        self._whisper_cpp_label = wx.StaticText(
            page, label=i18n.t("transcription_whisper_cpp_label")
        )
        sizer.Add(self._whisper_cpp_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._whisper_cpp_combo = wx.ComboBox(page, style=wx.CB_READONLY)
        sizer.Add(self._whisper_cpp_combo, 0, wx.EXPAND | wx.ALL, 8)
        self._whisper_cpp_combo.Bind(wx.EVT_COMBOBOX, self._on_whisper_cpp_build_change)
        self._build_transcription_action_row(
            page, sizer, _WHISPER_CPP_ACTION_BUTTONS, _WHISPER_CPP_ACTIONS_GROUP,
        )
        self._populate_whisper_cpp_builds()

    def _refresh_whisper_cpp_labels(self):
        """Retranslate this section after a language change. The group's name
        is retranslated with the other groups, by the tab."""
        i18n = self.main_window.i18n
        self._whisper_cpp_label.SetLabel(i18n.t("transcription_whisper_cpp_label"))
        for action, label_key, _state_key in _WHISPER_CPP_ACTION_BUTTONS:
            self._transcription_action_buttons[action].SetLabel(i18n.t(label_key))
        # The items are sentences in the old language: forced past the
        # "nothing changed" check.
        self._whisper_cpp_build_labels = []
        self._populate_whisper_cpp_builds()

    def _show_whisper_cpp_status(self):
        """Measure every build's folder and redraw the list from it."""
        self._whisper_cpp_states = {
            build.id: whisper_cpp_runtime.installation_state(build).state
            for build in whisper_cpp_builds.BUILDS
        }
        # Builds WinZapp's own folder lacks but the reused folder serves.
        self._whisper_cpp_reused = {
            build.id for build in whisper_cpp_builds.BUILDS
            if self._whisper_cpp_states[build.id] != whisper_cpp_runtime.STATE_INSTALLED
            and whisper_cpp_runtime.usable_root(build) is not None
        }
        self._populate_whisper_cpp_builds()

    def _populate_whisper_cpp_builds(self):
        """Rebuild the builds list, keeping whatever was selected selected."""
        i18n = self.main_window.i18n
        builds = listed_builds(
            getattr(self._transcription_probe, "compute_capability", None),
            self._whisper_cpp_states,
        )
        ids = [build.id for build in builds]
        reused = getattr(self, "_whisper_cpp_reused", set())
        labels = [
            whisper_cpp_build_label(i18n, build, self._whisper_cpp_states.get(build.id),
                                    reused=build.id in reused)
            for build in builds
        ]
        if ids != self._whisper_cpp_build_ids or labels != self._whisper_cpp_build_labels:
            selected = self._selected_whisper_cpp_build()
            # Set() replaces the list in one call, as for the model picker.
            self._whisper_cpp_combo.Set(labels)
            self._whisper_cpp_build_ids = ids
            self._whisper_cpp_build_labels = labels
            # The processor build is index 0, and the right fallback.
            self._select_id(self._whisper_cpp_combo, ids, selected)
        self._sync_transcription_action_buttons()

    def _selected_whisper_cpp_build(self):
        return self._selected_id(self._whisper_cpp_combo, self._whisper_cpp_build_ids)

    def _whisper_cpp_cuda_installed(self) -> bool:
        """Whether the graphics build was measured complete. False before the
        first measurement: the device a run would pick is then the processor,
        which is what the notices must not contradict."""
        return (self._whisper_cpp_states.get(whisper_cpp_builds.BUILD_CUDA.id)
                == whisper_cpp_runtime.STATE_INSTALLED
                # Served from the reused folder: what a run will use too.
                or whisper_cpp_builds.BUILD_CUDA.id in getattr(self, "_whisper_cpp_reused", set()))

    def _whisper_cpp_button_state(self):
        build_id = self._selected_whisper_cpp_build()
        if build_id is None:
            return None
        state = self._whisper_cpp_states.get(build_id)
        if (build_id in self._whisper_cpp_corrupted
                and state != whisper_cpp_runtime.STATE_ABSENT):
            return _TRANSCRIPTION_STATE_CORRUPTED
        return state

    def _sync_whisper_cpp_buttons(self):
        """Enable exactly the four buttons that can act on the selected build."""
        buttons = [
            self._transcription_action_buttons.get(action)
            for action, _label_key, _state_key in _WHISPER_CPP_ACTION_BUTTONS
        ]
        if None in buttons:
            # The page is still being built: the section comes last.
            return
        allowed = _transcription_action_states(
            self._whisper_cpp_button_state(), self._transcription_job_running
        )
        for button, (_action, _label_key, state_key) in zip(
                buttons, _WHISPER_CPP_ACTION_BUTTONS):
            button.Enable(allowed[state_key])

    def _on_whisper_cpp_build_change(self, event):
        """Another build, another set of buttons. Not Skip()ped: choosing
        which build to act on changes no setting, and the dialog-level
        handler would offer Apply for it."""
        self._forget_transcription_outcome()
        self._sync_transcription_action_buttons()

    # ── The four actions ─────────────────────────────────────────────────────

    def _start_whisper_cpp_action(self, action):
        """Ask before a download or a removal, then run it."""
        build_id = self._selected_whisper_cpp_build()
        if build_id is None:
            return
        if action in (transcription_management.ACTION_INSTALL_WHISPER_CPP,
                      transcription_management.ACTION_REPAIR_WHISPER_CPP):
            self._measure_whisper_cpp_install(action, build_id)
            return
        if (action == transcription_management.ACTION_REMOVE_WHISPER_CPP
                and not self._ask_whisper_cpp_removal(build_id)):
            return
        self._run_whisper_cpp_job(action, build_id, self._transcription_probe)

    def _measure_whisper_cpp_install(self, action, build_id):
        """The probe and the free space, off the wx thread — the same wait as
        a model download's (see _measure_transcription_download())."""
        self._set_transcription_job_running(True)
        root = whisper_cpp_runtime.default_runtime_dir()

        def _measured(probe):
            free = model_store.free_bytes(root)
            wx.CallAfter(self._confirm_whisper_cpp_install, action, build_id, probe, free)

        transcription_management.probe_in_background(_measured)

    def _confirm_whisper_cpp_install(self, action, build_id, probe, free_bytes):
        """Back on the wx thread with the measurements: ask, then run."""
        if not self:
            return
        self._adopt_transcription_probe(probe)
        self._set_transcription_job_running(False)
        repair = action == transcription_management.ACTION_REPAIR_WHISPER_CPP
        installed = tuple(
            installed_id for installed_id, state in self._whisper_cpp_states.items()
            if state == whisper_cpp_runtime.STATE_INSTALLED
        )
        summary = management_whisper_cpp.whisper_cpp_download_summary(
            build_id, probe, free_bytes, installed,
            device_preference=self._selected_transcription_device_preference(),
            repair=repair,
        )
        if summary is None or not self._ask_transcription_download(summary, repair):
            return
        self._run_whisper_cpp_job(action, build_id, probe)

    def _ask_whisper_cpp_removal(self, build_id) -> bool:
        """Ask before deleting. Removing the processor build takes the
        graphics one with it (management's rule), and the question says so."""
        i18n = self.main_window.i18n
        if build_id == whisper_cpp_builds.BUILD_CPU.id:
            text = i18n.t("transcription_confirm_remove_whisper_cpp_cpu")
        else:
            text = i18n.t("transcription_confirm_remove_whisper_cpp").format(
                build=_whisper_cpp_build_name(i18n, build_id)
            )
        return wx.MessageBox(
            text, i18n.t("transcription_remove_confirm_title"),
            wx.YES_NO | wx.ICON_QUESTION, self,
        ) == wx.YES

    def _run_whisper_cpp_job(self, action, build_id, probe):
        """Run it behind the progress dialog (or in the background), then say
        it and redraw."""
        self._start_transcription_job(
            action, build_id=build_id,
            # The install refuses the graphics build without the capability
            # it was offered for.
            compute_capability=getattr(probe, "compute_capability", None),
        )

    def _finish_whisper_cpp_job(self, action, build_id, job, result, error,
                                restore_focus=True):
        """What the tab does once a whisper.cpp action has ended."""
        code = getattr(error, "code", None)
        if code == transcription_errors.WHISPER_CPP_CORRUPTED:
            self._whisper_cpp_corrupted.add(build_id)
        elif error is None:
            self._whisper_cpp_corrupted.discard(build_id)
        self._announce_transcription_result(job, result, error)
        self._show_whisper_cpp_status()
        # The graphics build installed or gone changes what the card can do.
        self._show_transcription_hardware_notices()
        if restore_focus:
            self._restore_whisper_cpp_focus(action)

    def _restore_whisper_cpp_focus(self, action):
        """Never leave the focus on a button the action just switched off —
        the rule of _restore_transcription_focus(), for this row."""
        if (action == transcription_management.ACTION_VERIFY_WHISPER_CPP
                and self._focus_transcription_result(
                    self._transcription_action_buttons.get(action))):
            return
        button = self._transcription_action_buttons.get(action)
        if button is None or button.IsEnabled():
            return
        for other, _label_key, _state_key in _WHISPER_CPP_ACTION_BUTTONS:
            candidate = self._transcription_action_buttons.get(other)
            if candidate is not None and candidate.IsEnabled():
                candidate.SetFocus()
                return
        self._whisper_cpp_combo.SetFocus()
