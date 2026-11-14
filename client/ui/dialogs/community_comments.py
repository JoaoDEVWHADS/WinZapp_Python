"""Native announcement thread, with a single-attempt composer.

The thread reads itself again when WhatsApp counts a new or deleted reply
(MainWindow.on_announcement_reply_count), as a conversation does for its
messages: there is no Refresh button to press."""

import copy
import logging
from datetime import datetime

import wx

from core.community_comments import CommunityCommentsError, comment_author_label
from core.locale_format import get_datetime_format


class CommunityCommentsDialog(wx.Dialog):
    def __init__(self, parent, main_window, jid, message, name, on_count=None):
        i18n = main_window.i18n
        title = i18n.t("community_comments_window").format(name=name)
        super().__init__(parent, title=title, size=(760, 540),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._mw, self._jid = main_window, jid
        self._on_count = on_count
        self._message = copy.deepcopy(message)
        self._token = main_window.token
        self._closed = self._busy = self._loaded = self._uncertain = False
        self._refresh_pending = False
        self._rows = []
        self._register()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=i18n.t("community_comments_list")), 0, wx.ALL, 8)
        self._list = wx.ListBox(self)
        self._list.SetName(i18n.t("community_comments_list").replace("&", ""))
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._status = wx.StaticText(self, label=i18n.t("loading"))
        sizer.Add(self._status, 0, wx.ALL, 8)
        sizer.Add(wx.StaticText(self, label=i18n.t("community_comments_write")), 0, wx.LEFT, 8)
        self._text = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self._text.SetName(i18n.t("community_comments_write").replace("&", ""))
        self._text.Bind(wx.EVT_TEXT, self._on_text)
        self._text.Bind(wx.EVT_KEY_DOWN, self._on_text_key)
        sizer.Add(self._text, 0, wx.EXPAND | wx.ALL, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._send = wx.Button(self, label=i18n.t("community_comments_send"))
        close = wx.Button(self, wx.ID_CANCEL, i18n.t("close"))
        self._send.Bind(wx.EVT_BUTTON, self._on_send)
        close.Bind(wx.EVT_BUTTON, self._on_close)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        for button in (self._send, close):
            buttons.Add(button, 0, wx.RIGHT, 8)
        sizer.Add(buttons, 0, wx.ALL, 8)
        self.SetSizer(sizer)
        self._update_buttons()
        self._list.SetFocus()
        wx.CallAfter(self._on_refresh, None)

    def _register(self):
        dialogs = getattr(self._mw, "_announcement_comment_dialogs", None)
        if dialogs is None:
            dialogs = self._mw._announcement_comment_dialogs = set()
        dialogs.add(self)

    def close_comments(self):
        self._closed = True
        getattr(self._mw, "_announcement_comment_dialogs", set()).discard(self)

    def on_reply_count_changed(self, chat, key_id, count):
        """WhatsApp counted a reply to some announcement: read again when it is
        this one. A count already shown (the reply just sent from here, read
        back by _finish_send) is not read twice.

        Matched by group and key.id, never by the serialized id: its author
        part is the stored @c.us phone when _phone_to_lid has no entry, and
        the page sends @lid."""
        if (not self._active() or chat != self._jid
                or key_id != (self._message.get("key") or {}).get("id")):
            return
        if self._busy:
            self._refresh_pending = True
            return
        if self._loaded and count == len(self._rows):
            return
        self._on_refresh(None)

    def _run_pending_refresh(self):
        if self._refresh_pending and not self._busy:
            self._refresh_pending = False
            self._on_refresh(None)

    def _on_close(self, event):
        self.close_comments()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self.close_comments()
        event.Skip()

    def _active(self):
        return (not self._closed and not getattr(self._mw, "_shutting_down", False)
                and self._token == self._mw.token)

    def _resend_blocked(self):
        """After an unconfirmed send, the same text cannot go again until a
        read shows the reply arrived (_finish_refresh) or the text changes:
        a reply still on its way is missing from the read right after it,
        and a second Ctrl+Enter would post it twice to the whole community."""
        return self._uncertain and self._text.GetValue() == getattr(self, "_sent_text", None)

    def _update_buttons(self):
        active = self._active() and not self._busy
        self._send.Enable(active and self._loaded and not self._resend_blocked()
                          and bool(self._text.GetValue().strip()))
        # Never read-only while a read or a send runs: the screen reader said
        # "somente leitura" whenever the field was reached during one, which
        # is every time the dialog opens. Send is what waits, not typing.
        self._text.SetEditable(self._active())

    def _on_text(self, event):
        self._update_buttons()
        event.Skip()

    def _on_text_key(self, event):
        if event.ControlDown() and event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_send(None)
        else:
            event.Skip()

    def _on_refresh(self, event):
        if not self._active() or self._busy:
            return
        self._busy = True
        self._status.SetLabel(self._mw.i18n.t("loading"))
        self._update_buttons()

        def read():
            try:
                rows = self._mw.get_announcement_comments(self._jid, self._message)
                error = None
            except CommunityCommentsError as exc:
                rows, error = None, exc.code
            except Exception:
                rows, error = None, "unavailable"
            wx.CallAfter(self._finish_refresh, rows, error)

        try:
            self._mw._msg_bg_executor.submit(read)
        except Exception:
            self._finish_refresh(None, "unavailable")

    def _row_label(self, row):
        i18n = self._mw.i18n
        author = comment_author_label(row, self._mw, self._jid)
        try:
            stamp = datetime.fromtimestamp(row["timestamp"]).strftime(
                get_datetime_format(i18n.t("datetime_fmt")))
        except (ValueError, OSError, OverflowError):
            stamp = ""
        body = (i18n.t("community_comments_deleted") if row["type"] == "revoked" else
                i18n.t("community_comments_encrypted") if row["type"] == "ciphertext" else row["body"])
        return f"{author}, {stamp}: {body}".replace("\r", " ").replace("\n", " ")

    def _finish_refresh(self, rows, error):
        if not self._active():
            return
        self._busy = False
        i18n = self._mw.i18n
        if rows is None:
            # Never log the exception, parent id, author or message content.
            code = "not_announcement" if error == "not_announcement" else "unavailable"
            logging.warning("[community_comments] read_failed code=%s", code)
            if error == "not_announcement":
                self._loaded = False
            text = (i18n.t("community_comments_not_announcement") if error == "not_announcement"
                    else i18n.t("community_comments_failed"))
        else:
            old = self._list.GetSelection()
            selected = self._rows[old]["id"] if 0 <= old < len(self._rows) else None
            labels = [self._row_label(row) for row in rows]
            if labels != list(self._list.GetItems()) or [r["id"] for r in rows] != [r["id"] for r in self._rows]:
                self._list.Freeze()
                try:
                    self._list.SetItems(labels)
                    ids = [row["id"] for row in rows]
                    self._list.SetSelection(ids.index(selected) if selected in ids else
                                            (min(max(old, 0), len(ids) - 1) if ids else wx.NOT_FOUND))
                finally:
                    self._list.Thaw()
            arrived = self._uncertain and any(
                row.get("fromMe") is True and row["id"] not in getattr(self, "_own_before_send", ())
                for row in rows)
            self._rows, self._loaded = rows, True
            if getattr(self, "_on_count", None):
                self._on_count(len(rows))
            text = (i18n.t("community_comments_count").format(count=len(rows)) if rows else
                    i18n.t("community_comments_empty"))
            if arrived:
                # The unconfirmed reply is in the thread: it went.
                self._uncertain = False
                if self._text.GetValue() == getattr(self, "_sent_text", None):
                    self._text.ChangeValue("")
                text = f"{i18n.t('community_comments_sent')} {text}"
        self._status.SetLabel(text)
        self._update_buttons()
        self._mw.speak_output.output(text)
        self._run_pending_refresh()

    def _on_send(self, event):
        if not self._active() or self._busy or not self._loaded or self._resend_blocked():
            return
        text = self._text.GetValue()
        if not text.strip():
            return
        self._busy = True
        self._sent_text = text
        # A reply of one's own missing from these is what proves an
        # unconfirmed send went (_finish_refresh).
        self._own_before_send = {row["id"] for row in self._rows if row.get("fromMe") is True}
        self._update_buttons()
        self._status.SetLabel(self._mw.i18n.t("community_comments_sending"))

        def send():
            try:
                confirmed = self._mw.send_announcement_comment(self._jid, self._message, text) is True
            except Exception:
                confirmed = False
            wx.CallAfter(self._finish_send, confirmed)

        try:
            self._mw._msg_bg_executor.submit(send)
        except Exception:
            self._finish_send(False)

    def _finish_send(self, confirmed):
        if not self._active():
            return
        self._busy = False
        self._uncertain = not confirmed
        if not confirmed:
            logging.warning("[community_comments] send_failed code=unconfirmed")
        # Clear only what was sent: anything typed meanwhile is a new draft.
        if confirmed and self._text.GetValue() == getattr(self, "_sent_text", None):
            self._text.ChangeValue("")
        text = self._mw.i18n.t("community_comments_sent") if confirmed else self._mw.i18n.t("community_comments_unconfirmed")
        self._status.SetLabel(text)
        self._update_buttons()
        self._mw.speak_output.output(text)
        self._text.SetFocus()
        # Read the thread either way. After an unconfirmed send the reply may
        # or may not have gone; what the thread now shows is what lets the
        # user decide whether to send again (it is never resent from here).
        self._refresh_pending = False
        self._on_refresh(None)
