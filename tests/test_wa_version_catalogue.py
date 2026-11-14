"""core/wa_version_catalogue.py — does the installed catalogue reach calls?"""

import json

from core.wa_version_catalogue import (
    CALLS_MINIMUM_BUILD,
    build_key,
    catalogue_supports_calls,
    newest_build,
    read_catalogue,
)


def test_the_minimum_is_the_build_measured_to_bring_calls_up():
    """docs/traps/voice-calls.md: 2.3000.1046948731 never initialised VoIP,
    2.3000.1047835881 did."""
    assert CALLS_MINIMUM_BUILD == "2.3000.1047835881-alpha"


def test_build_key_compares_numerically_and_ignores_the_channel():
    assert build_key("2.3000.1047835881-alpha") == (2, 3000, 1047835881)
    assert build_key("2.3000.999") < build_key("2.3000.1000")
    assert build_key("") is None
    assert build_key("garbage") is None


def test_newest_build_reads_the_list_and_the_current_pointers():
    cat = {"versions": [{"version": "2.3000.1043870876-alpha"},
                        {"version": "2.3000.1046948731-alpha"}],
           "currentAlpha": "2.3000.1048563346-alpha"}
    assert newest_build(cat) == "2.3000.1048563346-alpha"


def test_supports_calls():
    stale = {"versions": [{"version": "2.3000.1046948731-alpha"}]}
    fresh = {"versions": [{"version": "2.3000.1047835881-alpha"}]}
    assert catalogue_supports_calls(stale) is False
    assert catalogue_supports_calls(fresh) is True


def test_cannot_tell_is_none_not_false_or_true():
    for bad in (None, [], {}, {"versions": "x"}, {"versions": [{"nope": 1}]}):
        assert catalogue_supports_calls(bad) is None


def test_read_catalogue(tmp_path):
    good = tmp_path / "versions.json"
    good.write_text(json.dumps({"versions": []}), encoding="utf-8")
    assert read_catalogue(str(good)) == {"versions": []}
    assert read_catalogue(str(tmp_path / "missing.json")) is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert read_catalogue(str(broken)) is None
