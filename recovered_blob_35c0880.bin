"""
OGG Opus encoder — pure Python OGG container + ctypes bindings to libopus.

No FFmpeg, no libogg, no opuslib pip package required.
Only libopus itself (libopus-0.dll on Windows) is needed as a native library.

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

import ctypes
import logging
import os
import struct
import sys
import wave
import io

import numpy as np

# ---------------------------------------------------------------------------
# libopus constants
# ---------------------------------------------------------------------------

_OPUS_APPLICATION_VOIP  = 2048
_OPUS_SET_BITRATE       = 4002
_OPUS_SET_COMPLEXITY    = 4010
_OPUS_GET_LOOKAHEAD     = 4027

_FRAME_SIZE    = 960       # 20 ms at 48 kHz — standard Opus frame
_TARGET_RATE   = 48000     # Opus always encodes at 48 kHz internally
_MAX_PKT_BYTES = 4000      # upper bound for one Opus packet

# ---------------------------------------------------------------------------
# DLL loading
# ---------------------------------------------------------------------------

_libopus: "ctypes.CDLL | None" = None


def _dll_search_paths() -> "list[str]":
    """Return candidate paths for libopus-0.dll in search priority order."""
    candidates: list[str] = []

    # Frozen (PyInstaller onedir): exe sits in <app_dir>, DLLs go to <app_dir>/lib/
    if hasattr(sys, "_MEIPASS"):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates += [
            os.path.join(exe_dir, "lib", "libopus-0.dll"),
            os.path.join(exe_dir, "lib", "opus.dll"),
            # onefile: everything extracted to _MEIPASS
            os.path.join(sys._MEIPASS, "libopus-0.dll"),
            os.path.join(sys._MEIPASS, "opus.dll"),
        ]
    else:
        # Development: client/lib/  (module lives at client/core/ogg_opus.py)
        lib_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
        candidates += [
            os.path.join(lib_dir, "libopus-0.dll"),
            os.path.join(lib_dir, "opus.dll"),
        ]

    # Fallback: system PATH (covers MSYS2, Chocolatey, manual installs)
    candidates += ["libopus-0.dll", "libopus.dll", "opus.dll"]
    return candidates


def _load_libopus() -> "ctypes.CDLL":
    """Load and return the libopus shared library, caching the result."""
    global _libopus
    if _libopus is not None:
        return _libopus

    for path in _dll_search_paths():
        try:
            lib = ctypes.CDLL(path)
            # Quick sanity check
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
    """Define ctypes signatures for the libopus functions we use."""
    lib.opus_encoder_create.restype  = ctypes.c_void_p
    lib.opus_encoder_create.argtypes = [
        ctypes.c_int,                   # Fs  (sample rate, must be 48000)
        ctypes.c_int,                   # channels
        ctypes.c_int,                   # application
        ctypes.POINTER(ctypes.c_int),   # *error
    ]

    lib.opus_encode.restype  = ctypes.c_int32
    lib.opus_encode.argtypes = [
        ctypes.c_void_p,                        # *st
        ctypes.POINTER(ctypes.c_int16),         # *pcm
        ctypes.c_int,                           # frame_size
        ctypes.POINTER(ctypes.c_ubyte),         # *data (output)
        ctypes.c_int32,                         # max_data_bytes
    ]

    lib.opus_encoder_destroy.restype  = None
    lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]

    # opus_encoder_ctl is variadic; set argtypes=None and handle per-call
    lib.opus_encoder_ctl.restype  = ctypes.c_int
    lib.opus_encoder_ctl.argtypes = None


def _ctl_set(lib: "ctypes.CDLL", enc: "ctypes.c_void_p", request: int, value: int) -> None:
    """Call opus_encoder_ctl with a single int SET argument."""
    lib.opus_encoder_ctl(enc, ctypes.c_int(request), ctypes.c_int(value))


def _ctl_get(lib: "ctypes.CDLL", enc: "ctypes.c_void_p", request: int) -> int:
    """Call opus_encoder_ctl with a pointer GET argument; return the int result."""
    val = ctypes.c_int(0)
    lib.opus_encoder_ctl(enc, ctypes.c_int(request), ctypes.byref(val))
    return val.value


# ---------------------------------------------------------------------------
# OGG page writer (RFC 3533) — pure Python, no libogg needed
# ---------------------------------------------------------------------------

def _ogg_crc32(data: bytes) -> int:
    """
    OGG-specific CRC-32.

    Uses generator polynomial 0x04c11db7 (ISO 3309, big-endian bit order).
    This is NOT the same as Python's zlib.crc32, which uses the reflected
    polynomial 0xEDB88320.
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
    Build the OGG segment lace table for a single packet.

    Returns (lace_table_bytes, packet_bytes).  A segment of exactly 255 bytes
    signals continuation, so a packet whose size is a multiple of 255 needs
    an extra zero-byte terminator segment.
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
    # Edge case: empty packet → single lace value of 0 (already handled above
    # because the first iteration gives take=0 and breaks immediately).
    return bytes(lace_vals), data


def _make_ogg_page(
    header_type: int,
    granule: int,
    serial: int,
    seqno: int,
    data: bytes,
) -> bytes:
    """
    Encode *data* (one complete OGG packet) into a single OGG page.

    header_type flags:
      0x01  continuation page
      0x02  beginning-of-stream (BOS)
      0x04  end-of-stream (EOS)
    """
    lace_tbl, payload = _lace(data)

    # OGG page header (27 bytes fixed + segment table)
    hdr = struct.pack(
        "<4sBBqIIIB",
        b"OggS",          # capture pattern
        0,                # stream_structure_version
        header_type,
        granule,          # absolute_granule_position (signed int64)
        serial,           # stream_serial_number
        seqno,            # page_sequence_no
        0,                # checksum placeholder
        len(lace_tbl),    # number_page_segments
    ) + lace_tbl

    page = hdr + payload
    crc  = _ogg_crc32(page)
    # CRC lives at bytes 22-25
    return page[:22] + struct.pack("<I", crc) + page[26:]


def _opus_id_header(channels: int, pre_skip: int, input_sample_rate: int) -> bytes:
    """Build the Opus identification header (RFC 7845 §5.1)."""
    return struct.pack(
        "<8sBBHIhB",
        b"OpusHead",
        1,                   # version
        channels,
        pre_skip,            # samples to discard at the start
        input_sample_rate,   # original sample rate (informational)
        0,                   # output gain (Q7.8 dB, 0 = no adjustment)
        0,                   # channel mapping family (0 = mono/stereo)
    )


def _opus_comment_header() -> bytes:
    """Build a minimal Opus comment header (RFC 7845 §5.2)."""
    vendor = b"WinZapp"
    return b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)


# ---------------------------------------------------------------------------
# PCM pre-processing helpers
# ---------------------------------------------------------------------------

def _to_mono_48k(samples: "np.ndarray", src_rate: int, src_channels: int) -> "np.ndarray":
    """Down-mix to mono and resample to 48 kHz if needed."""
    if src_channels == 2:
        stereo = samples.reshape(-1, 2).astype(np.int32)
        samples = ((stereo[:, 0] + stereo[:, 1]) >> 1).astype(np.int16)

    if src_rate != _TARGET_RATE:
        n_in  = len(samples)
        n_out = int(round(n_in * _TARGET_RATE / src_rate))
        # Linear interpolation — adequate quality for voice at these rates
        samples = np.interp(
            np.linspace(0, n_in - 1, n_out),
            np.arange(n_in),
            samples.astype(np.float64),
        ).clip(-32768, 32767).astype(np.int16)

    return samples


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
    pcm_bytes   : raw PCM data (16-bit little-endian, interleaved if stereo)
    sample_rate : original sample rate (e.g. 48000 or 44100)
    channels    : 1 (mono) or 2 (stereo); output is always mono
    bitrate     : target bit-rate in bps (default 64 kbps)

    Returns
    -------
    bytes — a complete, self-contained OGG Opus file
    """
    lib = _load_libopus()
    _setup_argtypes(lib)

    # --- 1. Pre-process PCM: mono + 48 kHz ----------------------------------
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).copy()
    samples = _to_mono_48k(samples, sample_rate, channels)

    # Pad to a whole number of frames
    pad = (-len(samples)) % _FRAME_SIZE
    if pad:
        samples = np.concatenate([samples, np.zeros(pad, dtype=np.int16)])

    # --- 2. Create Opus encoder ---------------------------------------------
    err = ctypes.c_int(0)
    enc = lib.opus_encoder_create(_TARGET_RATE, 1, _OPUS_APPLICATION_VOIP, ctypes.byref(err))
    if err.value != 0 or not enc:
        raise RuntimeError(f"opus_encoder_create failed with error {err.value}")

    try:
        _ctl_set(lib, enc, _OPUS_SET_BITRATE,    bitrate)
        _ctl_set(lib, enc, _OPUS_SET_COMPLEXITY, 5)
        pre_skip = _ctl_get(lib, enc, _OPUS_GET_LOOKAHEAD)

        # --- 3. Write OGG stream --------------------------------------------
        out_buf = (ctypes.c_ubyte * _MAX_PKT_BYTES)()
        serial  = int.from_bytes(os.urandom(4), "little")
        seqno   = 0
        granule = 0
        pages: list[bytes] = []

        # BOS page: Opus ID header
        pages.append(_make_ogg_page(
            0x02, 0, serial, seqno,
            _opus_id_header(1, pre_skip, sample_rate),
        ))
        seqno += 1

        # Comment header
        pages.append(_make_ogg_page(
            0x00, 0, serial, seqno,
            _opus_comment_header(),
        ))
        seqno += 1

        # Audio frames — one Opus packet per OGG page
        n_frames = len(samples) // _FRAME_SIZE
        for i in range(n_frames):
            frame  = samples[i * _FRAME_SIZE:(i + 1) * _FRAME_SIZE]
            c_pcm  = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
            pkt_len = lib.opus_encode(enc, c_pcm, _FRAME_SIZE, out_buf, _MAX_PKT_BYTES)
            if pkt_len < 0:
                raise RuntimeError(f"opus_encode returned error {pkt_len}")

            granule += _FRAME_SIZE
            eos = 0x04 if i == n_frames - 1 else 0x00
            pages.append(_make_ogg_page(
                eos, granule, serial, seqno,
                bytes(out_buf[:pkt_len]),
            ))
            seqno += 1

        return b"".join(pages)

    finally:
        lib.opus_encoder_destroy(enc)


def encode_wav_to_ogg_opus(wav_bytes: bytes, bitrate: int = 64000) -> bytes:
    """
    Convenience wrapper: read a WAV byte string and encode to OGG Opus.

    Accepts the output of Python's wave module (16-bit PCM WAV, any sample
    rate, mono or stereo).
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        nch      = wf.getnchannels()
        rate     = wf.getframerate()
        sampwidth = wf.getsampwidth()
        pcm      = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported (got {sampwidth*8}-bit)")

    return encode_pcm_to_ogg_opus(pcm, rate, nch, bitrate=bitrate)
