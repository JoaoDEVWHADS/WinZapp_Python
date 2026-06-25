import logging
import os
import requests


class MediaSendService:

    def __init__(self, main_window):
        self.mw = main_window

    def send_media_attachment(
        self, remote_jid: str, file_path: str,
        media_type: str, caption: str = "", quoted: dict = None
    ) -> bool:
        remote_jid = self.mw.message_send_service._resolve_jid_for_send(remote_jid)
        import mimetypes
        try:
            file_size = os.path.getsize(file_path)
        except Exception as exc:
            logging.error("[send_media] failed to stat file %s: %s", file_path, exc)
            return False
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        filename = os.path.basename(file_path)
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/send-file"
        headers = self.mw._api_headers({"Content-Type": None})
        data = {
            "phone":    remote_jid,
            "filename": filename,
            "caption":  caption,
        }
        if quoted:
            quoted_id = self.mw.message_send_service._serialize_quoted_id(quoted)
            if quoted_id:
                data["quotedMessageId"] = quoted_id
        timeout = max(120, file_size // (100 * 1024))
        timeout = min(timeout, 1800)
        try:
            with open(file_path, "rb") as fh:
                r = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (filename, fh, mime)},
                    timeout=timeout,
                )
            if r.status_code in (200, 201):
                try:
                    body = r.json()
                    resp = body.get("response", body)
                    if isinstance(resp, list) and resp:
                        resp = resp[0]
                    if isinstance(resp, dict):
                        msg_id = resp.get("id")
                        if isinstance(msg_id, dict):
                            msg_id = msg_id.get("_serialized", "")
                        if msg_id:
                            parts = msg_id.split("_")
                            return parts[2] if len(parts) > 2 else (parts[-1] if parts else msg_id)
                    return True
                except Exception:
                    return True
            err = f"HTTP {r.status_code}"
            try:
                body = r.json()
                detail = (body.get("message") or body.get("error") or "")
                if detail:
                    err = f"{err}: {detail}"
            except Exception:
                if r.text:
                    err = f"{err}: {r.text[:200]}"
            logging.error("[send_media] %s for %s (%s, %.1f MB): %s",
                          err, remote_jid, filename, file_size / (1024*1024), r.text[:300])
            return {"ok": False, "error": err, "retry": False}
        except Exception as exc:
            logging.error("[send_media] request exception for %s (%s): %s", remote_jid, filename, exc)
            return {"ok": False, "error": str(exc)[:200], "retry": False}
