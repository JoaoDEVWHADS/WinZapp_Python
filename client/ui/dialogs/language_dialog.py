"""
WinZapp – Language Selection Dialog
=====================================
Shown on first launch, before any API module installation or initial setup.
The user picks a language and clicks OK to proceed, or Cancel to exit.

This dialog intentionally avoids depending on settings infrastructure
(which may not be initialised yet). Bootstrap labels are loaded directly
from the locale JSON files. The list of languages
itself, however, is read from languages/language_map.json — the same file
core/i18n.py's LANGUAGE_NAMES loads from — so a new locale dropped in there
shows up here too without a rebuild.
"""

import json
import locale
import wx

from app_paths import resource_path

# Fallback used only if languages/language_map.json is missing or unreadable.
_FALLBACK_LANGUAGE_CHOICES = [
    ("Português (Brasil)",      "pt-BR"),
    ("English (United States)", "en-US"),
]


def _load_language_choices():
    """Return [(display_name, lang_code), ...] from language_map.json."""
    try:
        with open(resource_path("languages", "language_map.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return [(name, code) for code, name in data.items()]
    except Exception:
        pass
    return list(_FALLBACK_LANGUAGE_CHOICES)


# Maps human-readable name → language code (same order as LANGUAGE_NAMES in core/i18n.py)
_LANGUAGE_CHOICES = _load_language_choices()


def _bootstrap_language_code():
    """Best-effort locale for the picker before normal I18n exists."""
    try:
        current = (locale.getlocale()[0] or "").replace("_", "-")
    except Exception:
        current = ""
    codes = [code for _, code in _LANGUAGE_CHOICES]
    if current in codes:
        return current
    prefix = current.split("-", 1)[0].lower() if current else ""
    for code in codes:
        if code.split("-", 1)[0].lower() == prefix:
            return code
    return "pt-BR"


def _bootstrap_t(key):
    code = _bootstrap_language_code()
    try:
        with open(resource_path("languages", f"{code}.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key, key)
    except Exception:
        return key


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
            title=_bootstrap_t("language_select_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.selected_language: str = _bootstrap_language_code()
        self._lang_codes = [code for _, code in _LANGUAGE_CHOICES]

        self._build_ui()
        self.Fit()
        self.SetMinSize((360, -1))
        self.Centre()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label=_bootstrap_t("language_select_prompt"))
        sizer.Add(lbl, 0, wx.LEFT | wx.TOP | wx.RIGHT, 12)

        self._combo = wx.ComboBox(
            panel,
            style=wx.CB_READONLY,
            choices=[name for name, _ in _LANGUAGE_CHOICES],
        )
        try:
            self._combo.SetSelection(self._lang_codes.index(self.selected_language))
        except ValueError:
            self._combo.SetSelection(0)
        sizer.Add(self._combo, 0, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(panel, wx.ID_OK,     label=_bootstrap_t("ok"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_bootstrap_t("cancel"))
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
