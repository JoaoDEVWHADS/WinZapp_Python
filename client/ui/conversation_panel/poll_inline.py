"""PollInlineMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

A single-answer poll can be voted on without opening it: while its row is
focused in the message list, the first Tab lands on a list of its options, and
ticking one casts the vote at once (unlike the poll window, which waits for the
"Vote" button). The list exists only while such a row is focused, so it never
adds a Tab stop anywhere else. Polls that accept several answers keep the
window, where the user can tick a few options before confirming.
"""

import wx

from core.polls import (
    allows_multiple,
    option_label,
    options_by_votes,
    poll_content,
    poll_options,
    vote_percent,
    vote_poll_ids,
)


def inline_poll_applies(msg: dict) -> bool:
    """Whether *msg* is a confirmed single-answer poll that can be voted on."""
    if not isinstance(msg, dict) or msg.get("_local_pending"):
        return False
    poll = poll_content(msg.get("message") or {})
    return bool(poll) and allows_multiple(poll) is False and bool(poll_options(poll))


def poll_in_messages(msg: dict, messages, remote_jid: str, shown_jid: str) -> bool:
    """Whether the poll the list was filled for is still part of the open
    conversation. The panel rebuilds its message dicts, so the id is compared."""
    msg_id = ((msg or {}).get("key") or {}).get("id", "")
    return bool(msg_id) and remote_jid == shown_jid and any(
        isinstance(m, dict) and (m.get("key") or {}).get("id") == msg_id for m in messages
    )


def same_inline_poll(shown, shown_jid, msg, jid) -> bool:
    """Whether *msg* in chat *jid* is the poll already in the inline list:
    by its id, not by the dict, which a sync replaces."""
    if not isinstance(shown, dict) or not isinstance(msg, dict) or shown_jid != jid:
        return False
    shown_id = (shown.get("key") or {}).get("id")
    return bool(shown_id) and shown_id == (msg.get("key") or {}).get("id")


class PollInlineMixin:
    """The options list that follows a focused single-answer poll."""

    def _create_inline_poll_list(self, parent, sizer):
        """Build the (hidden) options list right after the message list."""
        self._poll_inline_msg = None
        self._poll_inline_order = []
        self._poll_inline_loading = False
        self._poll_inline_jid = ""
        self._poll_inline_seq = 0
        label = wx.StaticText(parent, label=self.main_window.i18n.t("poll_inline_options_label"))
        sizer.Add(label, 0, wx.LEFT | wx.RIGHT, 5)
        label.Hide()
        self._poll_inline_label = label
        lst = wx.ListCtrl(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER)
        lst.EnableCheckBoxes(True)
        lst.InsertColumn(0, "", width=360)
        lst.SetName(self.main_window.i18n.t("new_poll_options_list_label").rstrip(":"))
        lst.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_inline_poll_checked)
        lst.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_inline_poll_checked)
        sizer.Add(lst, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        lst.Hide()
        self._poll_inline_list = lst

    def _update_inline_poll(self, idx: int) -> None:
        """Show the options list for the focused row if it is a single-answer
        poll, hide it otherwise. Called whenever the focused message changes."""
        lst = getattr(self, "_poll_inline_list", None)
        if lst is None:
            return
        msg = None
        if 0 <= idx < len(self._sorted_messages):
            candidate = self._sorted_messages[idx]
            if not self._is_separator(candidate) and inline_poll_applies(candidate):
                msg = candidate
        if msg is None:
            self._hide_inline_poll()
            return
        jid = (self.conversation or {}).get("remoteJid", "")
        if same_inline_poll(self._poll_inline_msg, getattr(self, "_poll_inline_jid", ""), msg, jid):
            # The same poll, possibly a fresh dict from a sync or a rebuild
            # (populate_messages() re-decides the focused row): keep the list
            # where the user is in it, and only read its votes again.
            self._poll_inline_msg = msg
            self._reload_inline_poll()
        else:
            self._poll_inline_msg = msg
            self._poll_inline_jid = jid
            self._fill_inline_poll(msg)
        if not lst.IsShown():
            self._poll_inline_label.Show()
            lst.Show()
            self.conversation_panel.Layout()

    def _hide_inline_poll(self) -> None:
        """Hide the options list and forget its poll (a ticked box in a list the
        user has left must never cast a vote)."""
        lst = getattr(self, "_poll_inline_list", None)
        if lst is None:
            return
        self._poll_inline_msg = None
        self._poll_inline_seq += 1
        if lst.IsShown():
            self._poll_inline_label.Hide()
            lst.Hide()
            self.conversation_panel.Layout()

    def _fill_inline_poll(self, msg: dict) -> None:
        lst = self._poll_inline_list
        options = options_by_votes(poll_options(poll_content(msg.get("message") or {})))
        self._poll_inline_order = [opt["name"] for opt in options]
        self._poll_inline_loading = True
        lst.Freeze()
        try:
            lst.DeleteAllItems()
            for opt in options:
                index = lst.InsertItem(
                    lst.GetItemCount(),
                    option_label(self.main_window.i18n, opt, vote_percent(opt, options)),
                )
                lst.CheckItem(index, opt["mine"])
        finally:
            lst.Thaw()
            self._poll_inline_loading = False
        # Item 0 (or the voted one) is the focused item, so a screen reader
        # that Tabs in reads a row instead of an empty list; no SetFocus here.
        mine = [i for i, opt in enumerate(options) if opt["mine"]]
        first = mine[0] if mine else 0
        if options:
            lst.Focus(first)
            lst.Select(first)
        row = lst.GetItemRect(0).height if options else 0
        lst.SetMinSize((-1, min(len(options), 6) * (row or 24) + 8))

    def _restore_inline_ticks(self, msg: dict) -> None:
        """Put the ticks back to the recorded vote after a vote that failed."""
        lst = self._poll_inline_list
        mine = {o["name"]: o["mine"] for o in poll_options(poll_content(msg.get("message") or {}))}
        self._poll_inline_loading = True
        try:
            for index, name in enumerate(self._poll_inline_order):
                lst.CheckItem(index, mine.get(name, False))
        finally:
            self._poll_inline_loading = False

    def _reload_inline_poll(self) -> None:
        """New vote counts for the shown poll, without touching the ticks. Only rows
        whose text changed are rewritten, so the focused list stays quiet unless
        a count moved (the row just voted on must show its new count)."""
        msg, lst = self._poll_inline_msg, self._poll_inline_list
        if msg is None:
            return
        options = poll_options(poll_content(msg.get("message") or {}))
        by_name = {o["name"]: o for o in options}
        self._poll_inline_loading = True
        lst.Freeze()
        try:
            for index, name in enumerate(self._poll_inline_order):
                option = by_name.get(name)
                if option is None:
                    continue
                text = option_label(self.main_window.i18n, option, vote_percent(option, options))
                if lst.GetItemText(index) != text:
                    lst.SetItemText(index, text)
        finally:
            lst.Thaw()
            self._poll_inline_loading = False

    def _on_inline_poll_checked(self, event) -> None:
        event.Skip()
        if self._poll_inline_loading or self._poll_inline_msg is None:
            return
        msg = self._poll_inline_msg
        if not poll_in_messages(
            msg, self._sorted_messages,
            (self.conversation or {}).get("remoteJid", ""), self._poll_inline_jid,
        ):
            self._hide_inline_poll()
            return
        lst, index = self._poll_inline_list, event.GetIndex()
        checked = lst.IsItemChecked(index)
        # Single answer: choosing one option replaces the previous choice.
        if checked:
            self._poll_inline_loading = True
            try:
                for other in range(lst.GetItemCount()):
                    if other != index and lst.IsItemChecked(other):
                        lst.CheckItem(other, False)
            finally:
                self._poll_inline_loading = False
        names = [self._poll_inline_order[index]] if checked else []
        ids = vote_poll_ids(poll_options(poll_content(msg.get("message") or {})), names)
        i18n = self.main_window.i18n

        self._poll_inline_seq += 1
        seq = self._poll_inline_seq

        def done(ok: bool):
            if seq != self._poll_inline_seq:
                return   # a newer tick (or leaving the poll) superseded this vote
            self.main_window.speak_output.output(
                i18n.t("poll_vote_sent" if ok else "poll_vote_failed")
            )
            if not ok and self._poll_inline_msg is msg:
                self._restore_inline_ticks(msg)   # show what is actually voted

        self._send_poll_vote(msg, ids, done)
