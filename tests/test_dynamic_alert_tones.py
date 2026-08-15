from pathlib import Path

from core.alert_tones import discover_alert_tone_choices, resolve_alert_tone_path


def _pack(folder: Path, alerts=None):
    return {
        "id": folder.name,
        "dir": str(folder),
        "events": {},
        "alerts": alerts or {},
    }


def test_discovers_extra_audio_files_with_natural_order(tmp_path):
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir()
    for name in ("Alert-10.ogg", "Alert-2.ogg", "Campainha.mp3", "ignore.txt"):
        (alerts_dir / name).touch()

    choices = discover_alert_tone_choices(_pack(tmp_path), None)

    assert [label for _key, label in choices] == ["Alert-2", "Alert-10", "Campainha"]
    assert choices[0][0] == "file:alerts/Alert-2.ogg"


def test_manifest_keys_are_preserved_without_duplicate_scanned_files(tmp_path):
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir()
    (alerts_dir / "Alert-01.ogg").touch()
    pack = _pack(tmp_path, {"alert_1": "alerts/Alert-01.ogg"})

    assert discover_alert_tone_choices(pack, None) == [("alert_1", "Alert-01")]


def test_pack_without_alerts_folder_falls_back_to_default(tmp_path):
    active_dir = tmp_path / "active"
    active_dir.mkdir()
    default_dir = tmp_path / "default"
    (default_dir / "alerts").mkdir(parents=True)
    (default_dir / "alerts" / "Fallback.ogg").touch()

    choices = discover_alert_tone_choices(_pack(active_dir), _pack(default_dir))

    assert choices == [("file:alerts/Fallback.ogg", "Fallback")]


def test_missing_alerts_folders_return_empty_list(tmp_path):
    active_dir = tmp_path / "active"
    default_dir = tmp_path / "default"
    active_dir.mkdir()
    default_dir.mkdir()

    assert discover_alert_tone_choices(_pack(active_dir), _pack(default_dir)) == []


def test_partial_pack_keeps_missing_default_choices_available(tmp_path):
    active_dir = tmp_path / "active"
    default_dir = tmp_path / "default"
    (active_dir / "alerts").mkdir(parents=True)
    (default_dir / "alerts").mkdir(parents=True)
    (active_dir / "alerts" / "Custom.ogg").touch()
    (default_dir / "alerts" / "Fallback.ogg").touch()

    choices = discover_alert_tone_choices(_pack(active_dir), _pack(default_dir))

    assert choices == [
        ("file:alerts/Custom.ogg", "Custom"),
        ("file:alerts/Fallback.ogg", "Fallback"),
    ]


def test_resolves_discovered_file_with_default_fallback(tmp_path):
    active_dir = tmp_path / "active"
    default_dir = tmp_path / "default"
    active_dir.mkdir()
    (default_dir / "alerts").mkdir(parents=True)
    expected = default_dir / "alerts" / "Fallback.wav"
    expected.touch()

    resolved = resolve_alert_tone_path(
        _pack(active_dir), _pack(default_dir), "file:alerts/Fallback.wav"
    )

    assert resolved == str(expected)


def test_discovered_file_cannot_escape_pack_folder(tmp_path):
    outside = tmp_path / "outside.ogg"
    outside.touch()
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()

    assert resolve_alert_tone_path(
        _pack(pack_dir), None, "file:../outside.ogg"
    ) == ""
