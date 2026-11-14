"""Reusing CUDA libraries and whisper.cpp programs already downloaded elsewhere.

Two folders, each with a read-only field, a Browse button and a Forget button,
each in the window of what it holds (transcription_windows.py): the CUDA
libraries' and the whisper.cpp program's. In one window the two rows' buttons
shared their words and so their Alt keys. The rules (what a folder
must hold, why it is only ever read) are core/transcription/reused_runtimes.py.

A folder is checked the moment it is chosen — the CUDA one loads its libraries,
which maps ~0.7 GB, so that happens off the wx thread — and stored only on
Apply/OK, as every other setting of the dialog: Cancel discards the choice.
The stored value is install-wide (app_settings), like the models folder.
"""

import os
import threading

import wx

from core.transcription import management_text, reused_runtimes
from ui.dialogs.settings_pages import dialog_owner

#: The words of each row, the same on both: relabelled by kind in
#: _refresh_transcription_reuse_labels(), where the dicts below keep each control.
_GROUP_KEY = "transcription_reuse_group"
_BROWSE_KEY = "transcription_models_dir_browse_btn"
_FORGET_KEY = "transcription_external_forget_btn"

_CUDA = "cuda"
_WHISPER_CPP = "whisper_cpp"

#: kind -> (label key, browse-dialog key, app_settings key)
_KINDS = {
    _CUDA: ("transcription_reuse_cuda_label", "transcription_reuse_browse_cuda",
            reused_runtimes.CUDA_SETTING),
    _WHISPER_CPP: ("transcription_reuse_whisper_cpp_label",
                   "transcription_reuse_browse_whisper_cpp",
                   reused_runtimes.WHISPER_CPP_SETTING),
}


class TranscriptionReuseMixin:
    """The reuse group, for `SettingsDialog`."""

    def _init_transcription_reuse(self) -> None:
        if getattr(self, "_transcription_reuse_fields", None) is not None:
            return
        self._transcription_reuse_dirs = {_CUDA: "", _WHISPER_CPP: ""}
        self._transcription_reuse_checking = set()
        self._transcription_reuse_boxes = {}
        self._transcription_reuse_labels = {}
        self._transcription_reuse_fields = {}
        self._transcription_reuse_choose = {}
        self._transcription_reuse_forget = {}

    def _build_transcription_reuse_cuda(self, page, sizer) -> None:
        self._build_transcription_reuse_row(page, sizer, _CUDA, "transcription_reuse_cuda_label")

    def _build_transcription_reuse_whisper_cpp(self, page, sizer) -> None:
        self._build_transcription_reuse_row(page, sizer, _WHISPER_CPP,
                                            "transcription_reuse_whisper_cpp_label")

    def _build_transcription_reuse_row(self, page, sizer, kind, label_key) -> None:
        """One folder's row. *label_key* is _KINDS[kind]'s, given by the
        caller so tests/settings_controls.py can read it off the call."""
        i18n = self.main_window.i18n
        self._init_transcription_reuse()
        box = wx.StaticBox(page, label=i18n.t(_GROUP_KEY))
        group = wx.StaticBoxSizer(box, wx.VERTICAL)
        label = wx.StaticText(box, label=i18n.t(label_key))
        group.Add(label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        field = wx.TextCtrl(box, style=wx.TE_DONTWRAP)
        field.SetEditable(False)
        choose = wx.Button(box, label=i18n.t(_BROWSE_KEY))
        forget = wx.Button(box, label=i18n.t(_FORGET_KEY))
        choose.Bind(wx.EVT_BUTTON, lambda _e, k=kind: self._on_transcription_reuse_choose(k))
        forget.Bind(wx.EVT_BUTTON, lambda _e, k=kind: self._on_transcription_reuse_forget(k))
        row.Add(field, 1, wx.EXPAND | wx.RIGHT, 8)
        row.Add(choose, 0, wx.RIGHT, 8)
        row.Add(forget, 0)
        group.Add(row, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(group, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._transcription_reuse_boxes[kind] = box
        self._transcription_reuse_labels[kind] = label
        self._transcription_reuse_fields[kind] = field
        self._transcription_reuse_choose[kind] = choose
        self._transcription_reuse_forget[kind] = forget
        self._refresh_transcription_reuse_labels()

    # ── Showing ──────────────────────────────────────────────────────────────

    def _show_transcription_reuse(self) -> None:
        i18n = self.main_window.i18n
        for kind, field in self._transcription_reuse_fields.items():
            folder = self._transcription_reuse_dirs[kind]
            # ChangeValue: showing a folder is not an edit (see
            # _show_transcription_models_dir).
            field.ChangeValue(folder or i18n.t("transcription_reuse_none"))
            self._transcription_reuse_forget[kind].Enable(bool(folder))
            # Browse stays enabled while its folder is checked (a second press
            # is ignored): it holds the focus, and a disabled control says
            # nothing to a screen reader.

    def _refresh_transcription_reuse_labels(self) -> None:
        i18n = self.main_window.i18n
        for kind, label in self._transcription_reuse_labels.items():
            self._transcription_reuse_boxes[kind].SetLabel(i18n.t(_GROUP_KEY))
            label.SetLabel(i18n.t(_KINDS[kind][0]))
            self._transcription_reuse_choose[kind].SetLabel(i18n.t(_BROWSE_KEY))
            self._transcription_reuse_forget[kind].SetLabel(i18n.t(_FORGET_KEY))
        self._show_transcription_reuse()

    # ── Loading and applying ─────────────────────────────────────────────────

    def _load_transcription_reuse(self) -> None:
        app = self._install_wide_settings()
        for kind, (_label, _dialog, setting) in _KINDS.items():
            stored = ""
            if app is not None:
                try:
                    stored = str(app.get(setting) or "")
                except Exception:
                    stored = ""
            self._transcription_reuse_dirs[kind] = stored
        self._show_transcription_reuse()

    def _apply_transcription_reuse(self) -> None:
        """Store what changed, and put it into effect now."""
        app = self._install_wide_settings()
        if app is None:
            return
        changed = False
        for kind, (_label, _dialog, setting) in _KINDS.items():
            wanted = self._transcription_reuse_dirs[kind]
            try:
                if str(app.get(setting) or "") != wanted:
                    app.set(setting, wanted)
                    changed = True
            except Exception:
                # An unreadable or unwritable app.json: the choice is kept in
                # the dialog and tried again on the next Apply.
                continue
        if changed:
            reused_runtimes.configure_from(app)
            # The CUDA line and the builds list say when what they describe
            # comes from the reused folder (transcription_reuse_in_use_note),
            # and the device notices follow what a run will pick: redrawn now
            # that the folders changed.
            self._show_transcription_cuda_status()
            self._show_whisper_cpp_status()
            self._show_transcription_hardware_notices()

    # ── Choosing and forgetting ──────────────────────────────────────────────

    def _on_transcription_reuse_choose(self, kind) -> None:
        if kind in self._transcription_reuse_checking:
            return
        i18n = self.main_window.i18n
        _label, dialog_key, _setting = _KINDS[kind]
        current = self._transcription_reuse_dirs[kind]
        default_path = current if current and os.path.isdir(current) else ""
        with wx.DirDialog(dialog_owner(self),
                          message=i18n.t(dialog_key), defaultPath=default_path,
                          style=wx.DD_DEFAULT_STYLE) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            chosen = dlg.GetPath()
        self._transcription_reuse_checking.add(kind)
        self._show_transcription_reuse()

        def _work():
            try:
                if kind == _CUDA:
                    check = reused_runtimes.check_cuda_folder(chosen)
                else:
                    check = reused_runtimes.check_whisper_cpp_folder(chosen)
            except Exception:
                check = None
            wx.CallAfter(self._finish_transcription_reuse_check, kind, check)

        threading.Thread(target=_work, name="reuse-check", daemon=True).start()

    def _finish_transcription_reuse_check(self, kind, check) -> None:
        if not self:
            return
        self._transcription_reuse_checking.discard(kind)
        i18n = self.main_window.i18n
        if check is None:
            key, args = "transcription_reuse_not_a_folder", {}
        elif kind == _CUDA:
            key, args = reused_runtimes.cuda_check_message(check)
        else:
            key, args = reused_runtimes.whisper_cpp_check_message(
                check, lambda build_id: management_text.build_name(i18n, build_id))
        text = i18n.t(key).format(**args)
        if check is not None and check.code == reused_runtimes.OK:
            self._transcription_reuse_dirs[kind] = check.path
            self._show_transcription_reuse()
            self._mark_dirty()
            self.main_window.speak_output.output(text, interrupt=True)
            return
        self._show_transcription_reuse()
        wx.MessageBox(text, i18n.t("settings_title"), wx.OK | wx.ICON_INFORMATION,
                      dialog_owner(self))

    def _on_transcription_reuse_forget(self, kind) -> None:
        if not self._transcription_reuse_dirs[kind]:
            return
        self._transcription_reuse_dirs[kind] = ""
        self._show_transcription_reuse()
        self._mark_dirty()
        self._transcription_reuse_choose[kind].SetFocus()
        self.main_window.speak_output.output(
            self.main_window.i18n.t("transcription_reuse_forgotten"), interrupt=True)
