"""
WinZapp – Poll Dialog
=====================
Opened with Enter on a poll message. Shows the question, whether one or several
options may be chosen, and the options with their votes, most voted first (the
order WhatsApp's own desktop uses). The options are a plain wx.ListCtrl with
check boxes (the widget the reaction picker uses): the checked ones are the
user's vote, sent with "Vote". One progress bar per option shows its share.

The counts are refreshed in place while the dialog is open (a timer reads the
message again, which the panel keeps current), without moving focus or
changing what the user ticked.
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

_REFRESH_MS = 3000


class PollDialog(wx.Dialog):
    """*send_vote(msg, local_ids, on_done)* casts the vote in the background."""

    def __init__(self, main_window, msg: dict, send_vote, name_of=None):
        self._mw = main_window
        self._msg = msg
        self._send_vote = send_vote
        self._name_of = name_of
        i18n = main_window.i18n
        poll = poll_content(msg.get("message") or {})
        super().__init__(
            main_window,
            title=i18n.t("poll_dialog_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        multiple = allows_multiple(poll)
        self._multiple = multiple is not False
        self._loading = True
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        question = wx.TextCtrl(
            panel, value=poll.get("name") or "",
            style=wx.TE_READONLY | wx.TE_MULTILINE,
        )
        sizer.Add(wx.StaticText(panel, label=i18n.t("poll_dialog_question_label")),
                  0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        sizer.Add(question, 0, wx.EXPAND | wx.ALL, 8)

        if multiple is not None:
            hint = i18n.t("poll_allows_several" if multiple else "poll_allows_one")
            sizer.Add(wx.StaticText(panel, label=hint), 0, wx.LEFT | wx.RIGHT, 8)

        # Fixed for the life of the dialog: rows must not move under the cursor.
        self._order = [opt["name"] for opt in options_by_votes(poll_options(poll))]
        self._list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER
        )
        self._list.EnableCheckBoxes(True)
        self._list.InsertColumn(0, "", width=340)
        self._list.Freeze()
        try:
            for name in self._order:
                self._list.InsertItem(self._list.GetItemCount(), name)
        finally:
            self._list.Thaw()
        self._list.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_checked)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        self._gauges = {}
        for name in self._order:
            gauge = wx.Gauge(panel, range=100)
            self._gauges[name] = gauge
            sizer.Add(gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._status = wx.StaticText(panel, label="")
        sizer.Add(self._status, 0, wx.LEFT | wx.RIGHT, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self._vote_btn = wx.Button(panel, label=i18n.t("poll_vote_button"))
        self._vote_btn.Bind(wx.EVT_BUTTON, self._on_vote)
        btns.Add(self._vote_btn, 0, wx.ALL, 5)
        voters_btn = wx.Button(panel, label=i18n.t("poll_voters_button"))
        voters_btn.Bind(wx.EVT_BUTTON, self._on_view_votes)
        btns.Add(voters_btn, 0, wx.ALL, 5)
        btns.Add(wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close")), 0, wx.ALL, 5)
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        self._checked_once = False
        self._reload(initial=True)
        self._loading = False
        self.SetMinSize((380, 360))
        self.Fit()
        self.CentreOnParent()
        if self._list.GetItemCount():
            self._list.Focus(0)
            self._list.Select(0)
        self._list.SetFocus()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._reload(), self._timer)
        self._timer.Start(_REFRESH_MS)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._timer.Stop()
        event.Skip()

    # ── Data ────────────────────────────────────────────────────────────────

    def _options(self) -> list[dict]:
        return poll_options(poll_content(self._msg.get("message") or {}))

    def _reload(self, initial: bool = False) -> None:
        """Write the current counts into the rows and bars; the ticks are left
        alone after the first load, so a refresh never undoes the user's choice."""
        i18n = self._mw.i18n
        options = self._options()
        by_name = {opt["name"]: opt for opt in options}
        self._loading = True
        self._list.Freeze()
        try:
            for index, name in enumerate(self._order):
                option = by_name.get(name)
                if option is None:
                    continue
                percent = vote_percent(option, options)
                text = option_label(i18n, option, percent)
                if self._list.GetItemText(index) != text:
                    self._list.SetItemText(index, text)
                self._gauges[name].SetValue(percent or 0)
                self._gauges[name].SetName(
                    i18n.t("poll_option_percent").format(name=name, percent=percent or 0)
                    if percent is not None else name
                )
                if initial or (not self._checked_once and option["mine"]):
                    self._list.CheckItem(index, option["mine"])
        finally:
            self._list.Thaw()
            self._loading = False

    def _checked_names(self) -> list[str]:
        return [
            name for index, name in enumerate(self._order)
            if self._list.IsItemChecked(index)
        ]

    # ── Events ──────────────────────────────────────────────────────────────

    def _on_checked(self, event):
        if self._loading:
            event.Skip()
            return
        self._checked_once = True
        index = event.GetIndex()
        if not self._multiple:
            # A single-answer poll: ticking an option unticks the others.
            for other in range(self._list.GetItemCount()):
                if other != index and self._list.IsItemChecked(other):
                    self._list.CheckItem(other, False)
        event.Skip()

    def _on_view_votes(self, event):
        from ui.dialogs.poll_voters_dialog import PollVotersDialog

        dlg = PollVotersDialog(self, self._mw, self._msg, self._name_of)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _on_vote(self, event):
        i18n = self._mw.i18n
        names = self._checked_names()
        ids = vote_poll_ids(self._options(), names)
        self._vote_btn.Disable()
        self._status.SetLabel(i18n.t("poll_vote_sending"))

        def done(ok: bool):
            if not self:  # the dialog was closed meanwhile
                return
            self._vote_btn.Enable()
            self._status.SetLabel(i18n.t("poll_vote_sent" if ok else "poll_vote_failed"))
            self._mw.speak_output.output(i18n.t("poll_vote_sent" if ok else "poll_vote_failed"))

        self._send_vote(self._msg, ids, done)
