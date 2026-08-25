"""Regression: patch_sender_layer_source()'s transitional-state migration
(client/core/wppconnect_sender_layer_patch.py) was never actually called
from either of the two real patch-application sites — setup_api.py's
_patch_wppconnect_sender_layer() and ApiSetupDialog's copy of the same
name (client/ui/dialogs/api_setup.py) — both only ever looped over the
literal ALL_PATCHES (original, patched) pairs directly. Confirmed by
tests/test_large_file_patch.py, whose only caller of
patch_sender_layer_source() was itself — nothing in setup_api.py or
api_setup.py reached it.

The function migrates a transitional sender.layer.js state that predates
the current PATCHED_SEND_FILE constant and isn't a literal ALL_PATCHES
entry: an intermediate chunked-upload variant using the old
`if (base64.length > 8 * 1024 * 1024)` marker instead of
`if (largeFilePath)`. A machine whose node_modules was patched by an
earlier WinZapp build during this feature's development would have been
silently stuck there forever — every future setup_api.py re-run reports
"did not match the expected upstream source" and skips it, never applying
the current 1 GB document-upload-limit override.

Both entry points now call patch_sender_layer_source() after the
ALL_PATCHES loop to close that gap.
"""

import importlib.util
import os

from core import wppconnect_sender_layer_patch as sender_patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_setup_api():
    spec = importlib.util.spec_from_file_location(
        "setup_api", os.path.join(REPO_ROOT, "setup_api.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _intermediate_chunked_source() -> str:
    """Same construction as test_large_file_patch.py's
    test_sender_patch_migrates_intermediate_chunked_source: the current
    PATCHED_SEND_FILE with its `if (largeFilePath)` marker swapped back
    for the older `if (base64.length > 8 * 1024 * 1024)` one."""
    body = sender_patch.PATCHED_SEND_FILE.replace(
        "        if (largeFilePath) {\n",
        "        if (base64.length > 8 * 1024 * 1024) {\n",
        1,
    )
    return body + "\n    }\n    /**"


def test_setup_api_migrates_the_intermediate_chunked_source(tmp_path):
    layers_dir = (
        tmp_path / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
    )
    layers_dir.mkdir(parents=True)
    sender_js = layers_dir / "sender.layer.js"
    sender_js.write_text(_intermediate_chunked_source(), encoding="utf-8")

    setup_api = _load_setup_api()
    # The intermediate source matches none of the literal ALL_PATCHES pairs
    # (it's a third, undocumented transitional state), so the ordinary
    # per-pair accounting reports it as unmigrated (`missing`) — that part
    # of the return value is unrelated to and unaffected by the extra
    # patch_sender_layer_source() migration step under test here.
    setup_api._patch_wppconnect_sender_layer(str(tmp_path))

    content = sender_js.read_text(encoding="utf-8")
    assert "if (largeFilePath)" in content
    assert "if (base64.length >" not in content


def test_api_setup_dialog_migrates_the_intermediate_chunked_source(tmp_path):
    from ui.dialogs.api_setup import ApiSetupDialog

    layers_dir = tmp_path / "layers"
    layers_dir.mkdir(parents=True)
    sender_js = layers_dir / "sender.layer.js"
    sender_js.write_text(_intermediate_chunked_source(), encoding="utf-8")

    ApiSetupDialog._patch_wppconnect_sender_layer(str(tmp_path))

    content = sender_js.read_text(encoding="utf-8")
    assert "if (largeFilePath)" in content
    assert "if (base64.length >" not in content


def test_setup_api_is_idempotent_on_already_current_content(tmp_path):
    layers_dir = (
        tmp_path / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
    )
    layers_dir.mkdir(parents=True)
    sender_js = layers_dir / "sender.layer.js"
    # A file already fully up to date — the extra migration step must be a
    # true no-op here, not perturb already-current content.
    sender_js.write_text(
        sender_patch.PATCHED_SEND_FILE + "\n    }\n    /**", encoding="utf-8"
    )

    setup_api = _load_setup_api()
    setup_api._patch_wppconnect_sender_layer(str(tmp_path))
    first_pass = sender_js.read_text(encoding="utf-8")
    setup_api._patch_wppconnect_sender_layer(str(tmp_path))
    second_pass = sender_js.read_text(encoding="utf-8")

    assert first_pass == second_pass
