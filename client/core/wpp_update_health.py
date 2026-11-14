"""Validate the local API, independently of the WhatsApp connection."""

import time
from urllib.parse import urlsplit, urlunsplit

import requests


def wait_for_port_closed(is_running, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while is_running():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def wait_for_api(server: str, port: int, *, identity: dict | None = None,
                 timeout: float = 15.0, cancelled=lambda: False) -> bool:
    parsed = urlsplit(server)
    host = parsed.hostname or "127.0.0.1"
    authority = f"[{host}]" if ":" in host else host
    base = urlunsplit((parsed.scheme or "http", f"{authority}:{parsed.port or port}", "", "", ""))
    deadline = time.monotonic() + timeout
    with requests.Session() as session:
        session.trust_env = False  # The local API must not go through a proxy.
        while time.monotonic() < deadline and not cancelled():
            try:
                with session.get(base + "/healthz", timeout=2, allow_redirects=False) as response:
                    healthy = response.status_code == 200 and response.json().get("message") == "OK"
                if healthy:
                    with session.get(base + "/winzapp/identity", timeout=2, allow_redirects=False) as response:
                        got = response.json()
                        if (response.status_code == 200 and isinstance(got, dict)
                                and got.get("protocol_version") == 1
                                and all(got.get(key) == value for key, value in (identity or {}).items())):
                            return True
            except (requests.RequestException, ValueError, AttributeError):
                pass
            time.sleep(0.5)
    return False
