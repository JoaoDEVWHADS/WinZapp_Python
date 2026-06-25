import base64
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import wx

from app_paths import data_path
from core.utils import encrypt


class MediaExpiredError(Exception):
    """CDN URL for this media has expired (HTTP 403 or 410 from WhatsApp)."""


class MediaSyncService:
    """Downloads and encrypts media (images, audio, video, documents, stickers)
    from WPPConnect so it can be stored and displayed offline."""

    # WhatsApp CDN URLs (mmg.whatsapp.net) expire after ~90 days.  Attempting
    # to download older media causes the WPPConnect to enter a 5-second retry
    # loop for every expired URL, which starves the API thread pool and eventually
    # breaks sends.  Never request media older than this threshold.
    _MEDIA_MAX_AGE_SECONDS = 14 * 24 * 3600  # 14 days — WhatsApp CDN typical TTL
    _MEDIA_SYNC_WORKERS    = 6               # parallel workers during bulk sync
    _MEDIA_SYNC_TIMEOUT    = 20              # seconds per request during bulk sync

    def __init__(self, main_window):
        self.mw = main_window

    # ------------------------------------------------------------------
    # Bulk / background sync
    # ------------------------------------------------------------------

    def sync_media_for_all_chats(self):
        _MEDIA_TYPES = {"audioMessage", "documentMessage", "imageMessage",
                        "stickerMessage", "videoMessage"}
        tasks = [
            msg
            for chat in self.mw.chats.values()
            for msg in chat.get("messages", {}).get("messages", {}).get("records", [])
            if msg.get("messageType") in _MEDIA_TYPES
        ]
        if not tasks:
            return

        timeout = self._MEDIA_SYNC_TIMEOUT
        with ThreadPoolExecutor(max_workers=self._MEDIA_SYNC_WORKERS) as pool:
            futs = {pool.submit(self.sync_if_media, msg, timeout): msg for msg in tasks}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    pass

        self._save_media_failed_ids()

    def sync_chat_media(self, chat):
        records = chat.get("messages", {}).get("messages", {}).get("records", [])
        for message in records:
            try:
                self.sync_if_media(message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Per-message sync
    # ------------------------------------------------------------------

    def sync_if_media(self, msg, timeout=60):
        """Download media for a single message during the background sync phase."""
        message_type = msg.get("messageType", "")
        _MEDIA_TYPES = {"documentMessage", "imageMessage", "stickerMessage", "videoMessage"}
        if message_type not in _MEDIA_TYPES and message_type != "audioMessage":
            return

        ts = int(msg.get("messageTimestamp", 0) or 0)
        if ts and (time.time() - ts) > self._MEDIA_MAX_AGE_SECONDS:
            return

        msg_id = msg.get("key", {}).get("id", "")

        if msg_id and msg_id in self.mw._media_failed_ids:
            return

        try:
            if message_type == "audioMessage":
                self.handle_audio_message(msg, timeout=timeout)
            else:
                conv = self.mw.conversations_panel
                def _prog(p, mid=msg_id):
                    wx.CallAfter(conv.update_message_download_progress, mid, p)
                self.handle_media_message(msg, progress_callback=_prog, timeout=timeout)
                if msg_id:
                    wx.CallAfter(conv.update_message_download_progress, msg_id, 1.0)
        except MediaExpiredError:
            if msg_id:
                self.mw._media_failed_ids.add(msg_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Media download & encryption
    # ------------------------------------------------------------------

    def handle_media_message(self, msg, progress_callback=None, timeout=60):
        """Download and encrypt a document/image/sticker/video to data/media/."""
        msg_id = msg.get("key", {}).get("id", "")
        if not msg_id:
            return
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
        media_path = data_path("media", f"{msg_id}.wzmedia")
        if os.path.isfile(media_path):
            return
        b64 = self.get_base64_from_media(msg, progress_callback=progress_callback,
                                         timeout=timeout)
        if not b64:
            return
        content = base64.b64decode(b64)
        encrypted = encrypt(content, self.mw.key)
        with open(media_path, "wb") as f:
            f.write(encrypted)

    def handle_audio_message(self, msg, timeout=60):
        voice_messages_dir = data_path("voice_messages")
        msg_id = msg.get('key', {}).get('id', '')
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
        audio_file_path = os.path.join(voice_messages_dir, f"{msg_id}.msv")
        if os.path.isfile(audio_file_path):
            return
        base64_audio = self.get_base64_from_media(msg, timeout=timeout)
        if not base64_audio:
            return
        audio_content = base64.b64decode(base64_audio)
        self.mw.save_audio_locally(msg, audio_content)

    def get_base64_from_media(self, media, progress_callback=None, timeout=60):
        """
        Fetch encrypted media from WPPConnect and return its base64 string.

        Raises MediaExpiredError when the WhatsApp CDN URL has expired (HTTP 403/410).
        When *progress_callback* is provided the request is streamed and the
        callback is called with a float in [0, 1] as each chunk arrives.
        """
        _key = media.get("key", {})
        msg_id = _key.get("id", "")
        if msg_id and "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]

        if msg_id:
            from_me = _key.get("fromMe", False)
            from_me_str = "true" if from_me else "false"
            remote_jid = _key.get("remoteJid", "")

            lid = getattr(self.mw, "_phone_to_lid", {}).get(remote_jid, "")
            if lid:
                remote_jid = lid
            elif remote_jid.endswith("@s.whatsapp.net"):
                remote_jid = remote_jid.replace("@s.whatsapp.net", "@c.us")

            msg_id = f"{from_me_str}_{remote_jid}_{msg_id}"

            if remote_jid.endswith("@g.us"):
                participant = _key.get("participant", "")
                if participant:
                    if participant.endswith("@s.whatsapp.net") or participant.endswith("@c.us"):
                        participant = participant.split("@")[0] + "@c.us"
                    msg_id = f"{msg_id}_{participant}"
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/get-media-by-message/{msg_id}"
        headers = self.mw._api_headers()

        if progress_callback is None:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code in (403, 410):
                raise MediaExpiredError(response.status_code)
            if response.status_code in (200, 201):
                return response.json().get("base64", "")
            return ""

        try:
            response = requests.get(url, headers=headers, stream=True, timeout=timeout)
            if response.status_code in (403, 410):
                raise MediaExpiredError(response.status_code)
            if response.status_code not in (200, 201):
                return ""
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunks: list = []
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress_callback(downloaded / total)
            body = b"".join(chunks).decode("utf-8", errors="replace")
            try:
                return json.loads(body).get("base64", "")
            except Exception:
                return base64.b64encode(b"".join(chunks)).decode("utf-8")
        except MediaExpiredError:
            raise
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Failed-media persistence
    # ------------------------------------------------------------------

    def _load_media_failed_ids(self) -> set:
        """Load the set of message IDs whose media CDN URL has previously expired."""
        try:
            with open(data_path("media_failed.json"), "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

    def _save_media_failed_ids(self):
        """Persist the failed-media set so expired IDs are skipped on future launches."""
        with self.mw._media_failed_lock:
            try:
                with open(data_path("media_failed.json"), "w", encoding="utf-8") as f:
                    json.dump(list(self.mw._media_failed_ids), f)
            except Exception:
                pass
