import os
import sys
import wx
import json
import requests
from traceback import format_exc
from sound_system import SoundSystem

class ConversationsPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent
        self.init_UI()

    def init_UI(self):
        self.conversations_label = wx.StaticText(self, label=self.main_window.i18n.t("conversations"), pos=(10,10))
        self.conversations_list = wx.ListCtrl(self, size=(380, 200), pos=(10, 40), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, self.main_window.i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversation_panel = wx.Panel(self)
        self.conversation_panel.Hide() #hidden by default

    def on_conversation_selected(self, event):
        self.conversation_panel.Show()
