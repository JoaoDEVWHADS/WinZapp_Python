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

        self.SetSize((100, 300))
        self.SetBackgroundColour(wx.Colour(240, 240, 240))

        self.init_UI()

    def init_UI(self):
        self.nav_label = wx.StaticText(self, label=self.main_window.i18n.t("main_nav"), pos=(10, 10))
        self.nav_list = wx.ListCtrl(self, size=(80, 250), pos=(10, 30), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.nav_list.InsertColumn(0, self.main_window.i18n.t("main_nav"), width=80)
        self.nav_list.Append((f"{self.main_window.i18n.t("conversations")} alt+1",))
        self.nav_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_nav_item_selected)
        self.nav_list.Focus(0)
        self.nav_list.Select(0)

    def on_nav_item_selected(self, event):
        index = event.GetIndex()
        #Get all childs for the content panel, then hide them and show the selected one
        panels = self.main_window.content_panel.GetChildren()
        for i, panel in enumerate(panels):
            if i == index:
                panel.Show()
                if isinstance(panel, ConversationsPanel):
                    panel.conversations_list.SetFocus()
            else:
                panel.Hide()