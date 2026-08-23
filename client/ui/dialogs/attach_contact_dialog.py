"""
WinZapp – Attach Contact Dialog
================================
Modal dialog that lets the user select a contact from the contacts list
to attach to an outgoing message.

The dialog presents a two-column ListCtrl (name / phone) populated from
``main_window.contacts``.  On confirmation, :attr:`selected_contact` is
set to the chosen contact dict (keyed by remoteJid) and the dialog
returns ``wx.ID_OK``.
"""

import wx
from core.utils import format_number, contact_dedup_key


class AttachContactDialog(wx.Dialog):
    """
    Shows the contacts list and returns the chosen contact on OK.

    Parameters
    ----------
    main_window : MainWindow
    """

    def __init__(self, main_window):
        self._mw = main_window
        i18n = main_window.i18n
        super().__init__(
            main_window,
            title=i18n.t("attach_contact_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.selected_contact: dict | None = None
        self._contacts_list: list = []   # parallel to list rows

        self._build_ui()
        self.SetSize((420, 440))
        self.CentreOnParent()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        i18n = self._mw.i18n
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, i18n.t("conversations"), width=200)
        self._list.InsertColumn(1, i18n.t("phone_label"), width=160)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, label=i18n.t("send_attachment"))
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(dlg_sizer)

        # Populate — main_window.contacts intentionally holds more than one
        # entry per real person (the same contact is bridged under @lid,
        # @c.us and/or @s.whatsapp.net, and Brazilian numbers additionally
        # under both their 8- and 9-digit mobile form — see
        # core.utils.contact_dedup_key()), so iterating it directly showed
        # every contact twice, once per JID variant, each formatted
        # differently (issue #70). Collapse to one row per real person,
        # preferring whichever variant is a phone JID — an @lid isn't a real
        # phone number and can't produce a valid vCard when the contact is
        # actually sent — and sort alphabetically for predictable
        # keyboard/screen-reader navigation instead of dict-insertion order.
        # Also skip a bare @lid with no bridged phone number at all (an
        # unresolved LID, or one that only ever appeared as a group
        # participant's sender-name entry — main_window.contacts has no
        # isMyContact/isSaved flag for those, so the same legitimacy check
        # add_member_dialog.py already applies is repeated here). Without
        # this, an @lid contact_dedup_key() can't fold into any phone entry
        # still got its own row showing raw, unconverted @lid digits — not a
        # duplicate exactly, but useless junk that can't build a vCard
        # (format_number() refuses to format a LID as a phone number) and
        # looked like the same duplication bug from the user's report.
        chats = getattr(self._mw, "chats", {})
        contacts = self._mw.contacts
        best_by_key: dict[str, dict] = {}
        for jid, contact in contacts.items():
            if not jid or jid.endswith("@g.us"):
                continue
            is_own_contact = (
                contact.get("isMyContact") is True
                or contact.get("isMe") is True
                or contact.get("isSaved") is True
                or jid in chats
            )
            if not is_own_contact:
                continue
            key = contact_dedup_key(self._mw, jid)
            if jid.endswith("@lid") and key == jid.split("@", 1)[0]:
                # contact_dedup_key() only returns the raw @lid local part
                # when _lid_to_phone has no bridge for it — i.e. this LID
                # never resolved to an actual phone number.
                continue
            entry = {**contact, "remoteJid": jid}
            existing = best_by_key.get(key)
            if existing is None or (
                existing["remoteJid"].endswith("@lid") and not jid.endswith("@lid")
            ):
                best_by_key[key] = entry

        if not best_by_key:
            self._list.Append((i18n.t("no_contacts"), ""))
        else:
            rows = [
                (
                    entry.get("name") or entry.get("pushName")
                    or format_number(entry["remoteJid"]),
                    entry,
                )
                for entry in best_by_key.values()
            ]
            rows.sort(key=lambda r: r[0].lower())
            for name, entry in rows:
                self._list.Append((name, format_number(entry["remoteJid"])))
                self._contacts_list.append(entry)
            self._list.Focus(0)
            self._list.Select(0)

    # ── Events ──────────────────────────────────────────────────────────────

    def _on_activate(self, event):
        self._on_ok(event)

    def _on_ok(self, event):
        idx = self._list.GetFirstSelected()
        if idx < 0 or idx >= len(self._contacts_list):
            return
        self.selected_contact = self._contacts_list[idx]
        self.EndModal(wx.ID_OK)
