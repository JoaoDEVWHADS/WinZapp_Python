"""Tests synchronization between core.utils.DEFAULT_SETTINGS and client/data/settings_default.json."""

import json
import os
import sys

from core.utils import DEFAULT_SETTINGS


def test_default_settings_matches_json_structure():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "client", "data", "settings_default.json")
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    assert set(DEFAULT_SETTINGS.keys()) == set(json_data.keys()), (
        f"Top-level keys mismatch: {set(DEFAULT_SETTINGS.keys()) ^ set(json_data.keys())}"
    )

    for section, val in DEFAULT_SETTINGS.items():
        if isinstance(val, dict):
            assert isinstance(json_data[section], dict), f"Section {section} must be a dict"
            assert set(val.keys()) == set(json_data[section].keys()), (
                f"Keys in section {section} mismatch: {set(val.keys()) ^ set(json_data[section].keys())}"
            )
            for k in val:
                assert val[k] == json_data[section][k], (
                    f"Default value mismatch for {section}.{k}: {val[k]!r} != {json_data[section][k]!r}"
                )
