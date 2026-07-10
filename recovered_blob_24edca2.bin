"""
WinZapp – Keyboard Shortcuts Dialog
====================================
Shows all keyboard shortcuts grouped by section in a read-only text area.
Opened with F1 from any main-window panel, and also linked from the
"Quick tip" dialog that appears after first pairing.
"""

import wx


class ShortcutsDialog(wx.Dialog):
    """
    Modal dialog listing all WinZapp keyboard shortcuts grouped by section.

    Parameters
    ----------
    main_window : MainWindow
    """

    def __init__(self, main_window):
        i18n = main_window.i18n
        super().__init__(
            main_window,
            title=i18n.t("shortcuts_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._mw = main_window
        self._build_ui(i18n)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self, i18n):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Read-only text control with the shortcuts list
        text = self._build_text(i18n)
        self._text_ctrl = wx.TextCtrl(
            panel,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
        )
        sizer.Add(self._text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # Close button — also responds to Esc (wx.ID_CANCEL)
        btn_sizer = wx.StdDialogButtonSizer()
        close_btn = wx.Button(panel, wx.ID_CANCEL, i18n.t("close"))
        btn_sizer.AddButton(close_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(sizer)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetSize((520, 420))
        self.CenterOnParent()

        self._text_ctrl.SetFocus()

    # ── Content ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_text(i18n) -> str:
        """Compose the shortcuts text from i18n keys."""
        def section(key):
            return f"── {i18n.t(key)} ──"

        lines = [
            section("shortcuts_nav_section"),
            i18n.t("shortcut_alt1_label"),
            i18n.t("shortcut_alt4_label"),
            i18n.t("shortcut_alt5_label"),
            i18n.t("shortcut_ctrl_comma_label"),
            i18n.t("shortcut_f1_label"),
            i18n.t("shortcut_ctrl_n_label"),
            "",
            section("shortcuts_conv_section"),
            i18n.t("shortcut_alt2_label"),
            i18n.t("shortcut_alt3_label"),
            i18n.t("shortcut_ctrl_shift_f_label"),
            i18n.t("shortcut_alt_shift_r_label"),
            i18n.t("shortcut_alt_shift_c_label"),
            i18n.t("shortcut_alt_shift_v_label"),
            "",
            section("shortcuts_status_section"),
            i18n.t("shortcut_ctrl_left_label"),
            i18n.t("shortcut_ctrl_right_label"),
            "",
            section("shortcuts_search_section"),
            i18n.t("shortcut_search_enter_label"),
            i18n.t("shortcut_search_shift_enter_label"),
        ]
        return "\n".join(lines)
