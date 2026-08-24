"""Tests for a measured video duration surviving a resync and a restart.

Reported live: playing a video with no stated duration filled the length in on
the list, and closing and reopening the app brought it back without one.

A duration WinZapp measures from the file is not something the server knows —
WhatsApp Web keeps handing that message over with duration 0 — so every path
that refreshes a chat from the API used to erase it:

* sync_chat_messages() replaces the in-memory records with the API copy;
* every one of those paths then batch-inserts the API copy over the stored
  rows, which is what made it survive nothing at all across restarts.

Two rules close it, one per side of the same fact:

* DatabaseManager._with_known_video_duration() — at the single point every
  write passes through, an incoming video that states no duration keeps the
  one already on the row. No sync path can forget it.
* carry_over_video_durations() — the same rule for the records held in
  memory, so the length doesn't vanish from the open list until the next
  restart.

A message's video is immutable, so a duration measured once stays valid for
that message id; a copy that DOES state a duration always wins, since that is
the sender's own answer finally arriving.
"""

import pytest

from core.utils import carry_over_video_durations, video_seconds


def _video_msg(mid="VID1", seconds=0, jid="grupo@g.us"):
    return {
        "key": {"id": mid, "remoteJid": jid, "fromMe": False},
        "messageType": "videoMessage",
        "messageTimestamp": 1000,
        "message": {"videoMessage": {"seconds": seconds, "mimetype": "video/mp4"}},
    }


def _seconds_of(msg):
    return video_seconds((msg.get("message") or {}).get("videoMessage"))


# =============================================================================
#  In-memory side — carry_over_video_durations()
# =============================================================================


class TestCarryOverVideoDurations:
    def test_a_measured_length_survives_the_api_copy_replacing_the_record(self):
        api = [_video_msg(seconds=0)]
        local = [_video_msg(seconds=422)]

        assert carry_over_video_durations(api, local) == 1
        assert _seconds_of(api[0]) == 422

    def test_a_length_the_sender_finally_states_wins(self):
        """Not a conflict to protect against — that is the real answer
        arriving, and it outranks anything measured locally."""
        api = [_video_msg(seconds=30)]
        local = [_video_msg(seconds=422)]

        assert carry_over_video_durations(api, local) == 0
        assert _seconds_of(api[0]) == 30

    def test_only_the_matching_message_is_touched(self):
        api = [_video_msg("A", seconds=0), _video_msg("B", seconds=0)]
        local = [_video_msg("B", seconds=17)]

        carry_over_video_durations(api, local)

        assert _seconds_of(api[0]) is None
        assert _seconds_of(api[1]) == 17

    def test_a_local_record_with_no_measurement_carries_nothing(self):
        api = [_video_msg(seconds=0)]
        assert carry_over_video_durations(api, [_video_msg(seconds=0)]) == 0
        assert _seconds_of(api[0]) is None

    def test_non_video_records_are_ignored_on_both_sides(self):
        audio = {"key": {"id": "AUD1"}, "messageType": "audioMessage",
                 "message": {"audioMessage": {"seconds": 0}}}
        assert carry_over_video_durations([audio], [dict(audio)]) == 0
        assert audio["message"]["audioMessage"]["seconds"] == 0

    @pytest.mark.parametrize("junk", [None, [], [None, "texto", 42]])
    def test_junk_input_is_tolerated(self, junk):
        assert carry_over_video_durations(junk, junk) == 0
        assert carry_over_video_durations([_video_msg()], junk) == 0


# =============================================================================
#  Database side — DatabaseManager._with_known_video_duration()
# =============================================================================


class TestStoredDurationIsNotOverwritten:
    async def test_a_resync_copy_cannot_erase_a_measured_duration(self, in_memory_db):
        """The restart case, end to end: the length is stored, the server's
        copy comes back stating none, and reading the chat back still has it."""
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) == 422

    async def test_batch_insert_keeps_it_too(self, in_memory_db):
        """Every sync path inserts in batches — that is the write that
        actually ran on restart."""
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))

        await in_memory_db.insert_messages_batch("grupo@g.us", [_video_msg(seconds=0)])

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) == 422

    async def test_a_stated_duration_replaces_the_measured_one(self, in_memory_db):
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=30))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) == 30

    async def test_a_first_insert_with_no_duration_stores_none(self, in_memory_db):
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) is None

    async def test_the_measurement_written_later_is_stored(self, in_memory_db):
        """The forward direction: the video arrives stating nothing, playback
        measures it, and that write is what has to land."""
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=137))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) == 137

    async def test_another_chats_copy_of_the_same_id_is_not_consulted(self, in_memory_db):
        """Rows are keyed (message_id, remote_jid); the lookup must stay
        inside the chat being written."""
        await in_memory_db.insert_message("outro@g.us", _video_msg(seconds=422))

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) is None

    async def test_a_message_with_no_id_is_still_rejected(self, in_memory_db):
        """The id-less guard runs after the duration lookup now — it must
        still drop the record rather than store it."""
        msg = _video_msg(seconds=0)
        msg["key"]["id"] = ""

        await in_memory_db.insert_message("grupo@g.us", msg)

        assert await in_memory_db.get_messages("grupo@g.us") == []

    async def test_a_deleted_message_takes_its_duration_with_it(self, in_memory_db):
        """The measurement lives inside the message row's own JSON, nowhere
        else — deleting the message (for me, for everyone, mirrored from the
        phone, or a cleared chat) must leave nothing behind for a later copy
        of the same id to inherit."""
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))
        await in_memory_db.delete_message("grupo@g.us", "VID1")

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) is None

    async def test_a_revoke_does_not_bring_the_duration_back(self, in_memory_db):
        """"Apagar para todos" received live is the one deletion that KEEPS
        the row: _apply_remote_revoke() rewrites it as a protocolMessage so it
        still reads as "Mensagem apagada" in the timeline. The video (and its
        measured length) must go with the content — this rule only ever fills
        in a video that is still a video."""
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))

        revoked = {
            "key": {"id": "VID1", "remoteJid": "grupo@g.us", "fromMe": False},
            "messageType": "protocolMessage",
            "messageTimestamp": 1000,
            "message": {"protocolMessage": {"type": 3}},
        }
        await in_memory_db.insert_message("grupo@g.us", revoked)

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert stored["messageType"] == "protocolMessage"
        assert "videoMessage" not in stored["message"]

    async def test_clearing_a_chat_leaves_nothing_to_inherit(self, in_memory_db):
        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=422))
        await in_memory_db.delete_chat_messages("grupo@g.us")

        await in_memory_db.insert_message("grupo@g.us", _video_msg(seconds=0))

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert _seconds_of(stored) is None

    async def test_an_audio_message_is_left_to_its_own_rule(self, in_memory_db):
        """A voice note of 0 seconds is a real answer — nothing here may
        resurrect an older length over it."""
        audio = {"key": {"id": "AUD1", "remoteJid": "grupo@g.us"},
                 "messageType": "audioMessage", "messageTimestamp": 1,
                 "message": {"audioMessage": {"seconds": 12}}}
        await in_memory_db.insert_message("grupo@g.us", audio)

        audio_zero = {**audio, "message": {"audioMessage": {"seconds": 0}}}
        await in_memory_db.insert_message("grupo@g.us", audio_zero)

        [stored] = await in_memory_db.get_messages("grupo@g.us")
        assert stored["message"]["audioMessage"]["seconds"] == 0
