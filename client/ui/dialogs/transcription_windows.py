"""The windows of the Transcription tab: groups of its options reached from a
button on the tab, as on the Audio and Interface pages.

The tab had grown to more controls than there are letters, so its controls
could not each have an Alt+letter of their own (the code said so in two
places). Six groups now live in windows of their own, each with its own
letters:

* the advanced options: the calculation precision (TranscriptionPrecisionMixin),
  keeping the model loaded and transcribing without the progress window
  (TranscriptionOptionsMixin);
* the saved transcriptions (TranscriptionCacheMixin);
* the options for statuses (TranscriptionOptionsMixin);
* the models folder and the models in other folders (ExternalModelsMixin);
* the CUDA libraries, and the folder to reuse them from;
* the whisper.cpp program (WhisperCppMixin), and the folder to reuse it from
  (TranscriptionReuseMixin).

The two downloads that are not models have a window each because their action
buttons are the same words (Install, Repair and so on), and so the same letters.

Their controls are built once and kept, like the tab's, so loading, applying
and the dialog's Apply button work as before; the settings' search finds them
and opens the window on the option (SettingsPages.add_subpage).
"""

import wx

from ui.dialogs.settings_pages import SubPageDialog


def window_title(label: str) -> str:
    """A window's title from the label of the button that opens it."""
    return label.replace("&", "").rstrip(".… ").strip()


class TranscriptionWindowsMixin:
    """The Transcription tab's six windows, for `SettingsDialog`."""

    def _build_transcription_windows(self, page) -> None:
        """The windows and their panels; the builders fill the panels. *page*
        is the tab, which the windows belong next to (the settings dialog is
        their parent)."""
        i18n = self.main_window.i18n
        ok = i18n.t("ok")
        self._transcription_advanced_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_advanced_button")), ok, on_change=self._mark_dirty)
        self._transcription_advanced_panel = wx.Panel(self._transcription_advanced_dialog)
        self._transcription_advanced_sizer = wx.BoxSizer(wx.VERTICAL)
        self._transcription_saved_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_saved_button")), ok, on_change=self._mark_dirty)
        self._transcription_saved_panel = wx.Panel(self._transcription_saved_dialog)
        self._transcription_saved_sizer = wx.BoxSizer(wx.VERTICAL)
        self._transcription_statuses_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_statuses_button")), ok, on_change=self._mark_dirty)
        self._transcription_statuses_panel = wx.Panel(self._transcription_statuses_dialog)
        self._transcription_statuses_sizer = wx.BoxSizer(wx.VERTICAL)
        self._transcription_folders_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_folders_button")), ok, on_change=self._mark_dirty)
        self._transcription_folders_panel = wx.Panel(self._transcription_folders_dialog)
        self._transcription_folders_sizer = wx.BoxSizer(wx.VERTICAL)
        self._transcription_cuda_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_cuda_button")), ok, on_change=self._mark_dirty)
        self._transcription_cuda_panel = wx.Panel(self._transcription_cuda_dialog)
        self._transcription_cuda_sizer = wx.BoxSizer(wx.VERTICAL)
        self._transcription_whisper_dialog = SubPageDialog(
            self, window_title(i18n.t("transcription_whisper_cpp_button")), ok, on_change=self._mark_dirty)
        self._transcription_whisper_panel = wx.Panel(self._transcription_whisper_dialog)
        self._transcription_whisper_sizer = wx.BoxSizer(wx.VERTICAL)

    def _transcription_windows(self):
        """(dialog, panel, sizer, button, key) of each window, in tab order."""
        return (
            (self._transcription_advanced_dialog, self._transcription_advanced_panel,
             self._transcription_advanced_sizer, self._transcription_advanced_btn,
             "transcription_advanced_button"),
            (self._transcription_saved_dialog, self._transcription_saved_panel,
             self._transcription_saved_sizer, self._transcription_saved_btn,
             "transcription_saved_button"),
            (self._transcription_statuses_dialog, self._transcription_statuses_panel,
             self._transcription_statuses_sizer, self._transcription_statuses_btn,
             "transcription_statuses_button"),
            (self._transcription_folders_dialog, self._transcription_folders_panel,
             self._transcription_folders_sizer, self._transcription_folders_btn,
             "transcription_folders_button"),
            (self._transcription_cuda_dialog, self._transcription_cuda_panel,
             self._transcription_cuda_sizer, self._transcription_cuda_btn,
             "transcription_cuda_button"),
            (self._transcription_whisper_dialog, self._transcription_whisper_panel,
             self._transcription_whisper_sizer, self._transcription_whisper_btn,
             "transcription_whisper_cpp_button"),
        )

    def _add_transcription_advanced_button(self, page, sizer) -> None:
        self._transcription_advanced_btn = wx.Button(
            page, label=self.main_window.i18n.t("transcription_advanced_button"))
        self._transcription_advanced_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_advanced_dialog.open())
        sizer.Add(self._transcription_advanced_btn, 0, wx.ALL, 8)

    def _add_transcription_saved_button(self, page, sizer) -> None:
        self._transcription_saved_btn = wx.Button(page, label=self.main_window.i18n.t("transcription_saved_button"))
        self._transcription_saved_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_saved_dialog.open())
        sizer.Add(self._transcription_saved_btn, 0, wx.ALL, 8)

    def _add_transcription_statuses_button(self, page, sizer) -> None:
        self._transcription_statuses_btn = wx.Button(
            page, label=self.main_window.i18n.t("transcription_statuses_button"))
        self._transcription_statuses_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_statuses_dialog.open())
        sizer.Add(self._transcription_statuses_btn, 0, wx.ALL, 8)

    def _add_transcription_folders_button(self, page, sizer) -> None:
        self._transcription_folders_btn = wx.Button(
            page, label=self.main_window.i18n.t("transcription_folders_button"))
        self._transcription_folders_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_folders_dialog.open())
        sizer.Add(self._transcription_folders_btn, 0, wx.ALL, 8)

    def _add_transcription_cuda_button(self, page, sizer) -> None:
        self._transcription_cuda_btn = wx.Button(
            page, label=self.main_window.i18n.t("transcription_cuda_button"))
        self._transcription_cuda_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_cuda_dialog.open())
        sizer.Add(self._transcription_cuda_btn, 0, wx.ALL, 8)

    def _add_transcription_whisper_cpp_button(self, page, sizer) -> None:
        self._transcription_whisper_btn = wx.Button(
            page, label=self.main_window.i18n.t("transcription_whisper_cpp_button"))
        self._transcription_whisper_btn.Bind(wx.EVT_BUTTON, lambda e: self._transcription_whisper_dialog.open())
        sizer.Add(self._transcription_whisper_btn, 0, wx.ALL, 8)

    def _finish_transcription_windows(self) -> None:
        """Once the builders have filled the panels."""
        for dialog, panel, sizer, _button, _key in self._transcription_windows():
            panel.SetSizer(sizer)
            dialog.set_body(panel)

    def _register_transcription_windows(self) -> None:
        """For the settings' search, once the tab is in the category list."""
        index = self._notebook.FindPage(self._transcription_page)
        for dialog, panel, _sizer, button, key in self._transcription_windows():
            self._notebook.add_subpage(
                index, window_title(self.main_window.i18n.t(key)), panel,
                lambda control=None, opened=dialog: opened.open(control))

    def _refresh_transcription_window_labels(self) -> None:
        i18n = self.main_window.i18n
        for dialog, _panel, _sizer, button, key in self._transcription_windows():
            button.SetLabel(i18n.t(key))
            dialog.SetTitle(window_title(i18n.t(key)))
