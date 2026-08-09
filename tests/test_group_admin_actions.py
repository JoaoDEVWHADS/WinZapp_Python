"""Tests for MainWindow's group-admin REST methods:
remove/promote/demote_group_members(), set_group_subject(), and
set_group_description().

These back the group-data dialog's new admin-only participant context menu
(remove/promote/demote a member) and "edit name"/"edit description" buttons.
All five are thin request wrappers following the same (True, "") /
(False, error_message) contract as the existing add_group_members().

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against
a small stub — same approach as tests/test_restart_wpp_session.py.
"""

import pytest

from main import MainWindow


class _Stub:
    _group_participant_action = MainWindow._group_participant_action
    remove_group_members  = MainWindow.remove_group_members
    promote_group_members = MainWindow.promote_group_members
    demote_group_members  = MainWindow.demote_group_members
    set_group_subject      = MainWindow.set_group_subject
    set_group_description  = MainWindow.set_group_description

    def __init__(self):
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "test-token"


def _fake_post_ok(url, json=None, headers=None, timeout=None, **kw):
    class _Resp:
        status_code = 200
        text = ""
    _fake_post_ok.calls.append((url, json))
    return _Resp()
_fake_post_ok.calls = []


def _fake_post_fail(url, json=None, headers=None, timeout=None, **kw):
    class _Resp:
        status_code = 403
        text = "not an admin"
    return _Resp()


class TestParticipantActions:
    @pytest.mark.parametrize("method,endpoint", [
        ("remove_group_members", "remove-participant-group"),
        ("promote_group_members", "promote-participant-group"),
        ("demote_group_members", "demote-participant-group"),
    ])
    def test_success_hits_the_right_endpoint_with_groupid_and_phone(self, monkeypatch, method, endpoint):
        _fake_post_ok.calls = []
        monkeypatch.setattr("main.requests.post", _fake_post_ok)
        stub = _Stub()

        ok, err = getattr(stub, method)("123-456@g.us", ["5511999999999"])

        assert ok is True
        assert err == ""
        url, payload = _fake_post_ok.calls[0]
        assert url == f"http://127.0.0.1:6300/api/test-token/{endpoint}"
        assert payload["groupId"] == "123-456@g.us"
        # Bare digits get the @c.us suffix; an already-qualified jid is left alone.
        assert payload["phone"] == ["5511999999999@c.us"]

    def test_jid_already_qualified_is_not_double_suffixed(self, monkeypatch):
        _fake_post_ok.calls = []
        monkeypatch.setattr("main.requests.post", _fake_post_ok)
        stub = _Stub()

        stub.remove_group_members("123-456@g.us", ["5511999999999@lid"])

        _, payload = _fake_post_ok.calls[0]
        assert payload["phone"] == ["5511999999999@lid"]

    def test_failure_returns_false_and_error_text(self, monkeypatch):
        monkeypatch.setattr("main.requests.post", _fake_post_fail)
        stub = _Stub()

        ok, err = stub.remove_group_members("123-456@g.us", ["5511999999999"])

        assert ok is False
        assert "403" in err
        assert "not an admin" in err

    def test_request_exception_is_caught_and_reported(self, monkeypatch):
        def _raise(*a, **kw):
            raise ConnectionError("boom")
        monkeypatch.setattr("main.requests.post", _raise)
        stub = _Stub()

        ok, err = stub.promote_group_members("123-456@g.us", ["5511999999999"])

        assert ok is False
        assert "boom" in err


class TestGroupSubjectAndDescription:
    def test_set_group_subject_posts_title(self, monkeypatch):
        _fake_post_ok.calls = []
        monkeypatch.setattr("main.requests.post", _fake_post_ok)
        stub = _Stub()

        ok, err = stub.set_group_subject("123-456@g.us", "New Name")

        assert ok is True
        url, payload = _fake_post_ok.calls[0]
        assert url == "http://127.0.0.1:6300/api/test-token/group-subject"
        assert payload == {"groupId": "123-456@g.us", "title": "New Name"}

    def test_set_group_description_posts_description(self, monkeypatch):
        _fake_post_ok.calls = []
        monkeypatch.setattr("main.requests.post", _fake_post_ok)
        stub = _Stub()

        ok, err = stub.set_group_description("123-456@g.us", "New description")

        assert ok is True
        url, payload = _fake_post_ok.calls[0]
        assert url == "http://127.0.0.1:6300/api/test-token/group-description"
        assert payload == {"groupId": "123-456@g.us", "description": "New description"}

    def test_set_group_description_failure_is_reported(self, monkeypatch):
        monkeypatch.setattr("main.requests.post", _fake_post_fail)
        stub = _Stub()

        ok, err = stub.set_group_description("123-456@g.us", "x")

        assert ok is False
        assert "403" in err
