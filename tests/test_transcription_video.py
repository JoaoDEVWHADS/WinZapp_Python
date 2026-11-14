"""Transcribing a video: its sound track goes through the same conversion as a
voice note, and a video with no sound says so in its own words."""

from core.transcription import audio_prep, errors

SILENT_VIDEO_LOG = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '<input>':
  Duration: 00:00:05.00, start: 0.000000, bitrate: 512 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 720x1280, 30 fps
Output #0, wav, to '<output>':
Output file #0 does not contain any stream
"""

VIDEO_WITH_SOUND_LOG = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '<input>':
  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 720x1280
  Stream #0:1[0x2](und): Audio: aac (LC), 44100 Hz, stereo, fltp, 128 kb/s
Output file #0 does not contain any stream
"""

UNKNOWN_LOG = "<input>: Invalid data found when processing input\n"


class TestASilentVideo:
    def test_it_is_recognised_from_ffmpegs_log(self):
        assert audio_prep.has_picture_but_no_sound(SILENT_VIDEO_LOG)
        assert not audio_prep.has_picture_but_no_sound(VIDEO_WITH_SOUND_LOG)
        assert not audio_prep.has_picture_but_no_sound(UNKNOWN_LOG)
        assert not audio_prep.has_picture_but_no_sound("")
        assert not audio_prep.has_picture_but_no_sound(None)

    def test_it_gets_its_own_code(self):
        error = audio_prep._classify_ffmpeg_failure(1, SILENT_VIDEO_LOG)
        assert error.code == errors.NO_AUDIO_TRACK

    def test_a_video_with_sound_that_fails_keeps_the_old_answers(self):
        assert audio_prep._classify_ffmpeg_failure(1, VIDEO_WITH_SOUND_LOG).code == (
            errors.UNSUPPORTED_AUDIO_FORMAT)
        assert audio_prep._classify_ffmpeg_failure(1, UNKNOWN_LOG).code == (
            errors.UNSUPPORTED_AUDIO_FORMAT)

    def test_the_code_has_a_sentence(self):
        assert errors.NO_AUDIO_TRACK in errors.ERROR_CODES
        assert errors.error_i18n_key(errors.NO_AUDIO_TRACK) == "transcription_error_no_audio_track"

    def test_it_does_not_pause_the_automatic_queue(self):
        from core.transcription import auto_queue
        assert not auto_queue.pauses_the_queue(errors.TranscriptionError(errors.NO_AUDIO_TRACK, "x"))


class TestTheConversionDropsThePicture:
    def test_ffmpeg_is_told_to_ignore_the_video_stream(self, monkeypatch, tmp_path):
        seen = {}

        class _Process:
            def wait(self, timeout=None):
                return 0

        def popen(command, **kwargs):
            seen["command"] = command
            return _Process()

        monkeypatch.setattr(audio_prep.subprocess, "Popen", popen)
        audio_prep._run_ffmpeg("ffmpeg", str(tmp_path / "in.mp4"), str(tmp_path / "out.wav"), 10, None)
        assert "-vn" in seen["command"]
