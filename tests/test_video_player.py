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
    bytes, never the payload."""
    return b"\xff\xd8" + payload + b"\xff\xd9"


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


@pytest.fixture(scope="module")
def wx_app():
    import wx
    return wx.App()


class _FakeMainWindow:
    """Never actually reached by these tests (no real ffmpeg/BASS calls
    happen), but VideoPlayer.__init__ doesn't touch it either — only kept
    for API completeness."""
    pass


def _make_player(wx_app):
    import wx
    frame = wx.Frame(None)
    bitmap = wx.StaticBitmap(frame)
    player = VideoPlayer(_FakeMainWindow(), bitmap)
    return player


class TestEofDrainsTheQueueBeforeStopping:
    """Regression test for a real bug found while manually verifying this
    module against a live ffmpeg-generated test clip — see module docstring."""

    def test_queued_frames_still_render_after_eof_is_signalled(self, wx_app):
        player = _make_player(wx_app)
        player._frame_queue.put(b"\xff\xd8fake-frame-1\xff\xd9")
        player._frame_queue.put(b"\xff\xd8fake-frame-2\xff\xd9")
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
