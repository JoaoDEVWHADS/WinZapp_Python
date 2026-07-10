"""
OGG Opus encoder — pure Python OGG container + ctypes bindings to libopus.

No FFmpeg, no libogg, no opuslib, no numpy required.
Only libopus itself (libopus-0.dll on Windows) is needed as a native library.
All PCM pre-processing uses Python's built-in ``array`` module.

Usage:
    from core.ogg_opus import encode_wav_to_ogg_opus

    with open("recorded.wav", "rb") as f:
        ogg_bytes = encode_wav_to_ogg_opus(f.read())
    # ogg_bytes is a complete OGG Opus file ready for base64-encoding and
    # sending to WhatsApp via /send-voice-base64.

DLL search order (Windows):
    1. <exe_dir>/lib/libopus-0.dll  (onedir frozen build)
    2. sys._MEIPASS/libopus-0.dll   (onefile frozen build)
    3. client/lib/libopus-0.dll     (development mode)
    4. System PATH: libopus-0.dll, opus.dll, libopus.dll
"""

import array
import ctypes
import io
import logging
import os
import struct
import sys
import wave

# ---------------------------------------------------------------------------
# libopus constants
# ---------------------------------------------------------------------------

_OPUS_APPLICATION_VOIP = 2048
_OPUS_SET_BITRATE      = 4002
_OPUS_SET_COMPLEXITY   = 4010
_OPUS_GET_LOOKAHEAD    = 4027

_FRAME_SIZE    = 960    # 20 ms at 48 kHz — standard Opus frame
_TARGET_RATE   = 48000  # Opus always encodes at 48 kHz internally
_MAX_PKT_BYTES = 4000   # upper bound for one encoded Opus packet

# ---------------------------------------------------------------------------
# DLL loading
# ---------------------------------------------------------------------------

_libopus: "ctypes.CDLL | None" = None


def _dll_search_paths() -> "list[str]":
    candidates: list[str] = []

    if hasattr(sys, "_MEIPASS"):
        # Frozen: try exe dir first (onedir), then _MEIPASS/lib/ (spec file
        # bundles it there), then _MEIPASS root (onefile legacy).
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates += [
            os.path.join(exe_dir, "lib", "libopus-0.dll"),
            os.path.join(exe_dir, "lib", "opus.dll"),
            os.path.join(sys._MEIPASS, "lib", "libopus-0.dll"),
            os.path.join(sys._MEIPASS, "lib", "opus.dll"),
            os.path.join(sys._MEIPASS, "libopus-0.dll"),
            os.path.join(sys._MEIPASS, "opus.dll"),
        ]
    else:
        # Dev: client/lib/ relative to this file (client/core/ogg_opus.py)
        lib_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"
        )
        candidates += [
            os.path.join(lib_dir, "libopus-0.dll"),
            os.path.join(lib_dir, "opus.dll"),
        ]

    # Well-known MSYS2 installation roots (user may not have ucrt64/bin in PATH).
    # Try both common install locations and both ucrt64 / mingw64 sub-systems.
    for _msys2_root in (
        r"C:\msys64",
        r"C:\msys2",
        r"C:\Program Files\msys64",
        r"C:\Program Files (x86)\msys64",
        r"C:\tools\msys64",
    ):
        for _sub in ("ucrt64", "mingw64", "mingw32", "usr"):
            candidates.append(os.path.join(_msys2_root, _sub, "bin", "libopus-0.dll"))
            candidates.append(os.path.join(_msys2_root, _sub, "bin", "opus.dll"))

    # Last resort: system PATH (Chocolatey, vcpkg, manual installs)
    candidates += ["libopus-0.dll", "libopus.dll", "opus.dll"]
    return candidates


def _load_libopus() -> "ctypes.CDLL":
    global _libopus
    if _libopus is not None:
        return _libopus

    for path in _dll_search_paths():
        try:
            lib = ctypes.CDLL(path)
            _ = lib.opus_encoder_create
            _ = lib.opus_encode
            _ = lib.opus_encoder_destroy
            _libopus = lib
            logging.info("[ogg_opus] libopus loaded from: %s", path)
            return _libopus
        except (OSError, AttributeError):
            continue

    raise RuntimeError(
        "libopus not found. Place libopus-0.dll in the app's lib/ directory.\n"
        "On MSYS2: pacman -S mingw-w64-ucrt-x86_64-opus\n"
        "Then copy C:/msys64/ucrt64/bin/libopus-0.dll to client/lib/"
    )


def _setup_argtypes(lib: "ctypes.CDLL") -> None:
    lib.opus_encoder_create.restype  = ctypes.c_void_p
    lib.opus_encoder_create.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.opus_encode.restype  = ctypes.c_int32
    lib.opus_encode.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int16),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int32,
    ]
    lib.opus_encoder_destroy.restype  = None
    lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
    # variadic — handle argtypes per-call
    lib.opus_encoder_ctl.restype  = ctypes.c_int
    lib.opus_encoder_ctl.argtypes = None


def _ctl_set(lib, enc, request: int, value: int) -> None:
    # Wrap enc in c_void_p so ctypes doesn't try to fit a 64-bit pointer into
    # a 32-bit c_int when argtypes is None (variadic function).
    lib.opus_encoder_ctl(ctypes.c_void_p(enc), ctypes.c_int(request), ctypes.c_int(value))


def _ctl_get(lib, enc, request: int) -> int:
    val = ctypes.c_int(0)
    lib.opus_encoder_ctl(ctypes.c_void_p(enc), ctypes.c_int(request), ctypes.byref(val))
    return val.value


# ---------------------------------------------------------------------------
# OGG page writer (RFC 3533) — pure Python, no libogg needed
# ---------------------------------------------------------------------------

def _ogg_crc32(data: bytes) -> int:
    """
    OGG-specific CRC-32 (ISO 3309 polynomial 0x04C11DB7, big-endian bit order).
    NOT the same as zlib.crc32 which uses the reflected polynomial.
    """
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _lace(data: bytes) -> "tuple[bytes, bytes]":
    """
    Build OGG segment lace table for a single packet.
    A segment of exactly 255 bytes signals continuation; append a 0-byte
    terminator if the packet size is a multiple of 255.
    """
    lace_vals: list[int] = []
    offset = 0
    n = len(data)
    while offset <= n:
        take = min(255, n - offset)
        lace_vals.append(take)
        offset += take
        if take < 255:
            break
    return bytes(lace_vals), data


def _make_ogg_page(
    header_type: int,
    granule: int,
    serial: int,
    seqno: int,
    data: bytes,
) -> bytes:
    lace_tbl, payload = _lace(data)
    hdr = struct.pack(
        "<4sBBqIIIB",
        b"OggS", 0, header_type,
        granule, serial, seqno, 0,
        len(lace_tbl),
    ) + lace_tbl
    page = hdr + payload
    crc  = _ogg_crc32(page)
    return page[:22] + struct.pack("<I", crc) + page[26:]


def _opus_id_header(channels: int, pre_skip: int, input_sample_rate: int) -> bytes:
    return struct.pack(
        "<8sBBHIhB",
        b"OpusHead", 1, channels, pre_skip, input_sample_rate, 0, 0,
    )


def _opus_comment_header() -> bytes:
    vendor = b"WinZapp"
    return b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)


# ---------------------------------------------------------------------------
# PCM pre-processing — no numpy, uses built-in array module
# ---------------------------------------------------------------------------

def _to_mono(pcm_bytes: bytes, channels: int) -> bytes:
    """Average all channels into one mono int16 stream."""
    if channels == 1:
        return pcm_bytes
    src = array.array("h", pcm_bytes)   # signed short (int16)
    if channels == 2:
        # Fast stereo downmixing using array slicing and zip
        left = src[0::2]
        right = src[1::2]
        out = array.array("h", ((l + r) // 2 for l, r in zip(left, right)))
        return bytes(out)
    n = len(src)
    out = array.array("h", [0] * (n // channels))
    for i in range(len(out)):
        total = sum(src[i * channels + ch] for ch in range(channels))
        val = total // channels
        out[i] = max(-32768, min(32767, val))
    return bytes(out)


def _resample(pcm_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Mono int16 linear-interpolation resampler."""
    if src_rate == dst_rate:
        return pcm_bytes
    src = array.array("h", pcm_bytes)
    n_in = len(src)
    if n_in == 0:
        return pcm_bytes
    n_out = int(round(n_in * dst_rate / src_rate))
    out = array.array("h", [0] * n_out)
    ratio = (n_in - 1) / max(n_out - 1, 1)
    for i in range(n_out):
        pos = i * ratio
        lo  = int(pos)
        hi  = min(lo + 1, n_in - 1)
        frac = pos - lo
        val  = int(src[lo] + frac * (src[hi] - src[lo]))
        out[i] = max(-32768, min(32767, val))
    return bytes(out)


def _pad_to_frames(pcm_bytes: bytes) -> bytes:
    """Append silence so the sample count is a multiple of _FRAME_SIZE."""
    n_samples = len(pcm_bytes) // 2
    rem = n_samples % _FRAME_SIZE
    if rem:
        pcm_bytes += bytes((_FRAME_SIZE - rem) * 2)
    return pcm_bytes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_pcm_to_ogg_opus(
    pcm_bytes: bytes,
    sample_rate: int,
    channels: int,
    bitrate: int = 64000,
) -> bytes:
    """
    Encode raw 16-bit signed PCM to an OGG Opus byte string.

    Parameters
    ----------
    pcm_bytes   : raw PCM (16-bit little-endian, interleaved if stereo)
    sample_rate : original sample rate (e.g. 48000 or 44100)
    channels    : 1 or 2; output is always mono
    bitrate     : target bit-rate in bps (default 64 kbps)
    """
    lib = _load_libopus()
    _setup_argtypes(lib)

    # 1. Pre-process: mono + 48 kHz
    pcm_bytes = _to_mono(pcm_bytes, channels)
    pcm_bytes = _resample(pcm_bytes, sample_rate, _TARGET_RATE)
    pcm_bytes = _pad_to_frames(pcm_bytes)

    # 2. Create Opus encoder
    err = ctypes.c_int(0)
    enc = lib.opus_encoder_create(_TARGET_RATE, 1, _OPUS_APPLICATION_VOIP, ctypes.byref(err))
    if err.value != 0 or not enc:
        raise RuntimeError(f"opus_encoder_create failed: {err.value}")

    try:
        _ctl_set(lib, enc, _OPUS_SET_BITRATE,    bitrate)
        _ctl_set(lib, enc, _OPUS_SET_COMPLEXITY, 5)
        pre_skip = _ctl_get(lib, enc, _OPUS_GET_LOOKAHEAD)

        # 3. Encode frames and build OGG stream
        out_buf = (ctypes.c_ubyte * _MAX_PKT_BYTES)()
        serial  = int.from_bytes(os.urandom(4), "little")
        seqno   = 0
        granule = 0
        pages: list[bytes] = []

        # BOS page: Opus ID header
        pages.append(_make_ogg_page(0x02, 0, serial, seqno,
                                    _opus_id_header(1, pre_skip, sample_rate)))
        seqno += 1

        # Comment header
        pages.append(_make_ogg_page(0x00, 0, serial, seqno,
                                    _opus_comment_header()))
        seqno += 1

        # Audio — one Opus packet per OGG page
        n_samples = len(pcm_bytes) // 2  # int16 → 2 bytes each
        n_frames  = n_samples // _FRAME_SIZE
        src = array.array("h", pcm_bytes)

        for i in range(n_frames):
            # Build a ctypes int16 array for this frame without copying via numpy
            frame = src[i * _FRAME_SIZE:(i + 1) * _FRAME_SIZE]
            # Use the array's buffer address directly
            buf_addr, _ = frame.buffer_info()
            c_pcm = ctypes.cast(buf_addr, ctypes.POINTER(ctypes.c_int16))

            pkt_len = lib.opus_encode(enc, c_pcm, _FRAME_SIZE, out_buf, _MAX_PKT_BYTES)
            if pkt_len < 0:
                raise RuntimeError(f"opus_encode returned error {pkt_len}")

            granule += _FRAME_SIZE
            eos = 0x04 if i == n_frames - 1 else 0x00
            pages.append(_make_ogg_page(eos, granule, serial, seqno,
                                        bytes(out_buf[:pkt_len])))
            seqno += 1

        return b"".join(pages)

    finally:
        lib.opus_encoder_destroy(enc)


def encode_wav_to_ogg_opus(wav_bytes: bytes, bitrate: int = 64000) -> bytes:
    """
    Convenience wrapper: read a WAV byte string and encode to OGG Opus.
    Accepts the output of Python's wave module (16-bit PCM WAV).
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        nch       = wf.getnchannels()
        rate      = wf.getframerate()
        sampwidth = wf.getsampwidth()
        pcm       = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported (got {sampwidth * 8}-bit)")

    return encode_pcm_to_ogg_opus(pcm, rate, nch, bitrate=bitrate)
