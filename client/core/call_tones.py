"""The tones WhatsApp plays itself during a call, made by WinZapp.

With the WPPConnect engine the WhatsApp Web page in the background plays them
(the ringback of the country dialed, the connecting and reconnecting beeps, the
busy signal). The Neonize engine has no page, so WinZapp makes the same tones.
They are plain synthesized tones -- one or two sine waves on a cadence -- and the
numbers come from the desktop client of WhatsApp (see ``call_tone_data``).

Pure functions, no wx and no audio device: ``synthesize_wav`` returns the bytes of
a WAV file holding one period of the tone, to be played in a loop.
"""
import array
import io
import math
import wave
from dataclasses import dataclass

from core.call_tone_data import RINGBACK_ROWS

SAMPLE_RATE = 16000
#: Peak of the finished wave, as a fraction of full scale. Call tones are heard
#: next to the voice of the other person: well below the notification sounds.
PEAK = 0.30
#: Fade at the edge of every burst, so the tone starts and stops without a click.
FADE_MS = 5


@dataclass(frozen=True)
class Tone:
    """freq1/freq2 in Hz (freq2 0 = a single tone), cadence ((on_ms, off_ms), ...)
    repeated for as long as the tone plays. With ``modulated`` freq2 is the rate
    at which freq1 is switched up and down, not a second tone. (Unverified reading:
    the original marks those rows with a flag whose use was not checked in its
    synthesis loop; compare by ear with a real call.)"""
    freq1: int
    freq2: int
    cadence: tuple
    modulated: bool = False
    loop: bool = True
    repeats: int = 1

    def key(self) -> str:
        """A stable file name for the cache of the synthesized wave."""
        cadence = "-".join(f"{on}x{off}" for on, off in self.cadence)
        return (f"{self.freq1}_{self.freq2}{'m' if self.modulated else ''}_{cadence}"
                f"_r{self.repeats}{'_loop' if self.loop else ''}")


#: Tones that do not depend on the country (the desktop client's own values).
CONNECTING = Tone(480, 0, ((200, 200), (200, 3000)))
RECONNECTING = CONNECTING
INTERRUPTION = CONNECTING
BUSY = Tone(480, 620, ((500, 500),))
GROUP_EVENT_SHORT = Tone(400, 0, ((150, 50), (250, 50)), loop=False)
#: The incoming call that is waiting while another one is in progress, and the
#: request to turn a voice call into a video call: 600 Hz double beep.
INCOMING_PENDING_CALL = Tone(600, 0, ((150, 50), (150, 3000)), loop=False, repeats=3)
VIDEO_UPGRADE_REQUEST = Tone(600, 0, ((150, 50), (150, 3000)), loop=False)

DEFAULT_RINGBACK_CODE = "1"


def _ringback_tone(row) -> Tone:
    _code, freq1, freq2, cadence, modulated = row
    return Tone(freq1, freq2, tuple(cadence), modulated)


def ringback_for(number: str) -> Tone:
    """The ringback of the country a call goes to. *number* is the digits of the
    phone number dialed, country calling code first; the first row of the table
    whose code starts it wins, as in the original. Without a number, or with no
    match, the American tone is used, like the original does."""
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    if digits:
        for row in RINGBACK_ROWS:
            if digits.startswith(row[0]):
                return _ringback_tone(row)
    return _ringback_tone(RINGBACK_ROWS[0])


def _burst(tone: Tone, frames: int, rate: int) -> list:
    """*frames* samples of the tone, as floats in -1..1, fade included."""
    fade = max(1, rate * FADE_MS // 1000)
    out = []
    for n in range(frames):
        t = n / rate
        if tone.modulated and tone.freq2:
            # 100 % amplitude modulation of the carrier
            value = math.sin(2 * math.pi * tone.freq1 * t) * 0.5 * (
                1 - math.cos(2 * math.pi * tone.freq2 * t))
        elif tone.freq2:
            value = (math.sin(2 * math.pi * tone.freq1 * t)
                     + math.sin(2 * math.pi * tone.freq2 * t)) / 2
        else:
            value = math.sin(2 * math.pi * tone.freq1 * t)
        edge = min(1.0, n / fade, (frames - 1 - n) / fade)
        out.append(value * edge)
    return out


def synthesize_wav(tone: Tone, rate: int = SAMPLE_RATE) -> bytes:
    """One period of *tone* (every on/off pair, *repeats* times) as a 16-bit mono
    WAV. A tone that loops is played in a loop; the silence after the last burst
    is part of the period."""
    samples = array.array("h")
    for _ in range(max(1, tone.repeats)):
        for on_ms, off_ms in tone.cadence:
            for value in _burst(tone, rate * on_ms // 1000, rate):
                samples.append(int(value * PEAK * 32767))
            samples.extend([0] * (rate * off_ms // 1000))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def period_ms(tone: Tone) -> int:
    """How long one period of the tone lasts."""
    return max(1, tone.repeats) * sum(on + off for on, off in tone.cadence)
