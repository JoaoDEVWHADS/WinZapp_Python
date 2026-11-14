"""The video of a call, each way, through ffmpeg (on the bridge's PATH: the
client puts client/lib first, core/neonize_bridge_process.environment).

meowcaller carries H.264 only, as Annex-B access units (one frame's NAL units
with their start codes), and neither encodes nor decodes pixels
(neonize_patches/neonize/0008). The client speaks JPEG both ways, as with
WPPConnect: `call:video:camera` brings its camera (10 frames a second, at
most 640x360) and `call:video:remote` shows the other side. So:

- `Encoder`: the camera's JPEGs -> H.264 baseline, no B frames, a key frame
  every second (a peer that asks for one gets it within the second), an
  access unit delimiter before each frame (x264 `aud=1`), which is where
  `split_access_units` cuts; the delimiters themselves are dropped;
- `Decoder`: the other side's access units -> JPEGs (`jpeg_frames` cuts the
  stream at each image's end).

Every stage runs on one thread (`-threads 1`, x264 `threads=1`): frame
threads held about ten frames each way, a second of delay (measured
2026-10-26: about 0.3 s each way now, one frame of it waiting for the next
delimiter). Each runs one ffmpeg without a window, fed by a writer thread that drops the
oldest frames when ffmpeg falls behind (a late frame is worth nothing in a
call) and read by another thread. The pure functions are at the top (tested
in test_video_codec.py, which also runs a real ffmpeg when there is one).
"""
import logging
import queue
import shutil
import subprocess
import sys
import threading

log = logging.getLogger("bridge")

FPS = 10
FRAME_MS = 1000 // FPS
MAX_JPEG = 256_000              # what the client accepts (core/websocket_client.py)
_PENDING_LIMIT = 4 << 20         # a stream that never delimits a frame is dropped
_QUEUE = 30                     # 3 s: dropping a unit spoils the picture until the next key frame

_START = b"\x00\x00\x01"
_AUD = 9


def nal_starts(data: bytes) -> list:
    """(offset of the start code, offset of the NAL header) of each NAL unit."""
    found, i = [], data.find(_START)
    while i >= 0 and i + 3 < len(data):
        code = i - 1 if i > 0 and data[i - 1] == 0 else i      # 4-byte start code
        found.append((code, i + 3))
        i = data.find(_START, i + 3)
    return found


def drop_delimiters(access_unit: bytes) -> bytes:
    """The access unit without its delimiter NAL units (type 9)."""
    starts = nal_starts(access_unit)
    parts = []
    for n, (code, header) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(access_unit)
        if access_unit[header] & 0x1F != _AUD:
            parts.append(access_unit[code:end])
    return b"".join(parts)


def split_access_units(data: bytes) -> tuple:
    """Cuts an H.264 Annex-B stream at each access unit delimiter. Returns
    (access units, rest): the last unit waits in `rest` until the next
    delimiter shows it is whole. What comes before the first delimiter is no
    frame and is dropped."""
    delimiters = [code for code, header in nal_starts(data) if data[header] & 0x1F == _AUD]
    if not delimiters:
        return [], data[-_PENDING_LIMIT:] if len(data) > _PENDING_LIMIT else data
    units = []
    for start, end in zip(delimiters, delimiters[1:]):
        unit = drop_delimiters(data[start:end])
        if unit:
            units.append(unit)
    return units, data[delimiters[-1]:]


def jpeg_frames(data: bytes) -> tuple:
    """Cuts ffmpeg's MJPEG stream into whole JPEGs. Returns (frames, rest)."""
    frames = []
    while True:
        start = data.find(b"\xff\xd8")
        if start < 0:
            return frames, b""
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            return frames, data[start:]
        frames.append(data[start:end + 2])
        data = data[end + 2:]


def encoder_command(ffmpeg: str) -> list:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer",
            "-probesize", "32", "-analyzeduration", "0",
            "-threads", "1", "-f", "mjpeg", "-framerate", str(FPS), "-i", "-", "-an",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-profile:v", "baseline", "-g", str(FPS), "-bf", "0",
            "-b:v", "400k", "-maxrate", "500k", "-bufsize", "500k",
            "-x264-params", "aud=1:repeat-headers=1:threads=1",
            "-flush_packets", "1", "-f", "h264", "-"]


def decoder_command(ffmpeg: str) -> list:
    # no "-fflags nobuffer -flags low_delay" here: with them ffmpeg 7 decodes
    # nothing from a raw H.264 pipe (tried 2026-10-26)
    return [ffmpeg, "-hide_banner", "-loglevel", "error",
            "-probesize", "32", "-analyzeduration", "0",
            "-threads", "1", "-f", "h264", "-i", "-", "-an",
            "-vf", "scale=640:360:force_original_aspect_ratio=decrease",
            "-pix_fmt", "yuvj420p", "-c:v", "mjpeg", "-q:v", "7", "-flush_packets", "1",
            "-f", "image2pipe", "-"]


def find_ffmpeg():
    return shutil.which("ffmpeg")


class _Pipe:
    """One ffmpeg: `push` queues input; `on_output(chunk)` gets what it writes."""

    def __init__(self, command, cut, on_item, name):
        self._queue = queue.Queue(maxsize=_QUEUE)
        self._cut, self._on_item, self._name = cut, on_item, name
        self._closed = threading.Event()
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, creationflags=flags)
        threading.Thread(target=self._write, daemon=True, name=f"{name}-in").start()
        threading.Thread(target=self._read, daemon=True, name=f"{name}-out").start()

    def push(self, data: bytes):
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:                  # ffmpeg is behind: the oldest goes
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                pass

    def _write(self):
        try:
            while not self._closed.is_set():
                try:
                    data = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._proc.stdin.close()
            except OSError:
                pass

    def _read(self):
        pending = b""
        try:
            while True:
                chunk = self._proc.stdout.read1(65536)
                if not chunk:
                    break
                items, pending = self._cut(pending + chunk)
                for item in items:
                    try:
                        self._on_item(item)
                    except Exception:
                        log.exception("%s output", self._name)
        except (OSError, ValueError):
            pass
        finally:
            if not self._closed.is_set():
                log.warning("%s: ffmpeg stopped (exit %s)", self._name, self._proc.poll())

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._proc.kill()
        except OSError:
            pass


class Encoder(_Pipe):
    """JPEGs in (`push`), H.264 access units out (`on_access_unit`)."""

    def __init__(self, ffmpeg, on_access_unit):
        super().__init__(encoder_command(ffmpeg), split_access_units, on_access_unit,
                         "video-encoder")


class Decoder(_Pipe):
    """H.264 access units in (`push`), JPEGs out (`on_jpeg`)."""

    def __init__(self, ffmpeg, on_jpeg):
        def whole(data):
            return jpeg_frames(data)

        def small(jpeg):
            if len(jpeg) <= MAX_JPEG:
                on_jpeg(jpeg)
        super().__init__(decoder_command(ffmpeg), whole, small, "video-decoder")


class FfmpegCodec:
    """What CallMedia asks for each call: `encoder(on_access_unit)` and
    `decoder(on_jpeg)`. `available()` is None when there is no ffmpeg."""

    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg

    @classmethod
    def available(cls):
        ffmpeg = find_ffmpeg()
        return cls(ffmpeg) if ffmpeg else None

    def encoder(self, on_access_unit):
        return Encoder(self.ffmpeg, on_access_unit)

    def decoder(self, on_jpeg):
        return Decoder(self.ffmpeg, on_jpeg)
