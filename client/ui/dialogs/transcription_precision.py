"""The precision picker of the Transcription tab (part 11), split out of transcription_tab.py.

One read-only combobox, right under "where to run the transcription" because
what it offers depends on that answer: faster-whisper's compute type, with
"automatic" first and then what `ctranslate2.get_supported_compute_types()`
said for the device the run would land on (`precision.picker_choices()`), read
off the probe the tab already takes on its first visit — never a probe of its
own, and never on opening the dialog. Before that probe every precision is
listed, so the stored one always has an entry to show.

Disabled, never hidden, while whisper.cpp is the backend: its quantization is
the model file, chosen in the model list. A control that is consistently there
keeps the tab order the user learned (the rule `_sync_transcription_language_
controls()` follows), and the label says which component it is for.

A choice the device cannot run stays selected — writing "automatic" over it
on OK would drop the user's choice silently — and the tab's warning field
says which precision will be used instead, as the run itself will.

`TranscriptionPrecisionMixin` is mixed into `SettingsDialog` beside
`TranscriptionTabMixin`, whose state it reads (the probe, the device radio,
the backend picker, the warning field).
"""

import wx

from core.combo_search import bind_incremental_search
from core.transcription import (
    backend as transcription_backend,
    device as transcription_device,
    precision,
    preferences as transcription_preferences,
)

#: Shown in the warning field when the choice cannot run on the device
#: selected above. Formatted with the two names, at render time, so a language
#: change re-says it in the new language.
_PRECISION_REPLACED = "transcription_notice_precision_replaced"


class TranscriptionPrecisionMixin:
    """The faster-whisper precision picker of `SettingsDialog`'s Transcription tab."""

    def _build_transcription_precision(self, page, sizer):
        """The label and the combobox, laid out in `page` where they belong in
        the tab order: after the device, which decides what they offer."""
        i18n = self.main_window.i18n
        #: Parallel to the combobox items: index -> the value stored in
        #: settings.json ("auto" or a compute type), and the item texts as last
        #: set, so a redraw that would say the same thing leaves the list alone.
        self._transcription_precision_values = []
        self._transcription_precision_labels = []
        #: (chosen, used) compute types when the choice cannot run on the
        #: device the run would land on, else None. Rendered with the other
        #: notices by _render_transcription_substitutions().
        self._transcription_precision_replacement = None

        self._transcription_precision_label = wx.StaticText(
            page, label=i18n.t("transcription_precision_label")
        )
        sizer.Add(self._transcription_precision_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._transcription_precision_combo = wx.ComboBox(page, style=wx.CB_READONLY)
        bind_incremental_search(self._transcription_precision_combo)
        sizer.Add(self._transcription_precision_combo, 0, wx.EXPAND | wx.ALL, 8)
        self._populate_transcription_precision_choices()
        self._transcription_precision_combo.Bind(
            wx.EVT_COMBOBOX, self._on_transcription_precision_change
        )

    def _transcription_precision_device(self):
        """The device a faster-whisper run would land on with the radio as it
        stands, or None before the probe — the same rule the run applies."""
        if self._transcription_probe is None:
            return None
        device_id, _reason = transcription_device.resolve_device(
            self._selected_transcription_device_preference(), self._transcription_probe
        )
        return device_id

    def _populate_transcription_precision_choices(self, selected=None):
        """Rebuild the list for the device as it now stands, selecting
        `selected` — the current selection when None. A choice the device
        cannot run keeps its entry (precision.picker_choices())."""
        i18n = self.main_window.i18n
        if selected is None:
            selected = self._selected_transcription_precision()
        values = list(precision.picker_choices(
            self._transcription_precision_device(), self._transcription_probe, selected
        ))
        labels = [i18n.t(transcription_preferences.OPTION_AUTO_I18N_KEY)] + [
            precision.display_name(i18n, value) for value in values[1:]
        ]
        if (values != self._transcription_precision_values
                or labels != self._transcription_precision_labels):
            # Set() replaces the list in one call, as for the model picker.
            self._transcription_precision_combo.Set(labels)
            self._transcription_precision_values = values
            self._transcription_precision_labels = labels
            self._select_id(self._transcription_precision_combo, values, selected)

    def _selected_transcription_precision(self):
        return self._selected_id(
            self._transcription_precision_combo, self._transcription_precision_values
        )

    def _sync_transcription_precision(self):
        """Follow the device, the probe and the backend: the list, whether it
        can be used, and whether the choice has to be replaced.

        Called by _show_transcription_hardware_notices(), which is where every
        one of those changes already ends up.
        """
        self._populate_transcription_precision_choices()
        enabled = (self._transcription_picker_backend()
                   == transcription_backend.BACKEND_FASTER_WHISPER)
        for control in (self._transcription_precision_label,
                        self._transcription_precision_combo):
            control.Enable(enabled)
        device_id = self._transcription_precision_device()
        chosen = self._selected_transcription_precision()
        self._transcription_precision_replacement = None
        if enabled and device_id is not None and precision.is_choice(chosen):
            choice = precision.resolve_compute_type(
                chosen, device_id, self._transcription_probe
            )
            if choice.replaced:
                self._transcription_precision_replacement = (
                    choice.requested, choice.compute_type
                )

    def _transcription_precision_notice(self) -> str:
        """The sentence for the warning field, or "" when there is none."""
        if not getattr(self, "_transcription_precision_replacement", None):
            return ""
        i18n = self.main_window.i18n
        chosen, used = self._transcription_precision_replacement
        return i18n.t(_PRECISION_REPLACED).format(
            chosen=precision.display_name(i18n, chosen),
            used=precision.display_name(i18n, used),
        )

    def _load_transcription_precision(self, section):
        """Show the stored choice (from `_load_transcription_values()`)."""
        stored = section[transcription_preferences.SETTING_COMPUTE_TYPE]
        self._populate_transcription_precision_choices(stored)
        # Selected even when the list was already right: Set() is skipped
        # then, and with it the selection.
        self._select_id(
            self._transcription_precision_combo, self._transcription_precision_values, stored
        )
        self._sync_transcription_precision()

    def _apply_transcription_precision(self, section):
        """Write the choice back (from `_apply_transcription_values()`) — only
        what the tab presented, like every other setting there."""
        chosen = self._selected_transcription_precision()
        if chosen is not None and self._transcription_setting_may_be_written(
                transcription_preferences.SETTING_COMPUTE_TYPE):
            section[transcription_preferences.SETTING_COMPUTE_TYPE] = chosen

    def _refresh_transcription_precision_labels(self):
        """Retranslate after a language change: the items are sentences in the
        old language, so the "nothing changed" check is forced past."""
        self._transcription_precision_label.SetLabel(
            self.main_window.i18n.t("transcription_precision_label")
        )
        self._transcription_precision_labels = []
        self._populate_transcription_precision_choices()

    def _on_transcription_precision_change(self, event):
        """Redraw the tab's read-only warning field, which says whether the
        device can run the new choice (nothing is spoken)."""
        self._show_transcription_hardware_notices()
        # Skip(): the dialog-level handler is what shows Apply.
        event.Skip()
