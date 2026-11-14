"""The tones of a call, made by WinZapp for the Neonize engine.

The numbers come from the desktop client of WhatsApp; the checks below are the
ones anyone can verify with a phone: a call to Brazil rings 1 s every 5 s at
425 Hz, one to the United States 2 s every 6 s at 440+480 Hz, and so on.
"""
import io
import wave
from types import SimpleNamespace

from core import call_tone_player as ctp
from core import call_tones as ct
from core.call_tone_data import RINGBACK_ROWS


def samples_of(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth()) == (1, 2)
        raw = wav.readframes(wav.getnframes())
        rate = wav.getframerate()
    values = [int.from_bytes(raw[i:i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
    return values, rate


def frequency_of(values, rate):
    """Zero crossings per second of the samples, halved."""
    crossings = sum(1 for a, b in zip(values, values[1:]) if (a < 0) != (b < 0))
    return crossings / 2 / (len(values) / rate)


# -- the table -----------------------------------------------------------------

def test_the_table_is_the_full_set_of_the_original():
    assert len(RINGBACK_ROWS) == 151
    assert RINGBACK_ROWS[0][0] == "1"          # the default, and the North American plan


def test_known_countries_ring_the_way_their_phones_do():
    assert ct.ringback_for("5511999990000") == ct.Tone(425, 0, ((1000, 4000),))     # Brazil
    assert ct.ringback_for("351912345678") == ct.Tone(400, 0, ((1000, 5000),))     # Portugal
    assert ct.ringback_for("34600123456") == ct.Tone(425, 0, ((1500, 3000),))       # Spain
    assert ct.ringback_for("14155550123") == ct.Tone(440, 480, ((2000, 4000),))     # USA / Canada
    assert ct.ringback_for("447700900123") == ct.Tone(400, 450, ((400, 200), (400, 2000)))  # UK


def test_no_number_or_an_unknown_one_rings_like_the_default():
    default = ct.ringback_for("1")
    assert ct.ringback_for("") == default
    assert ct.ringback_for(None) == default
    assert ct.ringback_for("0000") == default


def test_punctuation_in_the_number_is_ignored():
    assert ct.ringback_for("+55 (11) 99999-0000") == ct.ringback_for("5511999990000")


def test_every_row_makes_a_tone():
    for row in RINGBACK_ROWS:
        tone = ct.ringback_for(row[0])
        assert tone.cadence and all(on > 0 for on, _ in tone.cadence)


# -- the wave ------------------------------------------------------------------

def test_a_single_tone_has_the_right_pitch_and_cadence():
    wav = ct.synthesize_wav(ct.Tone(425, 0, ((1000, 4000),)))
    values, rate = samples_of(wav)
    assert len(values) == rate * 5                      # 1 s on, 4 s off
    assert max(abs(v) for v in values) <= ct.PEAK * 32767 + 1
    burst, silence = values[:rate], values[rate:]
    assert all(v == 0 for v in silence)
    assert abs(frequency_of(burst[rate // 10:-rate // 10], rate) - 425) < 8


def test_a_dual_tone_is_the_sum_of_both():
    values, rate = samples_of(ct.synthesize_wav(ct.Tone(480, 620, ((500, 500),))))
    assert len(values) == rate
    assert max(abs(v) for v in values[:rate // 2]) > 0.2 * 32767


def test_a_tone_starts_and_stops_without_a_click():
    values, _ = samples_of(ct.synthesize_wav(ct.Tone(440, 0, ((300, 100),))))
    assert abs(values[0]) < 500 and abs(values[299 * 16 - 1]) < 2500


def test_a_modulated_tone_swells_and_fades():
    tone = ct.Tone(425, 25, ((1000, 0),), modulated=True)
    values, rate = samples_of(ct.synthesize_wav(tone))
    window = rate // 500
    peaks = [max(abs(v) for v in values[i:i + window]) for i in range(0, rate, window)]
    assert max(peaks) > 0.25 * 32767 and min(peaks) < 0.05 * 32767


def test_repeats_make_the_period_longer():
    once = ct.Tone(600, 0, ((150, 50), (150, 3000)), loop=False)
    assert ct.period_ms(ct.INCOMING_PENDING_CALL) == 3 * ct.period_ms(once)
    values, rate = samples_of(ct.synthesize_wav(ct.INCOMING_PENDING_CALL))
    assert len(values) * 1000 // rate == ct.period_ms(ct.INCOMING_PENDING_CALL)


def test_the_fixed_tones_are_the_originals():
    assert ct.BUSY == ct.Tone(480, 620, ((500, 500),))
    assert ct.CONNECTING.cadence == ((200, 200), (200, 3000)) and ct.CONNECTING.freq1 == 480
    assert ct.RECONNECTING == ct.INTERRUPTION == ct.CONNECTING
    assert ct.GROUP_EVENT_SHORT.loop is False


def test_a_tone_names_its_cache_file_by_what_it_is():
    assert ct.BUSY.key() != ct.CONNECTING.key()
    assert ct.BUSY.key() == ct.Tone(480, 620, ((500, 500),)).key()


# -- which state plays what ------------------------------------------------------

def test_the_ringback_plays_only_while_our_call_rings_and_by_the_country():
    assert ctp.tone_for_state("RINGING", True, "5511999990000") == ct.ringback_for("55")
    assert ctp.tone_for_state("ringing", True, "351912345678").freq1 == 400
    assert ctp.tone_for_state("RINGING", False, "5511999990000") is None    # an incoming ring is not ours


def test_our_call_rings_back_while_the_bridge_says_connecting():
    """Measured on a real call: offer 0.0 s, CONNECTING 0.7 s, answered 9.1 s. The
    other phone rang during all of CONNECTING, and the beeps were heard instead of
    the Brazilian ringback."""
    assert ctp.tone_for_state("CONNECTING", True, "5511999990000") == ct.Tone(425, 0, ((1000, 4000),))
    assert ctp.tone_for_state("CONNECTING", True, "") == ct.ringback_for("1")


def test_connecting_and_rejoining_beep_and_the_rest_is_silent():
    assert ctp.tone_for_state("CONNECTING", False, "") == ct.CONNECTING
    assert ctp.tone_for_state("REJOINING", True, "") == ct.RECONNECTING
    for state in ("CALLING", "ACTIVE", "ENDED", "REJECTED", "INCOMING_RING", "", None):
        assert ctp.tone_for_state(state, True, "55") is None


def test_the_number_behind_a_peer():
    assert ctp.peer_number({}, "5511999990000@s.whatsapp.net") == "5511999990000"
    assert ctp.peer_number({}, "5511999990000@c.us") == "5511999990000"
    assert ctp.peer_number({"9@lid": "351912345678@s.whatsapp.net"}, "9@lid") == "351912345678"
    assert ctp.peer_number({}, "9@lid") == ""            # the digits of an @lid are not a phone
    assert ctp.peer_number({}, "1203@g.us") == ""
    assert ctp.peer_number({}, "") == ""


# -- the player ------------------------------------------------------------------

class FakeSound:
    def __init__(self, path, looping):
        self.path, self.looping, self.played, self.stopped = path, looping, 0, 0

    def play(self):
        self.played += 1

    def stop(self):
        self.stopped += 1


def make_player(tmp_path):
    made = []

    def loader(_system, path, looping=False):
        sound = FakeSound(path, looping)
        made.append(sound)
        return sound

    return ctp.CallTonePlayer(None, str(tmp_path / "tones"), loader), made


def test_a_tone_is_written_once_and_played_in_a_loop(tmp_path):
    player, made = make_player(tmp_path)

    player.play(ct.BUSY)

    assert made[0].looping is True and made[0].played == 1
    assert samples_of(open(made[0].path, "rb").read())[1] == ct.SAMPLE_RATE
    assert player.playing == ct.BUSY


def test_the_same_tone_again_does_not_restart_it(tmp_path):
    player, made = make_player(tmp_path)

    player.play(ct.BUSY)
    player.play(ct.BUSY)

    assert len(made) == 1 and made[0].played == 1


def test_another_tone_replaces_the_first_and_stop_silences(tmp_path):
    player, made = make_player(tmp_path)

    player.play(ct.BUSY)
    player.play(ct.CONNECTING)
    player.stop()
    player.stop()

    assert made[0].stopped == 1 and made[1].stopped == 1 and player.playing is None


def test_a_one_shot_tone_is_not_looped(tmp_path):
    player, made = make_player(tmp_path)

    player.play(ct.GROUP_EVENT_SHORT)

    assert made[0].looping is False


def test_a_sound_that_cannot_play_does_not_break_the_call(tmp_path):
    def broken(*_a, **_k):
        raise RuntimeError("no device")

    player = ctp.CallTonePlayer(None, str(tmp_path), broken)

    player.play(ct.BUSY)

    assert player.playing is None


def window(neonize, player):
    return SimpleNamespace(_uses_neonize=lambda: neonize, _call_tone_player=player,
                           _lid_to_phone={})


def test_the_ringback_follows_the_call_state_for_neonize(tmp_path):
    player, made = make_player(tmp_path)
    mw = window(True, player)
    active = {"outgoing": True, "peer_jid": "5511999990000@s.whatsapp.net"}

    ctp.update_call_tone(mw, active, "RINGING")
    assert player.playing == ct.ringback_for("55")
    ctp.update_call_tone(mw, active, "ACTIVE")

    assert player.playing is None and made[0].stopped == 1


def test_wppconnect_keeps_the_tones_to_the_whatsapp_web_page(tmp_path):
    player, made = make_player(tmp_path)

    ctp.update_call_tone(window(False, player), {"outgoing": True, "peer_jid": "55@c.us"}, "RINGING")

    assert made == []


def test_stopping_with_no_player_yet_is_harmless():
    ctp.stop_call_tone(SimpleNamespace())


def test_a_player_that_cannot_be_built_does_not_break_the_call_state_handling():
    mw = SimpleNamespace(_uses_neonize=lambda: True, _lid_to_phone={})     # no sound_system, no player

    ctp.update_call_tone(mw, {"outgoing": True, "peer_jid": "55@c.us"}, "RINGING")


def test_the_cache_file_is_replaced_whole(tmp_path):
    player, made = make_player(tmp_path)

    player.play(ct.BUSY)

    assert not [name for name in (tmp_path / "tones").iterdir() if name.suffix == ".tmp"]


# -- the sound of a call that ends -------------------------------------------------

class _EndSound:
    def __init__(self):
        self.played = 0

    def play(self):
        self.played += 1


def ended_window(neonize, last_state="ACTIVE"):
    return SimpleNamespace(_uses_neonize=lambda: neonize, call_ended_sound=_EndSound(),
                           _voice_call_last_announced_state=last_state)


def test_a_connected_call_that_ends_plays_the_ended_sound_once_on_neonize():
    mw, active = ended_window(True), {}

    ctp.play_call_ended_sound(mw, active)
    ctp.play_call_ended_sound(mw, active)           # a repeated end event

    assert mw.call_ended_sound.played == 1


def test_wppconnect_keeps_its_own_ended_sound():
    mw = ended_window(False)

    ctp.play_call_ended_sound(mw, {})

    assert mw.call_ended_sound.played == 0


def test_a_call_nobody_answered_ends_without_the_sound():
    for last in ("", "CONNECTING", "REJOINING"):
        mw = ended_window(True, last)

        ctp.play_call_ended_sound(mw, {})

        assert mw.call_ended_sound.played == 0


def test_a_sound_that_cannot_play_does_not_break_the_end_of_the_call():
    mw = SimpleNamespace(_uses_neonize=lambda: True, _voice_call_last_announced_state="ACTIVE")

    ctp.play_call_ended_sound(mw, {})        # no call_ended_sound attribute at all


def test_the_default_pack_carries_the_call_ended_event():
    import json
    import os
    from core.sound_system import SOUND_EVENTS
    root = os.path.join(os.path.dirname(__file__), "..", "client", "sounds", "default")
    manifest = json.load(open(os.path.join(root, "default.pack.json"), encoding="utf-8"))

    assert ("call_ended", "call_ended.ogg") in SOUND_EVENTS
    assert manifest["events"]["call_ended"] == "call_ended.ogg"
    with open(os.path.join(root, "call_ended.ogg"), "rb") as stream:
        assert stream.read(4) == b"OggS"


def test_the_sound_plays_when_the_end_is_confirmed_not_on_a_terminal_event_that_the_call_survives():
    """A voice call upgraded to video sends a terminal event and goes on: the
    sound belongs to _end_active_call_locally, which only a confirmed end reaches."""
    from main import MainWindow
    calls = []
    mw = SimpleNamespace(
        _uses_neonize=lambda: True, call_ended_sound=_EndSound(),
        _voice_call_last_announced_state="ACTIVE",
        _stop_voice_call_audio=lambda **k: calls.append("stop"),
        output=lambda *a, **k: calls.append("speak"),
        i18n=SimpleNamespace(t=lambda key: key),
        _watch_ended_call_log=lambda *a: None,
        _ensure_page_call_ended=lambda *a: None)

    MainWindow._end_active_call_locally(mw, {"peer_jid": "55@c.us"}, "ID", "55@c.us")

    assert mw.call_ended_sound.played == 1 and calls == ["stop", "speak"]
    import inspect
    from main_window import calls as calls_module
    terminal = inspect.getsource(calls_module.CallsMixin.on_voice_call_state_event)
    assert "play_call_ended_sound" not in terminal
