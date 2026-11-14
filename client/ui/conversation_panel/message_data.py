"""MessageDataMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

The "Message data" window (Alt+Shift+D, or the message's context menu): who said
it, what, when it was sent and — for a message WE sent — when it was delivered,
read and played.

Two sources, in this order:

1. WhatsApp itself, live (MainWindow.fetch_message_ack): the phone-synced times,
   which include receipts that arrived while WinZapp was closed. In a group that
   is a per-person breakdown ("Read (2/9): Ana, Bia").
2. What WinZapp recorded locally as the receipts arrived
   (MessageRenderingMixin._status_history_lines), when WhatsApp could not be
   asked — offline, a message it no longer holds, a failed call — or for a
   message that is not ours.

The call to WhatsApp can take seconds, so it runs on a worker thread, the wait
is spoken, and the window opens when it answers: a window that appears and then
changes under a screen reader's cursor would be worse than a short wait.

Methods run with ``self`` bound to the ConversationsPanel instance.
"""

import threading

import wx

from core import message_ack
from core.utils import format_number


class MessageDataMixin:
    """The Message data window."""

    #: True while a call to WhatsApp is out, so a second press does not open a
    #: second window behind the first.
    _message_data_pending = False

    def _wants_live_receipts(self, msg: dict, chat_jid: str) -> bool:
        """Only our own messages in a chat where receipts mean something."""
        if not (msg.get("key") or {}).get("fromMe"):
            return False
        if not chat_jid or chat_jid.endswith("@broadcast"):
            return False
        return not self._receipts_are_meaningless(chat_jid)

    def _on_menu_message_data(self, msg: dict):
        mw = self.main_window
        chat_jid = self.conversation.get("remoteJid", "") if self.conversation else ""
        if not self._wants_live_receipts(msg, chat_jid):
            self._show_message_data(msg, chat_jid, None)
            return
        if self._message_data_pending:
            return  # a second press while the first is still asking
        self._message_data_pending = True
        mw.output(mw.i18n.t("message_data_loading"))
        key = dict(msg.get("key") or {})

        def work():
            ack = mw.fetch_message_ack(chat_jid, key)
            wx.CallAfter(self._show_message_data, msg, chat_jid, ack)

        threading.Thread(target=work, daemon=True).start()

    def _show_message_data(self, msg: dict, chat_jid: str, ack):
        self._message_data_pending = False
        if not self:  # the panel was closed while WhatsApp was answering
            return
        i18n = self.main_window.i18n
        dlg = wx.Dialog(
            self.main_window, title=i18n.t("message_data"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(420, 280),
        )
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        info_ctrl = wx.TextCtrl(
            panel, value="\n".join(self._message_data_lines(msg, chat_jid, ack)),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        sizer.Add(info_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        close_btn = wx.Button(panel, wx.ID_OK, label=i18n.t("close"))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        dlg.SetSizer(dlg_sizer)
        info_ctrl.SetFocus()
        dlg.ShowModal()
        dlg.Destroy()

    def _message_data_lines(self, msg: dict, chat_jid: str, ack) -> list:
        """The text of the window, one line per fact (see the module docstring)."""
        i18n = self.main_window.i18n
        ts = self._extract_timestamp(msg)
        lines = [f"{self._sender_label(msg)}: {self._get_message_content(msg)}"]
        if ts:
            lines.append(f"{i18n.t('status_sent')}: {self._format_full_datetime(ts)}")
        history = (
            self._live_status_history_lines(msg, chat_jid, ack)
            or self._status_history_lines(msg, chat_jid, full_dates=True)
        )
        if history:
            lines.extend(history)
        else:
            status = self._map_status(msg, chat_jid)
            if status:
                lines.append(f"{i18n.t('message_data_status_label')}: {status}")
        return lines

    def _live_status_history_lines(self, msg: dict, chat_jid: str, ack) -> list:
        """Lines from WhatsApp's own answer for one of our messages, or [] when
        there is nothing to say from it (so the caller falls back to local history).
        """
        if not ack or not self._wants_live_receipts(msg, chat_jid):
            return []
        if chat_jid.endswith("@g.us"):
            return self._group_ack_breakdown_lines(ack)
        i18n = self.main_window.i18n
        label_keys = {
            "delivered": "status_delivered",
            "read": "status_read",
            "played": "status_played",
        }
        return [
            f"{i18n.t(label_keys[stage])}: {self._format_full_datetime(ts)}"
            for stage, ts in message_ack.direct_timeline(ack)
        ]

    def _group_ack_breakdown_lines(self, ack, max_names: int = 40) -> list:
        """'Read (2/9): Ana, Bia' style lines, one per stage, for a group message."""
        i18n = self.main_window.i18n
        label_keys = {
            "delivered": "status_delivered",
            "read": "status_read",
            "played": "status_played",
        }
        return message_ack.group_lines(
            ack,
            name_for=self._ack_participant_name,
            label_for=lambda stage: i18n.t(label_keys[stage]),
            more_for=lambda n: i18n.t("and_n_more_suffix").format(n=n),
            max_names=max_names,
        )

    def _ack_participant_name(self, raw_jid: str) -> str:
        """The name to show for one participant of a group's ack answer."""
        lid_to_phone = getattr(self.main_window, "_lid_to_phone", {})
        return message_ack.display_name(
            raw_jid,
            self._saved_contact_name(raw_jid) if raw_jid else "",
            lambda lid: lid_to_phone.get(lid, ""),
            format_number,
        )
