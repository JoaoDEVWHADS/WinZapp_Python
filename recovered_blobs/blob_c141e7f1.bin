"""Tests for the pure helpers in client/audio_devices.py (no PyAudio/BASS)."""

import audio_devices as ad


def test_normalize_fills_defaults_from_empty():
    out = ad.normalize_audio_devices({})
    assert out == {"voice_input": "", "voice_output": "", "effects_output": ""}


def test_normalize_coerces_non_strings_to_default():
    out = ad.normalize_audio_devices(
        {"voice_input": 123, "voice_output": None, "effects_output": "Speakers"})
    assert out["voice_input"] == ""      # int → default
    assert out["voice_output"] == ""     # None → default
    assert out["effects_output"] == "Speakers"


def test_normalize_ignores_non_dict():
    assert ad.normalize_audio_devices(None)["voice_input"] == ""
    assert ad.normalize_audio_devices("garbage")["effects_output"] == ""


def test_resolve_choice_default_stays_default():
    assert ad.resolve_device_choice("", ["A", "B"]) == ""


def test_resolve_choice_present_device_kept():
    assert ad.resolve_device_choice("Headset", ["Speakers", "Headset"]) == "Headset"


def test_resolve_choice_missing_device_falls_back_without_mutating():
    # Unplugged device → default, but caller's stored name is untouched (we just
    # return "", we don't rewrite settings), so it's picked up if it returns.
    saved = "USB Mic"
    assert ad.resolve_device_choice(saved, ["Built-in Mic"]) == ""
    assert saved == "USB Mic"


def test_outputs_share_device_both_default():
    assert ad.outputs_share_device({}) is True


def test_outputs_share_device_same_name():
    devs = {"voice_output": "Speakers", "effects_output": "Speakers"}
    assert ad.outputs_share_device(devs) is True


def test_outputs_differ_when_names_differ():
    devs = {"voice_output": "Headset", "effects_output": "Speakers"}
    assert ad.outputs_share_device(devs) is False


def test_bass_output_device_default_for_empty():
    # No name → default device sentinel, regardless of BASS availability.
    assert ad.bass_output_device("") == ad.BASS_DEFAULT_DEVICE


def test_bass_output_device_positional_number(monkeypatch):
    # Device number is position-in-list + 1 (BASS numbers from 1). A disabled
    # slot is kept as "" so positions — and thus device numbers — stay stable.
    monkeypatch.setattr(ad, "_bass_device_names_utf8",
                        lambda: ["Speakers", "", "Słuchawki USB"])
    assert ad.bass_output_device("Speakers") == 1
    assert ad.bass_output_device("Słuchawki USB") == 3   # not 2 — dead slot kept
    assert ad.bass_output_device("Nieistniejące") == ad.BASS_DEFAULT_DEVICE


def test_enumerate_output_skips_synthetic_and_disabled(monkeypatch):
    # "Default"/"No sound"/disabled ("") are filtered from the choosable list,
    # but UTF-8 names with diacritics survive intact.
    monkeypatch.setattr(ad, "_bass_device_names_utf8",
                        lambda: ["Default", "Speakers", "", "Głośniki tył", "No sound"])
    assert ad.enumerate_output_devices() == ["Speakers", "Głośniki tył"]


def test_input_index_none_for_empty():
    assert ad.input_device_index("") is None
