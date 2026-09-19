"""Python-owned microphone and speaker transport for WhatsApp voice calls.

Chromium keeps WhatsApp signaling, encryption, and WebRTC. It never opens the
physical microphone: Python captures PCM, forwards it to the page bridge, and
plays the PCM extracted from the remote WebRTC track.
"""

from __future__ import annotations

import base64
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - packaging always installs it
    sd = None

CALL_SAMPLE_RATE = 48_000
CALL_FRAME_MS = 20
CALL_FRAME_SAMPLES = CALL_SAMPLE_RATE * CALL_FRAME_MS // 1000
# 40 ms leaves two 20 ms hardware periods for ordinary Windows driver jitter
# without adding the large latency of PortAudio's generic "high" preset.
CALL_DEVICE_LATENCY_SECONDS = 0.040
CALL_MIC_QUEUE_LIMIT = 12
CALL_MIC_TARGET_BACKLOG_FRAMES = 2
CALL_OUTPUT_QUEUE_LIMIT = 40
CALL_OUTPUT_PREBUFFER_MS = 60
CALL_OUTPUT_REBUFFER_WAIT_MS = CALL_FRAME_MS
CALL_OUTPUT_MAX_BUFFER_MS = 200


@dataclass(frozen=True)
class CallAudioConfig:
    session: str
    input_device_name: str = ""
    output_device_name: str = ""


class CallAudioUnavailable(RuntimeError):
    """Raised when the local call audio devices cannot be opened."""


def _resample_mono(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Return mono float32 audio at ``target_rate`` using linear interpolation."""
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1, dtype=np.float32)
    data = data.reshape(-1)
    if not data.size or source_rate == target_rate:
        return data.astype(np.float32, copy=False)
    target_len = max(1, int(round(data.size * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, num=data.size, endpoint=False)
    target_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.interp(target_x, source_x, data).astype(np.float32)


def _pcm16_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2", copy=False).tobytes()


def _pcm16_float32(pcm: bytes) -> np.ndarray:
    if not pcm:
        return np.empty(0, dtype=np.float32)
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class _BassCallOutput:
    """BASS push stream for received call audio.

    Calls use the same BASS output-device namespace as normal program audio and
    effect sounds, but keep their own stream so the selected call speaker can
    be changed independently without touching the microphone or ending the
    WhatsApp call.
    """

    def __init__(self, device_name: str = ""):
        self._lock = threading.RLock()
        self._stream = None
        self._started = False
        self._device_name = str(device_name or "")
        self._device_index = self._resolve_device(self._device_name, allow_fallback=True)
        self._create_stream_locked()

    @staticmethod
    def _resolve_device(device_name: str, *, allow_fallback: bool) -> int:
        from core.audio_devices import (
            find_default_output_device_index,
            find_output_device_index,
        )

        if device_name:
            index = find_output_device_index(device_name)
            if index is not None:
                return int(index)
            if not allow_fallback:
                raise CallAudioUnavailable(
                    f"BASS output device is not available: {device_name}"
                )
            logging.warning(
                "[call_audio] BASS output %r is unavailable; using system default",
                device_name,
            )

        index = find_default_output_device_index()
        if index is None:
            raise CallAudioUnavailable("No BASS output device is available for the call")
        return int(index)

    @staticmethod
    def _ensure_device(device_index: int) -> None:
        """Initialise one extra BASS output without changing the app default."""
        from sound_lib.external.pybass import (
            BASS_ERROR_ALREADY,
            BASS_ErrorGetCode,
            BASS_GetDevice,
            BASS_Init,
            BASS_SetDevice,
        )

        try:
            previous = int(BASS_GetDevice())
        except Exception:
            previous = 0

        ok = bool(BASS_Init(int(device_index), CALL_SAMPLE_RATE, 0, 0, None))
        if not ok:
            error = int(BASS_ErrorGetCode())
            if error != BASS_ERROR_ALREADY:
                raise CallAudioUnavailable(
                    f"Could not initialise BASS output device {device_index} "
                    f"(error {error})"
                )

        # BASS_Init makes the just-initialised device current. Restore the
        # program output immediately so unrelated streams do not jump devices.
        if previous > 0 and previous != int(device_index):
            if not BASS_SetDevice(previous):
                logging.warning(
                    "[call_audio] could not restore BASS current device %s",
                    previous,
                )

    def _create_stream_locked(self) -> None:
        from sound_lib.stream import PushStream

        self._ensure_device(self._device_index)
        old = self._stream
        self._stream = None
        if old is not None:
            try:
                old.free()
            except Exception:
                pass

        try:
            stream = PushStream(freq=CALL_SAMPLE_RATE, chans=1)
            if int(stream.get_device()) != int(self._device_index):
                stream.set_device(int(self._device_index))
            self._stream = stream
            if self._started:
                self._stream.play()
        except Exception as exc:
            try:
                if self._stream is not None:
                    self._stream.free()
            except Exception:
                pass
            self._stream = None
            raise CallAudioUnavailable(
                f"Could not open BASS call output: {exc}"
            ) from exc

    def start(self) -> None:
        with self._lock:
            if self._stream is None:
                self._create_stream_locked()
            self._started = True
            self._stream.play()

    def write(self, samples) -> bool:
        data = _pcm16_bytes(np.asarray(samples, dtype=np.float32).reshape(-1))
        if not data:
            return False
        with self._lock:
            if self._stream is None:
                self._create_stream_locked()
            try:
                self._stream.push(data)
            except Exception:
                # Changing another BASS output can invalidate a channel on a
                # device that was reinitialised. Recover the call stream in
                # place instead of tearing down the whole CallAudioSession.
                logging.warning(
                    "[call_audio] BASS call stream became invalid; rebuilding it",
                    exc_info=True,
                )
                self._create_stream_locked()
                self._stream.push(data)
        return False

    def switch_device(self, device_name: str) -> bool:
        """Move the live BASS channel to another output device."""
        target_name = str(device_name or "")
        target = self._resolve_device(target_name, allow_fallback=False)
        with self._lock:
            if target == self._device_index:
                self._device_name = target_name
                return True

            self._ensure_device(target)
            if self._stream is None:
                self._device_index = target
                self._device_name = target_name
                self._create_stream_locked()
                return True

            try:
                self._stream.set_device(target)
            except Exception as exc:
                raise CallAudioUnavailable(
                    f"Could not move call output to BASS device {target}: {exc}"
                ) from exc

            self._device_index = target
            self._device_name = target_name

        logging.info(
            "[call_audio] BASS call output switched device=%r index=%s",
            self._device_name or "<default>",
            self._device_index,
        )
        return True

    def stop(self) -> None:
        with self._lock:
            self._started = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._started = False
            if stream is not None:
                try:
                    stream.free()
                except Exception:
                    logging.debug(
                        "[call_audio] failed to free BASS call stream",
                        exc_info=True,
                    )


class CallAudioSession:
    """Own the Python side of one low-latency voice-call audio pipeline."""

    def __init__(
        self,
        sio,
        config: CallAudioConfig,
        *,
        sounddevice_module=None,
        output_factory=None,
    ):
        self._sio = sio
        self._config = config
        self._sounddevice_injected = sounddevice_module is not None
        self._sd = sd if sounddevice_module is None else sounddevice_module
        self._output_factory = output_factory
        self._input_stream = None
        self._output_stream = None
        self._input_rate = CALL_SAMPLE_RATE
        self._input_device_name = str(config.input_device_name or "")
        self._input_lock = threading.RLock()
        self._input_generation = 0
        self._output_rate = CALL_SAMPLE_RATE
        self._mic_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=CALL_MIC_QUEUE_LIMIT)
        self._output_queue: "queue.Queue[tuple[bytes, int]]" = queue.Queue(
            maxsize=CALL_OUTPUT_QUEUE_LIMIT
        )
        self._stop_event = threading.Event()
        self._sender_thread: Optional[threading.Thread] = None
        self._player_thread: Optional[threading.Thread] = None
        self._mic_frames_sent = 0
        self._mic_bytes_sent = 0
        self._mic_frames_dropped_for_latency = 0
        self._microphone_muted = False
        self._output_rebuffer_count = 0
        self._output_samples_dropped = 0

    @property
    def microphone_muted(self) -> bool:
        return self._microphone_muted

    def set_microphone_muted(self, muted: bool) -> None:
        """Mute only this call's outgoing microphone, keeping the stream alive."""
        self._microphone_muted = bool(muted)
        logging.info("[call_audio] microphone %s", "muted" if self._microphone_muted else "unmuted")

    @property
    def running(self) -> bool:
        return not self._stop_event.is_set() and self._input_stream is not None

    @property
    def output_running(self) -> bool:
        return not self._stop_event.is_set() and self._output_stream is not None

    def start_output_only(self) -> None:
        """Open receive audio while ringing without opening the microphone."""
        if self.output_running:
            return
        self._stop_event.clear()
        self._output_stream, self._output_rate = self._open_output_stream()
        try:
            self._output_stream.start()
        except Exception:
            self._close_stream(self._output_stream)
            self._output_stream = None
            raise
        self._player_thread = threading.Thread(
            target=self._play_remote_loop,
            name="WinZappCallRemotePlayer",
            daemon=True,
        )
        self._player_thread.start()
        self._emit_start()

    def start(self) -> None:
        if self.running:
            return
        if self._sd is None:
            raise CallAudioUnavailable("sounddevice is not available in this Python runtime")

        # An incoming call may already have opened the receive side while it
        # was ringing. Reuse it and only add microphone capture on answer.
        self.start_output_only()
        try:
            self._input_stream, self._input_rate = self._open_input_stream(
                device_name=self._input_device_name,
                generation=self._input_generation,
            )
            self._input_stream.start()
        except Exception:
            self._close_stream(self._input_stream)
            self._input_stream = None
            raise

        self._sender_thread = threading.Thread(
            target=self._send_microphone_loop,
            name="WinZappCallMicSender",
            daemon=True,
        )
        self._sender_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._emit_stop()
        with self._input_lock:
            self._input_generation += 1
            self._close_stream(self._input_stream)
            self._input_stream = None
        self._close_stream(self._output_stream)
        self._output_stream = None
        self._drain_queue(self._mic_queue)
        self._drain_queue(self._output_queue)

    def enqueue_remote_audio(self, pcm: bytes, sample_rate: int) -> None:
        if self._stop_event.is_set() or not pcm:
            return
        try:
            sample_rate = int(sample_rate or CALL_SAMPLE_RATE)
        except (TypeError, ValueError):
            sample_rate = CALL_SAMPLE_RATE
        self._put_drop_oldest(self._output_queue, (bytes(pcm), sample_rate))

    def switch_input_device(self, device_name: str) -> bool:
        """Switch only microphone capture while keeping the call session alive.

        If receive-only ringing audio is active and the microphone has not been
        opened yet, just remember the new name so answering opens that device.
        During an active call the replacement stream is opened and started
        before the old stream is closed, avoiding a full call-audio restart.
        """
        requested = str(device_name or "")
        if self._sd is None:
            raise CallAudioUnavailable(
                "sounddevice is not available in this Python runtime"
            )

        with self._input_lock:
            if self._input_stream is None:
                self._input_device_name = requested
                logging.info(
                    "[call_audio] microphone preference changed before capture starts device=%r",
                    requested or "<default>",
                )
                return True

            next_generation = self._input_generation + 1
            new_stream = None
            try:
                new_stream, new_rate = self._open_input_stream(
                    device_name=requested,
                    strict=bool(requested),
                    generation=next_generation,
                )
                new_stream.start()
            except Exception:
                self._close_stream(new_stream)
                raise

            old_stream = self._input_stream
            self._input_stream = new_stream
            self._input_rate = new_rate
            self._input_device_name = requested
            self._input_generation = next_generation

            # Never replay PCM captured from the old device after the switch.
            self._drain_queue(self._mic_queue)
            self._close_stream(old_stream)

        logging.info(
            "[call_audio] microphone switched live device=%r rate=%s",
            requested or "<default>",
            self._input_rate,
        )
        return True

    def switch_output_device(self, device_name: str) -> bool:
        """Move received call audio without restarting capture or the call."""
        stream = self._output_stream
        if stream is None:
            raise CallAudioUnavailable("Call output is not running")
        switch = getattr(stream, "switch_device", None)
        if switch is None:
            raise CallAudioUnavailable(
                "The active call output backend cannot switch devices in place"
            )
        switched = bool(switch(device_name or ""))
        if switched:
            self._emit_output_device(device_name or "")
        return switched

    def _query_devices(self):
        try:
            return list(self._sd.query_devices())
        except Exception as exc:
            raise CallAudioUnavailable(f"Could not enumerate audio devices: {exc}") from exc

    @staticmethod
    def _normalized_name(value: str) -> str:
        return " ".join(str(value or "").replace("(", "").replace(")", "").lower().split())

    def _resolve_device(self, stored_name: str, *, input_device: bool) -> Optional[int]:
        if not stored_name:
            return None
        wanted = self._normalized_name(stored_name)
        devices = self._query_devices()
        candidates = []
        for index, info in enumerate(devices):
            channels_key = "max_input_channels" if input_device else "max_output_channels"
            if int(info.get(channels_key, 0) or 0) <= 0:
                continue
            actual = self._normalized_name(info.get("name", ""))
            if actual == wanted:
                return index
            if wanted and (wanted in actual or actual in wanted):
                candidates.append(index)
        return candidates[0] if candidates else None

    def _default_device_index(self, *, input_device: bool) -> Optional[int]:
        """Return PortAudio's concrete default device instead of opaque None."""
        try:
            defaults = getattr(getattr(self._sd, "default", None), "device", None)
            index = defaults[0 if input_device else 1]
            index = int(index)
            return index if index >= 0 else None
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _candidate_devices(self, stored_name: str, *, input_device: bool):
        preferred = self._resolve_device(stored_name, input_device=input_device)
        default_device = self._default_device_index(input_device=input_device)
        yielded = set()
        ordered = []
        if preferred is not None:
            ordered.append(preferred)
        if default_device is not None:
            ordered.append(default_device)
        # Keep PortAudio's implicit default as a compatibility fallback, but
        # prefer the concrete default index so we can inspect its native rate.
        ordered.append(None)
        for index in ordered:
            key = -1 if index is None else int(index)
            if key not in yielded:
                yielded.add(key)
                yield index
        channels_key = "max_input_channels" if input_device else "max_output_channels"
        for index, info in enumerate(self._query_devices()):
            if int(info.get(channels_key, 0) or 0) <= 0 or index in yielded:
                continue
            yielded.add(index)
            yield index

    def _candidate_rates(self, device_index: Optional[int]):
        # Opening the Windows mixer at its own rate avoids needless device
        # reconfiguration/resampling in the driver. The call transport stays
        # 48 kHz; Python already resamples at the boundary.
        rates = []
        try:
            info = self._sd.query_devices(device_index)
            native = int(round(float(info.get("default_samplerate") or 0)))
            if native > 0:
                rates.append(native)
        except Exception:
            pass
        for rate in (CALL_SAMPLE_RATE, 44_100, 32_000, 16_000):
            if rate not in rates:
                rates.append(rate)
        return rates

    def _stream_extra_settings(
        self, device_index: Optional[int], *, input_device: bool
    ):
        """Keep WASAPI in shared mode so a call cannot take over the device."""
        if sys.platform != "win32":
            return None
        actual_index = device_index
        if actual_index is None:
            actual_index = self._default_device_index(input_device=input_device)
        if actual_index is None:
            return None
        try:
            info = self._sd.query_devices(actual_index)
            hostapi = self._sd.query_hostapis(int(info.get("hostapi", -1)))
            if "wasapi" not in str(hostapi.get("name", "")).lower():
                return None
            settings_type = getattr(self._sd, "WasapiSettings", None)
            if settings_type is None:
                return None
            # Explicitly shared; auto_convert is only a fallback for a device
            # whose native rate cannot be opened for some reason.
            return settings_type(exclusive=False, auto_convert=True)
        except Exception:
            logging.debug(
                "[call_audio] could not apply shared WASAPI settings",
                exc_info=True,
            )
            return None

    def _open_input_stream(
        self,
        *,
        device_name: Optional[str] = None,
        strict: bool = False,
        generation: Optional[int] = None,
    ):
        selected_name = self._input_device_name if device_name is None else str(device_name or "")
        if generation is None:
            generation = self._input_generation

        if strict and selected_name:
            preferred = self._resolve_device(selected_name, input_device=True)
            if preferred is None:
                raise CallAudioUnavailable(
                    f"Selected microphone is not available: {selected_name}"
                )
            candidates = (preferred,)
        else:
            candidates = self._candidate_devices(selected_name, input_device=True)

        last_error = None
        for device in candidates:
            for rate in self._candidate_rates(device):
                try:
                    stream = self._sd.InputStream(
                        samplerate=rate,
                        blocksize=max(1, int(rate * CALL_FRAME_MS / 1000)),
                        device=device,
                        channels=1,
                        dtype="float32",
                        latency=CALL_DEVICE_LATENCY_SECONDS,
                        extra_settings=self._stream_extra_settings(
                            device, input_device=True
                        ),
                        callback=self._on_microphone_frame(rate, generation),
                    )
                    logging.info(
                        "[call_audio] input opened device=%r rate=%s latency=%r",
                        device,
                        rate,
                        getattr(stream, "latency", CALL_DEVICE_LATENCY_SECONDS),
                    )
                    return stream, rate
                except Exception as exc:
                    last_error = exc
        raise CallAudioUnavailable(f"No microphone could be opened for the call: {last_error}")

    def _open_output_stream(self):
        # Production call playback uses BASS, exactly like the program/effect
        # output device selectors. Explicitly injected sounddevice modules are
        # retained for the existing platform-neutral transport tests.
        if self._output_factory is not None:
            return self._output_factory(self._config.output_device_name), CALL_SAMPLE_RATE
        if not self._sounddevice_injected:
            return _BassCallOutput(self._config.output_device_name), CALL_SAMPLE_RATE

        last_error = None
        for device in self._candidate_devices(self._config.output_device_name, input_device=False):
            for rate in self._candidate_rates(device):
                try:
                    stream = self._sd.OutputStream(
                        samplerate=rate,
                        blocksize=max(1, int(rate * CALL_FRAME_MS / 1000)),
                        device=device,
                        channels=1,
                        dtype="float32",
                        latency=CALL_DEVICE_LATENCY_SECONDS,
                        extra_settings=self._stream_extra_settings(
                            device, input_device=False
                        ),
                    )
                    logging.info(
                        "[call_audio] injected test output opened device=%r rate=%s latency=%r",
                        device,
                        rate,
                        getattr(stream, "latency", CALL_DEVICE_LATENCY_SECONDS),
                    )
                    return stream, rate
                except Exception as exc:
                    last_error = exc
        raise CallAudioUnavailable(f"No speaker could be opened for the call: {last_error}")

    def _on_microphone_frame(self, source_rate: int, generation: int):
        def _callback(indata, _frames, _time_info, status):
            if status:
                logging.debug("[call_audio] microphone status: %s", status)
            if (
                self._stop_event.is_set()
                or indata is None
                or generation != self._input_generation
            ):
                return
            samples = _resample_mono(np.asarray(indata), source_rate, CALL_SAMPLE_RATE)
            if samples.size:
                self._put_drop_oldest(self._mic_queue, _pcm16_bytes(samples))

        return _callback

    def _dequeue_fresh_microphone_frame(self) -> tuple[bytes, int]:
        """Return current microphone audio instead of replaying stale backlog."""
        pcm = self._mic_queue.get(timeout=0.1)
        dropped = 0
        while self._mic_queue.qsize() > CALL_MIC_TARGET_BACKLOG_FRAMES:
            try:
                pcm = self._mic_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        return pcm, dropped

    def _send_microphone_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                pcm, dropped = self._dequeue_fresh_microphone_frame()
            except queue.Empty:
                continue

            if dropped:
                previous_dropped = self._mic_frames_dropped_for_latency
                self._mic_frames_dropped_for_latency += dropped
                if previous_dropped == 0 or (
                    previous_dropped // 50
                    != self._mic_frames_dropped_for_latency // 50
                ):
                    logging.info(
                        "[call_audio] skipped stale microphone audio frames=%s total=%s backlog=%s",
                        dropped,
                        self._mic_frames_dropped_for_latency,
                        self._mic_queue.qsize(),
                    )

            try:
                if self._microphone_muted:
                    pcm = b"\x00" * len(pcm)
                self._sio.emit(
                    "call:audio:mic",
                    {
                        "session": self._config.session,
                        "sampleRate": CALL_SAMPLE_RATE,
                        "encoding": "base64",
                        "pcm": base64.b64encode(pcm).decode("ascii"),
                    },
                )
                self._mic_frames_sent += 1
                self._mic_bytes_sent += len(pcm)
                if self._mic_frames_sent == 1 or self._mic_frames_sent % 50 == 0:
                    logging.info(
                        "[call_audio] microphone sent session=%s frames=%s bytes=%s",
                        self._config.session, self._mic_frames_sent, self._mic_bytes_sent,
                    )
            except Exception:
                logging.exception("[call_audio] failed to send microphone audio")
                time.sleep(0.05)

    def _play_remote_loop(self) -> None:
        """Play fixed 20 ms blocks behind a small jitter reservoir.

        Remote PCM reaches Python over Socket.IO and therefore does not arrive
        at perfectly even intervals. Writing every packet immediately made the
        Windows output device run dry between otherwise healthy packets, which
        sounded like short cuts. Keep only a small reservoir, re-prime after a
        real starvation, and discard old receive audio if a long stall ever
        builds an excessive backlog.
        """
        pending = np.empty(0, dtype=np.float32)
        primed = False
        priming_started_at: Optional[float] = None

        while not self._stop_event.is_set():
            frame_samples = max(1, int(self._output_rate * CALL_FRAME_MS / 1000))
            prebuffer_samples = max(
                frame_samples,
                int(self._output_rate * CALL_OUTPUT_PREBUFFER_MS / 1000),
            )
            max_buffer_samples = max(
                prebuffer_samples,
                int(self._output_rate * CALL_OUTPUT_MAX_BUFFER_MS / 1000),
            )

            if primed and pending.size >= frame_samples:
                if pending.size > max_buffer_samples:
                    dropped = int(pending.size - prebuffer_samples)
                    pending = pending[-prebuffer_samples:].copy()
                    self._output_samples_dropped += dropped
                    logging.info(
                        "[call_audio] remote backlog trimmed dropped_ms=%.1f total_dropped_ms=%.1f",
                        dropped * 1000.0 / self._output_rate,
                        self._output_samples_dropped * 1000.0 / self._output_rate,
                    )

                frame = pending[:frame_samples]
                pending = pending[frame_samples:]
                try:
                    if self._output_stream is not None:
                        underflowed = self._output_stream.write(frame.reshape(-1, 1))
                        if underflowed:
                            logging.debug("[call_audio] output stream reported underflow")
                except Exception:
                    logging.exception("[call_audio] failed to play remote call audio")
                    time.sleep(0.01)
                continue

            timeout = (
                CALL_OUTPUT_REBUFFER_WAIT_MS / 1000.0
                if primed
                else CALL_OUTPUT_PREBUFFER_MS / 1000.0
            )
            try:
                pcm, source_rate = self._output_queue.get(timeout=timeout)
            except queue.Empty:
                now = time.monotonic()
                if primed:
                    primed = False
                    priming_started_at = now if pending.size else None
                    self._output_rebuffer_count += 1
                    if self._output_rebuffer_count == 1 or self._output_rebuffer_count % 10 == 0:
                        logging.info(
                            "[call_audio] remote audio rebuffering count=%s buffered_ms=%.1f",
                            self._output_rebuffer_count,
                            pending.size * 1000.0 / self._output_rate,
                        )
                elif (
                    pending.size >= frame_samples
                    and priming_started_at is not None
                    and now - priming_started_at >= CALL_OUTPUT_PREBUFFER_MS / 1000.0
                ):
                    # Do not strand a short final packet forever just because
                    # it never reached the normal prebuffer target.
                    primed = True
                continue

            try:
                samples = _pcm16_float32(pcm)
                samples = _resample_mono(samples, source_rate, self._output_rate)
            except Exception:
                logging.exception("[call_audio] failed to decode remote call audio")
                continue

            if not samples.size:
                continue
            if pending.size:
                pending = np.concatenate((pending, samples))
            else:
                pending = samples.copy()
            if priming_started_at is None:
                priming_started_at = time.monotonic()
            if not primed and pending.size >= prebuffer_samples:
                primed = True

    def _emit_start(self) -> None:
        try:
            self._sio.emit(
                "call:audio:start",
                {
                    "session": self._config.session,
                    "outputDeviceName": self._config.output_device_name or "",
                },
            )
        except Exception:
            logging.debug("[call_audio] could not emit call:audio:start", exc_info=True)

    def _emit_output_device(self, device_name: str) -> None:
        """Keep local Chromium page audio on the same speaker as the call."""
        try:
            self._sio.emit(
                "call:audio:output-device",
                {
                    "session": self._config.session,
                    "outputDeviceName": device_name or "",
                },
            )
        except Exception:
            logging.debug(
                "[call_audio] could not emit browser call output device",
                exc_info=True,
            )

    def _emit_stop(self) -> None:
        try:
            self._sio.emit("call:audio:stop", {"session": self._config.session})
        except Exception:
            logging.debug("[call_audio] could not emit call:audio:stop", exc_info=True)

    @staticmethod
    def _close_stream(stream) -> None:
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            logging.debug("[call_audio] failed to stop stream", exc_info=True)
        try:
            stream.close()
        except Exception:
            logging.debug("[call_audio] failed to close stream", exc_info=True)

    @staticmethod
    def _drain_queue(items: queue.Queue) -> None:
        while True:
            try:
                items.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _put_drop_oldest(items: queue.Queue, item) -> None:
        try:
            items.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            items.get_nowait()
        except queue.Empty:
            pass
        try:
            items.put_nowait(item)
        except queue.Full:
            pass
