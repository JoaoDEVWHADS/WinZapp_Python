"""Tests for multipart upload progress reporting."""

import io

from main import _UploadProgressFile


def test_upload_progress_reports_each_read_and_caps_at_one():
    updates = []
    stream = _UploadProgressFile(io.BytesIO(b"abcdef"), 6, updates.append)

    assert stream.read(2) == b"ab"
    assert stream.read() == b"cdef"
    assert updates == [2 / 6, 1.0]
