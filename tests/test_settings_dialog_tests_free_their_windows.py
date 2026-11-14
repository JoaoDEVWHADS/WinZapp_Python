"""A test that builds a SettingsDialog must free it with destroy_now().

Destroy() on a top-level window only queues the deletion, and the suite never
runs an event loop, so every dialog (and the frame it hangs on) a test merely
Destroy()s keeps its native window handles for the rest of the run. The
Settings dialog is hundreds of controls and grows with every tab; once the
process runs out of handles, unrelated wx tests later in the run fail with
"invalid window" / "SetScrollPos: no HWND" (CI run 37573480646, after the
Transcription tab was added). tests/conftest.py destroy_now() frees them.
"""

import pathlib
import re

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
_EXEMPT = {pathlib.Path(__file__).name}


def _modules_building_the_dialog():
    return sorted(
        p
        for p in TESTS.glob("test_*.py")
        if p.name not in _EXEMPT
        and re.search(r"\bSettingsDialog\(", p.read_text(encoding="utf-8"))
    )


def test_the_scan_finds_the_modules_that_build_the_dialog():
    assert len(_modules_building_the_dialog()) >= 5


@pytest.mark.parametrize("path", _modules_building_the_dialog(), ids=lambda p: p.name)
def test_the_module_frees_what_it_builds(path):
    source = path.read_text(encoding="utf-8")
    if "pytestmark = pytest.mark.wxgui" not in source:
        pytest.skip("builds no real dialog: SettingsDialog is a stub here")
    assert "destroy_now" in source, f"{path.name} builds a SettingsDialog and never destroy_now()s it"
    # destroy_now() walks up to the frame; a bare dialog.Destroy() leaves it.
