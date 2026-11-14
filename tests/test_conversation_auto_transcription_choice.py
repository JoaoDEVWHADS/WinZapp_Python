"""A conversation's own automatic transcription boxes, local and online.

Asked for: in a group's or contact's data window, a box for the automatic
local transcription and one for the online one, each following the
install-wide option until the user sets it for that conversation, and each
able to turn the automatic transcription on there while the option is off.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from core import conversation_auto_ai as conv
from main_window.auto_ai_media import AutoAIMediaMixin
from tests.test_auto_transcription import JID, _Window, _msg, _result
from ui.dialogs.conversation_data_dialog import ConversationDataDialog

LOCAL, ONLINE = conv.TRANSCRIBE_LOCAL, conv.TRANSCRIBE_ONLINE


class TestTheChoice:
    def test_a_box_never_set_follows_the_install_wide_option(self):
        assert conv.transcription_wanted({}, JID, LOCAL, True) is True
        assert conv.transcription_wanted({}, JID, LOCAL, False) is False
        assert conv.transcription_choice({}, JID, ONLINE) is None

    def test_a_choice_wins_both_ways_and_is_kept_even_when_it_matches(self):
        settings = {}
        conv.set_transcription(settings, JID, LOCAL, True)
        assert conv.transcription_wanted(settings, JID, LOCAL, False) is True
        assert conv.transcription_choice(settings, JID, LOCAL) is True  # equal to nothing, still kept
        conv.set_transcription(settings, JID, ONLINE, False)
        assert conv.transcription_wanted(settings, JID, ONLINE, True) is False
        assert conv.transcription_wanted(settings, "other@s.whatsapp.net", ONLINE, True) is True

    def test_the_two_boxes_are_independent(self):
        settings = {}
        conv.set_transcription(settings, JID, LOCAL, False)
        assert conv.transcription_choice(settings, JID, ONLINE) is None
        assert conv.transcription_wanted(settings, JID, ONLINE, True) is True

    def test_the_old_shared_box_speaks_for_both_until_one_is_set(self):
        settings = {conv.SETTING: {JID: {conv.TRANSCRIBE: False}}}
        assert conv.transcription_wanted(settings, JID, LOCAL, True) is False
        assert conv.transcription_wanted(settings, JID, ONLINE, True) is False
        conv.set_transcription(settings, JID, LOCAL, True)
        assert conv.transcription_wanted(settings, JID, LOCAL, True) is True
        assert conv.transcription_wanted(settings, JID, ONLINE, True) is False
        conv.set_transcription(settings, JID, ONLINE, True)
        assert settings[conv.SETTING][JID] == {LOCAL: True, ONLINE: True}

    def test_an_old_true_only_allowed_and_never_turns_anything_on(self):
        """Reviewer: the old box only restricted ("may act here while the
        option is on"). Read as a choice, an old True ran local Whisper with
        the option off and, moved to the other box, sent voice notes to an
        online provider whose option was off."""
        settings = {conv.SCOPE_SETTING: conv.SCOPE_SELECTED,
                    conv.SETTING: {JID: {conv.TRANSCRIBE: True}}}
        assert conv.transcription_wanted(settings, JID, LOCAL, False) is False
        assert conv.transcription_wanted(settings, JID, ONLINE, False) is False
        # It still lets the option act here, as it did under "selected".
        assert conv.transcription_wanted(settings, JID, LOCAL, True) is True
        conv.set_transcription(settings, JID, LOCAL, False)
        assert conv.transcription_wanted(settings, JID, ONLINE, False) is False
        assert conv.transcription_choice(settings, JID, ONLINE) is None

    def test_the_selected_scope_still_starts_a_conversation_off(self):
        settings = {conv.SCOPE_SETTING: conv.SCOPE_SELECTED}
        assert conv.transcription_wanted(settings, JID, LOCAL, True) is False
        conv.set_transcription(settings, JID, LOCAL, True)
        assert conv.transcription_wanted(settings, JID, LOCAL, True) is True

    def test_describe_keeps_its_old_meaning(self):
        settings = {}
        conv.set_transcription(settings, JID, LOCAL, False)
        assert conv.allowed(settings, JID, conv.DESCRIBE) is True


class TestLocalAutomaticTranscription:
    def test_a_conversation_turned_on_is_transcribed_while_the_setting_is_off(self):
        window = _Window(enabled=False)
        conv.set_transcription(window.settings, JID, LOCAL, True)
        msg = _msg()
        window._maybe_auto_transcribe(JID, msg)
        assert window.queue.submitted == [((JID, "M1"), (JID, "M1", msg))]

    def test_a_conversation_turned_off_is_left_alone_while_the_setting_is_on(self):
        window = _Window(enabled=True)
        conv.set_transcription(window.settings, JID, LOCAL, False)
        window._maybe_auto_transcribe(JID, _msg())
        assert window.queue.submitted == []

    def test_a_box_cleared_while_queued_keeps_the_result_out(self):
        stored = []
        for box in (True, False):
            window = _Window(enabled=True)
            window.records = [_msg()]
            conv.set_transcription(window.settings, JID, LOCAL, box)
            window._store_auto_transcription(JID, "M1", _result())
            stored.append(len(window.stored))
        assert stored == [1, 0]


class _OnlineWindow(AutoAIMediaMixin):
    def __init__(self, online_on, local_on=False):
        self.settings = {"transcription": {"auto_transcribe_received": local_on}}
        self._config = {"enabled": True, "auto_transcribe": online_on, "auto_describe": False}

    def _normalize_jid(self, jid):
        return jid

    def _local_auto_transcription_for(self, jid):
        return conv.transcription_wanted(self.settings, jid, LOCAL,
                                         self.settings["transcription"]["auto_transcribe_received"])


class TestOnlineAutomaticTranscription:
    def test_the_conversation_box_replaces_the_install_wide_option(self):
        window = _OnlineWindow(online_on=False)
        config, local = window._auto_ai_config_for(JID, window._config)
        assert config["auto_transcribe"] is False and local is False
        conv.set_transcription(window.settings, JID, ONLINE, True)
        config, _local = window._auto_ai_config_for(JID, window._config)
        assert config["auto_transcribe"] is True
        assert window._config["auto_transcribe"] is False  # the shared options are not edited

    def test_local_still_wins_where_it_runs(self):
        window = _OnlineWindow(online_on=True)
        conv.set_transcription(window.settings, JID, LOCAL, True)
        _config, local = window._auto_ai_config_for(JID, window._config)
        assert local is True

    def test_voice_is_no_longer_gated_by_the_describe_box(self):
        window = _OnlineWindow(online_on=True)
        conv.set_allowed(window.settings, JID, conv.DESCRIBE, False)
        assert window._conversation_allows_auto_ai(JID, "audio") is True
        assert window._conversation_allows_auto_ai(JID, "image") is False


class TestTheDataWindow:
    def _dialog(self, selection):
        dialog = SimpleNamespace(
            _jid=JID,
            _mw=SimpleNamespace(settings={}, _normalize_jid=lambda jid: jid,
                                _schedule_save_settings=Mock()),
            _auto_transcribe_radio=SimpleNamespace(GetSelection=lambda: selection),
        )
        return dialog

    def test_a_pick_sets_both_boxes_at_once(self):
        """One group of three options: both transcriptions can no longer be
        ticked together for one conversation."""
        for index, expected in enumerate((
                {LOCAL: False, ONLINE: False},
                {LOCAL: False, ONLINE: True},
                {LOCAL: True, ONLINE: False})):
            dialog = self._dialog(index)
            event = SimpleNamespace(Skip=Mock())
            ConversationDataDialog._on_auto_transcription_changed(dialog, event)
            assert dialog._mw.settings[conv.SETTING] == {JID: expected}
            dialog._mw._schedule_save_settings.assert_called_once()
            event.Skip.assert_called_once()

    def test_the_options_are_offered_none_online_local(self):
        assert conv.TRANSCRIPTION_MODES == (
            conv.TRANSCRIPTION_NONE, conv.TRANSCRIPTION_ONLINE, conv.TRANSCRIPTION_LOCAL)

    def test_until_picked_the_group_inherits_the_install_wide_options(self):
        settings = {}
        assert conv.transcription_mode(settings, JID, False, False) == conv.TRANSCRIPTION_NONE
        assert conv.transcription_mode(settings, JID, False, True) == conv.TRANSCRIPTION_ONLINE
        assert conv.transcription_mode(settings, JID, True, False) == conv.TRANSCRIPTION_LOCAL
        # Both on (a settings.json from before the check): local wins, as it
        # does when the message arrives.
        assert conv.transcription_mode(settings, JID, True, True) == conv.TRANSCRIPTION_LOCAL

    def test_a_pick_outlives_the_install_wide_options(self):
        settings = {}
        conv.set_transcription_mode(settings, JID, conv.TRANSCRIPTION_ONLINE)
        assert conv.transcription_mode(settings, JID, True, False) == conv.TRANSCRIPTION_ONLINE
        conv.set_transcription_mode(settings, JID, conv.TRANSCRIPTION_NONE)
        assert conv.transcription_mode(settings, JID, True, True) == conv.TRANSCRIPTION_NONE

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ValueError):
            conv.set_transcription_mode({}, JID, "both")

    def test_the_online_option_that_cannot_be_read_is_off(self):
        broken = SimpleNamespace(_mw=SimpleNamespace(
            _ai_media_preferences=Mock(side_effect=RuntimeError("private"))))
        assert ConversationDataDialog._online_auto_transcribe(broken) is False
        on = SimpleNamespace(_mw=SimpleNamespace(
            _ai_media_preferences=lambda: {"auto_transcribe": True}))
        assert ConversationDataDialog._online_auto_transcribe(on) is True
