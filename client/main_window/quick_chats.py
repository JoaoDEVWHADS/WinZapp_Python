"""Account-local numbered chat shortcuts and their frame-level key routing."""

import logging

import wx

from core.conversation_view import ARCHIVED, MAIN
from core.quick_chats import slots_from_settings
from ui.shortcut_bindings import matches


class QuickChatsMixin:
    def _quick_chat_under_focus(self):
        """Use only the focused chat row or the visibly open conversation."""
        focus = wx.Window.FindFocus()
        panel = getattr(self, "conversations_panel", None)
        if focus is None or panel is None:
            return None
        for owner in (panel, getattr(self, "archived_conversations_panel", None),
                      getattr(self, "locked_conversations_panel", None)):
            if owner is None:
                continue
            lst = getattr(owner, "conversations_list", None)
            if focus is lst:
                index = lst.GetFocusedItem()
                chats = getattr(owner, "chats_list", ())
                return chats[index] if 0 <= index < len(chats) else None
        detail = getattr(panel, "conversation_panel", None)
        if detail is None or not detail.IsShown():
            return None
        while focus is not None:
            if focus is detail:
                return panel.conversation
            focus = focus.GetParent()
        return None

    def _assign_quick_chat(self, digit: int, chat=None):
        if chat is None:
            chat = self._quick_chat_under_focus()
        jid = chat.get("remoteJid", "") if isinstance(chat, dict) else ""
        if not jid:
            self.output(self.i18n.t("quick_chat_no_focus"), interrupt=True)
            return
        if self.is_chat_locked(jid):
            self.output(self.i18n.t("quick_chat_protected"), interrupt=True)
            return
        slots = self.settings.get("quick_chats")
        if not isinstance(slots, dict):
            slots = self.settings["quick_chats"] = {}
        slots[str(digit)] = jid
        self.save_settings()
        name = self.chat_display_name(chat)
        self.output(self.i18n.t("quick_chat_assigned").format(digit=digit, name=name),
                    interrupt=True)

    def _open_quick_chat(self, digit: int):
        jid = slots_from_settings(self.settings).get(str(digit))
        if jid is None:
            self.output(self.i18n.t("quick_chat_empty").format(digit=digit),
                        interrupt=True)
            return
        chat = self.get_chat(jid)
        if chat is None:
            self.output(self.i18n.t("quick_chat_unavailable").format(digit=digit),
                        interrupt=True)
            return
        if self.is_chat_locked(jid):
            self.output(self.i18n.t("quick_chat_unavailable").format(digit=digit),
                        interrupt=True)
            return
        panel = getattr(self, "conversations_panel", None)
        if panel is None:
            self.output(self.i18n.t("quick_chat_unavailable").format(digit=digit),
                        interrupt=True)
            return
        origin = ARCHIVED if self.is_chat_archived(jid) else MAIN
        panel.show_chat_panel(origin, focus=False)
        if origin == ARCHIVED:
            # The archived list normally opens this pane from its own row.
            # A quick slot must also work while that list is search-filtered.
            archived = getattr(self, "archived_conversations_panel", None)
            if archived is not None:
                archived.Hide()
            panel.conversations_label.Hide()
            panel.conversations_list.Hide()
            panel.Show()
            self.content_panel.Layout()
        panel.navigate_to_conversation(chat, origin=origin)

    def _on_quick_chat_char(self, event):
        """Handle both numbered families before a focused child accelerator."""
        try:
            for digit in range(10):
                if matches(self, event, f"main.quick_chat_open[{digit}]"):
                    self._open_quick_chat(digit)
                    return
                if matches(self, event, f"main.quick_chat_assign[{digit}]"):
                    self._assign_quick_chat(digit)
                    return
        except Exception:
            logging.exception("[quick-chats] shortcut handler failed")
        event.Skip()
