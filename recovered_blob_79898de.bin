import logging
import requests


class GroupService:

    def __init__(self, main_window):
        self.mw = main_window

    def get_group_info(self, jid: str) -> dict:
        url = (
            f"{self.mw.wpp_server}:{self.mw.wpp_port}"
            f"/api/{self.mw.token}/group-info/{jid}"
        )
        headers = self.mw._api_headers()
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                res_data = r.json() or {}
                return res_data.get("response", {})
        except Exception as e:
            logging.error(f"[get_group_info] error: {e}")
        return {}

    def leave_group(self, jid: str):
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/leave-group"
        headers = self.mw._api_headers()
        try:
            requests.post(url, json={"groupId": jid}, headers=headers, timeout=10)
        except Exception:
            pass
        self.mw.archive_chat(jid)

    def create_group(self, name: str, participants: list) -> tuple:
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/create-group"
        headers = self.mw._api_headers()
        payload = {
            "name":         name,
            "participants": [f"{p}@c.us" for p in participants],
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code in (200, 201):
                resp = r.json().get("response", {})
                gid = resp.get("gid", {})
                if isinstance(gid, dict):
                    gid = gid.get("_serialized", "")
                return True, gid or ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)

    def add_group_members(self, group_jid: str, participant_jids: list) -> tuple:
        url = f"{self.mw.wpp_server}:{self.mw.wpp_port}/api/{self.mw.token}/add-participant-group"
        headers = self.mw._api_headers()
        payload = {
            "groupId":      group_jid,
            "participantId": [j if "@" in j else f"{j}@c.us" for j in participant_jids],
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code in (200, 201):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            return False, str(exc)
