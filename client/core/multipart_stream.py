"""Streaming multipart/form-data support for WinZapp media uploads."""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Callable

ProgressCallback = Callable[[float], Any]


def _quote_disposition(value: Any) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _field_pairs(fields: Mapping[str, Any] | Iterable[tuple[str, Any]]):
    items = fields.items() if isinstance(fields, Mapping) else fields
    for name, value in items:
        if value is None:
            continue
        values = value if isinstance(value, (list, tuple)) else (value,)
        for item in values:
            if item is not None:
                yield str(name), str(item)


class StreamingMultipartBody:
    """Replayable multipart body that yields the file in bounded chunks.

    requests' ``files=`` encoder eagerly calls ``read()`` and buffers the full
    multipart body before the socket upload starts. A callback around that file
    therefore measures request construction, not upload progress. This class is
    an iterable with an exact length, so urllib3 streams it while still sending
    Content-Length.
    """

    def __init__(
        self,
        *,
        file_path: str,
        filename: str,
        mime_type: str,
        fields: Mapping[str, Any] | Iterable[tuple[str, Any]],
        progress_callback: ProgressCallback | None = None,
        chunk_size: int = 256 * 1024,
        boundary: str | None = None,
    ) -> None:
        self.file_path = os.fspath(file_path)
        self.filename = str(filename)
        self.mime_type = str(mime_type or "application/octet-stream")
        self.progress_callback = progress_callback
        self.chunk_size = max(16 * 1024, int(chunk_size))
        self.boundary = boundary or f"----WinZapp{uuid.uuid4().hex}"
        self.content_type = f"multipart/form-data; boundary={self.boundary}"
        self.file_size = os.path.getsize(self.file_path)

        boundary_b = self.boundary.encode("ascii")
        pieces: list[bytes] = []
        for name, value in _field_pairs(fields):
            pieces.append(
                b"--" + boundary_b + b"\r\n"
                + (
                    'Content-Disposition: form-data; name="%s"\r\n\r\n'
                    % _quote_disposition(name)
                ).encode("utf-8")
                + value.encode("utf-8")
                + b"\r\n"
            )
        pieces.append(
            b"--" + boundary_b + b"\r\n"
            + (
                'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
                % _quote_disposition(self.filename)
            ).encode("utf-8")
            + (f"Content-Type: {self.mime_type}\r\n\r\n").encode("utf-8")
        )
        self._prefix = b"".join(pieces)
        self._suffix = b"\r\n--" + boundary_b + b"--\r\n"
        self._content_length = len(self._prefix) + self.file_size + len(self._suffix)

    def __len__(self) -> int:
        return self._content_length

    @property
    def content_length(self) -> int:
        return self._content_length

    def _report(self, progress: float) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(max(0.0, min(1.0, float(progress))))
        except Exception:
            # UI reporting must not abort the actual send.
            pass

    def __iter__(self) -> Iterator[bytes]:
        self._report(0.0)
        yield self._prefix

        sent = 0
        with open(self.file_path, "rb") as fh:
            while True:
                chunk = fh.read(self.chunk_size)
                if not chunk:
                    break
                # The generator resumes here only after urllib3 consumed the
                # yielded chunk, so progress no longer runs ahead during body
                # construction like requests' built-in files= encoder does.
                yield chunk
                sent += len(chunk)
                if self.file_size:
                    self._report(sent / self.file_size)

        self._report(1.0)
        yield self._suffix
