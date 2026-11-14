"""ContactMessagesMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

Moved verbatim out of ui/conversations.py. Methods run with ``self`` bound to
the ConversationsPanel instance, so every attribute set in
ConversationsPanel.__init__/init_UI is available here.
"""

import re
import wx
from core.utils import format_number


class ContactMessagesMixin:
    """Contact (vCard) and location messages.
    """

    def _location_maps_url(self, msg: dict) -> str | None:
        """Build an openable Google Maps URL from a locationMessage/
        liveLocationMessage's coordinates, or None if it carries none.

        WinZapp has no in-app map view — unlike the phone client, which
        renders the location inline — so "opening" a location here means
        handing its coordinates to the system's default map/browser handler,
        the same way an image or document opens in its associated app.
        """
        msg_type = msg.get("messageType", "")
        inner = (msg.get("message") or {}).get(msg_type)
        if not isinstance(inner, dict):
            return None
        lat = inner.get("degreesLatitude")
        lng = inner.get("degreesLongitude")
        if lat is None or lng is None:
            return None
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            return None
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

    def _jid_from_vcard(self, vcard: str) -> str | None:
        """Extract the WhatsApp JID from a vCard string."""
        if not vcard:
            return None
        m = re.search(r"waid=(\d+)", vcard)
        if m:
            return m.group(1) + "@s.whatsapp.net"
        m2 = re.search(r"TEL[^:]*:\+?([\d\s\-()]+)", vcard)
        if m2:
            digits = re.sub(r"\D", "", m2.group(1))
            if digits:
                return digits + "@s.whatsapp.net"
        return None

    def _contact_display_name(self, msg: dict) -> str:
        """Extract a contactMessage's display name — prefers WPPConnect's own
        displayName field, falling back to parsing "FN:" out of the vCard
        (some clients only ever populate the vcard, or stuff the whole vcard
        into displayName)."""
        i18n = self.main_window.i18n
        contact = (msg.get("message") or {}).get("contactMessage") or {}
        name  = contact.get("displayName") or ""
        vcard = contact.get("vcard") or ""

        if not name or "BEGIN:VCARD" in name:
            vcard_to_parse = name if "BEGIN:VCARD" in name else vcard
            parsed_name = ""
            for line in vcard_to_parse.splitlines():
                if line.startswith("FN:"):
                    parsed_name = line[3:].strip()
                    break
            name = parsed_name or i18n.t("unknown_contact")
        return name

    @staticmethod
    def _vcard_phone_numbers(vcard: str) -> list:
        """Every phone number a contact card carries, in card order.

        A vCard can hold several TEL lines (mobile / work / home), and issue #84
        asks for the user to pick which one when it does. Deliberately parses
        the TEL lines rather than reusing _jid_from_vcard(), which answers a
        different question ("which WhatsApp account is this?") and stops at the
        first waid= it finds — the right answer for opening a conversation, and
        the wrong one for "copy the number", which must be able to offer all of
        them. Each entry is (label, number): the label is the TYPE= parameter
        when the card names one, so a list of three bare numbers still reads as
        something in a screen reader.

        Numbers are returned exactly as the card writes them, minus whitespace
        runs — WhatsApp cards are inconsistent about "+55 51 9..." vs
        "+5551 9...", and rewriting them would mean guessing a country.
        """
        if not vcard:
            return []
        out = []
        seen = set()
        for line in vcard.splitlines():
            line = line.strip()
            if not line.upper().startswith("TEL"):
                continue
            prop, _, value = line.partition(":")
            number = " ".join(value.split()).strip()
            if not number:
                continue
            digits = re.sub(r"\D", "", number)
            if not digits or digits in seen:
                continue
            seen.add(digits)
            label = ""
            m = re.search(r"TYPE=([^;:]+)", prop, re.IGNORECASE)
            if m:
                label = m.group(1).strip().strip('"')
            out.append((label, number))
        return out

    def _contact_message_numbers(self, msg: dict) -> list:
        """_vcard_phone_numbers() for a contactMessage, with the waid fallback.

        Some cards carry the WhatsApp id and nothing parseable as a TEL line;
        _jid_from_vcard() already knows how to dig that out, so fall back to it
        rather than telling the user the card has no number when it plainly
        shows one.
        """
        contact = (msg.get("message") or {}).get("contactMessage") or {}
        numbers = self._vcard_phone_numbers(contact.get("vcard", ""))
        if numbers:
            return numbers
        jid = self._jid_from_vcard(contact.get("vcard", ""))
        if jid:
            return [("", format_number(jid))]
        return []

    def _pick_contact_number(self, msg: dict) -> str:
        """The number to act on, asking the user when the card holds several.

        Returns "" when the card has no number (announced) or the user cancels
        the choice. The dialog is a plain wx.SingleChoiceDialog on purpose —
        the accessibility rule in CLAUDE.md is standard controls, and a
        single-choice list is exactly what this is.
        """
        i18n = self.main_window.i18n
        numbers = self._contact_message_numbers(msg)
        if not numbers:
            self.main_window.output(i18n.t("contact_no_number"), interrupt=True)
            return ""
        if len(numbers) == 1:
            return numbers[0][1]
        choices = [f"{lbl}: {num}" if lbl else num for lbl, num in numbers]
        dlg = wx.SingleChoiceDialog(
            self, i18n.t("contact_pick_number"), i18n.t("contact_details_title"),
            choices,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return ""
            return numbers[dlg.GetSelection()][1]
        finally:
            dlg.Destroy()

    def _on_contact_view_details(self, msg: dict):
        """Context menu > "Ver nome e número": name plus every number on the
        card, spoken and shown, since the message row itself only ever renders
        the name (issue #84)."""
        i18n = self.main_window.i18n
        name = self._contact_display_name(msg)
        numbers = self._contact_message_numbers(msg)
        if numbers:
            lines = [f"{lbl}: {num}" if lbl else num for lbl, num in numbers]
            body = "\n".join([name] + lines)
        else:
            body = "\n".join([name, i18n.t("contact_no_number")])
        self.main_window.output(body.replace("\n", ". "), interrupt=True)
        wx.MessageBox(body, i18n.t("contact_details_title"), wx.OK | wx.ICON_INFORMATION, self)

    def _on_contact_copy_number(self, msg: dict):
        """Ctrl+C / context menu on a contact message: copy the phone number."""
        number = self._pick_contact_number(msg)
        if not number:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(number))
                wx.TheClipboard.Flush()
            finally:
                wx.TheClipboard.Close()
            self.main_window.output(
                self.main_window.i18n.t("contact_number_copied"), interrupt=True
            )
        else:
            self.main_window.output(
                self.main_window.i18n.t("msg_copy_error"), interrupt=True
            )

    def _on_contact_converse(self, event, jid: str | None = None):
        """Navigate to the conversation with the contact from the selected
        message. *jid* lets Enter/Space activation (_do_activate_message)
        pass the focused row's own JID directly instead of relying on
        self._contact_msg_jid, the side channel _on_message_focused() sets
        for the Converse button."""
        jid = jid or self._contact_msg_jid
        if not jid:
            return
        chat = self.main_window.get_chat(jid)
        if chat is not None:
            self.navigate_to_conversation(chat)

    def _on_save_contact_message(self, event):
        """Ctrl+Shift+S / the "Salvar contato" button next to "Conversar":
        open NewContactDialog pre-filled from the focused contactMessage, to
        add that contact locally in WinZapp — same dialog/flow
        conversation_data_dialog.py's "Adicionar contato" uses."""
        index = self.messages_list.GetFirstSelected()
        if index < 0 or index >= len(self._sorted_messages):
            return
        msg = self._sorted_messages[index]
        if self._is_separator(msg) or msg.get("messageType", "") != "contactMessage":
            return
        contact = (msg.get("message") or {}).get("contactMessage") or {}
        jid = self._jid_from_vcard(contact.get("vcard", ""))
        if not jid:
            return

        i18n = self.main_window.i18n
        name = self._contact_display_name(msg)
        parts  = name.split(None, 1) if name and name != i18n.t("unknown_contact") else []
        p_name = parts[0] if parts else ""
        p_sur  = parts[1] if len(parts) > 1 else ""

        from ui.dialogs.new_contact import NewContactDialog
        dlg = NewContactDialog(
            self.main_window, self,
            prefill_phone=format_number(jid),
            prefill_name=p_name,
            prefill_surname=p_sur,
        )
        dlg.ShowModal()
        dlg.Destroy()
