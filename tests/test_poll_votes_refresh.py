"""The panel's vote-refresh logic (poll_messages.py): which polls are asked
about, when a lookup is skipped, and when the rows repaint.

ConversationsPanel needs a wx.App, so its methods run against plain stubs.
"""

import types

from ui.conversations import ConversationsPanel


def _poll_rec(msg_id, pending=False, kind="pollCreationMessage"):
    return {"messageType": kind, "_local_pending": pending, "key": {"id": msg_id},
            "message": {kind: {"name": "Q", "options": [{"name": "A"}, {"name": "B"}]}}}


class TestRefresh:
    def test_only_the_newest_confirmed_polls_are_asked_about(self):
        records = [_poll_rec(f"P{i}") for i in range(12)]
        records.append(_poll_rec("PENDING", pending=True))
        records.append({"messageType": "conversation", "key": {"id": "T"}})
        panel = types.SimpleNamespace(
            conversation={"messages": {"messages": {"records": records}}},
            _POLL_VOTES_MAX_POLLS=10)
        found = ConversationsPanel._open_poll_records(panel)
        assert [r["key"]["id"] for r in found] == [f"P{i}" for i in range(2, 12)]

    def test_nothing_is_asked_while_a_lookup_runs_or_inside_the_interval(self, monkeypatch):
        started = []
        monkeypatch.setattr("ui.conversation_panel.poll_messages.threading.Thread",
                            lambda **kw: types.SimpleNamespace(start=lambda: started.append(kw)))
        base = dict(
            _POLL_VOTES_MIN_INTERVAL=10, _poll_votes_busy=False, _poll_votes_at=0.0,
            conversation={"remoteJid": "5511@s.whatsapp.net"},
            _open_poll_records=lambda: [_poll_rec("P1")], _poll_votes_worker=lambda *a: None)
        busy = types.SimpleNamespace(**{**base, "_poll_votes_busy": True})
        ConversationsPanel.refresh_poll_votes(busy, force=True)
        assert started == []
        recent = types.SimpleNamespace(**{**base, "_poll_votes_at": 10 ** 12})
        ConversationsPanel.refresh_poll_votes(recent)
        assert started == []
        idle = types.SimpleNamespace(**base)
        ConversationsPanel.refresh_poll_votes(idle)
        assert len(started) == 1 and idle._poll_votes_busy is True

    def test_a_result_for_another_conversation_is_dropped(self):
        rec = _poll_rec("P1")
        panel = types.SimpleNamespace(
            _poll_votes_busy=True, conversation={"remoteJid": "other@s.whatsapp.net"},
            refresh_messages_if_changed=lambda: (_ for _ in ()).throw(AssertionError("repainted")),
            _reload_inline_poll=lambda: None)
        result = {"P1": {"options": [{"name": "A", "votes": 1, "localId": 0, "mine": False},
                                     {"name": "B", "votes": 0, "localId": 1, "mine": False}]}}
        ConversationsPanel._apply_poll_votes(panel, "5511@s.whatsapp.net", [rec], result)
        assert panel._poll_votes_busy is False
        assert "votes" not in rec["message"]["pollCreationMessage"]["options"][0]

    def test_the_rows_repaint_only_when_a_count_changed(self):
        rec = _poll_rec("P1")
        repaints = []
        panel = types.SimpleNamespace(
            _poll_votes_busy=True, conversation={"remoteJid": "5511@s.whatsapp.net"},
            refresh_messages_if_changed=lambda: repaints.append(1),
            _reload_inline_poll=lambda: None)
        result = {"P1": {"options": [{"name": "A", "votes": 1, "localId": 0, "mine": False},
                                     {"name": "B", "votes": 0, "localId": 1, "mine": False}]}}
        ConversationsPanel._apply_poll_votes(panel, "5511@s.whatsapp.net", [rec], result)
        ConversationsPanel._apply_poll_votes(panel, "5511@s.whatsapp.net", [rec], result)
        assert repaints == [1]
        assert rec["message"]["pollCreationMessage"]["options"][0]["votes"] == 1


class TestVoterName:
    def _name(self, remote_jid, sender):
        seen = []
        panel = types.SimpleNamespace(
            conversation={"remoteJid": remote_jid},
            _sender_label=lambda msg: seen.append(msg["key"]) or "Ana")
        assert ConversationsPanel._poll_voter_name(panel, sender) == "Ana"
        return seen[0]

    def test_in_a_group_the_voter_is_the_participant(self):
        key = self._name("120363000000000001@g.us", "111@lid")
        assert key["participant"] == "111@lid" and key["fromMe"] is False

    def test_in_a_private_chat_the_voter_is_the_chats_contact(self):
        key = self._name("5511999999999@s.whatsapp.net", "111@lid")
        assert key["participant"] == ""
