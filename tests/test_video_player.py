"""Tests for client/core/video_player.py.

This module plays a video's audio track through BASS directly on the
source file (via the bass_aac plugin, sound_lib/lib/x64/bass_aac.dll,
copied into client/lib/ the same way bassopus.dll already was) and renders
its picture by decoding a low-rate MJPEG frame sequence with the bundled
ffmpeg binary — see the module's own docstring for the full "why" (BASS
alone has no video-rendering capability at all).

extract_jpeg_frames() — the pure MJPEG-stream-parsing logic — needs no wx/
ffmpeg/audio device and is tested directly; it's the trickiest bit of
custom protocol handling in the module (ffmpeg's `image2pipe`/mjpeg output
is just JPEG images concatenated back to back with no separate framing
header).

TestEofDrainsTheQueueBeforeStopping exercises a real, live-reproduced bug:
the first version of _on_playback_finished() stopped the render timer the
instant ffmpeg's output pipe closed (EOF), even when several already-
decoded frames were still sitting in the bounded queue waiting to be drawn
— cutting off the last ~1 second of every video. Verified against a real
synthetic test clip (ffmpeg lavfi testsrc) during development: 16/24 frames
rendered before the fix, 24/24 after. These tests pin the fixed behaviour
using a real wx.Timer (needs a running wx.App) but no ffmpeg process or
audio device — frames/EOF are injected directly into the player's internal
queue/flag instead.
"""

import queue

import pytest

from core.video_player import extract_jpeg_frames, VideoPlayer


def _jpeg(payload: bytes) -> bytes:
    """A minimal fake JPEG: SOI + payload + EOI. Not a real decodable
    image, but the framing logic under test only ever looks at the marker
    bytes, never the payload. Only safe for extract_jpeg_frames() tests
    below, which never actually decode it — see _real_jpeg_bytes() for why
    _on_timer()'s tests (which DO decode, via wx.Image) can't use this."""
    return b"\xff\xd8" + payload + b"\xff\xd9"


def _real_jpeg_bytes(wx_app) -> bytes:
    """A genuinely valid, decodable 2x2 JPEG — unlike _jpeg() above, needed
    anywhere a test feeds a frame through VideoPlayer._on_timer(), which
    decodes it for real via wx.Image(..., wx.BITMAP_TYPE_JPEG). Feeding
    that decoder deliberately-malformed bytes (_jpeg()'s SOI+garbage+EOI)
    is exactly what test_video_player.py used to do here — caught as a
    normal Python exception (and silently ignored) most of the time, but
    crashed the whole pytest *process* on GitHub Actions' headless Windows
    runner: pytest's own "N passed" summary printed successfully, then the
    process died with a non-zero exit code moments later with no
    traceback — reproduced live via two failed release builds in a row,
    bisected down to specifically the tests that fed garbage into
    _on_timer(). A real (if trivial) JPEG removes the malformed-input path
    entirely instead of trying to make the crash itself survivable.
    """
    import os
    import tempfile
    import wx
    img = wx.Image(2, 2)
    img.SetRGB(0, 0, 255, 0, 0)
    img.SetRGB(1, 0, 0, 255, 0)
    img.SetRGB(0, 1, 0, 0, 255)
    img.SetRGB(1, 1, 255, 255, 0)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    try:
        img.SaveFile(tmp.name, wx.BITMAP_TYPE_JPEG)
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp.name)


class TestExtractJpegFrames:
    def test_empty_buffer_yields_nothing(self):
        frames, remainder = extract_jpeg_frames(b"")
        assert frames == []
        assert remainder == b""

    def test_a_single_complete_frame(self):
        frame = _jpeg(b"one-frame-of-pixels")
        frames, remainder = extract_jpeg_frames(frame)
        assert frames == [frame]
        assert remainder == b""

    def test_multiple_back_to_back_frames(self):
        f1 = _jpeg(b"frame1")
        f2 = _jpeg(b"frame2")
        f3 = _jpeg(b"frame3")
        frames, remainder = extract_jpeg_frames(f1 + f2 + f3)
        assert frames == [f1, f2, f3]
        assert remainder == b""

    def test_a_partial_trailing_frame_is_kept_as_remainder(self):
        """Simulates the realistic case: a chunk boundary lands mid-frame —
        the incomplete frame must NOT be emitted yet, and must survive to
        be completed once more bytes arrive."""
        complete = _jpeg(b"done")
        partial  = b"\xff\xd8" + b"still-arriving"  # no EOI yet
        frames, remainder = extract_jpeg_frames(complete + partial)
        assert frames == [complete]
        assert remainder == partial

    def test_the_remainder_completes_correctly_on_the_next_call(self):
        """Two-chunk simulation: first call leaves a partial frame as
        remainder, caller re-feeds remainder+next_chunk, the frame comes out
        whole."""
        first_chunk = b"\xff\xd8" + b"half"
        frames1, remainder1 = extract_jpeg_frames(first_chunk)
        assert frames1 == []
        assert remainder1 == first_chunk

        second_chunk = remainder1 + b"-more" + b"\xff\xd9"
        frames2, remainder2 = extract_jpeg_frames(second_chunk)
        assert frames2 == [b"\xff\xd8" + b"half-more" + b"\xff\xd9"]
        assert remainder2 == b""

    def test_garbage_before_the_first_soi_is_dropped(self):
        frame = _jpeg(b"payload")
        frames, remainder = extract_jpeg_frames(b"\x00\x01garbage" + frame)
        assert frames == [frame]
        assert remainder == b""

    def test_no_soi_at_all_returns_everything_as_remainder(self):
        junk = b"not a jpeg stream at all"
        frames, remainder = extract_jpeg_frames(junk)
        assert frames == []
        assert remainder == junk


class _FakeMainWindow:
    """Never actually reached by these tests (no real ffmpeg/BASS calls
    happen), but VideoPlayer.__init__ doesn't touch it either — only kept
    for API completeness."""
    pass


_created_players = []


def _make_player(wx_app):
    import wx
    frame = wx.Frame(None)
    bitmap = wx.StaticBitmap(frame)
    player = VideoPlayer(_FakeMainWindow(), bitmap)
    _created_players.append(player)
    return player


@pytest.fixture(autouse=True)
def _destroy_leftover_frames():
    """Every test here builds its own throwaway wx.Frame via _make_player()
    and none of them ever call player.stop()/frame.Destroy() — each one
    left its wx.Timer armed and its wx.Frame/wx.StaticBitmap alive for the
    rest of the process. That went unnoticed locally, but wx.App tearing
    down with a still-running wx.Timer bound to a window that's about to
    be destroyed crashed the whole pytest process on GitHub Actions'
    headless Windows runner: pytest's own "N passed" summary printed
    successfully, then the process died with a non-zero exit code ~2
    seconds later with no traceback at all — reproduced live via two
    failed release builds in a row, bisected down to this file
    specifically. stop() first (so no armed Timer survives to fire against
    a window that's mid-destruction), then Destroy() every top-level
    window (not just the one this test happened to create — a prior
    test's leak would otherwise still be sitting there).
    """
    yield
    import wx
    for player in _created_players:
        try:
            player.stop()
        except Exception:
            pass
    _created_players.clear()
    for win in list(wx.GetTopLevelWindows()):
        try:
            win.Destroy()
        except Exception:
            pass


class TestEofDrainsTheQueueBeforeStopping:
    """Regression test for a real bug found while manually verifying this
    module against a live ffmpeg-generated test clip — see module docstring."""

    def test_queued_frames_still_render_after_eof_is_signalled(self, wx_app):
        player = _make_player(wx_app)
        real_jpeg = _real_jpeg_bytes(wx_app)
        player._frame_queue.put(real_jpeg)
        player._frame_queue.put(real_jpeg)
        player._eof_reached = True
        player.is_playing = True

        # First tick: a queued frame is still there — must render it, not
        # stop, even though EOF has already been signalled.
        player._on_timer(None)
        assert player.is_playing is True
        assert player._frame_queue.qsize() == 1

        player._on_timer(None)
        assert player.is_playing is True
        assert player._frame_queue.qsize() == 0

    def test_stops_only_once_the_queue_is_actually_empty_and_eof_was_seen(self, wx_app):
        player = _make_player(wx_app)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)  # queue already empty + eof -> stop now

        assert player.is_playing is False
        assert player._timer.IsRunning() is False

    def test_an_empty_queue_without_eof_does_not_stop(self, wx_app):
        """Just a momentary gap between frames arriving — not the end of
        the stream — must not be mistaken for playback finishing."""
        player = _make_player(wx_app)
        player.is_playing = True
        player._eof_reached = False

        player._on_timer(None)

        assert player.is_playing is True

    def test_a_stale_generation_does_not_signal_eof_onto_a_newer_playback(self, wx_app):
        """An old (stopped/replaced) reader thread finishing late must not
        be able to mark a NEWER load_and_play() as finished."""
        player = _make_player(wx_app)
        old_generation = player._generation
        player._generation += 1  # simulate a second load_and_play() having started
        player.is_playing = True

        # This is exactly what _read_frames()'s finally-block does, called
        # with the OLD generation number it captured before the newer video
        # started.
        if old_generation == player._generation:
            player._eof_reached = True

        assert player._eof_reached is False


class _FakeAudioCtrl:
    """Stands in for the BASS channel (_audio_stream/_tempo_ctrl) — only
    the is_active() method _audio_still_active() actually calls."""

    def __init__(self, active_value):
        self._active_value = active_value

    def is_active(self):
        return self._active_value


class TestAudioOnlyPlaybackDoesNotFinishWhileAudioIsStillPlaying:
    """Regression: for an audio-only source (a status/message with no
    video stream at all), ffmpeg's frame pipe has nothing to output and
    reaches EOF almost immediately — long before BASS is actually done
    playing. The old code treated frame-EOF alone as "playback finished",
    flipping is_playing back to False moments after starting — reported
    live as "pause always restarts instead of pausing" for audio
    statuses, since is_playing had already gone False on its own by the
    time the user clicked pause."""

    def test_does_not_finish_while_bass_reports_still_active(self, wx_app):
        from sound_lib.external.pybass import BASS_ACTIVE_PLAYING

        player = _make_player(wx_app)
        player._audio_stream = _FakeAudioCtrl(BASS_ACTIVE_PLAYING)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)

        assert player.is_playing is True

    def test_does_not_finish_while_bass_reports_paused(self, wx_app):
        """A channel the user just paused reports BASS_ACTIVE_PAUSED, not
        BASS_ACTIVE_PLAYING — must still count as "not finished", or a
        deliberate pause would get wrongly treated as the end of
        playback."""
        from sound_lib.external.pybass import BASS_ACTIVE_PAUSED

        player = _make_player(wx_app)
        player._audio_stream = _FakeAudioCtrl(BASS_ACTIVE_PAUSED)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)

        assert player.is_playing is True

    def test_finishes_once_bass_reports_fully_stopped(self, wx_app):
        from sound_lib.external.pybass import BASS_ACTIVE_STOPPED

        player = _make_player(wx_app)
        player._audio_stream = _FakeAudioCtrl(BASS_ACTIVE_STOPPED)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)

        assert player.is_playing is False

    def test_tempo_ctrl_takes_priority_over_audio_stream_when_both_are_set(self, wx_app):
        from sound_lib.external.pybass import BASS_ACTIVE_PLAYING, BASS_ACTIVE_STOPPED

        player = _make_player(wx_app)
        player._audio_stream = _FakeAudioCtrl(BASS_ACTIVE_STOPPED)
        player._tempo_ctrl = _FakeAudioCtrl(BASS_ACTIVE_PLAYING)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)

        assert player.is_playing is True

    def test_no_audio_ctrl_at_all_finishes_immediately_like_before(self, wx_app):
        """Nothing ever started (or a genuine video whose audio already
        tore down) — must not hang waiting for an audio channel that
        doesn't exist."""
        player = _make_player(wx_app)
        player._eof_reached = True
        player.is_playing = True

        player._on_timer(None)

        assert player.is_playing is False


class TestIsPlayingReflectsStopEvent:
    """is_playing used to be a plain attribute that stop() cleared at the
    very end of its own teardown — a caller checking it mid-stop() (e.g.
    two rapid toggle_pause() calls racing a stop() triggered by switching
    statuses/conversations) could observe a stale "still playing" for that
    window. It's now a property backed by _is_active, additionally gated
    on _stop_event — set at the very START of stop(), before any teardown
    happens."""

    def test_true_after_being_set(self, wx_app):
        player = _make_player(wx_app)
        player.is_playing = True
        assert player.is_playing is True

    def test_false_once_stop_event_is_set_even_if_is_active_was_never_cleared(self, wx_app):
        player = _make_player(wx_app)
        player.is_playing = True
        player._stop_event.set()  # what stop() does first, before teardown
        assert player.is_playing is False

    def test_stop_clears_it(self, wx_app):
        player = _make_player(wx_app)
        player.is_playing = True
        player.stop()
        assert player.is_playing is False
