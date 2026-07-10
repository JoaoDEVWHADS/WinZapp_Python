import os
import sys
import wx
from traceback import format_exc
from sound_system import SoundSystem
from conversations import ConversationsPanel


class NavigationPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)

        self.main_window = main_window
        self.parent = parent

        self.init_UI()

    def init_UI(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.nav_label = wx.StaticText(self, label=self.main_window.i18n.t("main_nav"))
        sizer.Add(self.nav_label, 0, wx.LEFT | wx.TOP, 5)

        self.nav_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.nav_list.InsertColumn(0, self.main_window.i18n.t("main_nav"), width=80)

        i18n = self.main_window.i18n
        self.nav_list.Append((f"{i18n.t('conversations')} alt+1",))
        self.nav_list.Append((f"{i18n.t('settings')} {i18n.t('settings_shortcut')}",))

        self.nav_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_nav_item_selected)
        self.nav_list.Focus(0)
        self.nav_list.Select(0)
        sizer.Add(self.nav_list, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)

    def refresh_labels(self):
        """Update all translatable labels after a language change."""
        i18n = self.main_window.i18n
        self.nav_label.SetLabel(i18n.t("main_nav"))
        col = wx.ListItem()
        col.SetText(i18n.t("main_nav"))
        self.nav_list.SetColumn(0, col)
        self.nav_list.SetItemText(0, f"{i18n.t('conversations')} alt+1")
        self.nav_list.SetItemText(1, f"{i18n.t('settings')} {i18n.t('settings_shortcut')}")

    def on_nav_item_selected(self, event):
        index = event.GetIndex()
        if index == 1:
            # Settings item
            self.main_window.open_settings()
            return
        panels = self.main_window.content_panel.GetChildren()
        for i, panel in enumerate(panels):
            if i == index:
                panel.Show()
                if isinstance(panel, ConversationsPanel):
                    panel.conversations_list.SetFocus()
            else:
                panel.Hide()
