"""Dependency regression coverage for native-VoIP incoming calls."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wa_js_is_pinned_after_native_voip_incoming_call_fix():
    """Do not let npm reuse the old lockfile commit that missed activeCall."""
    package = json.loads(
        (ROOT / "client" / "api_patches" / "package.json").read_text(
            encoding="utf-8"
        )
    )
    wa_js = package["dependencies"]["@wppconnect-team/wa-js"]
    assert wa_js.endswith("#6972a845474e75f77800361c7b242818c5eea377")
