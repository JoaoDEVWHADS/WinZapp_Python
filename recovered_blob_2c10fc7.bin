import os
import sys
import wx
from wx.adv import CommandLinkButton as CmdBtn
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
        self.create_accelerator_table()

    def init_UI(self):
        self.conversations_label = wx.StaticText(self, label=self.main_window.i18n.t("conversations"), pos=(10,10))
        self.conversations_list = wx.ListCtrl(self, size=(380, 200), pos=(10, 40), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.InsertColumn(0, self.main_window.i18n.t("conversations"), width=200)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_selected)
        self.conversation_panel = wx.Panel(self)
        self.conversation_panel.Hide() #hidden by default
        self.message_label = wx.StaticText(self.conversation_panel, label=self.main_window.i18n.t("type_message"))
        self.message_field = wx.TextCtrl(self.conversation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP, size=(300, 25))
        self.record_voice_message_btn = CmdBtn(self.conversation_panel, mainLabel=self.main_window.i18n.t("record_voice_message"), note="Ctrl+R", size=(150, 40))
        self.record_voice_message_btn.Bind(wx.EVT_BUTTON, self.on_record_voice_message)

    def on_conversation_selected(self, event):
        self.conversation = self.main_window.chats[event.GetIndex()]
        self.conversation_name = self.main_window.chat_names[event.GetIndex()]
        print(self.conversation)
        #Set conversation name on label
        if not self.conversation.get("key", {}).get("isGroup", False):
            self.message_label.SetLabel(f"{self.main_window.i18n.t('type_message')} {self.conversation_name}")
        else:
            self.message_label.SetLabel(f"{self.main_window.i18n.t('type_message_group')} {self.conversation_name}")
        self.conversation_panel.Show()
        self.message_field.SetFocus()

    def create_accelerator_table(self):
        #Set IDs
        self.ID_CTRL_R = wx.NewIdRef()
        self.ID_ESC = wx.NewIdRef()
        #create accelerator table
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('R'), self.ID_CTRL_R),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.ID_ESC)
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self.on_record_voice_message, id=self.ID_CTRL_R)
        self.Bind(wx.EVT_MENU, self.close_conversation, id=self.ID_ESC)
    def on_record_voice_message(self, event):
        pass

    def close_conversation(self, event):
        self.conversation_panel.Hide()
        self.conversations_list.SetFocus()