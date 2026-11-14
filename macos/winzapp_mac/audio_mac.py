"""Recover the microphone after CoreAudio restarts.

WinZapp keeps one pyaudio.PyAudio per panel for the whole session, and
PortAudio snapshots the device list when it initialises. When coreaudiod
restarts (an audio driver update, Crosspoint, a crash) every device handle
in that snapshot goes dead and each recording attempt fails with "No input
stream could be opened" until WinZapp is relaunched.

HealingPyAudio re-initialises PortAudio — a fresh device list — the first
time an open() fails for a reason other than the requested format, then
retries. Rebuilding costs ~0.9 s on a machine with many devices, so it is
done only on such a failure, never per recording.
"""

import logging

import pyaudio

_OrigPyAudio = pyaudio.PyAudio

# Failures that just mean "try the next rate/channel combination".
_FORMAT_ERRORS = {
    getattr(pyaudio, "paInvalidSampleRate", -9997),
    getattr(pyaudio, "paInvalidChannelCount", -9998),
    getattr(pyaudio, "paSampleFormatNotSupported", -9994),
}


class HealingPyAudio(_OrigPyAudio):
    def __init__(self):
        super().__init__()
        self._healed_since_success = False

    def _reinitialise(self):
        try:
            super().terminate()
        except Exception:
            pass
        _OrigPyAudio.__init__(self)
        logging.info("[audio_mac] PortAudio re-initialised (%d devices)",
                     self.get_device_count())

    def open(self, *args, **kwargs):
        try:
            stream = super().open(*args, **kwargs)
        except Exception as exc:
            code = exc.args[1] if isinstance(exc, OSError) and len(exc.args) > 1 else None
            if code in _FORMAT_ERRORS or self._healed_since_success:
                raise
            logging.warning("[audio_mac] open failed (%s) — refreshing the device list and retrying", exc)
            self._healed_since_success = True
            self._reinitialise()
            stream = super().open(*args, **kwargs)
        self._healed_since_success = False
        return stream


def install():
    pyaudio.PyAudio = HealingPyAudio
