"""
WinZapp – Language Selection Dialog
=====================================
Shown on first launch, before any API module installation or initial setup.
The user picks a language and clicks OK to proceed, or Cancel to exit.

This dialog intentionally avoids using the I18n / settings infrastructure
(which may not be initialised yet) and hard-codes English/Portuguese labels
as a minimal bootstrap interface.
"""

import wx


# Maps human-readable name → language code (same order as LANGUAGE_NAMES in core/i18n.py)
_LANGUAGE_CHOICES = [
    ("Português (Brasil)",        "pt-BR"),
    ("English (United States)",   "en-US"),
    ("Español (España)",          "es-ES"),
]


class LanguageSelectionDialog(wx.Dialog):
    """
    First-run language picker shown before i18n is fully initialised.

    Attributes
    ----------
    selected_language : str
        BCP-47 language code chosen by the user (e.g. ``"pt-BR"``).
        Only valid after the dialog returns ``wx.ID_OK``.
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            title="Selecionar um idioma | WinZapp",
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.selected_language: str = "pt-BR"
        self._lang_codes = [code for _, code in _LANGUAGE_CHOICES]

        self._build_ui()
        self.Fit()
        self.SetMinSize((360, -1))
        self.Centre()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="Selecionar um idioma")
        sizer.Add(lbl, 0, wx.LEFT | wx.TOP | wx.RIGHT, 12)

        self._combo = wx.ComboBox(
            panel,
            style=wx.CB_READONLY,
            choices=[name for name, _ in _LANGUAGE_CHOICES],
        )
        self._combo.SetSelection(0)
        sizer.Add(self._combo, 0, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(panel, wx.ID_OK,     label="OK")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(dlg_sizer)

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_ok(self, event):
        sel = self._combo.GetSelection()
        if sel != wx.NOT_FOUND:
            self.selected_language = self._lang_codes[sel]
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)
