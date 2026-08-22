"""Tests for the bounded boot message sync.

Every chat must get the configured first page before lower-priority deep
history begins.  Fetching 1,000 messages for the ten newest chats at boot used
all workers while private history was still landing, leaving other private
conversations visibly stuck at 1 or 15 messages.  Deep history now runs only in
the background after the first-page repair queue drains.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so
the methods under test are exercised against a stub carrying just the state
they touch.
"""

import main as main_module
from main import MainWindow


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeDb:
    def upsert_chat(self, jid, data):
        pass

    def insert_messages_batch(self, jid, messages):
        pass


class _SyncStub:
    """Minimal MainWindow stand-in for sync_remote_chats()."""

    def __init__(self, chats):
        self.chats = chats
        self.calls = []
        self.repair_calls = []
        self.settings = {"user_interface": {"messages_page_size": 200}}

    def history_page_target(self):
        return int(
            self.settings.get("user_interface", {}).get("messages_page_size", 200)
        )

    def sync_chat_messages(self, chat):
        self.calls.append((chat.get("remoteJid"), chat.get("_sync_limit")))

    def _repair_short_chat(self, chat):
        self.repair_calls.append(chat.get("remoteJid"))
        self.sync_chat_messages(chat)


def _chats(n, start_t):
    return {
        f"jid{i:04d}@c.us": {"remoteJid": f"jid{i:04d}@c.us", "t": start_t - i}
        for i in range(n)
    }


class TestSyncRemoteChatsBoundedWindow:
    def test_all_chats_use_the_normal_page_limit(self):
        stub = _SyncStub(_chats(15, start_t=100))
        MainWindow.sync_remote_chats(stub)
        limits = dict(stub.calls)
        assert len(limits) == 15
        assert all(limit is None for limit in limits.values())
        assert set(stub.repair_calls) == set(limits)

    def test_invalid_jids_are_filtered_before_ranking(self):
        stub = _SyncStub({
            "bad0": {"remoteJid": "0", "t": 999},
            "bad1": {"remoteJid": "", "t": 998},
            f"jid0000@c.us": {"remoteJid": "jid0000@c.us", "t": 1},
            f"jid0001@c.us": {"remoteJid": "jid0001@c.us", "t": 0},
        })
        MainWindow.sync_remote_chats(stub)
        limits = dict(stub.calls)
        assert set(limits) == {"jid0000@c.us", "jid0001@c.us"}
        assert all(limit is None for limit in limits.values())


class _MessagesStub:
    """Minimal MainWindow stand-in for sync_chat_messages()."""

    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self, get_urls):
        self.get_urls = get_urls
        self.settings = {"user_interface": {"messages_page_size": 200}}
        self._phone_to_lid = {}
        self._wa_connected = True
        self.chats = {}
        self._initial_sync_running = True
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6308
        self.token = "tok"
        self.db = _FakeDb()

    def _is_cleared_message(self, remote_jid, message):
        return False

    def _note_backfill_state(self, remote_jid, chat, api_ok):
        pass

    def _refresh_open_conversation_after_sync(self, remote_jid, chat):
        pass

    def _normalize_fetched_messages(self, raw_messages, remote_jid):
        return []

    def _learn_sender_names_bulk(self, messages):
        return False


class TestSyncChatMessagesHonorsPageLimit:
    def test_legacy_deep_tag_cannot_override_configured_count(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            main_module.requests, "get",
            lambda url, **kwargs: urls.append(url) or _Resp(200, {"response": []}),
        )
        stub = _MessagesStub(urls)
        chat = {"remoteJid": "jid0000@c.us", "t": 100, "_sync_limit": 1000}
        MainWindow.sync_chat_messages(stub, chat)
        assert len(urls) == 1
        assert "count=200" in urls[0]

    def test_untagged_chat_falls_back_to_messages_page_size(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            main_module.requests, "get",
            lambda url, **kwargs: urls.append(url) or _Resp(200, {"response": []}),
        )
        stub = _MessagesStub(urls)
        chat = {"remoteJid": "jid0000@c.us", "t": 100}
        MainWindow.sync_chat_messages(stub, chat)
        assert len(urls) == 1
        assert "count=200" in urls[0]
