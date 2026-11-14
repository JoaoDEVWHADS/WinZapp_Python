"""An explicit hidden-online flag must not erase observed private activity.

Plain owners, synthetic models and fake clocks only; no wx.App or live I/O.
"""
import pytest

from core import contact_presence as presence
from tests.test_contact_presence_freshness import Owner, PN, LID, scheduled
from tests.test_contact_presence_runtime import _run


@pytest.mark.parametrize("state", ["composing", "recording"])
def test_activity_survives_an_explicit_offline_flag(state):
    owner = Owner()
    entry = presence.merge(owner, PN, {"lastKnownPresence": state, "isOnline": False}, now=100)
    assert entry["lastKnownPresence"] == state
    assert entry["isOnline"] is False
    assert entry["lastSeen"] is None


@pytest.mark.parametrize("state", ["composing", "recording"])
def test_expired_activity_cannot_become_online(state):
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": state, "isOnline": False}, now=100)
    assert presence.cached(owner, PN, now=109)["lastKnownPresence"] == state
    assert presence.cached(owner, PN, now=110)["lastKnownPresence"] == "unavailable"


@pytest.mark.parametrize("state,expected", [("typing", "composing"), ("recording_audio", "recording")])
def test_shipped_http_runtime_preserves_activity_when_online_is_hidden(state, expected):
    result = _run({"model": {"hasData": True, "isOnline": False,
                             "chatstate": {"type": state, "t": 1000}}})
    snapshot = presence.response_snapshot(result["body"])
    assert snapshot["lastKnownPresence"] == expected
    assert snapshot["isOnline"] is False and snapshot["lastSeen"] is None


def test_activity_does_not_renew_an_older_online_observation():
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": "available", "isOnline": True}, now=100)
    presence.merge(owner, PN, {"lastKnownPresence": "composing"}, now=185)
    entry = presence.cached(owner, PN, now=190)
    assert entry["lastKnownPresence"] == "composing"
    assert entry["isOnline"] is None


def test_alias_activity_and_withheld_timestamp_keep_the_same_revision():
    owner = Owner()
    owner._lid_to_phone[LID], owner._phone_to_lid[PN] = PN, LID
    entry = presence.merge(owner, LID, {"lastKnownPresence": "recording", "isOnline": False,
                                      "restricted": True, "lastSeen": 1000}, now=100)
    assert entry["lastKnownPresence"] == "recording" and entry["lastSeen"] is None
    assert presence.cached(owner, PN, fresh=False) is entry


@pytest.mark.parametrize("state", ["composing", "recording"])
@pytest.mark.parametrize("online", [False, True, None])
def test_all_three_views_show_activity_without_fabricating_online(state, online):
    from tests.test_contact_presence_views import views
    from main_window.chat_events import ChatEventsMixin
    from ui.conversation_panel.conversation_info import ConversationInfoMixin
    from ui.dialogs.conversation_data_dialog import ConversationDataDialog
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": state, "isOnline": online})
    panel, dialog, button, text, _ = views(owner)
    ConversationInfoMixin._refresh_presence_note(panel, PN)
    announcement = ChatEventsMixin._presence_announcement_for_chat(owner, panel.conversation)
    ConversationDataDialog._populate_personal_unsafe(dialog, {})
    expected = "typing_indicator" if state == "composing" else "recording_indicator"
    assert button.text == announcement == expected and expected in text.text
    assert "Online" not in text.text


@pytest.mark.parametrize("state", ["composing", "recording"])
def test_real_event_path_announces_once_and_clears_activity_without_online(state, monkeypatch):
    from tests.test_presence_speech_gating import _Stub, _Timer
    import main_window.chat_events as events
    clock = [100]
    monkeypatch.setattr(presence.time, "monotonic", lambda: clock[0])
    timers = []
    monkeypatch.setattr(events.wx, "CallLater", lambda ms, fn: timers.append(fn) or _Timer())
    owner = _Stub(conversation_jid=PN)
    owner._lid_to_phone[LID], owner._phone_to_lid[PN] = PN, LID
    payload = {LID: {"lastKnownPresence": state, "isOnline": False}}
    owner.on_presence_update(LID, payload)
    owner.on_presence_update(LID, payload)
    assert len(owner.speak_output.outputs) == 1
    assert owner._composing_chats[PN][PN] == state
    assert not presence.visible_online(presence.cached(owner, PN))
    clock[0] = 110
    timers[-1]()
    assert owner._composing_chats[PN] == {}
    assert presence.cached(owner, PN)["lastKnownPresence"] == "unavailable"
    owner.on_presence_update(LID, payload)
    assert len(owner.speak_output.outputs) == 2


def test_http_refresh_enters_the_same_event_pipeline(scheduled):
    # Reuse the scheduler fixture explicitly without constructing the UI.
    owner, workers, callbacks = scheduled
    calls = []
    owner._fetch_contact_presence = lambda jid: {"lastKnownPresence": "recording", "isOnline": False}
    owner.on_presence_update = lambda jid, data, **kw: calls.append((jid, data, kw))
    owner._refresh_open_contact_presence()
    workers.pop()()
    callbacks.pop()()
    assert calls == [(PN, {PN: {"lastKnownPresence": "recording", "isOnline": False}}, {"refresh_offline": False})]


def test_activity_expiry_keeps_only_separately_confirmed_online():
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": "composing", "isOnline": True}, now=100)
    entry = presence.cached(owner, PN, now=110)
    assert entry["lastKnownPresence"] == "available" and presence.visible_online(entry)
    assert presence.cached(owner, PN, now=190) == {}


@pytest.mark.parametrize("online,expected", [(True, "available"), (False, "unavailable")])
def test_paused_activity_ends_immediately_without_changing_explicit_visibility(online, expected):
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": "recording", "isOnline": online}, now=100)
    entry = presence.merge(owner, PN, {"lastKnownPresence": "paused", "isOnline": online}, now=101)
    assert entry["lastKnownPresence"] == expected


def test_restricted_activity_never_restores_old_last_seen_or_online():
    owner = Owner()
    presence.merge(owner, PN, {"lastKnownPresence": "unavailable", "lastSeen": 1000}, now=99)
    entry = presence.merge(owner, PN, {"lastKnownPresence": "composing", "isOnline": True,
                                      "restricted": True, "lastSeen": 1000}, now=100)
    assert entry["lastSeen"] is None and not presence.visible_online(entry)
    assert presence.cached(owner, PN, now=110)["lastKnownPresence"] == ""
