"""Tabbed dialog for audio device settings during or before a call."""

import wx

from core.audio_devices import (
    enumerate_input_devices,
    enumerate_output_devices,
)


class CallAudioSettingsDialog(wx.Dialog):
    """Accessible tabbed dialog for selecting playback and recording devices."""

    def __init__(self, parent):
        self.main_window = parent if hasattr(parent, "i18n") else parent.GetParent()
        i18n = self.main_window.i18n
        super().__init__(
            parent,
            title=i18n.t("call_audio_settings_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        audio_cfg = self.main_window.settings.get("audio_devices", {})
        self._initial_output = audio_cfg.get("output_device_name", "")
        self._initial_input = audio_cfg.get("input_device_name", "")

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self._notebook = wx.Notebook(panel)

        # ── Tab 1: Reprodução (Playback) ─────────────────────────────────────
        playback_tab = wx.Panel(self._notebook)
        playback_sizer = wx.BoxSizer(wx.VERTICAL)

        output_label = wx.StaticText(
            playback_tab, label=i18n.t("playback_device_label")
        )
        self._output_combo = wx.ComboBox(
            playback_tab, style=wx.CB_READONLY
        )

        playback_sizer.Add(output_label, 0, wx.ALL, 8)
        playback_sizer.Add(self._output_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        playback_tab.SetSizer(playback_sizer)
        self._notebook.AddPage(playback_tab, i18n.t("tab_playback"))

        # ── Tab 2: Gravação (Recording) ──────────────────────────────────────
        recording_tab = wx.Panel(self._notebook)
        recording_sizer = wx.BoxSizer(wx.VERTICAL)

        input_label = wx.StaticText(
            recording_tab, label=i18n.t("recording_device_label")
        )
        self._input_combo = wx.ComboBox(
            recording_tab, style=wx.CB_READONLY
        )

        recording_sizer.Add(input_label, 0, wx.ALL, 8)
        recording_sizer.Add(self._input_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        recording_tab.SetSizer(recording_sizer)
        self._notebook.AddPage(recording_tab, i18n.t("tab_recording"))

        main_sizer.Add(self._notebook, 1, wx.EXPAND | wx.ALL, 8)

        # ── OK / Cancel Buttons ──────────────────────────────────────────────
        btn_sizer = wx.StdDialogButtonSizer()
        self._ok_btn = wx.Button(panel, wx.ID_OK)
        self._cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(self._cancel_btn)
        btn_sizer.Realize()

        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(main_sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.SetMinSize((420, 220))
        self.CentreOnParent()

        self._populate_devices(i18n)

        self._ok_btn.SetDefault()
        self._ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self._cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

    def _populate_devices(self, i18n):
        # Output devices
        self._output_device_names = [name for _idx, name in enumerate_output_devices()]
        if self._initial_output and self._initial_output not in self._output_device_names:
            self._output_device_names.append(self._initial_output)

        output_choices = [i18n.t("audio_default_output_device")] + self._output_device_names
        self._output_combo.Set(output_choices)
        if self._initial_output and self._initial_output in self._output_device_names:
            self._output_combo.SetSelection(self._output_device_names.index(self._initial_output) + 1)
        else:
            self._output_combo.SetSelection(0)

        # Input devices
        self._input_device_names = [name for _idx, name in enumerate_input_devices()]
        if self._initial_input and self._initial_input not in self._input_device_names:
            self._input_device_names.append(self._initial_input)

        input_choices = [i18n.t("audio_default_input_device")] + self._input_device_names
        self._input_combo.Set(input_choices)
        if self._initial_input and self._initial_input in self._input_device_names:
            self._input_combo.SetSelection(self._input_device_names.index(self._initial_input) + 1)
        else:
            self._input_combo.SetSelection(0)

    def _on_ok(self, _event):
        out_sel = self._output_combo.GetSelection()
        selected_output = self._output_device_names[out_sel - 1] if out_sel > 0 else ""

        in_sel = self._input_combo.GetSelection()
        selected_input = self._input_device_names[in_sel - 1] if in_sel > 0 else ""

        audio_devices = self.main_window.settings.setdefault("audio_devices", {})
        audio_devices["output_device_name"] = selected_output
        audio_devices["input_device_name"] = selected_input

        if hasattr(self.main_window, "save_settings"):
            self.main_window.save_settings()
        if hasattr(self.main_window, "apply_audio_devices"):
            self.main_window.apply_audio_devices()

        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _event):
        self.EndModal(wx.ID_CANCEL)
