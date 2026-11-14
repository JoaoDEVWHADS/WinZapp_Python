"""The media cleanup engine: what it lists, and that it deletes only that."""
import os

import pytest

from core import media_cleanup as cleanup


def _msg(msg_id, msg_type="imageMessage", **extra):
    msg = {"messageType": msg_type, "key": {"id": msg_id, "fromMe": False},
           "message": {msg_type: {}}}
    msg.update(extra)
    return msg


@pytest.fixture
def cache(tmp_path):
    media = tmp_path / "media"
    voice = tmp_path / "voice_messages"
    media.mkdir()
    voice.mkdir()

    def path_for(msg_type, msg_id):
        if msg_type == "audioMessage":
            return str(voice / f"{msg_id}.msv")
        return str(media / f"{msg_id}.wzmedia")

    def put(name_dir, name, size):
        path = (media if name_dir == "media" else voice) / name
        path.write_bytes(b"x" * size)
        return str(path)

    return {"media": media, "voice": voice, "path_for": path_for, "put": put,
            "roots": [str(media), str(voice)]}


def test_it_lists_only_cached_files_of_the_wanted_categories(cache):
    cache["put"]("media", "P1.wzmedia", 1000)
    cache["put"]("media", "V1.wzmedia", 5000)
    cache["put"]("voice", "A1.msv", 300)
    records = {"chat@s.whatsapp.net": [
        _msg("P1"), _msg("V1", "videoMessage"), _msg("A1", "audioMessage"),
        _msg("P2"),                      # never downloaded
    ]}
    preview = cleanup.scan(records, ["photos", "videos", "audios"], path_for=cache["path_for"])
    assert sorted(c.message_id for c in preview.candidates) == ["A1", "P1", "V1"]
    assert preview.total_bytes == 6300 and preview.chats_affected == 1
    only_photos = cleanup.scan(records, ["photos"], path_for=cache["path_for"])
    assert [c.message_id for c in only_photos.candidates] == ["P1"]


def test_a_voice_note_is_its_own_category_not_audio(cache):
    cache["put"]("voice", "N1.msv", 10)
    note = _msg("N1", "audioMessage")
    note["message"]["audioMessage"] = {"ptt": True}
    records = {"c": [note]}
    assert cleanup.scan(records, ["audios"], path_for=cache["path_for"]).total_files == 0
    found = cleanup.scan(records, ["voice_messages"], path_for=cache["path_for"])
    assert [c.category for c in found.candidates] == ["voice_messages"]


def test_minimum_size_and_one_file_for_several_messages(cache):
    cache["put"]("media", "P1.wzmedia", 100)
    cache["put"]("media", "P2.wzmedia", 5000)
    records = {"a": [_msg("P1"), _msg("P2")], "b": [_msg("P2")]}
    preview = cleanup.scan(records, ["photos"], min_size_bytes=1000, path_for=cache["path_for"])
    assert [c.message_id for c in preview.candidates] == ["P2"]


def test_unsent_and_failed_messages_keep_their_files(cache):
    cache["put"]("media", "L1.wzmedia", 10)
    cache["put"]("media", "F1.wzmedia", 10)
    pending = _msg("L1", _local_pending=True)
    failed = _msg("F1", _send_failed=True)
    preview = cleanup.scan({"c": [pending, failed]}, ["photos"], path_for=cache["path_for"])
    assert preview.total_files == 0


def test_execute_deletes_exactly_the_previewed_files(cache):
    kept = cache["put"]("media", "KEEP.wzmedia", 10)
    gone = cache["put"]("media", "P1.wzmedia", 100)
    preview = cleanup.scan({"c": [_msg("P1")]}, ["photos"], path_for=cache["path_for"])
    # A file that appears after the scan is not part of what was confirmed.
    late = cache["put"]("media", "P3.wzmedia", 10)
    progress = []
    stats = cleanup.execute(preview, cache["roots"],
                            progress_cb=lambda done, total: progress.append((done, total)))
    assert stats.files_deleted == 1 and stats.bytes_freed == 100
    assert not os.path.exists(gone) and os.path.exists(kept) and os.path.exists(late)
    assert progress == [(1, 1)]


def test_execute_never_touches_a_file_outside_the_cache_folders(cache, tmp_path):
    outside = tmp_path / "Documents" / "mine.pdf"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    preview = cleanup.CleanupPreview([cleanup.CleanupCandidate(
        "c", "X", "documents", 1, str(outside))])
    stats = cleanup.execute(preview, cache["roots"])
    assert outside.exists() and stats.files_deleted == 0 and stats.files_failed == 1


def test_a_file_already_gone_is_counted_and_cancel_stops(cache):
    p1 = cache["put"]("media", "P1.wzmedia", 10)
    cache["put"]("media", "P2.wzmedia", 10)
    preview = cleanup.scan({"c": [_msg("P1"), _msg("P2")]}, ["photos"], path_for=cache["path_for"])
    os.remove(p1)
    stats = cleanup.execute(preview, cache["roots"])
    assert stats.files_missing == 1 and stats.files_deleted == 1

    cache["put"]("media", "P1.wzmedia", 10)
    cache["put"]("media", "P2.wzmedia", 10)
    preview = cleanup.scan({"c": [_msg("P1"), _msg("P2")]}, ["photos"], path_for=cache["path_for"])
    stats = cleanup.execute(preview, cache["roots"], should_cancel=lambda: True)
    assert stats.cancelled and stats.files_deleted == 0


def test_execute_reports_the_ids_it_deleted(cache):
    cache["put"]("media", "P1.wzmedia", 10)
    preview = cleanup.scan({"c": [_msg("P1"), _msg("P2")]}, ["photos"], path_for=cache["path_for"])
    stats = cleanup.execute(preview, cache["roots"])
    assert stats.deleted_ids == ["P1"]


# ── the index of cleaned media ────────────────────────────────────────────

def test_the_index_remembers_across_instances_and_clears(tmp_path):
    from core.media_cleaned import CleanedMediaIndex

    path = str(tmp_path / "acct" / "media_cleaned.json")
    index = CleanedMediaIndex(lambda: path)
    assert not index.contains("A1") and len(index) == 0
    assert index.add_many(["A1", "B2", "", None]) == 2
    assert index.add_many(["A1"]) == 0
    assert index.contains("A1") and index.contains("B2")

    again = CleanedMediaIndex(lambda: path)
    assert again.contains("A1") and len(again) == 2

    again.clear()
    assert not again.contains("A1")
    assert not os.path.exists(path)
    assert not CleanedMediaIndex(lambda: path).contains("A1")


def test_the_index_follows_the_accounts_folder(tmp_path):
    from core.media_cleaned import CleanedMediaIndex

    current = {"path": str(tmp_path / "a" / "media_cleaned.json")}
    index = CleanedMediaIndex(lambda: current["path"])
    index.add_many(["X"])
    current["path"] = str(tmp_path / "b" / "media_cleaned.json")
    assert not index.contains("X")          # another account, another list
    index.add_many(["Y"])
    current["path"] = str(tmp_path / "a" / "media_cleaned.json")
    assert index.contains("X") and not index.contains("Y")


def test_a_damaged_index_file_reads_as_empty(tmp_path):
    from core.media_cleaned import CleanedMediaIndex

    path = tmp_path / "media_cleaned.json"
    path.write_text("{ not json", encoding="utf-8")
    index = CleanedMediaIndex(lambda: str(path))
    assert not index.contains("A") and len(index) == 0
    assert index.add_many(["A"]) == 1 and index.contains("A")


def test_f5_keeps_the_cleaned_index_and_a_logout_clears_it(tmp_path, monkeypatch):
    """The only way cleaned media comes back is a logout or a new pairing."""
    import types

    import main_window.media as media_module
    from core.media_cleaned import CleanedMediaIndex

    path = str(tmp_path / "media_cleaned.json")
    monkeypatch.setattr(media_module, "data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    window = types.SimpleNamespace(_media_failed_ids={"x": 1})
    window._media_cleaned_idx = CleanedMediaIndex(lambda: path)
    window._media_cleaned_index = lambda: window._media_cleaned_idx
    window.is_media_cleaned = lambda msg_id: media_module.MediaMixin.is_media_cleaned(window, msg_id)
    window.mark_media_cleaned = lambda ids: window._media_cleaned_idx.add_many(ids)
    window.mark_media_cleaned(["A1"])

    # F5 forgets the expired-link ids and nothing else.
    media_module.MediaMixin._forget_media_failures(window)
    assert window._media_failed_ids == {}
    assert window.is_media_cleaned("A1")

    # A message id in WhatsApp's composite form is reduced like the cache file's.
    assert window.is_media_cleaned("false_5511@s.whatsapp.net_A1")

    # A logout or a new pairing is the one thing that empties it.
    media_module.MediaMixin._forget_cleaned_media(window)
    assert not window.is_media_cleaned("A1")
