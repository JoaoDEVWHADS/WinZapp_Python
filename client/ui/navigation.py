import os
import sys
import wx
from traceback import format_exc
from core.sound_system import SoundSystem
from ui.conversations import ConversationsPanel


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
        self.nav_list.InsertColumn(0, self.main_window.i18n.t("main_nav"), width=180)

        i18n = self.main_window.i18n
        # Index 0: Conversations   Index 1: Status   Index 2: Archived   Index 3: Settings
        self.nav_list.Append((f"{i18n.t('conversations')} alt+1",))
        self.nav_list.Append((i18n.t("status_nav"),))
        self.nav_list.Append((i18n.t("archived_chats_nav"),))
        self.nav_list.Append((f"{i18n.t('settings')} {i18n.t('settings_shortcut')}",))

        self.nav_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_nav_item_selected)
        self.nav_list.Bind(wx.EVT_KEY_DOWN, self._on_nav_key_down)
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
        self.nav_list.SetItemText(1, i18n.t("status_nav"))
        self.nav_list.SetItemText(2, i18n.t("archived_chats_nav"))
        self.nav_list.SetItemText(3, f"{i18n.t('settings')} {i18n.t('settings_shortcut')}")

    def _on_nav_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_SPACE:
            idx = self.nav_list.GetFocusedItem()
            if idx >= 0:
                self.nav_list.Select(idx)
                class _E:
                    def GetIndex(self): return idx
                self.on_nav_item_selected(_E())
        else:
            event.Skip()

    def on_nav_item_selected(self, event):
        index = event.GetIndex()
        mw = self.main_window

        if index == 3:
            mw.open_settings()
            return

        # Hide all content panels, show the right one
        mw.conversations_panel.Hide()
        if hasattr(mw, "status_panel"):
            mw.status_panel.Hide()
        if hasattr(mw, "archived_conversations_panel"):
            mw.archived_conversations_panel.Hide()

        if index == 0:
            mw.conversations_panel.Show()
            mw.content_panel.Layout()
            mw.conversations_panel.conversations_list.SetFocus()
            if (mw.conversations_panel.conversations_list.GetFocusedItem() != -1
                    and mw.conversations_panel.conversations_list.GetItemCount() > 0):
                mw.output(
                    mw.conversations_panel.conversations_list.GetItemText(
                        mw.conversations_panel.conversations_list.GetFocusedItem()
                    ),
                    interrupt=True,
                )
        elif index == 1 and hasattr(mw, "status_panel"):
            mw.status_panel.Show()
            mw.content_panel.Layout()
            mw.status_panel._add_status_btn.SetFocus()
            mw.status_panel.on_show()
        elif index == 2 and hasattr(mw, "archived_conversations_panel"):
            mw.archived_conversations_panel.Show()
            mw.content_panel.Layout()
            mw.archived_conversations_panel.conversations_list.SetFocus()
