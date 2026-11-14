"""The saved-transcription ("cache") controls of the Transcription tab.

A transcription is kept per model (core/transcription/stored.py): changing the
model asks for a new one, and the old model's text stays for the day the user
goes back to it. This mixin holds everything about that keeping:

* a general switch (``cache_enabled``, on by default) and, for the selected
  model, a choice that overrides it (follow the general setting / on / off, in
  ``cache_by_model`` by model id). With the cache off for a model its new
  results are not saved: ``MainWindow.store_message_transcription()`` answers
  SAVE_DISABLED and the result is shown in the window instead. Texts already
  saved stay until cleared — the buttons below.
* a button that deletes what the selected model made, in every chat, and one
  that deletes what every model made. Other models' results are untouched by
  the first.

Clearing is not one of the tab's job-driven actions: nothing is downloaded and
no progress dialog is needed, only a confirmation, the database write (done by
the main window, on its transcription write queue) and one spoken sentence. The
buttons sit under the model's action group as buttons of their own because a
group button is one word, and no one word says what these delete.
"""

import wx

from core.transcription import model_names
from core.transcription import preferences as transcription_preferences
from core.transcription import stored as stored_transcription


class TranscriptionCacheMixin:
    """The cache controls, for `SettingsDialog`."""

    def _build_transcription_cache(self, page, sizer) -> None:
        i18n = self.main_window.i18n
        self._transcription_cache_check = wx.CheckBox(
            page, label=i18n.t("transcription_cache_check")
        )
        sizer.Add(self._transcription_cache_check, 0, wx.ALL, 8)
        self._transcription_cache_overrides = {}
        self._transcription_cache_model_label = wx.StaticText(
            page, label=i18n.t("transcription_cache_model_label")
        )
        sizer.Add(self._transcription_cache_model_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._transcription_cache_choice = wx.Choice(page)
        self._transcription_cache_choice.Set(self._transcription_cache_choice_labels())
        self._transcription_cache_choice.SetSelection(0)
        self._transcription_cache_choice.Bind(wx.EVT_CHOICE, self._on_transcription_cache_choice)
        sizer.Add(self._transcription_cache_choice, 0, wx.EXPAND | wx.ALL, 8)
        self._transcription_clear_cache_btn = wx.Button(page, label=i18n.t("transcription_clear_cache_btn"))
        self._transcription_clear_cache_btn.Bind(
            wx.EVT_BUTTON, self._on_transcription_clear_cache
        )
        sizer.Add(self._transcription_clear_cache_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._transcription_clear_all_cache_btn = wx.Button(
            page, label=i18n.t("transcription_clear_all_cache_btn")
        )
        self._transcription_clear_all_cache_btn.Bind(
            wx.EVT_BUTTON, self._on_transcription_clear_all_cache
        )
        sizer.Add(self._transcription_clear_all_cache_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._sync_transcription_clear_cache_button()

    def _transcription_cache_choice_labels(self):
        i18n = self.main_window.i18n
        return [i18n.t("transcription_cache_follow"), i18n.t("transcription_cache_on"),
                i18n.t("transcription_cache_off")]

    # ── Loading, applying, relabelling ───────────────────────────────────────

    def _load_transcription_cache(self) -> None:
        section = self.main_window.settings.get("transcription", {})
        self._transcription_cache_check.SetValue(bool(section.get("cache_enabled", True)))
        own = section.get("cache_by_model", {})
        self._transcription_cache_overrides = {
            key: value for key, value in (own.items() if isinstance(own, dict) else ())
            if isinstance(key, str) and key and isinstance(value, bool)
        }
        self._sync_transcription_clear_cache_button()

    def _apply_transcription_cache(self) -> None:
        section = self.main_window.settings.setdefault("transcription", {})
        section["cache_enabled"] = self._transcription_cache_check.GetValue()
        section["cache_by_model"] = dict(self._transcription_cache_overrides)

    def _refresh_transcription_cache_labels(self) -> None:
        i18n = self.main_window.i18n
        if getattr(self, "_transcription_cache_check", None) is None:
            return
        self._transcription_cache_check.SetLabel(i18n.t("transcription_cache_check"))
        self._transcription_cache_model_label.SetLabel(i18n.t("transcription_cache_model_label"))
        self._transcription_clear_cache_btn.SetLabel(i18n.t("transcription_clear_cache_btn"))
        self._transcription_clear_all_cache_btn.SetLabel(i18n.t("transcription_clear_all_cache_btn"))
        selected = self._transcription_cache_choice.GetSelection()
        self._transcription_cache_choice.Set(self._transcription_cache_choice_labels())
        self._transcription_cache_choice.SetSelection(max(selected, 0))

    # ── The selected model's choice ──────────────────────────────────────────

    def _sync_transcription_cache_choice(self) -> None:
        choice = getattr(self, "_transcription_cache_choice", None)
        if choice is None:
            return
        model_id = self._transcription_clear_cache_target()
        choice.Enable(model_id is not None)
        stored = self._transcription_cache_overrides.get(model_id)
        # SetSelection fires no event, so showing a model's choice is not an edit.
        choice.SetSelection(0 if stored is None else (1 if stored else 2))

    def _on_transcription_cache_choice(self, event) -> None:
        model_id = self._transcription_clear_cache_target()
        if model_id is not None:
            index = self._transcription_cache_choice.GetSelection()
            if index == 1:
                self._transcription_cache_overrides[model_id] = True
            elif index == 2:
                self._transcription_cache_overrides[model_id] = False
            else:
                self._transcription_cache_overrides.pop(model_id, None)
        # On to the dialog, which shows Apply when anything changed.
        event.Skip()

    # ── Clearing ─────────────────────────────────────────────────────────────

    def _transcription_clear_cache_target(self):
        """The model the button acts on, or None: "Automatic" names no model."""
        model_id = self._selected_transcription_model()
        if model_id is None or model_id == transcription_preferences.AUTO:
            return None
        return model_id

    def _sync_transcription_clear_cache_button(self) -> None:
        button = getattr(self, "_transcription_clear_cache_btn", None)
        if button is None:
            return
        button.Enable(
            not self._transcription_job_running
            and self._transcription_clear_cache_target() is not None
        )
        self._transcription_clear_all_cache_btn.Enable(not self._transcription_job_running)
        self._sync_transcription_cache_choice()

    def _on_transcription_clear_cache(self, event) -> None:
        model_id = self._transcription_clear_cache_target()
        if (model_id is None or self._transcription_job_running
                or getattr(self, "_transcription_clearing", False)):
            return
        i18n = self.main_window.i18n
        text = i18n.t("transcription_clear_cache_confirm").format(
            model=model_names.display_name(i18n, model_id) or ""
        )
        if wx.MessageBox(
                text, i18n.t("settings_title"), wx.YES_NO | wx.ICON_QUESTION, self
        ) != wx.YES:
            return
        backend_id = self._selected_transcription_backend()
        # One clear at a time. Not by disabling the button: it holds the focus,
        # and a disabled control says nothing to a screen reader.
        self._transcription_clearing = True

        def _done(count):
            # Spoken even if Settings was closed meanwhile: the database has
            # answered, and it is still true and useful.
            if self:
                self._transcription_clearing = False
            self.main_window.speak_output.output(
                i18n.t(stored_transcription.clear_cache_message_key(count)).format(
                    count=count or 0), interrupt=True)

        self.main_window.clear_model_transcriptions(model_id, backend_id, _done)

    def _on_transcription_clear_all_cache(self, event) -> None:
        if self._transcription_job_running or getattr(self, "_transcription_clearing", False):
            return
        i18n = self.main_window.i18n
        if wx.MessageBox(
                i18n.t("transcription_clear_all_cache_confirm"), i18n.t("settings_title"),
                wx.YES_NO | wx.ICON_QUESTION, self
        ) != wx.YES:
            return
        # One clear at a time (see _on_transcription_clear_cache()).
        self._transcription_clearing = True

        def _done(count):
            if self:
                self._transcription_clearing = False
            key = ("transcription_clear_all_cache_none" if count == 0
                   else stored_transcription.clear_cache_message_key(count))
            self.main_window.speak_output.output(i18n.t(key).format(count=count or 0),
                                                 interrupt=True)

        self.main_window.clear_all_transcriptions(_done)
