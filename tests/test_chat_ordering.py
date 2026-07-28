"""Tests for which stored record decides a chat's position and its preview.

The conversations list contradicted itself. _last_msg_preview() skipped silent
bookkeeping — groupNotification ("X entrou no grupo"), notification_template —
when choosing what to show, but _chat_last_ts() counted every record when
deciding where to put the chat.

Measured on a real account:

    a discussion group  newest record notification_template  day 2, 09:47
                        real last message                    day 1, 19:55
    a quiet group       newest record groupNotification      day 2, 09:52
                        real last message                    5 days earlier

Both sat among conversations from minutes earlier while displaying a preview
days old — the "contatos antigos no topo da lista" report. Both now share one
rule, so the order always matches what is on screen.
"""

import pytest

from main import MainWindow


counts = MainWindow._counts_as_last_message


def _msg(mtype, ts, **extra):
    m = {"messageType": mtype, "timestamp": ts}
    m.update(extra)
    return m


class TestWhatCountsAsActivity:
    @pytest.mark.parametrize("mtype", [
        "conversation", "extendedTextMessage", "imageMessage", "audioMessage",
        "documentMessage", "stickerMessage", "reactionMessage", "pollCreationMessage",
        "pollCreationMessageV2", "pollCreationMessageV3", "pollUpdateMessage",
    ])
    def test_real_messages_count(self, mtype):
        assert counts(_msg(mtype, 100)) is True

    @pytest.mark.parametrize("mtype", [
        "groupNotification", "notification_template", "e2e_notification", "",
        "someFutureTypeWeDoNotKnow",
    ])
    def test_bookkeeping_does_not_count(self, mtype):
        assert counts(_msg(mtype, 100)) is False

    def test_a_revoke_counts_because_it_is_shown(self):
        m = _msg("protocolMessage", 100, message={"protocolMessage": {"type": 3}})
        assert counts(m) is True

    @pytest.mark.parametrize("ptype", [0, 1, 2, 5, None, "SETTING"])
    def test_other_protocol_messages_do_not(self, ptype):
        m = _msg("protocolMessage", 100, message={"protocolMessage": {"type": ptype}})
        assert counts(m) is False

    @pytest.mark.parametrize("bad", [None, "text", 42, [], {"no": "type"}])
    def test_junk_never_counts(self, bad):
        assert counts(bad) is False

    def test_a_permanently_failed_send_does_not_count(self):
        """A message that exhausted retries and never reached WhatsApp must
        not decide the chat-list preview/position — reported live: the
        preview kept showing a message the recipient never got, with no
        visible cue anything was wrong, until the conversation happened to
        be reopened for an unrelated reason."""
        m = _msg("conversation", 100, _send_failed=True)
        assert counts(m) is False

    def test_a_still_pending_send_counts_normally(self):
        """Only a CONFIRMED failure is excluded — a message still sending
        (optimistic local echo) is exactly what WhatsApp's own official
        client shows as the preview too."""
        m = _msg("conversation", 100, _local_pending=True)
        assert counts(m) is True


def _sort_key(chat_t, records):
    """_chat_last_ts()'s rule: the newest of `t` and any record that counts."""
    ts = chat_t
    for m in records:
        if not counts(m):
            continue
        ts = max(ts, m["timestamp"])
    return ts or 1


class TestSortKeyMatchesPreview:
    def test_a_join_notification_does_not_float_a_stale_group(self):
        """The quiet-group case, with its observed timestamps."""
        real, notif = 1753222560, 1753617120  # the join lands ~4.6 days later
        key = _sort_key(real, [_msg("conversation", real),
                               _msg("groupNotification", notif)])
        assert key == real, "a join must not make a five-day-old group look live"

    def test_a_real_message_still_floats_the_chat(self):
        old, new = 1753222560, 1753617120
        key = _sort_key(old, [_msg("conversation", old), _msg("conversation", new)])
        assert key == new

    def test_the_chats_own_timestamp_is_still_a_floor(self):
        """WhatsApp's `t` already excludes notifications, so it stays trusted."""
        assert _sort_key(500, [_msg("groupNotification", 900)]) == 500

    def test_a_chat_with_only_notifications_keeps_its_own_time(self):
        """The observed case where every stored record is a notification."""
        assert _sort_key(1752104280, [_msg("groupNotification", 1753264920)]) == 1752104280

    def test_a_chat_with_nothing_at_all_sorts_last(self):
        assert _sort_key(0, []) == 1
        assert _sort_key(0, [_msg("groupNotification", 900)]) == 1
