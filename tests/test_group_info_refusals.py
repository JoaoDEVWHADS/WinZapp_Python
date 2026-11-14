"""Groups the account cannot read are not asked again on every resync.

Reported (Neonize): sends sometimes took much longer than on WPPConnect. The
bridge's log showed ~40 groups the account had left asked for their name on
every resync, 9,570 failures in a day, each holding a bridge thread and
arriving in bursts with the stalls. Only a definite refusal (not in the group,
no such group) stops the asking, and only for the run."""
from types import SimpleNamespace

from main_window import groups as groups_module
from main_window.groups import GroupsMixin, group_info_refused


def test_only_a_definite_refusal_counts():
    assert group_info_refused({"status": "error", "code": "not_in_group"})
    assert group_info_refused({"status": "error", "code": "group_not_found"})
    assert not group_info_refused({"status": "error", "code": None})
    assert not group_info_refused({"status": "error", "code": "group_unavailable"})
    assert not group_info_refused(None)


class _Response:
    def __init__(self, ok, body):
        self.ok = ok
        self._body = body

    def json(self):
        return self._body


def _window(chats):
    return SimpleNamespace(wpp_server="http://synthetic.invalid", wpp_port=6300, token="t",
                           chats=chats, _schedule_save=lambda dirty_jid=None: None,
                           _group_name_from_chat_dict=lambda chat: chat.get("name", ""))


def test_a_refused_group_is_not_asked_again_in_the_same_run(monkeypatch):
    asked = []
    answers = {"left@g.us": _Response(False, {"status": "error", "code": "not_in_group"}),
               "slow@g.us": _Response(False, {"status": "error", "code": None}),
               "named@g.us": _Response(True, {"response": {"name": "Família"}})}

    def fake_get(url, **kwargs):
        jid = url.rsplit("/", 1)[1]
        asked.append(jid)
        return answers[jid]

    monkeypatch.setattr(groups_module, "api_get", fake_get)
    window = _window({jid: {} for jid in answers})
    window._fill_group_name = lambda jid: GroupsMixin._fill_group_name(window, jid)

    GroupsMixin._resolve_missing_group_names(window)
    assert sorted(asked) == ["left@g.us", "named@g.us", "slow@g.us"]
    assert window.chats["named@g.us"]["name"] == "Família"

    asked.clear()
    GroupsMixin._resolve_missing_group_names(window)
    # the refused group is skipped; a timeout-like failure is asked again
    assert asked == ["slow@g.us"]
