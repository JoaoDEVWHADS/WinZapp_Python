"""Regression test: @mention suggestions did not pick up a member who
joined a group while its conversation was already open.

_fetch_group_participants() (ui/conversations.py) only ever ran when a group
conversation was *opened* — nothing re-ran it while one stayed open and a
member joined/left/was added mid-conversation, so the mention cache went
stale for the rest of the session (observed live: a member joined at
23:09:17, the user tried to @mention them at 23:09:55 and got nothing, and
the cache only caught up ~3.5 minutes later on an unrelated re-open).

_refresh_mention_cache_on_membership_change() reacts to the live
groupNotification that already announces the join/leave, re-running the
same participant fetch the panel does on open.

Tested as a plain function bound to a stub, per the project's convention for
MainWindow (a wx.Frame) — see tests/test_group_rename.py.
"""

import threading

import pytest

from main import MainWindow


class _ConversationsPanelStub:
    def __init__(self, open_jid: str | None):
        self.conversation = {"remoteJid": open_jid} if open_jid else None
        self.fetch_calls = []

    def _fetch_group_participants(self, jid):
        self.fetch_calls.append(jid)


class _MainWindowStub:
    _refresh_mention_cache_on_membership_change = (
        MainWindow._refresh_mention_cache_on_membership_change
    )
    _GROUP_MEMBERSHIP_NOTIF_SUBTYPES = MainWindow._GROUP_MEMBERSHIP_NOTIF_SUBTYPES

    def __init__(self, open_jid: str | None = "123@g.us"):
        self.conversations_panel = _ConversationsPanelStub(open_jid)

    def _normalize_jid(self, jid):
        return jid


@pytest.fixture(autouse=True)
def run_threads_inline(monkeypatch):
    """The refetch dispatches to a background thread the same way opening
    the conversation does; run it inline so the test can observe it."""
    class _Inline:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(threading, "Thread", _Inline)


def _membership_msg(subtype: str):
    return {
        "messageType": "groupNotification",
        "message": {"groupNotification": {"subtype": subtype}},
    }


class TestRefreshesOnlyForActualMembershipChanges:
    @pytest.mark.parametrize("subtype", ["add", "remove", "invite", "leave"])
    def test_membership_subtypes_refetch_the_open_group(self, subtype):
        mw = _MainWindowStub(open_jid="123@g.us")

        mw._refresh_mention_cache_on_membership_change(
            "123@g.us", _membership_msg(subtype))

        assert mw.conversations_panel.fetch_calls == ["123@g.us"]

    @pytest.mark.parametrize("subtype", ["subject", "picture", "promote", "demote"])
    def test_non_membership_subtypes_do_not_refetch(self, subtype):
        mw = _MainWindowStub(open_jid="123@g.us")

        mw._refresh_mention_cache_on_membership_change(
            "123@g.us", _membership_msg(subtype))

        assert mw.conversations_panel.fetch_calls == []


def test_a_different_open_conversation_is_left_alone():
    """A membership change in some other group must not refetch whatever
    the user actually has open right now."""
    mw = _MainWindowStub(open_jid="999@g.us")

    mw._refresh_mention_cache_on_membership_change("123@g.us", _membership_msg("add"))

    assert mw.conversations_panel.fetch_calls == []


def test_no_open_conversation_is_a_no_op():
    mw = _MainWindowStub(open_jid=None)

    mw._refresh_mention_cache_on_membership_change("123@g.us", _membership_msg("add"))

    assert mw.conversations_panel.fetch_calls == []


def test_non_group_jid_is_ignored():
    mw = _MainWindowStub(open_jid="5511999@s.whatsapp.net")

    mw._refresh_mention_cache_on_membership_change(
        "5511999@s.whatsapp.net", _membership_msg("add"))

    assert mw.conversations_panel.fetch_calls == []


def test_regular_message_is_ignored():
    mw = _MainWindowStub(open_jid="123@g.us")
    msg = {"messageType": "conversation", "message": {"conversation": "oi"}}

    mw._refresh_mention_cache_on_membership_change("123@g.us", msg)

    assert mw.conversations_panel.fetch_calls == []
