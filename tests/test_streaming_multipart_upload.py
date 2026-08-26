"""Regression tests for the real HTTP upload progress path."""

import pytest

from core.message_queue import MessageCancelled
from core.multipart_stream import MultipartSourceChanged, StreamingMultipartBody


def test_streaming_multipart_reports_monotonic_file_progress(tmp_path):
    payload = (b"0123456789abcdef" * 8192) + b"tail"
    path = tmp_path / "documento.bin"
    path.write_bytes(payload)
    seen = []

    body = StreamingMultipartBody(
        file_path=str(path),
        filename="documento.bin",
        mime_type="application/octet-stream",
        fields={"phone": ["5511999999999@c.us"], "type": "document"},
        progress_callback=seen.append,
        chunk_size=16 * 1024,
        boundary="----WinZappTest",
    )

    encoded = b"".join(body)
    assert len(encoded) == body.content_length == len(body)
    assert payload in encoded
    assert b'name="phone"' in encoded
    assert b'filename="documento.bin"' in encoded
    assert seen[0] == 0.0
    assert seen[-1] == 1.0
    assert seen == sorted(seen)
    assert any(0.0 < value < 1.0 for value in seen), (
        "progress must have real intermediate values; the old requests files= "
        "path jumped from 0 straight to 100 while preparing the body"
    )


def test_file_is_not_eagerly_read_during_body_construction(tmp_path):
    path = tmp_path / "large.zip"
    path.write_bytes(b"x" * 100_000)
    seen = []

    body = StreamingMultipartBody(
        file_path=str(path),
        filename=path.name,
        mime_type="application/zip",
        fields={"type": "document"},
        progress_callback=seen.append,
    )

    # Construction only stats the file and builds tiny framing bytes. The
    # callback starts when requests/urllib3 begins iterating the request body.
    assert seen == []
    it = iter(body)
    next(it)  # multipart fields/header only
    assert seen == [0.0]


def test_requests_keeps_the_streaming_body_unbuffered(tmp_path):
    import requests

    path = tmp_path / "payload.bin"
    path.write_bytes(b"z" * 200_000)
    body = StreamingMultipartBody(
        file_path=str(path),
        filename=path.name,
        mime_type="application/octet-stream",
        fields={"type": "document"},
    )
    prepared = requests.Request(
        "POST",
        "http://127.0.0.1:1/upload",
        data=body,
        headers={"Content-Type": body.content_type},
    ).prepare()
    assert prepared.body is body
    assert prepared.headers["Content-Length"] == str(body.content_length)


class TestCancellationActuallyStopsTheUpload:
    """Regression: MessageQueue signals a user cancellation by raising
    MessageCancelled from inside the progress_callback it hands to
    StreamingMultipartBody (see message_queue.py's _media_progress).
    _report() used to swallow every exception the callback raised,
    including that one, with the comment "UI reporting must not abort the
    actual send" — so cancelling never actually stopped __iter__() from
    reading and yielding the rest of the file. The message queue's own
    `except MessageCancelled:` handler exists specifically to catch this
    once it's allowed to actually propagate."""

    def test_message_cancelled_propagates_out_of_iteration(self, tmp_path):
        path = tmp_path / "large.bin"
        path.write_bytes(b"x" * 100_000)

        calls = []

        def _cancel_after_first_chunk(progress):
            calls.append(progress)
            if len(calls) >= 2:  # 0.0, then the first real chunk
                raise MessageCancelled("cancel-me")

        body = StreamingMultipartBody(
            file_path=str(path),
            filename=path.name,
            mime_type="application/octet-stream",
            fields={"type": "document"},
            progress_callback=_cancel_after_first_chunk,
            chunk_size=16 * 1024,
        )

        with pytest.raises(MessageCancelled):
            b"".join(body)

        # Cancellation fires on the very next progress report after the
        # first chunk — proof iteration actually stopped there instead of
        # running to completion and reporting/ignoring the cancellation.
        assert len(calls) == 2

    def test_other_progress_callback_errors_are_still_swallowed(self, tmp_path):
        """A progress_callback bug unrelated to cancellation (e.g. a
        destroyed wx widget raising inside a UI update) must not abort the
        actual upload — only MessageCancelled is special."""
        path = tmp_path / "small.bin"
        path.write_bytes(b"y" * 1000)

        def _flaky_callback(progress):
            raise RuntimeError("widget already destroyed")

        body = StreamingMultipartBody(
            file_path=str(path),
            filename=path.name,
            mime_type="application/octet-stream",
            fields={"type": "document"},
            progress_callback=_flaky_callback,
            chunk_size=16 * 1024,
        )

        encoded = b"".join(body)
        assert b"y" * 1000 in encoded


class TestSendMediaAttachmentPropagatesCancellation:
    """The other half of the fix: StreamingMultipartBody now lets
    MessageCancelled escape __iter__(), but send_media_attachment()'s own
    `except Exception as exc: return self._classify_send_exception(...)`
    would still have swallowed it right back into a plain retryable-failure
    dict — never reaching MessageQueue's `except MessageCancelled:` handler
    at all, since that handler only ever sees an actual raised exception,
    not a return value. Both fixes are required together.

    Reuses the _Stub/media_file pattern from
    test_send_media_unsupported_error.py (requests.post monkeypatched,
    since MainWindow can't be instantiated without a running wx.App)."""

    def test_message_cancelled_propagates_instead_of_being_classified(self, tmp_path, monkeypatch):
        import main
        from main import MainWindow

        class _Stub:
            send_media_attachment = MainWindow.send_media_attachment
            _check_wa_connection_closed = MainWindow._check_wa_connection_closed
            _find_api_ffmpeg = staticmethod(MainWindow._find_api_ffmpeg)

            def __init__(self):
                self.wpp_server = "http://127.0.0.1"
                self.wpp_port = 6300
                self.token = "session:key"
                self.i18n = type("I18n", (), {"t": lambda self, k: k})()
                self._wa_connected = True

            def _resolve_jid_for_send(self, jid):
                return jid

            def _legacy_phone_for_send(self, jid):
                return ""

            def _serialize_quoted_id(self, quoted, fallback_jid=""):
                return ""

        media_file = tmp_path / "video.mp4"
        media_file.write_bytes(b"fake video bytes")

        def _consuming_post(url, **kwargs):
            # A real requests.post would iterate the streaming body itself
            # while writing to the socket — reproduce that here so the
            # cancellation raised from inside the body's progress_callback
            # actually gets a chance to fire, same as it would in production.
            for _chunk in kwargs["data"]:
                pass
            raise AssertionError("upload should have been cancelled before finishing")

        monkeypatch.setattr(main.requests, "post", _consuming_post)

        def _cancel_immediately(progress):
            raise MessageCancelled("cancel-me")

        with pytest.raises(MessageCancelled):
            _Stub().send_media_attachment(
                "5511999999999@s.whatsapp.net", str(media_file), "video",
                progress_callback=_cancel_immediately,
            )


class TestTheBodyMatchesTheLengthItAnnounced:
    """Content-Length is computed in __init__ from os.path.getsize(), but the
    bytes are read in __iter__. The body is deliberately replayable so
    MessageQueue can retry a send, which means those two moments can be minutes
    apart — long enough for the user to have re-recorded an audio, or for an
    external program to have rewritten the file.

    Streaming a body that no longer matches the announced length is the kind of
    failure that surfaces nowhere near its cause: the server blocks waiting for
    bytes that never arrive, or accepts a truncated multipart whose closing
    boundary landed inside the file part. Both look like a flaky network."""

    @staticmethod
    def _body(path, **kw):
        return StreamingMultipartBody(
            file_path=str(path),
            filename="a.bin",
            mime_type="application/octet-stream",
            fields={"phone": "x"},
            **kw,
        )

    def test_a_file_that_grew_is_refused_instead_of_streamed(self, tmp_path):
        path = tmp_path / "grew.bin"
        path.write_bytes(b"x" * 1000)
        body = self._body(path)
        announced = len(body)

        path.write_bytes(b"x" * 4000)

        with pytest.raises(MultipartSourceChanged) as excinfo:
            list(body)
        assert "1000" in str(excinfo.value) and "4000" in str(excinfo.value)
        # The length already in the headers is what the mismatch is measured
        # against, so it must be named in the error.
        assert str(announced) in str(excinfo.value)

    def test_a_file_that_shrank_is_refused_instead_of_streamed(self, tmp_path):
        path = tmp_path / "shrank.bin"
        path.write_bytes(b"x" * 4000)
        body = self._body(path)

        path.write_bytes(b"x" * 10)

        with pytest.raises(MultipartSourceChanged):
            list(body)

    def test_an_unchanged_file_still_streams_and_replays(self, tmp_path):
        path = tmp_path / "stable.bin"
        path.write_bytes(b"payload" * 500)
        body = self._body(path)

        first = b"".join(body)
        second = b"".join(body)

        assert first == second, "the body must stay replayable for retries"
        assert len(first) == len(body) == body.content_length

    def test_the_guard_does_not_fire_on_a_zero_byte_file(self, tmp_path):
        """getsize() == 0 is a legitimate (if useless) upload, not a mismatch —
        and 0 is exactly the value a sloppy `if not size` guard would trip on."""
        path = tmp_path / "empty.bin"
        path.write_bytes(b"")
        body = self._body(path)

        assert b"".join(body) == body._prefix + body._suffix
