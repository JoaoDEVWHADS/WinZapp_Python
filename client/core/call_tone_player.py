"""Plays the call tones of ``call_tones`` while a call goes through its phases.

Only for the Neonize engine: with WPPConnect the WhatsApp Web page plays them.
``tone_for_state`` is the rule (pure); ``CallTonePlayer`` writes each tone once
as a WAV in the cache and plays it in a loop through the app's sound system.
"""
import logging
import os

from core.call_tones import (
    CONNECTING, RECONNECTING, Tone, ringback_for, synthesize_wav,
)


def tone_for_state(state: str, outgoing: bool, peer_number: str):
    """The tone a call in *state* plays, or None for silence.

    The ringback is what the caller hears while the other phone rings, by the
    country of the number dialed. A short beep cadence plays while the media
    connects and while the call rejoins after losing the network. Nothing plays
    once the call is active or over."""
    state = str(state or "").upper()
    # The bridge reports CONNECTING from the moment the media transport starts
    # (under a second after the offer) until the other person answers: for our
    # own call that whole stretch is the other phone ringing, so it is the ringback
    # (measured: offer 0.0 s, CONNECTING 0.7 s, answered 9.1 s). Only a call that
    # was offered to us beeps while it connects.
    if outgoing and state in ("RINGING", "CONNECTING"):
        return ringback_for(peer_number)
    if state == "CONNECTING":
        return CONNECTING
    if state == "REJOINING":
        return RECONNECTING
    return None


def peer_number(lid_to_phone: dict, peer_jid: str) -> str:
    """The digits of the number behind *peer_jid*: a phone JID is its own, an
    @lid goes through the map and stays empty when its number is not known
    (the digits of an @lid are not a phone number)."""
    jid = str(peer_jid or "")
    if jid.endswith("@lid"):
        jid = (lid_to_phone or {}).get(jid, "")
    if not jid.endswith(("@s.whatsapp.net", "@c.us")):
        return ""
    return jid.split("@", 1)[0].split(":", 1)[0]


class CallTonePlayer:
    """One tone at a time. *loader* makes a sound from a file path, like
    ``sound_system.load_sound``."""

    def __init__(self, sound_system, cache_dir: str, loader):
        self._sound_system = sound_system
        self._cache_dir = cache_dir
        self._loader = loader
        self._tone = None
        self._sound = None

    @property
    def playing(self):
        return self._tone

    def _file_of(self, tone: Tone) -> str:
        os.makedirs(self._cache_dir, exist_ok=True)
        path = os.path.join(self._cache_dir, tone.key() + ".wav")
        if not os.path.isfile(path):
            partial = path + ".tmp"      # a process that dies mid-write leaves no short WAV
            with open(partial, "wb") as stream:
                stream.write(synthesize_wav(tone))
            os.replace(partial, path)
        return path

    def play(self, tone: Tone) -> None:
        if tone == self._tone:
            return          # the same tone keeps going: a repeated event must not restart it
        self.stop()
        try:
            self._sound = self._loader(self._sound_system, self._file_of(tone), looping=tone.loop)
            self._sound.play()
            self._tone = tone
        except Exception:
            logging.exception("[call_tone] could not play %s", tone.key())
            self._sound = None

    def stop(self) -> None:
        sound, self._sound, self._tone = self._sound, None, None
        if sound is None:
            return
        try:
            sound.stop()
        except Exception:
            logging.debug("[call_tone] stop failed", exc_info=True)


def update_call_tone(mw, active: dict, state: str) -> None:
    """Applies the tone of *state* for the active call of main window *mw*."""
    if not getattr(mw, "_uses_neonize", lambda: False)():
        return
    try:
        player = _player_of(mw)
        tone = tone_for_state(
            state, bool(active.get("outgoing")),
            peer_number(getattr(mw, "_lid_to_phone", {}), active.get("peer_jid", "")))
        if tone is None:
            player.stop()
        else:
            player.play(tone)
    except Exception:
        # a missing sound must never keep the call-state handling from running
        logging.exception("[call_tone] could not apply the tone of state %s", state)


def stop_call_tone(mw) -> None:
    player = getattr(mw, "_call_tone_player", None)
    if player is not None:
        player.stop()


def _player_of(mw) -> CallTonePlayer:
    player = getattr(mw, "_call_tone_player", None)
    if player is None:
        from app_paths import data_path
        from core.sound_system import load_sound
        player = mw._call_tone_player = CallTonePlayer(
            mw.sound_system, data_path("cache", "call_tones"), load_sound)
    return player


def play_call_ended_sound(mw, active: dict) -> None:
    """The sound a call that was connected makes when it ends, once, on the Neonize
    engine only (with WPPConnect the WhatsApp Web page plays its own). It is the
    ``call_ended`` Sound Event, so it follows the pack and the user's settings."""
    if not getattr(mw, "_uses_neonize", lambda: False)():
        return
    if getattr(mw, "_voice_call_last_announced_state", "") != "ACTIVE":
        return          # a call nobody answered ends without it
    if active.get("end_sound_played"):
        return
    active["end_sound_played"] = True
    try:
        mw.call_ended_sound.play()
    except Exception:
        logging.exception("[call_tone] could not play the call-ended sound")
