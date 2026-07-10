"""Service responsible for @lid JID mapping, resolution, and caching.

Extracted from MainWindow (main.py) to reduce god-class complexity.
All methods preserve original logic exactly — no behavioural changes.
"""

import os
import threading
import time
import logging
import requests
import wx

from core.utils import decrypt_json, format_number, is_phone_like
from app_paths import data_path


class JidMappingService:
    """Manages WhatsApp @lid → @s.whatsapp.net JID mapping lifecycle."""

    def __init__(self, main_window):
        self.main_window = main_window

    # ── helpers used internally ─────────────────────────────────────────

    def _normalize_jid(self, jid: str) -> str:
        return self.main_window._normalize_jid(jid)

    def _is_self_jid(self, jid: str) -> bool:
        return self.main_window._is_self_jid(jid)

    # ── public interface ────────────────────────────────────────────────

    def _merge_lid_into_phone(self, lid_jid: str, phone_jid: str):
        """Merge a @lid chat entry into the canonical phone (@s.whatsapp.net) entry.

        If only @lid exists, renames it.
        If both exist, copies @lid messages into phone_jid (dedup by ID), then
        removes the @lid entry.
        """
        mw = self.main_window
        if lid_jid not in mw.chats:
            return
        if phone_jid in mw.chats:
            dst_records = (
                mw.chats[phone_jid]
                .setdefault("messages", {})
                .setdefault("messages", {})
                .setdefault("records", [])
            )
            src_records = (
                mw.chats[lid_jid]
                .get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            dst_ids = {r.get("key", {}).get("id") for r in dst_records}
            for r in src_records:
                if r.get("key", {}).get("id") not in dst_ids:
                    dst_records.append(r)
        else:
            lid_chat = mw.chats.pop(lid_jid)
            lid_chat["remoteJid"] = phone_jid
            mw.chats[phone_jid] = lid_chat
        mw.chats.pop(lid_jid, None)

    def _load_local_lid_cache(self):
        """Load _lid_to_phone / _phone_to_lid / unresolvable sets from disk."""
        mw = self.main_window
        messages_file = data_path("messages.dat")
        try:
            if os.path.exists(messages_file):
                with open(messages_file, "rb") as f:
                    encrypted_data = f.read()
                    if encrypted_data:
                        decrypted_data = decrypt_json(encrypted_data, mw.key)
                        mw._lid_to_phone = decrypted_data.get("lid_to_phone", {})
                        mw._phone_to_lid = {v: k for k, v in mw._lid_to_phone.items()}
                        mw._unresolvable_lids = set(decrypted_data.get("unresolvable_lids", []))
                        mw._unresolvable_names = set(decrypted_data.get("unresolvable_names", []))
                        mw._status_updates = decrypted_data.get("status_updates", {})
                        logging.info(
                            f"[LID Cache] Loaded {len(mw._lid_to_phone)} JID mappings, "
                            f"{len(mw._unresolvable_lids)} LIDs, "
                            f"{len(mw._unresolvable_names)} names, "
                            f"and status updates for {len(mw._status_updates)} participants."
                        )
                        return
        except Exception as e:
            logging.error(f"[LID Cache] Error loading JID mappings from cache: {e}")
        mw._lid_to_phone = {}
        mw._phone_to_lid = {}
        mw._unresolvable_lids = set()
        mw._unresolvable_names = set()

    def _build_lid_to_phone_cache(self):
        """
        Build self._lid_to_phone: a dict mapping @lid JIDs to @s.whatsapp.net
        JIDs by scanning remoteJidAlt fields across all loaded chat messages.

        WPPConnect v2 normalises the key before emitting the WebSocket event:
          OLD format: remoteJid=@lid,          remoteJidAlt=@s.whatsapp.net
          NEW format: remoteJid=@s.whatsapp.net, remoteJidAlt=@lid  (after swap)
        Both formats are handled here so the cache is populated regardless of
        which version of the API produced the stored messages.
        """
        mw = self.main_window
        cache = getattr(mw, "_lid_to_phone", {}).copy()
        for chat in mw.chats.values():
            for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
                key    = msg.get("key", {})
                remote = key.get("remoteJid", "")
                alt    = key.get("remoteJidAlt", "")

                if alt and alt.endswith("@c.us"):
                    alt = alt[:-5] + "@s.whatsapp.net"
                if remote and remote.endswith("@c.us"):
                    remote = remote[:-5] + "@s.whatsapp.net"

                if alt and alt.endswith("@s.whatsapp.net"):
                    if remote.endswith("@lid"):
                        cache[remote] = alt
                    participant = key.get("participant", "")
                    if participant.endswith("@lid"):
                        cache[participant] = alt

                elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                    cache[alt] = remote

        mw._lid_to_phone  = cache
        mw._phone_to_lid  = {v: k for k, v in cache.items()}
        if not hasattr(mw, "_presence_cache"):
            mw._presence_cache = {}
        if not hasattr(mw, "_composing_chats"):
            mw._composing_chats = {}
        if not hasattr(mw, "_presence_timers"):
            mw._presence_timers = {}
        if not hasattr(mw, "_presence_pushname_map"):
            mw._presence_pushname_map = dict(
                mw.settings.get("presence_pushname_map", {})
            )

    def _extract_lid_mapping(self, msg):
        """Extract JID mapping from a message object and update cache & persist if new."""
        mw = self.main_window
        if not isinstance(msg, dict):
            return
        key = msg.get("key")
        if not isinstance(key, dict):
            return
        remote = key.get("remoteJid", "")
        alt = key.get("remoteJidAlt", "")
        participant = key.get("participant", "")

        if self._is_self_jid(remote) or self._is_self_jid(alt) or self._is_self_jid(participant):
            if alt and (self._is_self_jid(remote) != self._is_self_jid(alt)):
                alt = ""
            if participant and (self._is_self_jid(remote) != self._is_self_jid(participant)):
                participant = ""

        updated = False
        if not hasattr(mw, "_lid_to_phone"):
            mw._lid_to_phone = {}
        if not hasattr(mw, "_phone_to_lid"):
            mw._phone_to_lid = {}

        if alt and alt.endswith("@s.whatsapp.net"):
            if remote.endswith("@lid") and mw._lid_to_phone.get(remote) != alt:
                mw._lid_to_phone[remote] = alt
                mw._phone_to_lid[alt] = remote
                updated = True
                logging.info(f"[LID Mapping] Extracted mapping from message key: {remote} <-> {alt}")
        elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
            if mw._lid_to_phone.get(alt) != remote:
                mw._lid_to_phone[alt] = remote
                mw._phone_to_lid[remote] = alt
                updated = True
                logging.info(f"[LID Mapping] Extracted mapping from message key (alt): {alt} <-> {remote}")

        if not key.get("fromMe", False):
            if remote.endswith("@lid") and participant.endswith("@s.whatsapp.net"):
                if mw._lid_to_phone.get(remote) != participant:
                    mw._lid_to_phone[remote] = participant
                    mw._phone_to_lid[participant] = remote
                    updated = True
                    logging.info(f"[LID Mapping] Extracted mapping from 1:1 chat key: {remote} <-> {participant}")
            elif remote.endswith("@s.whatsapp.net") and participant.endswith("@lid"):
                if mw._lid_to_phone.get(participant) != remote:
                    mw._lid_to_phone[participant] = remote
                    mw._phone_to_lid[remote] = participant
                    updated = True
                    logging.info(f"[LID Mapping] Extracted mapping from 1:1 chat key (reversed): {participant} <-> {remote}")

        if updated:
            for lid, phone in list(mw._lid_to_phone.items()):
                if phone in mw.contacts and mw.contacts[phone]:
                    if lid not in mw.contacts or mw.contacts[lid].get("name") in (None, "", "Contato sem nome"):
                        mw.contacts[lid] = mw.contacts[phone].copy()
                        mw.contacts[lid]["id"] = lid
                        mw.contacts[lid]["remoteJid"] = lid

            mw.save_data(mw.chats, mw.contacts)
            wx.CallAfter(mw._schedule_set_chats)

        msg_obj = msg.get("message") or {}
        ext = msg_obj.get("extendedTextMessage") or {}
        mentioned = (
            (msg.get("contextInfo") or {}).get("mentionedJid")
            or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
            or ext.get("contextInfo", {}).get("mentionedJid")
            or []
        )
        if isinstance(mentioned, list):
            lids_to_resolve = []
            phone_jids_to_resolve = []
            for jid in mentioned:
                if not isinstance(jid, str):
                    continue
                if jid.endswith("@lid"):
                    if jid not in getattr(mw, "_lid_to_phone", {}):
                        lids_to_resolve.append(jid)
                elif jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us"):
                    normalized = self._normalize_jid(jid)
                    contact = mw.contacts.get(normalized)
                    name = ""
                    if contact:
                        name = (contact.get("name") or contact.get("pushName") or "").strip()
                    if not name or name == "Contato sem nome" or is_phone_like(name):
                        phone_jids_to_resolve.append(jid)

            if lids_to_resolve:
                logging.info(f"[LID Mapping] Found unresolved mentioned LIDs in message: {lids_to_resolve}")
                def resolve_in_bg():
                    self.resolve_lid_jids_via_api(lids_to_resolve)
                threading.Thread(target=resolve_in_bg, daemon=True).start()

            if phone_jids_to_resolve:
                logging.info(f"[Contact Resolution] Found unresolved mentioned phone JIDs in message: {phone_jids_to_resolve}")
                def resolve_phones_in_bg():
                    updated = False
                    for p_jid in phone_jids_to_resolve:
                        try:
                            res = mw.get_contact_profile(p_jid)
                            if res:
                                res_data = res.get("response", {})
                                if isinstance(res_data, dict):
                                    name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                                    if name and name != "Contato sem nome" and not is_phone_like(name):
                                        normalized = self._normalize_jid(p_jid)
                                        if normalized not in mw.contacts:
                                            mw.contacts[normalized] = {}
                                        mw.contacts[normalized]["name"] = name
                                        mw.contacts[normalized]["pushName"] = name

                                        if not hasattr(mw, "_presence_pushname_map"):
                                            mw._presence_pushname_map = {}
                                        mw._presence_pushname_map[normalized] = name
                                        updated = True
                        except Exception as e:
                            logging.error(f"[Contact Resolution] Error resolving {p_jid}: {e}")
                    if updated:
                        mw.save_data(mw.chats, mw.contacts)
                        wx.CallAfter(mw._schedule_set_chats)
                        if hasattr(mw, "conversations_panel"):
                            wx.CallAfter(mw.conversations_panel.refresh_active_conversation_messages)
                threading.Thread(target=resolve_phones_in_bg, daemon=True).start()

    def scan_all_cached_messages_for_mentions(self):
        """Scan all cached messages in self.chats, find all unresolved LIDs/phones, and resolve them."""
        mw = self.main_window

        def _scan():
            time.sleep(3)
            logging.info("[Mentions Scan] Starting scan of all cached messages...")

            lids_to_resolve = set()
            phones_to_resolve = set()

            chats_snapshot = list(mw.chats.values())
            for chat in chats_snapshot:
                records = chat.get("messages", {}).get("messages", {}).get("records", [])
                for msg in list(records):
                    if not isinstance(msg, dict):
                        continue
                    key = msg.get("key") or {}
                    remote = key.get("remoteJid", "")
                    alt = key.get("remoteJidAlt", "")
                    participant = key.get("participant", "")

                    if alt and alt.endswith("@s.whatsapp.net"):
                        if remote.endswith("@lid") and mw._lid_to_phone.get(remote) != alt:
                            self.register_jid_mapping(remote, alt)
                    elif alt and alt.endswith("@lid") and remote.endswith("@s.whatsapp.net"):
                        if mw._lid_to_phone.get(alt) != remote:
                            self.register_jid_mapping(alt, remote)

                    msg_obj = msg.get("message") or {}
                    ext = msg_obj.get("extendedTextMessage") or {}
                    mentioned = (
                        (msg.get("contextInfo") or {}).get("mentionedJid")
                        or (msg_obj.get("contextInfo") or {}).get("mentionedJid")
                        or ext.get("contextInfo", {}).get("mentionedJid")
                        or []
                    )
                    if isinstance(mentioned, list):
                        for jid in mentioned:
                            if not isinstance(jid, str):
                                continue
                            if jid.endswith("@lid"):
                                if jid not in getattr(mw, "_lid_to_phone", {}):
                                    lids_to_resolve.add(jid)
                            elif jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us"):
                                normalized = self._normalize_jid(jid)
                                contact = mw.contacts.get(normalized)
                                name = ""
                                if contact:
                                    name = (contact.get("name") or contact.get("pushName") or "").strip()
                                if not name or name == "Contato sem nome" or is_phone_like(name):
                                    phones_to_resolve.add(jid)

            if lids_to_resolve:
                logging.info(f"[Mentions Scan] Found {len(lids_to_resolve)} unresolved mentioned LIDs.")
                self.resolve_lid_jids_via_api(list(lids_to_resolve))

            if phones_to_resolve:
                logging.info(f"[Mentions Scan] Found {len(phones_to_resolve)} unresolved mentioned phone JIDs.")
                updated = False
                for p_jid in list(phones_to_resolve):
                    try:
                        res = mw.get_contact_profile(p_jid)
                        if res:
                            res_data = res.get("response", {})
                            if isinstance(res_data, dict):
                                name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                                if name and name != "Contato sem nome" and not is_phone_like(name):
                                    normalized = self._normalize_jid(p_jid)
                                    if normalized not in mw.contacts:
                                        mw.contacts[normalized] = {}
                                    mw.contacts[normalized]["name"] = name
                                    mw.contacts[normalized]["pushName"] = name
                                    if not hasattr(mw, "_presence_pushname_map"):
                                        mw._presence_pushname_map = {}
                                    mw._presence_pushname_map[normalized] = name
                                    updated = True
                        time.sleep(0.1)
                    except Exception as e:
                        logging.error(f"[Mentions Scan] Error resolving phone {p_jid}: {e}")
                if updated:
                    mw.save_data(mw.chats, mw.contacts)
                    wx.CallAfter(mw._schedule_set_chats)
                    if hasattr(mw, "conversations_panel"):
                        wx.CallAfter(mw.conversations_panel.refresh_active_conversation_messages)

            logging.info("[Mentions Scan] Scan and resolution of cached messages completed.")

        threading.Thread(target=_scan, daemon=True).start()

    def _find_alt_jid_from_messages(self, chat):
        """Find the canonical @s.whatsapp.net phone JID for a chat by scanning its
        message keys.  Handles both WPPConnect v2 key formats and normalises
        any @c.us JIDs encountered to @s.whatsapp.net on the fly:

          OLD: remoteJid=@lid,   remoteJidAlt=@s.whatsapp.net|@c.us → return alt (normalised)
          NEW: remoteJid=phone,  remoteJidAlt=@lid                  → return remoteJid
        Returns the phone JID (@s.whatsapp.net) string, or None if not found.
        """
        def _norm(j: str) -> str:
            if not j:
                return j
            if j.endswith("@c.us"):
                j = j[:-5] + "@s.whatsapp.net"
            if ":" in j:
                parts = j.split("@")
                if len(parts) == 2:
                    j = parts[0].split(":")[0] + "@" + parts[1]
            return j

        for msg in chat.get("messages", {}).get("messages", {}).get("records", []):
            key    = msg.get("key", {})
            remote = _norm(key.get("remoteJid", ""))
            alt    = _norm(key.get("remoteJidAlt", ""))
            if alt and alt.endswith("@s.whatsapp.net"):
                return alt
            if remote and remote.endswith("@s.whatsapp.net") and alt and alt.endswith("@lid"):
                return remote
        return None

    def resolve_self_lid(self):
        """Query WPPConnect API for own PN-LID mapping so self-mentions resolve correctly."""
        mw = self.main_window
        my_jid = getattr(mw, "my_jid", "")
        if not my_jid:
            return

        my_lid = getattr(mw, "my_lid", "")
        if my_lid and my_lid in getattr(mw, "_lid_to_phone", {}):
            return

        def _resolve():
            try:
                url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/contact/pn-lid/{my_jid}"
                headers = mw._api_headers()
                logging.info(f"[Self LID Resolution] Querying pn-lid mapping for own JID {my_jid}...")
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code in (200, 201):
                    res = response.json() or {}
                    logging.info(f"[Self LID Resolution] Response: {res}")
                    lid_obj = res.get("lid") or {}
                    lid_jid = None
                    if isinstance(lid_obj, dict):
                        lid_jid = lid_obj.get("_serialized") or lid_obj.get("id")
                    elif isinstance(lid_obj, str):
                        lid_jid = lid_obj
                    if not lid_jid:
                        lid_jid = res.get("lidJid")

                    phone_obj = res.get("phone") or res.get("phoneJid") or res.get("id") or {}
                    phone_jid = None
                    if isinstance(phone_obj, dict):
                        phone_jid = phone_obj.get("_serialized") or phone_obj.get("id")
                    elif isinstance(phone_obj, str):
                        phone_jid = phone_obj

                    if lid_jid and phone_jid:
                        normalized_phone = self._normalize_jid(phone_jid)
                        normalized_lid = self._normalize_jid(lid_jid)
                        mw.my_jid = normalized_phone
                        mw.my_lid = normalized_lid

                        if hasattr(mw, "_lid_to_phone"):
                            old_phone = mw._lid_to_phone.get(normalized_lid)
                            if old_phone and old_phone != normalized_phone:
                                mw._lid_to_phone.pop(normalized_lid, None)
                                mw._phone_to_lid.pop(old_phone, None)
                                logging.warning(f"[Self LID Resolution] Cleaned corrupt mapping: {normalized_lid} was mapped to {old_phone}")

                            old_lid = mw._phone_to_lid.get(normalized_phone)
                            if old_lid and old_lid != normalized_lid:
                                mw._phone_to_lid.pop(old_lid, None)
                                mw._lid_to_phone.pop(old_lid, None)
                                logging.warning(f"[Self LID Resolution] Cleaned corrupt mapping: {normalized_phone} was mapped to {old_lid}")

                        self.register_jid_mapping(normalized_lid, normalized_phone)
                        logging.info(f"[Self LID Resolution] Successfully resolved and registered own JID mapping: {normalized_lid} <-> {normalized_phone}")
            except Exception as e:
                logging.error(f"[Self LID Resolution] Error resolving self LID: {e}")

        threading.Thread(target=_resolve, daemon=True).start()

    def register_jid_mapping(self, lid_jid, phone_jid):
        """Register a bidirectional mapping between @lid and @s.whatsapp.net, and persist it."""
        mw = self.main_window
        if not lid_jid or not phone_jid:
            return
        if not lid_jid.endswith("@lid") or not phone_jid.endswith("@s.whatsapp.net"):
            return

        if self._is_self_jid(lid_jid) or self._is_self_jid(phone_jid):
            if not (self._is_self_jid(lid_jid) and self._is_self_jid(phone_jid)):
                logging.warning(f"[LID Mapping] Blocked corrupt self-mapping attempt: {lid_jid} <-> {phone_jid}")
                return

        if not hasattr(mw, "_lid_to_phone"):
            mw._lid_to_phone = {}
        if not hasattr(mw, "_phone_to_lid"):
            mw._phone_to_lid = {}

        current_phone = mw._lid_to_phone.get(lid_jid)
        if current_phone != phone_jid:
            mw._lid_to_phone[lid_jid] = phone_jid
            mw._phone_to_lid[phone_jid] = lid_jid
            logging.info(f"[LID Mapping] Registered JID mapping: {lid_jid} <-> {phone_jid}")

            if hasattr(mw, "_unresolvable_lids") and lid_jid in mw._unresolvable_lids:
                mw._unresolvable_lids.discard(lid_jid)

            if phone_jid in mw.contacts and mw.contacts[phone_jid]:
                if lid_jid not in mw.contacts or mw.contacts[lid_jid].get("name") in (None, "", "Contato sem nome"):
                    mw.contacts[lid_jid] = mw.contacts[phone_jid].copy()
                    mw.contacts[lid_jid]["id"] = lid_jid
                    mw.contacts[lid_jid]["remoteJid"] = lid_jid

            mw.save_data(mw.chats, mw.contacts)
            wx.CallAfter(mw._schedule_set_chats)

    def resolve_lid_jids_via_api(self, jids):
        """Resolve a list of @lid JIDs to phone JIDs using WPPConnect contact endpoint."""
        mw = self.main_window
        if not jids:
            return

        for lid_jid in jids:
            if not lid_jid.endswith("@lid"):
                continue

            if not hasattr(mw, "_lid_resolution_lock"):
                mw._lid_resolution_lock = threading.Lock()
            if not hasattr(mw, "_unresolvable_lids"):
                mw._unresolvable_lids = set()
            if not hasattr(mw, "_resolving_lids"):
                mw._resolving_lids = set()

            if not hasattr(mw, "_unresolvable_names"):
                mw._unresolvable_names = set()

            query_pn = lid_jid not in getattr(mw, "_lid_to_phone", {}) and lid_jid not in mw._unresolvable_lids

            contact = mw.contacts.get(lid_jid, {})
            has_name = contact.get("name") or contact.get("pushName")
            query_name = not has_name and lid_jid not in mw._unresolvable_names

            if not query_pn and not query_name:
                continue

            with mw._lid_resolution_lock:
                if lid_jid in mw._resolving_lids:
                    continue
                mw._resolving_lids.add(lid_jid)

            try:
                canonical_jid = getattr(mw, "_lid_to_phone", {}).get(lid_jid)
                headers = mw._api_headers()

                if query_pn:
                    url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/contact/pn-lid/{lid_jid}"
                    logging.info(f"[LID Resolution] Querying WPPConnect pn-lid mapping for {lid_jid}...")
                    response = requests.get(url, headers=headers, timeout=10)
                    if response.status_code in (200, 201):
                        res = response.json() or {}
                        logging.info(f"[LID Resolution] pn-lid response for {lid_jid}: {res}")
                        res_data = res.get("response") if isinstance(res.get("response"), dict) else res
                        pn_obj = res_data.get("phoneNumber") or {}
                        pn_jid = None
                        if isinstance(pn_obj, dict):
                            pn_jid = pn_obj.get("_serialized") or pn_obj.get("id")
                        elif isinstance(pn_obj, str):
                            pn_jid = pn_obj
                        if not pn_jid:
                            pn_jid = res_data.get("pnJid")
                        if pn_jid:
                            canonical_jid = self._normalize_jid(pn_jid)
                            if canonical_jid and canonical_jid.endswith("@s.whatsapp.net"):
                                self.register_jid_mapping(lid_jid, canonical_jid)

                target_jid = canonical_jid if canonical_jid else lid_jid
                url_profile = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/contact/{target_jid}"
                logging.info(f"[LID Resolution] Querying profile details for {target_jid}...")
                resp_profile = requests.get(url_profile, headers=headers, timeout=10)
                if (query_name or (query_pn and canonical_jid)) and resp_profile.status_code in (200, 201):
                    res_prof = resp_profile.json() or {}
                    res_data = res_prof.get("response") if isinstance(res_prof.get("response"), dict) else res_prof
                    if not isinstance(res_data, dict):
                        res_data = {}

                    profile_pn_jid = None
                    id_obj = res_data.get("id") or {}
                    if isinstance(id_obj, dict):
                        ser_id = id_obj.get("_serialized") or ""
                        if ser_id.endswith(("@c.us", "@s.whatsapp.net")):
                            profile_pn_jid = ser_id
                    if not profile_pn_jid:
                        pn_obj = res_data.get("phoneNumber") or {}
                        if isinstance(pn_obj, dict):
                            profile_pn_jid = pn_obj.get("_serialized") or pn_obj.get("id")
                        elif isinstance(pn_obj, str):
                            profile_pn_jid = pn_obj
                    if not profile_pn_jid:
                        profile_pn_jid = res_data.get("pnJid")
                    if not profile_pn_jid:
                        profile_pn_jid = res_data.get("phone")

                    if profile_pn_jid:
                        profile_canonical = self._normalize_jid(profile_pn_jid)
                        if profile_canonical and profile_canonical.endswith("@s.whatsapp.net"):
                            self.register_jid_mapping(lid_jid, profile_canonical)
                            if not canonical_jid:
                                canonical_jid = profile_canonical
                    name = res_data.get("name") or res_data.get("pushname") or res_data.get("pushName") or res_data.get("displayName")
                    if name and name != "Contato sem nome" and not is_phone_like(name):
                        if lid_jid not in mw.contacts:
                            mw.contacts[lid_jid] = {}
                        mw.contacts[lid_jid]["name"] = name
                        mw.contacts[lid_jid]["pushName"] = name

                        if not hasattr(mw, "_presence_pushname_map"):
                            mw._presence_pushname_map = {}
                        mw._presence_pushname_map[lid_jid] = name

                        if canonical_jid:
                            if canonical_jid not in mw.contacts:
                                mw.contacts[canonical_jid] = {}
                            mw.contacts[canonical_jid]["name"] = name
                            mw.contacts[canonical_jid]["pushName"] = name
                            mw._presence_pushname_map[canonical_jid] = name
                    else:
                        logging.info(f"[LID Resolution] Profile name not resolved/accepted for {target_jid}. Original name field: {name}. Response data: {res_data}")
                else:
                    logging.error(f"[LID Resolution] fetchProfile API error {resp_profile.status_code} for {target_jid}: {resp_profile.text}")
            except Exception as e:
                logging.error(f"[LID Resolution] Exception during resolution of {lid_jid}: {e}")
            finally:
                with mw._lid_resolution_lock:
                    mw._resolving_lids.discard(lid_jid)
                    if query_pn and lid_jid not in getattr(mw, "_lid_to_phone", {}):
                        mw._unresolvable_lids.add(lid_jid)
                    if query_name:
                        contact_now = mw.contacts.get(lid_jid, {})
                        has_name_now = contact_now.get("name") or contact_now.get("pushName")
                        if not has_name_now:
                            mw._unresolvable_names.add(lid_jid)
                time.sleep(0.1)

        mw.save_data(mw.chats, mw.contacts)
        wx.CallAfter(mw._schedule_set_chats)
        if hasattr(mw, "conversations_panel"):
            wx.CallAfter(mw.conversations_panel.refresh_active_conversation_messages)

    def start_background_lid_resolution(self):
        mw = self.main_window

        def _resolve_lids():
            logging.info("[start_background_lid_resolution] Waiting for WhatsApp connection...")
            waited = 0
            while waited < 30:
                if getattr(mw, "_wa_connected", False):
                    break
                time.sleep(1)
                waited += 1

            if not getattr(mw, "_wa_connected", False):
                logging.info("[start_background_lid_resolution] Aborting: WhatsApp not connected after 30 seconds.")
                return

            raw_lids = set()
            for jid in list(mw.chats.keys()):
                if jid.endswith("@lid"):
                    raw_lids.add(jid)
            for jid in list(mw.contacts.keys()):
                if jid.endswith("@lid"):
                    raw_lids.add(jid)

            active_chat_lids = set()
            for jid in list(mw.chats.keys()):
                if jid.endswith("@lid"):
                    active_chat_lids.add(jid)

            lids_to_resolve = []
            lid_to_phone = getattr(mw, "_lid_to_phone", {})
            unresolvable = getattr(mw, "_unresolvable_lids", set())
            unresolvable_names = getattr(mw, "_unresolvable_names", set())

            def _needs_resolve(jid):
                if jid not in lid_to_phone and jid not in unresolvable:
                    return True
                contact = mw.contacts.get(jid, {})
                has_name = contact.get("name") or contact.get("pushName")
                if not has_name and jid not in unresolvable_names:
                    return True
                return False

            for jid in sorted(active_chat_lids):
                if _needs_resolve(jid):
                    lids_to_resolve.append(jid)

            other_lids = raw_lids - active_chat_lids
            for jid in sorted(other_lids):
                if _needs_resolve(jid):
                    lids_to_resolve.append(jid)

            if not lids_to_resolve:
                logging.info("[start_background_lid_resolution] No @lid JIDs to resolve.")
                return

            logging.info(f"[start_background_lid_resolution] START: Found {len(lids_to_resolve)} @lid JIDs to resolve in background.")
            batch_size = 25
            for i in range(0, len(lids_to_resolve), batch_size):
                if not getattr(mw, "_wa_connected", False):
                    logging.info("[start_background_lid_resolution] Aborting resolution loop (WhatsApp disconnected)")
                    break
                batch = lids_to_resolve[i:i+batch_size]
                try:
                    logging.info(f"[start_background_lid_resolution] Querying batch of {len(batch)} JIDs...")
                    self.resolve_lid_jids_via_api(batch)
                    time.sleep(1.0)
                except Exception as e:
                    logging.error(f"[start_background_lid_resolution] Error JID batch: {e}")
            logging.info("[start_background_lid_resolution] COMPLETED background JID resolution loop.")

        threading.Thread(target=_resolve_lids, daemon=True).start()
