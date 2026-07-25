"""
WinZapp – Reactions List Dialog
================================
Modal dialog showing who reacted to a message and with which emoji.
Opened from the "Reações" button in the conversation panel (visible only
when the focused message has reactions).
"""

import wx


class ReactionsDialog(wx.Dialog):
    """
    Parameters
    ----------
    main_window       : MainWindow
    conversation_panel : ConversationPanel — supplies _get_participant_name()
                          and the "_me_" self-reactor sentinel.
    reactions         : dict {sender_key: emoji} — see
                        ConversationPanel._reaction_map.
    """

    def __init__(self, main_window, conversation_panel, reactions: dict):
        i18n = main_window.i18n
        super().__init__(
            main_window,
            title=i18n.t("reactions_dialog_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._mw    = main_window
        self._panel = conversation_panel
        self._build_ui(i18n, reactions)
        self.SetMinSize((380, 320))
        self.Fit()
        self.CentreOnParent()

    def _build_ui(self, i18n, reactions: dict):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER
        )
        self._list.InsertColumn(0, "", width=340)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        for sender_key, emoji in reactions.items():
            name = (
                self._mw.self_reference_label()
                if sender_key == self._panel._SELF_REACTOR_KEY
                else self._panel._get_participant_name(sender_key)
            )
            text = i18n.t("reacted_with_emoji").format(name=name, emoji=emoji)
            self._list.InsertItem(self._list.GetItemCount(), text)

        # A pre-populated list must never leave focus/selection pointing at
        # nothing — mirrors the conversation list's own convention.
        if self._list.GetItemCount() > 0:
            self._list.Focus(0)
            self._list.Select(0)

        close_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        self._list.SetFocus()
