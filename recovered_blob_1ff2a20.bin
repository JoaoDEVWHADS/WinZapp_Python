import logging
import requests
import wx


class ContactService:

    def __init__(self, main_window):
        self.mw = main_window

    def block_contact(self, jid: str, action: str = "block"):
        endpoint = "block-contact" if action == "block" else "unblock-contact"
        url = (
            f"{self.mw.wpp_server}:{self.mw.wpp_port}"
            f"/api/{self.mw.token}/{endpoint}"
        )
        headers = self.mw._api_headers()
        try:
            requests.post(
                url, json={"phone": jid},
                headers=headers, timeout=10,
            )
        except Exception:
            pass

    def get_contact_profile(self, jid: str) -> dict:
        original_jid = jid
        if jid.endswith("@lid"):
            resolved = getattr(self.mw, "_lid_to_phone", {}).get(jid, "")
            if resolved:
                jid = resolved
            else:
                if jid not in getattr(self.mw, "_unresolvable_lids", set()):
                    self.mw.resolve_lid_jids_via_api([original_jid])
                    resolved = getattr(self.mw, "_lid_to_phone", {}).get(original_jid, "")
                    if resolved:
                        jid = resolved
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/contact/{jid}"
        headers = self.mw._api_headers()
        try:
            r = requests.get(url, headers=headers, timeout=10)
            logging.info(f"[get_contact_profile] Querying for {original_jid} (using JID: {jid}). Response status: {r.status_code}")
            if r.status_code in (200, 201):
                res = r.json() or {}
                logging.info(f"[get_contact_profile] API Response for {original_jid}: {res}")
                res_data = res.get("response", {})
                if not isinstance(res_data, dict):
                    res_data = {}

                if original_jid.endswith("@lid") and jid.endswith("@lid"):
                    canonical_jid = self.mw._normalize_jid(res_data.get("id", {}).get("_serialized") or res_data.get("id") or "")
                    if canonical_jid and canonical_jid.endswith("@s.whatsapp.net"):
                        logging.info(f"[get_contact_profile] SUCCESS: Mapped {original_jid} to {canonical_jid} via profile query")
                        if not hasattr(self.mw, "_lid_to_phone"):
                            self.mw._lid_to_phone = {}
                        if not hasattr(self.mw, "_phone_to_lid"):
                            self.mw._phone_to_lid = {}
                        self.mw._lid_to_phone[original_jid] = canonical_jid
                        self.mw._phone_to_lid[canonical_jid] = original_jid

                        wx.CallAfter(self.mw.chat_list_builder._schedule_set_chats)
                        self.mw.data_persistence.save_data(self.mw.chats, self.mw.contacts)
                return res
        except Exception as e:
            logging.exception(f"[get_contact_profile] Error querying for {original_jid}: {e}")
        return {}
