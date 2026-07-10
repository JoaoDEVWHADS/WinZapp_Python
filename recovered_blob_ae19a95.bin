import os
import sys
import wx
import wx.dataview


class AccessibleSearchInConversation(wx.Accessible):
    """Reports Ctrl+Shift+F as the keyboard shortcut for the search-in-conversation button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+F")


class AccessibleSearchNextResult(wx.Accessible):
    """Reports Enter as the keyboard shortcut for the next-result button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Enter")


class AccessibleSearchPrevResult(wx.Accessible):
    """Reports Shift+Enter as the keyboard shortcut for the previous-result button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Shift+Enter")


class AccessibleStatusPrev(wx.Accessible):
    """Reports Ctrl+Left as the keyboard shortcut for the previous-status button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Left")


class AccessibleStatusNext(wx.Accessible):
    """Reports Ctrl+Right as the keyboard shortcut for the next-status button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Right")


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


class AccessibleSaveAs(wx.Accessible):
    """Reports Ctrl+Shift+S as the keyboard shortcut for the Save-As button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+S")


class AccessibleConversationDataButton(wx.Accessible):
    """Reports Ctrl+Shift+D as the keyboard shortcut for the conversation-data button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+D")


class AccessibleAddAttachmentButton(wx.Accessible):
    """Reports Ctrl+Shift+A as the keyboard shortcut for the Add Attachment button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+A")


class AccessibleDiscardVoiceMessage(wx.Accessible):
    """Reports Ctrl+Shift+D as the keyboard shortcut for the Discard button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+D")


class AccessiblePauseResumeRecording(wx.Accessible):
    """Reports Ctrl+Shift+P as the keyboard shortcut for the Pause/Resume button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+Shift+P")


class AccessibleSendVoiceMessage(wx.Accessible):
    """Reports Ctrl+R as the keyboard shortcut for the Send Voice Message button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+R")


class AccessibleNewConversationButton(wx.Accessible):
    """Reports Ctrl+N as the keyboard shortcut for the New Conversation button."""

    def GetKeyboardShortcut(self, childId):
        return (wx.ACC_OK, "Ctrl+N")


class AccessibleMessagesList(wx.Accessible):
    """
    Custom accessible for the conversation messages ListCtrl.

    The native Win32 ListView control truncates each item's text to ~259
    characters, both visually and in the MSAA name exposed to screen readers.
    Long messages (e.g. a paragraph ending in a URL) therefore got cut off and
    could only be read in full through the Alt+C popup.  This accessible returns
    the complete, untruncated rendered text for each row so the screen reader
    always announces the whole message.
    """

    def __init__(self, conversations_panel):
        super().__init__()
        self._panel = conversations_panel

    def GetName(self, childId):
        # childId 0 is the control itself; rows are 1-based.
        # We return an empty string for items (childId > 0) to prevent the native OS
        # MSAA list proxy from announcing the truncated text.
        # This completely avoids speech duplication and double entries in NVDA history,
        # allowing our debounced self.main_window.output() to cleanly announce the full message.
        if childId == 0:
            return (wx.ACC_NOT_IMPLEMENTED, "")
        return (wx.ACC_OK, "")


class AccessibleAudioSlider(wx.Accessible):
    def __init__(self, conversations_panel):
        super().__init__()
        self._panel = conversations_panel

    def GetName(self, childId):
        panel = self._panel
        i18n = panel.main_window.i18n
        if panel._audio_stream is not None and panel._audio_stream_duration > 0:
            try:
                pos = panel._audio_stream.get_position()
                total = panel._audio_stream.get_length()
                current_secs = int(pos / total * panel._audio_stream_duration) if total > 0 else 0
            except Exception:
                current_secs = 0
            current_str = panel._format_duration(current_secs)
            total_str = panel._format_duration(panel._audio_stream_duration)
            return (wx.ACC_OK, f"{current_str} {i18n.t('of')} {total_str}")
        return (wx.ACC_OK, "")


class MockListEvent:
    def __init__(self, index):
        self._index = index
    def GetIndex(self):
        return self._index
    def Skip(self):
        pass


class CompatDataViewListCtrl(wx.dataview.DataViewListCtrl):
    """
    Subclass of wx.dataview.DataViewListCtrl that mimics the wx.ListCtrl API.
    Used to bypass the native Windows SysListView32 512-character screen reader limitation
    by utilizing the generic wxWindowNR backend, exactly like Easygram does.
    """
    def __init__(self, parent, style=0):
        super().__init__(parent, style=wx.dataview.DV_ROW_LINES | wx.dataview.DV_SINGLE)
        self.Bind(wx.dataview.EVT_DATAVIEW_COLUMN_HEADER_CLICK, self._on_header_click)

    def _on_header_click(self, event):
        event.Veto()

    def InsertColumn(self, col, heading, format=0, width=-1):
        self.AppendTextColumn(heading, width=width)

    def GetItemCount(self):
        return super().GetItemCount()

    def Focus(self, row):
        item = self.RowToItem(row)
        if item.IsOk():
            self.SelectRow(row)

    def Select(self, row, select=True):
        if select:
            self.SelectRow(row)
        else:
            self.UnselectRow(row)

    def EnsureVisible(self, row):
        item = self.RowToItem(row)
        if item.IsOk():
            super().EnsureVisible(item)

    def SetItemText(self, row, col_or_text, text=None):
        if text is None:
            self.SetValue(col_or_text, row, 0)
        else:
            self.SetValue(text, row, col_or_text)

    def GetItemText(self, row, col=0):
        return self.GetValue(row, col)

    def Append(self, entry_tuple):
        self.AppendItem([entry_tuple[0]])

    def InsertItem(self, pos, text):
        """DataViewListCtrl only supports append, so we rebuild the list to insert at pos."""
        count = self.GetItemCount()
        values = [self.GetValue(i, 0) for i in range(count)]
        values.insert(pos, text)
        self.DeleteAllItems()
        for v in values:
            self.AppendItem([v])
        return pos

    def DeleteItem(self, row):
        """DataViewListCtrl has no native delete-by-row, so we rebuild the list."""
        count = self.GetItemCount()
        if row < 0 or row >= count:
            return
        values = [self.GetValue(i, 0) for i in range(count) if i != row]
        self.DeleteAllItems()
        for v in values:
            self.AppendItem([v])

    def GetFocusedItem(self):
        return self.GetSelectedRow()

    def GetFirstSelected(self):
        return self.GetSelectedRow()

    def SetColumn(self, col, listItem):
        column = self.GetColumn(col)
        if column:
            column.SetTitle(listItem.GetText())

    def Bind(self, event_type, handler, *args, **kwargs):
        if event_type == wx.EVT_LIST_ITEM_ACTIVATED:
            def _on_activated(evt):
                row = self.ItemToRow(evt.GetItem())
                if row != wx.NOT_FOUND:
                    handler(MockListEvent(row))
            super().Bind(wx.dataview.EVT_DATAVIEW_ITEM_ACTIVATED, _on_activated, *args, **kwargs)

        elif event_type in (wx.EVT_LIST_ITEM_SELECTED, wx.EVT_LIST_ITEM_FOCUSED):
            def _on_selected(evt):
                row = self.ItemToRow(evt.GetItem())
                if row != wx.NOT_FOUND:
                    handler(MockListEvent(row))
            super().Bind(wx.dataview.EVT_DATAVIEW_SELECTION_CHANGED, _on_selected, *args, **kwargs)

        else:
            super().Bind(event_type, handler, *args, **kwargs)
