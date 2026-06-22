import re


class TestBug6PayloadRemoteJidAlt:
    """Bug 6: get_base64_from_media payload must include remoteJidAlt for @lid lookups."""

    def test_payload_has_remote_jid_alt_key(self):
        src = open("client/main.py", encoding="utf-8").read()
        # Find the payload key construction inside get_base64_from_media
        m = re.search(r'def get_base64_from_media.*?"key":\s*\{.*?\}', src, re.DOTALL)
        assert m, "Could not find key payload in get_base64_from_media"
        assert "remoteJidAlt" in m.group(), "remoteJidAlt missing from key payload"

    def test_remote_jid_alt_default_empty(self):
        src = open("client/main.py", encoding="utf-8").read()
        m = re.search(r'def get_base64_from_media.*?"key":\s*\{.*?\}', src, re.DOTALL)
        assert m
        assert '"_key.get("remoteJidAlt", "")"' in m.group() or '"remoteJidAlt": _key.get("remoteJidAlt", "")' in m.group()
