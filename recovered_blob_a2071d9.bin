import os
import sys
import wx

class AccessibleSearchConversations(wx.Accessible):
    def __init__(self, shortcut):
        super().__init__()
        self.shortcut = shortcut

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, self.shortcut)


class AccessibleRecordVoiceMessage(wx.Accessible):
    def __init__(self, shortcut):
        super().__init__()
        self.shortcut = shortcut

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, self.shortcut)