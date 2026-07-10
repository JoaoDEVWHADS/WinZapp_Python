"""
WinZapp Message Send Service
----------------------------
Encapsulates all outgoing-message API calls (text, reaction, contact vCard),
JID resolution for sends, quoted-message serialization, and the callbacks
that the MessageQueue invokes on success/failure.

Extracted from MainWindow to reduce the god class.
"""

import os
import json
import base64
import shutil
import logging
import requests
import wx

from app_paths import data_path
from core.utils import encrypt


class MessageSendService:

    def __init__(self, main_window):
        self.mw = main_window

    # ── Quoted-message helpers ────────────────────────────────────────────────

    def _clean_quoted(self, quoted: dict) -> dict:
        """Return a minimal quoted dict the WPPConnect DTO accepts.

        Only ``key`` is sent.  The WPPConnect will fetch the full message
        content from its internal Baileys message store using
        ``getMessage(key, true)``.  This avoids serialising binary fields
        (``jpegThumbnail``, ``mediaKey``, ``fileEncSha256``, …) that arrive
        from Socket.IO as Python ``bytes`` objects and cannot be JSON-encoded.

        JIDs are normalised before sending:
          - @c.us  → @s.whatsapp.net  (legacy format)
          - @lid   → @s.whatsapp.net  when the reverse cache knows the mapping
        """
        if not quoted or not isinstance(quoted, dict):
            return None
        key_raw = quoted.get("key")
        if not key_raw or not isinstance(key_raw, dict):
            return None
        _ALLOWED = {"id", "remoteJid", "fromMe", "participant"}
        clean_key = {k: v for k, v in key_raw.items() if k in _ALLOWED}
        if not clean_key.get("id"):
            return None

        # Normalise JIDs so the API always receives @s.whatsapp.net format.
        lid_to_phone = getattr(self.mw, "_lid_to_phone", {})
        for field in ("remoteJid", "participant"):
            jid = clean_key.get(field, "")
            if not jid:
                continue
            jid = self.mw._normalize_jid(jid)          # @c.us → @s.whatsapp.net
            if jid.endswith("@lid"):
                phone = lid_to_phone.get(jid, "")
                if phone:
                    jid = phone
            clean_key[field] = jid

        return {"key": clean_key}

    def _serialize_quoted_id(self, quoted: dict) -> str:
        """Serialize a quoted message key into the format expected by WPPConnect.
        For groups, this correctly appends the participant's JID."""
        if not quoted:
            return None
        _cq = self._clean_quoted(quoted)
        if not _cq or not _cq.get("key", {}).get("id"):
            return None

        quoted_id = _cq.get("key", {}).get("id")

        # If the ID already has underscores, keep it but ensure standard domains are corrected
        if "_" in quoted_id:
            if "@s.whatsapp.net" in quoted_id:
                quoted_id = quoted_id.replace("@s.whatsapp.net", "@c.us")
            return quoted_id

        from_me = _cq.get("key", {}).get("fromMe", False)
        from_me_str = "true" if from_me else "false"

        # Determine the correct remoteJid for WPPConnect
        raw_key = quoted.get("key", {}) if isinstance(quoted, dict) else {}
        raw_remote_jid = raw_key.get("remoteJid", "")

        if raw_remote_jid:
            phone_to_lid = getattr(self.mw, "_phone_to_lid", {})
            if raw_remote_jid.endswith("@lid"):
                quoted_remote_jid = raw_remote_jid
            else:
                norm_remote_jid = self.mw._normalize_jid(raw_remote_jid)
                lid_jid = phone_to_lid.get(norm_remote_jid, "")
                if lid_jid:
                    quoted_remote_jid = lid_jid
                elif norm_remote_jid.endswith("@s.whatsapp.net"):
                    quoted_remote_jid = norm_remote_jid.replace("@s.whatsapp.net", "@c.us")
                else:
                    quoted_remote_jid = norm_remote_jid
        else:
            quoted_remote_jid = _cq.get("key", {}).get("remoteJid", "")
            if quoted_remote_jid.endswith("@s.whatsapp.net"):
                quoted_remote_jid = quoted_remote_jid.replace("@s.whatsapp.net", "@c.us")

        serialized_id = f"{from_me_str}_{quoted_remote_jid}_{quoted_id}"

        # For group chats, WPPConnect requires the participant JID at the end
        if quoted_remote_jid.endswith("@g.us"):
            raw_participant = raw_key.get("participant", "") or _cq.get("key", {}).get("participant", "")
            if not raw_participant and from_me:
                raw_participant = getattr(self.mw, "my_jid", "")

            if raw_participant:
                phone_to_lid = getattr(self.mw, "_phone_to_lid", {})
                if raw_participant.endswith("@lid"):
                    participant = raw_participant
                else:
                    norm_participant = self.mw._normalize_jid(raw_participant)
                    lid_jid = phone_to_lid.get(norm_participant, "")
                    if lid_jid:
                        participant = lid_jid
                    elif norm_participant.endswith("@s.whatsapp.net"):
                        participant = norm_participant.replace("@s.whatsapp.net", "@c.us")
                    else:
                        participant = norm_participant
                serialized_id = f"{serialized_id}_{participant}"

        return serialized_id

    # ── Mention / JID resolution helpers ──────────────────────────────────────

    def _canonical_mention_jids(self, mentioned_jids):
        """Return mention JIDs in the phone-number format Baileys/WPPConnect can tag."""
        out = []
        seen = set()
        lid_to_phone = getattr(self.mw, "_lid_to_phone", {})
        for raw_jid in mentioned_jids or []:
            jid = self.mw._normalize_jid(str(raw_jid or ""))
            if not jid:
                continue
            if jid.endswith("@lid"):
                jid = lid_to_phone.get(jid, jid)
            if jid not in seen:
                seen.add(jid)
                out.append(jid)
        return out

    def _resolve_jid_for_send(self, jid: str) -> str:
        """
        Translate a @lid JID to its @s.whatsapp.net equivalent before sending.
        Returns the original jid unchanged for @g.us / @s.whatsapp.net / @c.us.
        """
        if not jid.endswith("@lid"):
            return jid
        phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid, "")
        if phone_jid:
            return phone_jid
        # Not in cache — attempt a live resolution (blocks briefly, happens at
        # most once per unknown LID since resolve_lid_jids_via_api stores the result).
        logging.info("[_resolve_jid_for_send] @lid %s not in cache — resolving via API", jid)
        try:
            self.mw.resolve_lid_jids_via_api([jid])
        except Exception as exc:
            logging.warning("[_resolve_jid_for_send] resolve_lid_jids_via_api failed for %s: %s", jid, exc)
        phone_jid = getattr(self.mw, "_lid_to_phone", {}).get(jid, "")
        if phone_jid:
            logging.info("[_resolve_jid_for_send] Resolved %s → %s", jid, phone_jid)
            return phone_jid
        logging.warning("[_resolve_jid_for_send] Could not resolve @lid %s — sending as-is (will likely fail)", jid)
        return jid

    # ── Send message types ────────────────────────────────────────────────────

    def send_text_message(self, remote_jid, text, quoted=None, mentioned_jids=None):
        """Send a plain-text message via the WPPConnect Server API."""
        # Always send using the phone JID (@s.whatsapp.net / @g.us).
        # WPPConnect's contactToArray normalises to @c.us internally; passing
        # @lid JIDs breaks the server with HTTP 500 (confirmed in production logs).
        remote_jid = self._resolve_jid_for_send(remote_jid)

        headers = self.mw._api_headers()

        quoted_id = None

        if mentioned_jids:
            url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-mentioned"
            phone_net = remote_jid
            if phone_net.endswith("@s.whatsapp.net"):
                phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")

            mentioned = self._canonical_mention_jids(mentioned_jids)
            mentioned_clean = [m.replace("@s.whatsapp.net", "@c.us") if m.endswith("@s.whatsapp.net") else m for m in mentioned]

            payload = {
                "phone": [phone_net],
                "message": text,
                "mentioned": mentioned_clean,
                "options": {
                    "linkPreview": False
                }
            }
        else:
            quoted_id = self._serialize_quoted_id(quoted) if quoted else None
            if quoted_id:
                url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-reply"
                phone_net = remote_jid
                if phone_net.endswith("@s.whatsapp.net"):
                    phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
                payload = {
                    "phone": [phone_net],
                    "message": text,
                    "messageId": quoted_id,
                    "options": {
                        "linkPreview": False
                    }
                }
                logging.debug("[send_text_message] sending quoted reply via send-reply to %s, quoted key.id=%s", phone_net, quoted_id)
            else:
                phone_net = remote_jid
                if phone_net.endswith("@s.whatsapp.net"):
                    phone_net = phone_net.replace("@s.whatsapp.net", "@c.us")
                url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-message"
                payload = {
                    "phone": [phone_net],
                    "message": text,
                    "isGroup": phone_net.endswith("@g.us"),
                    "options": {
                        "linkPreview": False
                    }
                }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                # Fallback: if we attempted to send a quoted message and failed (e.g. message not found in server memory),
                # try sending it as a plain message instead of leaving it pending forever.
                if quoted_id:
                    logging.warning("[send_text_message] Quoted send failed (HTTP %s). Retrying without quote...", response.status_code)
                    url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-message"
                    fb_phone = remote_jid
                    if fb_phone.endswith("@s.whatsapp.net"):
                        fb_phone = fb_phone.replace("@s.whatsapp.net", "@c.us")
                    payload = {
                        "phone": [fb_phone],
                        "message": text,
                        "isGroup": fb_phone.endswith("@g.us"),
                        "options": {
                            "linkPreview": False
                        }
                    }
                    response = requests.post(url, json=payload, headers=headers, timeout=15)

                if response.status_code not in (200, 201):
                    err = f"HTTP {response.status_code}: {response.text[:300]}"
                    logging.error("[send_text_message] %s for %s", err, remote_jid)
                    self.mw._check_wa_connection_closed(response)
                    return {"ok": False, "error": err, "retry": False}
            self.mw._wa_connected = True
            try:
                body = response.json()
                # WPPConnect retorna a resposta dentro de 'response'
                resp = body.get("response", {})
                if isinstance(resp, list) and len(resp) > 0:
                    resp = resp[0]
                if isinstance(resp, dict):
                    msg_id = resp.get("id")
                    if isinstance(msg_id, dict):
                        msg_id = msg_id.get("_serialized", "")
                    parts = msg_id.split("_") if msg_id else []
                    clean_id = parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)
                    return clean_id or True
                return True
            except Exception:
                return True
        except Exception as exc:
            err = str(exc)[:200]
            logging.error("[send_text_message] exception for %s: %s", remote_jid, err)
            return {"ok": False, "error": err, "retry": True}

    def send_reaction(self, remote_jid: str, msg_key: dict, emoji: str) -> bool:
        """Send a reaction to a message via the WPPConnect Server API."""
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/react-message"
        headers = self.mw._api_headers()
        payload = {
            "msgId": msg_key.get("id", ""),
            "reaction": emoji
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code not in (200, 201):
                print(f"[send_reaction] HTTP {response.status_code}: {response.text[:500]}")
                return False
            return True
        except Exception as exc:
            print(f"[send_reaction] exception: {exc}")
            return False

    # ── Callbacks invoked by MessageQueue ─────────────────────────────────────

    def _on_message_sent(self, local_id: str, audio_path: str = None, real_id: str = None):
        """
        Called on the main thread after a queued message is successfully sent.
        Updates the UI status label and cleans up any temporary audio file.
        real_id is the WhatsApp message ID returned by the API; it replaces the
        local UUID in the virtual message so playback can find the message in the DB.
        """
        # Save or copy the local audio copy under the real ID *before* calling _mark_message_sent
        # to prevent background media sync from downloading a file we already have.
        if audio_path and os.path.isfile(audio_path):
            if real_id and isinstance(real_id, str):
                try:
                    voice_messages_dir = data_path("voice_messages")
                    os.makedirs(voice_messages_dir, exist_ok=True)
                    local_audio_path = os.path.join(voice_messages_dir, f"{local_id}.msv")
                    real_audio_path = os.path.join(voice_messages_dir, f"{real_id}.msv")

                    if os.path.isfile(local_audio_path):
                        shutil.copy2(local_audio_path, real_audio_path)
                    else:
                        with open(audio_path, "rb") as f:
                            wav_data = f.read()
                        with open(real_audio_path, "wb") as f_out:
                            f_out.write(encrypt(wav_data, self.mw.key))
                except Exception as e:
                    print(f"[_on_message_sent] error saving sent audio locally: {e}")
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        if hasattr(self.mw, "conversations_panel"):
            self.mw.conversations_panel._mark_message_sent(local_id, real_id=real_id)

    def _on_message_failed(self, local_id: str, error: str = "", show_dialog: bool = False):
        """
        Called on the main thread after a queued message exhausts all retries.
        Marks the virtual message as failed in the UI and, for media attachments,
        shows an error dialog so the user knows the file was not delivered.
        """
        if hasattr(self.mw, "conversations_panel"):
            self.mw.conversations_panel._mark_message_failed(local_id)
        if show_dialog:
            self.mw.error_sound.play()
            detail = error[:300] if error else self.mw.i18n.t("error").format(app_name=self.mw.app_name)
            wx.MessageBox(
                self.mw.i18n.t("media_send_failed").format(error=detail),
                self.mw.i18n.t("error").format(app_name=self.mw.app_name),
                wx.OK | wx.ICON_ERROR,
            )

    # ── Contact attachment ────────────────────────────────────────────────────

    def send_contact_attachment(self, remote_jid: str, contact_info: dict,
                                quoted: dict = None) -> bool:
        """Send a contact card as an attachment."""
        remote_jid = self._resolve_jid_for_send(remote_jid)
        lid_jid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
        if lid_jid:
            remote_jid = lid_jid
        name = contact_info.get("pushName") or ""
        jid = contact_info.get("remoteJid", "")
        phone_raw = jid.split("@")[0] if "@" in jid else jid
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/contact-vcard"
        payload = {
            "phone":       [remote_jid],
            "isGroup":     remote_jid.endswith("@g.us"),
            "contactsId":  [f"{phone_raw}@c.us"],
        }
        if quoted:
            quoted_id = self._serialize_quoted_id(quoted)
            if quoted_id:
                payload["quotedMessageId"] = quoted_id
        headers = self.mw._api_headers()
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                try:
                    resp = r.json().get("response", {})
                    if isinstance(resp, list) and resp:
                        resp = resp[0]
                    return (resp or {}).get("id") or True
                except Exception:
                    return True
            return None
        except Exception:
            return None
