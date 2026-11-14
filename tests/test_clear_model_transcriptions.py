"""Clearing every stored transcription of one model, across all conversations.

The text sits inside the encrypted message_json, so the database reads, edits
and rewrites the rows that can hold one. What must hold: only that model's
results go, the others stay and one of them becomes the message's current one
at a later decision, a message left with nothing gets a tombstone, nothing else
about a row changes, and the scan does not hold the write lock for the whole
database.
"""

import asyncio

import pytest

from core.transcription import stored
from core.transcription.stored import TRANSCRIPTION_KEY

JID = "5511988887777@s.whatsapp.net"
JID2 = "5511977776666@s.whatsapp.net"


def _audio(mid, jid=JID, msg_type="audioMessage", status=3, **extra):
    msg = {
        "key": {"id": mid, "remoteJid": jid, "fromMe": False},
        "messageType": msg_type,
        "messageTimestamp": 1_700_000_000,
        "status": status,
        "message": {msg_type: {"seconds": 7, "mimetype": "audio/ogg; codecs=opus"}},
    }
    msg.update(extra)
    return msg


def _rec(model, text, at, backend="faster_whisper"):
    return {"text": text, "language": "pt", "language_probability": 0.9,
            "model_id": model, "backend": backend, "vad_used": True, "at": at}


async def _record(db, mid, jid=JID):
    [msg] = [m for m in await db.get_messages(jid) if m["key"]["id"] == mid]
    return msg


async def _raw_row(db, mid, jid=JID):
    cursor = await db._conn.execute(
        "SELECT * FROM messages WHERE remote_jid=? AND message_id=?", (jid, mid))
    return await cursor.fetchone()


class TestWhatGoes:
    async def test_a_message_with_only_that_model_gets_a_tombstone(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "olá", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 1

        msg = await _record(in_memory_db, "A")
        assert stored.saved_transcription(msg) is None
        assert msg[TRANSCRIPTION_KEY]["deleted"] is True
        assert msg[TRANSCRIPTION_KEY]["at"] >= 100.0

    async def test_another_models_result_is_left_alone(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("medium", "olá", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 0

        msg = await _record(in_memory_db, "A")
        assert stored.saved_transcription(msg)["text"] == "olá"
        assert msg[TRANSCRIPTION_KEY]["at"] == 5.0

    async def test_with_two_models_the_other_one_becomes_current(self, in_memory_db):
        value = stored.with_result(_rec("small", "a", 5.0), _rec("medium", "b", 9.0))
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: value}))

        await in_memory_db.clear_model_transcriptions("medium", None, 100.0)

        msg = await _record(in_memory_db, "A")
        saved = stored.saved_transcription(msg)
        assert saved["text"] == "a" and saved["model_id"] == "small"
        assert stored.made_time(saved) == 5.0
        assert stored.saved_transcription(msg, ("auto", "medium")) is None

    async def test_every_conversation_is_cleared(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "x", 5.0)}))
        await in_memory_db.insert_message(JID2, _audio("B", jid=JID2, **{TRANSCRIPTION_KEY: _rec("small", "y", 5.0)}))
        await in_memory_db.insert_message(JID2, _audio("C", jid=JID2, **{TRANSCRIPTION_KEY: _rec("tiny", "z", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 2

        assert stored.saved_transcription(await _record(in_memory_db, "A")) is None
        assert stored.saved_transcription(await _record(in_memory_db, "B", JID2)) is None
        assert stored.saved_transcription(await _record(in_memory_db, "C", JID2))["text"] == "z"

    async def test_a_backend_scopes_it(self, in_memory_db):
        value = stored.with_result(
            _rec("small", "x", 1.0, backend="faster_whisper"),
            _rec("small", "y", 2.0, backend="whisper_cpp"))
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: value}))

        assert await in_memory_db.clear_model_transcriptions("small", "whisper_cpp", 100.0) == 1

        saved = stored.saved_transcription(await _record(in_memory_db, "A"))
        assert saved["backend"] == "faster_whisper"

    async def test_messages_without_a_transcription_are_untouched(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("PLAIN"))
        before = (await _raw_row(in_memory_db, "PLAIN"))["message_json"]

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 0

        assert (await _raw_row(in_memory_db, "PLAIN"))["message_json"] == before

    async def test_text_messages_are_not_even_read(self, in_memory_db):
        text = {"key": {"id": "T", "remoteJid": JID, "fromMe": False},
                "messageType": "conversation", "messageTimestamp": 1,
                "message": {"conversation": "oi"}}
        await in_memory_db.insert_message(JID, text)

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 0

    async def test_an_empty_model_id_clears_nothing(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "x", 5.0)}))
        assert await in_memory_db.clear_model_transcriptions("", None, 100.0) == 0
        assert stored.saved_transcription(await _record(in_memory_db, "A")) is not None


class TestNothingElseChanges:
    async def test_the_status_and_the_other_columns_stay(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", status=4, **{TRANSCRIPTION_KEY: _rec("small", "x", 5.0)}))
        before = await _raw_row(in_memory_db, "A")

        await in_memory_db.clear_model_transcriptions("small", None, 100.0)

        after = await _raw_row(in_memory_db, "A")
        for column in ("message_id", "remote_jid", "from_me", "participant",
                       "message_type", "timestamp", "status"):
            assert after[column] == before[column]
        msg = await _record(in_memory_db, "A")
        assert msg["status"] == 4 and msg["key"]["id"] == "A"

    async def test_the_cleared_text_is_gone_from_the_disk_form_too(self, in_memory_db):
        secret = "zzqq o cofre fica na terceira gaveta yyww"
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", secret, 5.0)}))

        await in_memory_db.clear_model_transcriptions("small", None, 100.0)

        row = await _raw_row(in_memory_db, "A")
        assert secret not in in_memory_db._decrypt_json(row["message_json"]).__repr__()

    async def test_a_stale_copy_cannot_bring_it_back(self, in_memory_db):
        old = _rec("small", "velha", 5.0)
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: old}))
        await in_memory_db.clear_model_transcriptions("small", None, 100.0)

        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: old}))

        assert stored.saved_transcription(await _record(in_memory_db, "A")) is None

    async def test_a_clock_set_back_still_beats_the_row(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "x", 5000.0)}))

        await in_memory_db.clear_model_transcriptions("small", None, 1.0)

        msg = await _record(in_memory_db, "A")
        assert msg[TRANSCRIPTION_KEY]["at"] > 5000.0


class TestTheScan:
    async def test_it_works_through_more_rows_than_one_chunk(self, in_memory_db, monkeypatch):
        monkeypatch.setattr(type(in_memory_db), "_CLEAR_TRANSCRIPTIONS_CHUNK", 7)
        for number in range(30):
            keep = number % 3 == 0
            model = "tiny" if keep else "small"
            await in_memory_db.insert_message(
                JID, _audio(f"M{number:03d}", **{TRANSCRIPTION_KEY: _rec(model, f"t{number}", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 20

        remaining = [m for m in await in_memory_db.get_messages(JID)
                     if stored.saved_transcription(m)]
        assert len(remaining) == 10

    async def test_the_write_lock_is_released_between_chunks(self, in_memory_db, monkeypatch):
        """A writer that arrives mid-scan gets in before the scan finishes."""
        monkeypatch.setattr(type(in_memory_db), "_CLEAR_TRANSCRIPTIONS_CHUNK", 5)
        for number in range(40):
            await in_memory_db.insert_message(
                JID, _audio(f"M{number:03d}", **{TRANSCRIPTION_KEY: _rec("small", "t", 5.0)}))
        order = []

        async def writer():
            await asyncio.sleep(0)
            await in_memory_db.insert_message(JID, _audio("LATE"))
            order.append("writer")

        async def scan():
            await in_memory_db.clear_model_transcriptions("small", None, 100.0)
            order.append("scan")

        await asyncio.gather(scan(), writer())

        assert order == ["writer", "scan"]
        assert await _record(in_memory_db, "LATE")

    async def test_the_scan_runs_twice_without_harm(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "x", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 1
        assert await in_memory_db.clear_model_transcriptions("small", None, 200.0) == 0

    async def test_a_row_that_cannot_be_decrypted_is_skipped(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("small", "x", 5.0)}))
        await in_memory_db._conn.execute(
            "UPDATE messages SET message_json=? WHERE message_id='A'", ("not-a-token",))
        await in_memory_db._conn.commit()
        await in_memory_db.insert_message(JID, _audio("B", **{TRANSCRIPTION_KEY: _rec("small", "y", 5.0)}))

        assert await in_memory_db.clear_model_transcriptions("small", None, 100.0) == 1


class TestClearingEveryModel:
    async def test_every_result_of_every_model_goes_in_every_chat(self, in_memory_db):
        both = stored.with_result(_rec("base", "um", 5.0), _rec("small", "dois", 6.0))
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: both}))
        await in_memory_db.insert_message(JID2, _audio("B", jid=JID2, **{TRANSCRIPTION_KEY: _rec("base", "três", 7.0)}))
        await in_memory_db.insert_message(JID, _audio("C"))

        assert await in_memory_db.clear_all_transcriptions(100.0) == 3

        for mid, jid in (("A", JID), ("B", JID2)):
            msg = await _record(in_memory_db, mid, jid)
            assert stored.saved_transcription(msg) is None
            assert msg[TRANSCRIPTION_KEY]["deleted"] is True
            assert msg[TRANSCRIPTION_KEY]["at"] >= 100.0
        assert TRANSCRIPTION_KEY not in await _record(in_memory_db, "C")

    async def test_nothing_stored_is_zero_and_changes_nothing(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A"))
        before = tuple(await _raw_row(in_memory_db, "A"))
        assert await in_memory_db.clear_all_transcriptions(100.0) == 0
        assert tuple(await _raw_row(in_memory_db, "A")) == before

    async def test_a_second_clear_finds_only_tombstones(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("base", "um", 5.0)}))
        assert await in_memory_db.clear_all_transcriptions(100.0) == 1
        assert await in_memory_db.clear_all_transcriptions(200.0) == 0

    async def test_a_stale_copy_cannot_bring_the_text_back(self, in_memory_db):
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("base", "um", 5.0)}))
        await in_memory_db.clear_all_transcriptions(100.0)
        await in_memory_db.insert_message(JID, _audio("A", **{TRANSCRIPTION_KEY: _rec("base", "um", 5.0)}))
        assert stored.saved_transcription(await _record(in_memory_db, "A")) is None

    async def test_more_rows_than_a_chunk_are_all_visited(self, in_memory_db, monkeypatch):
        monkeypatch.setattr(type(in_memory_db), "_CLEAR_TRANSCRIPTIONS_CHUNK", 3)
        for index in range(8):
            await in_memory_db.insert_message(
                JID, _audio(f"M{index}", **{TRANSCRIPTION_KEY: _rec("base", f"t{index}", 5.0)}))
        assert await in_memory_db.clear_all_transcriptions(100.0) == 8
