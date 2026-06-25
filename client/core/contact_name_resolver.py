"""Service responsible for resolving contact display names from JIDs.

Extracted from MainWindow (main.py) to reduce god-class complexity.
All methods preserve original logic exactly — no behavioural changes.
"""

import logging

from core.utils import format_number, is_phone_like


class ContactNameResolver:
    """Resolves WhatsApp contact names using contacts dict, JID bridging, and fallbacks."""

    def __init__(self, main_window):
        self.mw = main_window

    # ── shared helpers ──────────────────────────────────────────────────

    def _get_contact_tolerant(self, jid):
        """Look up a contact by JID with Brazilian 9-digit tolerance."""
        if not jid:
            return None
        if ":" in jid:
            parts = jid.split("@")
            if len(parts) == 2:
                jid = parts[0].split(":")[0] + "@" + parts[1]
        c = self.mw.contacts.get(jid)
        if c:
            return c
        if jid.endswith("@s.whatsapp.net"):
            phone = jid.split("@")[0]
            if phone.startswith("55"):
                if len(phone) == 13 and phone[4] == "9":
                    alt = phone[:4] + phone[5:] + "@s.whatsapp.net"
                    return self.mw.contacts.get(alt)
                elif len(phone) == 12:
                    alt = phone[:4] + "9" + phone[4:] + "@s.whatsapp.net"
                    return self.mw.contacts.get(alt)
        return None

    def _name_from_contact(self, c):
        """Extract a valid display name from a contact dict."""
        for field in ("name", "pushName"):
            val = c.get(field)
            if val and isinstance(val, str):
                val = val.strip()
                if val and not val.isdigit() and not is_phone_like(val):
                    val_lower = val.lower()
                    if "sem nome" in val_lower or "unnamed" in val_lower or val_lower in ("no name", "unknown", "desconhecido"):
                        logging.info(f"[LID Mapping] Rejecting placeholder name '{val}' for contact JID '{c.get('id') or c.get('remoteJid')}'")
                        continue
                    return val
        return None

    # ── public interface ────────────────────────────────────────────────

    def _resolve_contact_name(self, chat):
        """
        Return the saved contact name (contact.pushName) for a private chat, or None.

        Tries all three JID formats (@s.whatsapp.net, @c.us, @lid) and returns
        the first valid pushName found.  Groups are skipped (always return None).
        Falls back to the presence-learned pushName map for @lid contacts.
        """
        remoteJid = chat.get("remoteJid", "")
        if not remoteJid or remoteJid.endswith("@g.us"):
            return None

        ppm = getattr(self.mw, "_presence_pushname_map", {})

        def _try(jid: str) -> str:
            if not jid:
                return ""
            c = self._get_contact_tolerant(jid)
            if c:
                return self._name_from_contact(c) or ""
            return ""

        def _ppm(jid: str) -> str:
            val = (ppm.get(jid) or "").strip()
            return val if val and not val.isdigit() and not is_phone_like(val) else ""

        local = remoteJid.rsplit("@", 1)[0]
        resolved = ""
        if remoteJid.endswith("@s.whatsapp.net"):
            resolved = (
                _try(remoteJid)
                or _try(local + "@c.us")
                or _try(getattr(self.mw, "_phone_to_lid", {}).get(remoteJid, ""))
                or _ppm(remoteJid)
            )
        elif remoteJid.endswith("@c.us"):
            phone_net = local + "@s.whatsapp.net"
            resolved = (
                _try(remoteJid)
                or _try(phone_net)
                or _try(getattr(self.mw, "_phone_to_lid", {}).get(phone_net, ""))
                or _ppm(remoteJid)
                or _ppm(phone_net)
            )
        elif remoteJid.endswith("@lid"):
            phone = (
                getattr(self.mw, "_lid_to_phone", {}).get(remoteJid, "")
                or self.mw._find_alt_jid_from_messages(chat)
                or ""
            )
            resolved = (
                _try(remoteJid)
                or (phone and (_try(phone) or _try(phone.rsplit("@", 1)[0] + "@c.us")))
                or _ppm(remoteJid)
                or (phone and _ppm(phone))
            )
        else:
            resolved = _try(remoteJid)

        if resolved:
            return resolved

        chat_name = chat.get("name", "")
        if chat_name and isinstance(chat_name, str):
            chat_name = chat_name.strip()
            if chat_name and not chat_name.isdigit() and not is_phone_like(chat_name):
                chat_name_lower = chat_name.lower()
                if "sem nome" in chat_name_lower or "unnamed" in chat_name_lower or chat_name_lower in ("no name", "unknown", "desconhecido"):
                    pass
                else:
                    return chat_name

        return None

    def find_name_through_messages(self, chat):
        if chat.get("remoteJid", "").endswith("@g.us"):
            return None
        messages_obj = chat.get("messages") or {}
        for message in messages_obj.get("messages", {}).get("records", []):
            if message.get("key", {}).get("fromMe"):
                continue
            push = message.get("pushName", "")
            if push and not is_phone_like(push):
                return push
        return None

    def find_jid_through_messages(self, chat):
        messages_obj = chat.get("messages") or {}
        for message in messages_obj.get("messages", {}).get("records", []):
            if not message.get("key", {}).get("fromMe"):
                key = message.get("key", {})
                alt = key.get("remoteJidAlt", "")
                if alt and alt.endswith("@s.whatsapp.net"):
                    return format_number(alt)
                jid = key.get("remoteJid", "")
                if jid and not jid.endswith("@lid") and not jid.endswith("@g.us"):
                    return format_number(jid)
        return None

    def _resolve_jid_name(self, jid_norm: str) -> str:
        """Return the best display name for a participant JID (contact lookup + fallback)."""

        ppm = getattr(self.mw, "_presence_pushname_map", {})

        candidates = [jid_norm]
        local = jid_norm.rsplit("@", 1)[0]
        if jid_norm.endswith("@s.whatsapp.net"):
            candidates.append(local + "@c.us")
            lid = getattr(self.mw, "_phone_to_lid", {}).get(jid_norm, "")
            if lid:
                candidates.append(lid)
        elif jid_norm.endswith("@c.us"):
            candidates.append(local + "@s.whatsapp.net")
        elif jid_norm.endswith("@lid"):
            phone = getattr(self.mw, "_lid_to_phone", {}).get(jid_norm, "")
            if phone:
                candidates.append(phone)
                candidates.append(phone.rsplit("@", 1)[0] + "@c.us")

        for cjid in candidates:
            contact = self._get_contact_tolerant(cjid)
            if contact:
                name = (contact.get("name") or contact.get("pushName") or "").strip()
                if name and not name.isdigit():
                    return name
            chat = self.mw.chats.get(cjid)
            if chat:
                name = (chat.get("name") or chat.get("pushName") or "").strip()
                if name and not name.isdigit():
                    return name
        for cjid in candidates:
            pname = (ppm.get(cjid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname
        if jid_norm.endswith("@lid"):
            phone = getattr(self.mw, "_lid_to_phone", {}).get(jid_norm, "")
            if phone:
                return format_number(phone)
        if not jid_norm.endswith(("@g.us", "@lid")):
            return format_number(jid_norm)
        return local

    def _preview_sender_from_jid(self, jid: str) -> str:
        """
        Resolve a participant JID to a display name for chat list previews.
        Tries contacts dict (with @lid bridging), then falls back to
        format_number on the phone-number JID. Never returns a bare @lid string.
        """
        if not jid:
            return ""

        ppm = getattr(self.mw, "_presence_pushname_map", {})
        phone_jid = ""
        contact = self._get_contact_tolerant(jid)
        if not contact and jid.endswith("@lid"):
            phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid, "")
            if phone_jid:
                contact = self._get_contact_tolerant(phone_jid)
        if contact:
            name = (contact.get("name") or contact.get("pushName") or "").strip()
            if name and not is_phone_like(name):
                return name
        for lookup_jid in ([jid, phone_jid] if phone_jid else [jid]):
            pname = (ppm.get(lookup_jid) or "").strip()
            if pname and not pname.isdigit() and not is_phone_like(pname):
                return pname
        if jid.endswith("@lid"):
            if not phone_jid:
                phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid, "")
            return format_number(phone_jid) if phone_jid else self.mw.i18n.t("unnamed_participant")
        if jid.endswith("@g.us"):
            return self.mw.i18n.t("unknown_group")
        return format_number(jid)
