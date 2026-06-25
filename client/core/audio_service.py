import os
import glob as _glob
import shutil
import subprocess
import base64
import logging

import requests

from app_paths import resource_path, data_path
from core.utils import encrypt


class AudioService:
    """Audio encoding (ffmpeg WAV→OGG), sending PTT voice messages via the
    WPPConnect API, and saving incoming audio messages to disk."""

    def __init__(self, main_window):
        self.mw = main_window

    # ------------------------------------------------------------------
    # ffmpeg discovery
    # ------------------------------------------------------------------

    @staticmethod
    def find_api_ffmpeg() -> str | None:
        """Locate ffmpeg binary: bundled npm package first, then system PATH."""
        installer_root = resource_path("api", "node_modules", "@ffmpeg-installer")
        hits = _glob.glob(os.path.join(installer_root, "**", "ffmpeg.exe"), recursive=True)
        if hits:
            return hits[0]
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        return None

    # ------------------------------------------------------------------
    # WAV → OGG conversion
    # ------------------------------------------------------------------

    def convert_wav_to_ogg(self, wav_path: str) -> str | None:
        """
        Convert a WAV file to OGG/Opus using the bundled ffmpeg binary.
        Returns the path to the new .ogg file, or None on failure.
        """
        ffmpeg = self.find_api_ffmpeg()
        if not ffmpeg or not os.path.isfile(ffmpeg):
            logging.warning(
                "[audio] ffmpeg not found -- sending WAV (may fail). Searched: %s",
                resource_path("api", "node_modules", "@ffmpeg-installer", "ffmpeg", "bin"),
            )
            return None
        ogg_path = wav_path + ".ogg"
        try:
            result = subprocess.run(
                [ffmpeg, "-y", "-i", wav_path,
                 "-ac", "1",
                 "-c:a", "libopus", "-b:a", "64k",
                 "-vbr", "on", "-compression_level", "10",
                 ogg_path],
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0 and os.path.isfile(ogg_path) and os.path.getsize(ogg_path) > 0:
                logging.debug("[audio] WAV->OGG conversion succeeded: %s", ogg_path)
                return ogg_path
            logging.error("[audio] ffmpeg WAV->OGG failed (rc=%s): %s",
                          result.returncode,
                          (result.stderr or b"").decode("utf-8", errors="replace")[-800:])
        except Exception as exc:
            logging.error("[audio] ffmpeg conversion exception: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Send audio (PTT) message
    # ------------------------------------------------------------------

    def send_audio_message(self, remote_jid: str, wav_path: str, quoted=None) -> bool:
        """
        Base64-encode a WAV/audio file and send it as a PTT voice message via the
        WPPConnect Server API. Uses /api/{session}/send-voice-base64.
        WAV is converted to OGG/Opus first (WhatsApp PTT requirement).
        """
        remote_jid = self.mw.message_send_service._resolve_jid_for_send(remote_jid)
        ogg_path = self.convert_wav_to_ogg(wav_path)
        send_path = ogg_path if ogg_path else wav_path
        mime = "data:audio/ogg;codecs=opus;base64," if ogg_path else "data:audio/wav;base64,"

        try:
            with open(send_path, "rb") as fh:
                audio_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception as exc:
            logging.error("[send_audio_message] failed to read audio file %s: %s", send_path, exc)
            return {"ok": False, "error": str(exc)[:200], "retry": False}
        finally:
            if ogg_path and os.path.isfile(ogg_path):
                try:
                    os.unlink(ogg_path)
                except Exception:
                    pass

        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-voice-base64"
        quoted_id = self.mw.message_send_service._serialize_quoted_id(quoted) if quoted else None
        payload = {
            "phone": [remote_jid],
            "base64Ptt": f"{mime}{audio_b64}",
            "isGroup": remote_jid.endswith("@g.us"),
        }
        if quoted_id:
            payload["quotedMessageId"] = quoted_id
        headers = self.mw._api_headers()
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code in (200, 201):
                self.mw._wa_connected = True
                try:
                    body = response.json()
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
            err = f"HTTP {response.status_code}: {response.text[:300]}"
            logging.error("[send_audio_message] %s for %s", err, remote_jid)
            self.mw.connection_manager._check_wa_connection_closed(response)
            return {"ok": False, "error": err, "retry": False}
        except Exception as e:
            err = str(e)[:200]
            logging.error("[send_audio_message] exception for %s: %s", remote_jid, err)
            return {"ok": False, "error": err, "retry": True}

    # ------------------------------------------------------------------
    # Save incoming audio locally
    # ------------------------------------------------------------------

    def save_audio_locally(self, msg, audio_content):
        voice_messages_dir = data_path("voice_messages")
        msg_id = msg.get("key", {}).get("id", "")
        if "_" in msg_id:
            parts = msg_id.split("_")
            msg_id = parts[2] if len(parts) > 2 else parts[-1]
        audio_file_path = os.path.join(voice_messages_dir, f"{msg_id}.msv")
        try:
            with open(audio_file_path, "wb") as audio_file:
                encrypted_audio = encrypt(audio_content, self.mw.key)
                audio_file.write(encrypted_audio)
        except Exception:
            pass
