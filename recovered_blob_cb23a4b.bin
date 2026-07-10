"""
new_conversation.py — WinZapp "Nova conversa" dialog.

Lets the user search contacts / existing chats by name or phone number and
navigate to the selected conversation.  Also provides buttons to open the
New Group and New Contact dialogs.

Ctrl+N shortcut is registered in ConversationsPanel.
"""

import re
import threading
import wx

from core.utils import format_number


class NewConversationDialog(wx.Dialog):
    """Search for a contact or number and open a conversation."""

    def __init__(self, main_window):
        self._mw = main_window
        i18n = main_window.i18n
        super().__init__(
            main_window,
            title=i18n.t("new_conversation_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._results: list = []  # list of (display_name, jid, chat_or_None)
        self._build_ui(i18n)
        self.SetMinSize((440, 380))
        self.SetSize((440, 480))
        self.CentreOnParent()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, i18n):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Search field
        search_label = wx.StaticText(panel, label=i18n.t("search_name_or_number"))
        sizer.Add(search_label, 0, wx.LEFT | wx.TOP, 10)

        self._search_field = wx.TextCtrl(
            panel, style=wx.TE_DONTWRAP | wx.TE_PROCESS_ENTER
        )
        self._search_field.Bind(wx.EVT_TEXT, self._on_search_text)
        self._search_field.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)
        sizer.Add(self._search_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Results list
        self._results_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self._results_list.InsertColumn(0, i18n.t("conversations"), width=380)
        self._results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        sizer.Add(self._results_list, 1, wx.EXPAND | wx.ALL, 10)

        # Buttons row
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._new_group_btn = wx.Button(panel, label=i18n.t("new_group"))
        self._new_group_btn.Bind(wx.EVT_BUTTON, self._on_new_group)
        btn_sizer.Add(self._new_group_btn, 0, wx.RIGHT, 8)

        self._new_contact_btn = wx.Button(panel, label=i18n.t("new_contact"))
        self._new_contact_btn.Bind(wx.EVT_BUTTON, self._on_new_contact)
        btn_sizer.Add(self._new_contact_btn, 0, wx.RIGHT, 8)

        btn_sizer.AddStretchSpacer()

        close_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close"))
        btn_sizer.Add(close_btn, 0)

        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        self._search_field.SetFocus()

    # ── Search logic ──────────────────────────────────────────────────────────

    def _on_search_text(self, event):
        query = self._search_field.GetValue().strip()
        self._do_search(query)

    def _on_search_enter(self, event):
        """Enter in the search field: if exactly one result, activate it."""
        if len(self._results) == 1:
            self._open_conversation(0)
        elif self._results_list.GetItemCount() > 0:
            self._results_list.Focus(0)
            self._results_list.Select(0)
            self._results_list.SetFocus()

    def _do_search(self, query: str):
        self._results = []
        self._results_list.DeleteAllItems()
        if not query:
            return

        mw       = self._mw
        i18n     = mw.i18n
        qlow     = query.lower()
        seen     = set()

        def _name_for_chat(chat):
            jid = chat.get("remoteJid", "")
            return (
                mw._resolve_contact_name(chat)
                or mw.find_name_through_messages(chat)
                or chat.get("pushName", "")
                or mw.find_jid_through_messages(chat)
                or format_number(jid)
            )

        # ── Search existing chats ─────────────────────────────────────────────
        for jid, chat in mw.chats.items():
            name = _name_for_chat(chat)
            if qlow in name.lower() or qlow in format_number(jid).lower():
                if jid not in seen:
                    seen.add(jid)
                    self._results.append((name, jid, chat))
                    self._results_list.Append((name,))

        # ── Search contacts not yet in chats ──────────────────────────────────
        for jid, contact in mw.contacts.items():
            if jid in seen:
                continue
            name = (
                contact.get("name") or contact.get("fullName")
                or contact.get("verifiedName") or contact.get("pushName")
                or format_number(jid)
            )
            if qlow in (name or "").lower() or qlow in format_number(jid).lower():
                seen.add(jid)
                self._results.append((name or format_number(jid), jid, None))
                self._results_list.Append((name or format_number(jid),))

        # ── If query looks like a phone number, add direct option ─────────────
        digits = re.sub(r"\D", "", query)
        if len(digits) >= 7:
            direct_jid = digits + "@s.whatsapp.net"
            if direct_jid not in seen:
                display = format_number(direct_jid)
                self._results.append((display, direct_jid, None))
                self._results_list.Append((display,))

        if not self._results:
            self._results_list.Append((self._mw.i18n.t("no_results"),))

    # ── Activation ────────────────────────────────────────────────────────────

    def _on_activate(self, event):
        self._open_conversation(event.GetIndex())

    def _open_conversation(self, index: int):
        if index < 0 or index >= len(self._results):
            return
        name, jid, chat = self._results[index]
        if chat is None:
            chat = {"remoteJid": jid, "pushName": name}
        self.EndModal(wx.ID_OK)
        mw = self._mw
        # Navigate after the dialog is gone
        wx.CallAfter(mw.conversations_panel.navigate_to_conversation, chat)
        wx.CallAfter(mw.conversations_panel.message_field.SetFocus)

    # ── Sub-dialogs ───────────────────────────────────────────────────────────

    def _on_new_group(self, event):
        from ui.dialogs.new_group import NewGroupDialog
        dlg = NewGroupDialog(self._mw)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_new_contact(self, event):
        from ui.dialogs.new_contact import NewContactDialog
        dlg = NewContactDialog(self._mw, parent=self)
        if dlg.ShowModal() == wx.ID_OK:
            jid  = dlg.result_jid
            name = dlg.result_name
            dlg.Destroy()
            if jid:
                self.EndModal(wx.ID_OK)
                chat = {"remoteJid": jid, "pushName": name}
                mw   = self._mw
                wx.CallAfter(mw.conversations_panel.navigate_to_conversation, chat)
                wx.CallAfter(mw.conversations_panel.message_field.SetFocus)
        else:
            dlg.Destroy()
