"""An order the seller sent or updated: its items and what it says, and, for
the buyer of an order paid outside the app, "Confirm order info".

The seller's order details and each later status arrive as one message
(core/commerce.py, ORDER_UPDATE_MESSAGE_TYPE) that already carries everything
shown here. The server is asked only whether the buyer may confirm it, which
it decides the way WhatsApp Web does (api_patches orderConfirmController.ts);
the button exists only after it said yes.

The confirmation is sent once and never retried: whatever the answer, the
order is read again, and only a reading that shows it confirmed is announced
as done.
"""

import logging
import wx

from core import commerce
from core.commerce import BuyerOrder, CommerceError
from ui.dialogs.background_work import BackgroundWork
from ui.dialogs.labelled_control import add_labelled


class OrderUpdateDialog(BackgroundWork, wx.Dialog):
    def __init__(self, parent, main_window, msg, message_id, chat_name):
        self._init_background(main_window)
        i18n = self._i18n
        self._message = message_id
        self._chat_name = chat_name
        self._buyer = None
        self._sent = False
        super().__init__(parent, title=i18n.t("commerce_order_title").format(name=chat_name),
                         size=(560, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        labels = commerce.order_update_item_labels(msg, i18n)
        self._items = None
        if labels:
            self._items = add_labelled(self, sizer, i18n.t("commerce_order_items"),
                                       lambda: wx.ListBox(self, choices=labels, style=wx.LB_SINGLE), 2)
            self._items.SetSelection(0)
        self._details = add_labelled(self, sizer, i18n.t("commerce_order_details"), lambda: wx.TextCtrl(
            self, value=commerce.order_update_description(msg, i18n),
            style=wx.TE_READONLY | wx.TE_MULTILINE), 1)
        self._status = wx.StaticText(self, label="")
        sizer.Add(self._status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._confirm = wx.Button(self, label=i18n.t("commerce_order_confirm"))
        self._confirm.Bind(wx.EVT_BUTTON, self._on_confirm)
        self._confirm.Hide()
        buttons.Add(self._confirm, 0, wx.ALL, 4)
        close = wx.Button(self, wx.ID_CANCEL, label=i18n.t("close"))
        close.Bind(wx.EVT_BUTTON, self._on_close)
        buttons.Add(close, 0, wx.ALL, 4)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
        self.SetSizer(sizer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        (self._items or self._details).SetFocus()
        self.CentreOnParent()
        if commerce.should_read_buyer(msg, message_id):
            wx.CallAfter(self._read_buyer)

    # ── what the buyer may do ─────────────────────────────────────────────

    def _read(self):
        """The buyer's view of the order, or the refusal's code."""
        try:
            return commerce.read_buyer_order(self._connection, self._message)
        except CommerceError as error:
            return error.code

    def _read_buyer(self):
        if self._busy or not self._current():
            return
        self._busy = True
        self._run_async(self._read, self._finish_read)

    def _finish_read(self, buyer):
        self._busy = False
        if not isinstance(buyer, BuyerOrder):
            # An order of another kind, or an older server: nothing to offer,
            # and nothing the user asked for went wrong.
            if buyer != "not_an_order":
                logging.info("[commerce] buyer_order_read_failed")
            return
        self._show_buyer(buyer)
        if buyer.confirmed:
            self._status.SetLabel(self._i18n.t("commerce_order_confirm_already"))

    def _show_buyer(self, buyer):
        self._buyer = buyer
        offered = buyer.can_confirm and not self._sent
        if self._confirm.IsShown() != offered:
            had_focus = self.FindFocus() is self._confirm
            self._confirm.Show(offered)
            self.Layout()
            if had_focus and not offered:
                self._details.SetFocus()

    # ── the confirmation ──────────────────────────────────────────────────

    def _on_confirm(self, event):
        if self._busy or self._sent or not (self._buyer and self._buyer.can_confirm) or not self._current():
            return
        i18n = self._i18n
        answer = wx.MessageBox(i18n.t("commerce_order_confirm_question").format(name=self._chat_name),
                               i18n.t("commerce_order_confirm_title"), wx.YES_NO | wx.ICON_QUESTION, self)
        if answer != wx.YES or self._sent or not self._current():
            return
        self._sent = True
        self._busy = True
        self._status.SetLabel(i18n.t("loading"))
        connection, message = self._connection, self._message

        def run():
            try:
                commerce.confirm_buyer_order(connection, message)
            except CommerceError as error:
                refused = error.code
            else:
                refused = ""
            return refused, self._read()
        self._run_async(run, self._finish_confirm)

    def _finish_confirm(self, outcome):
        self._busy = False
        refused, buyer = outcome if outcome else ("unavailable", None)
        i18n = self._i18n
        if isinstance(buyer, BuyerOrder):
            self._show_buyer(buyer)
        else:
            self._show_buyer(BuyerOrder(False, False))
        if isinstance(buyer, BuyerOrder) and buyer.confirmed:
            self._announce(i18n.t("commerce_order_confirm_done"))
        elif refused in ("already_confirmed",):
            self._announce(i18n.t("commerce_order_confirm_already"))
        elif refused in ("cannot_confirm", "not_an_order", "invalid_request"):
            self._announce(i18n.t("commerce_order_confirm_failed"))
        else:
            # Possibly sent: never offered again from here, and the user is
            # told to look at the chat first.
            logging.warning("[commerce] buyer_order_confirm_unconfirmed")
            self._announce(i18n.t("commerce_order_confirm_unconfirmed"))
