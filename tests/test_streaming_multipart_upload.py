"""Regression tests for the real HTTP upload progress path."""

from core.multipart_stream import StreamingMultipartBody


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
