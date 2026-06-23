import os
import sys
import wx


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


class AccessibleMessageList(wx.Accessible):
    """Provides full, untruncated message text to screen readers via IAccessible.

    The Windows ListView API truncates item text at ~512 characters when screen
    readers query IAccessible::get_accName. By overriding GetName here, we
    return the full rendered message directly from our data model — bypassing
    the OS truncation entirely, with no timing dependency.
    """

    def __init__(self, conversations_panel):
        super().__init__()
        self._panel = conversations_panel

    def GetName(self, childId):
        # childId == 0 → the list control itself; > 0 → item (1-based index)
        if childId == 0:
            return (wx.ACC_OK, "")
        idx = childId - 1
        msgs = getattr(self._panel, "_sorted_messages", [])
        if 0 <= idx < len(msgs):
            try:
                full_text = self._panel._render_message_line(msgs[idx], truncate=False)
                return (wx.ACC_OK, full_text)
            except Exception:
                pass
        return (wx.ACC_NOT_IMPLEMENTED, "")


class MessageListCtrl(wx.ListCtrl):
    """Virtual wx.ListCtrl for the messages panel.

    Uses LC_VIRTUAL so OnGetItemText is called for every item. Text is
    truncated at a safe limit (250 chars + "…") to stay within the native
    Windows ListView buffer, avoiding silent mid-word truncation.
    Full text is always available via _render_message_line(truncate=False)
    for search, link detection, and screen readers.
    """

    def __init__(self, parent, conversations_panel, **kwargs):
        style = kwargs.pop("style", 0) | wx.LC_REPORT | wx.LC_VIRTUAL
        super().__init__(parent, style=style, **kwargs)
        self._panel = conversations_panel

    def OnGetItemText(self, item: int, col: int) -> str:  # noqa: N802
        msgs = getattr(self._panel, "_sorted_messages", [])
        if 0 <= item < len(msgs):
            try:
                return self._panel._render_message_line(msgs[item], truncate=True)
            except Exception:
                pass
        return ""

