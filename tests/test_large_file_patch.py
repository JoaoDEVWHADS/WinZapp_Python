"""Regression checks for large-document delivery through WPPConnect."""

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from core import wppconnect_sender_layer_patch as sender_patch


def test_sender_patch_migrates_vanilla_and_legacy_sources():
    for source in (
        sender_patch.ORIGINAL_SEND_FILE,
        sender_patch.LEGACY_PATCHED_SEND_FILE,
    ):
        patched = source
        for original, replacement in sender_patch.ALL_PATCHES:
            patched = patched.replace(original, replacement)

        assert patched == sender_patch.PATCHED_SEND_FILE

    loading = sender_patch.ORIGINAL_FILE_LOADING
    for original, replacement in sender_patch.ALL_PATCHES:
        loading = loading.replace(original, replacement)
    assert loading == sender_patch.PATCHED_FILE_LOADING


def test_sender_patch_migrates_intermediate_chunked_source():
    intermediate = sender_patch.PATCHED_SEND_FILE.replace(
        "        if (largeFilePath) {\n",
        "        if (base64.length > 8 * 1024 * 1024) {\n",
        1,
    )
    method = intermediate + "\n    }\n    /**"

    migrated = sender_patch.patch_sender_layer_source(method)

    assert "if (largeFilePath)" in migrated
    assert "if (base64.length >" not in migrated


def test_large_files_use_bounded_browser_transfers():
    patched = sender_patch.PATCHED_SEND_FILE

    assert "createReadStream(largeFilePath" in patched
    assert "highWaterMark: 3 * 1024 * 1024" in patched
    assert "new File(chunks" in patched
    assert "__winzappFileTransfers.delete(id)" in patched
    assert "if (largeFilePath)" in patched


def test_document_limits_match_whatsapp_ceiling():
    conversations = (ROOT / "client" / "ui" / "conversations.py").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "client" / "main.py").read_text(encoding="utf-8")

    assert "_MAX_DOC_BYTES      = 1 * 1024 * 1024 * 1024" in conversations
    assert "MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024" in main
