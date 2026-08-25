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


def test_sender_patch_migrates_the_previous_chunked_patch_to_1gb():
    previous = sender_patch.PATCHED_SEND_FILE.replace(
        "                        const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
        "                        if (options.type === 'document' && mediaGating?.getUploadLimit && !mediaGating.__winzappUploadLimitPatched) {\n"
        "                            const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
        "                            mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
        "                                ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
        "                                : getUploadLimit(type, origin, isVcard);\n"
        "                            mediaGating.__winzappUploadLimitPatched = true;\n"
        "                        }\n",
        "",
    ).replace(
        "                    const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
        "                    if (options.type === 'document' && mediaGating?.getUploadLimit && !mediaGating.__winzappUploadLimitPatched) {\n"
        "                        const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
        "                        mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
        "                            ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
        "                            : getUploadLimit(type, origin, isVcard);\n"
        "                        mediaGating.__winzappUploadLimitPatched = true;\n"
        "                    }\n",
        "",
    )

    migrated = sender_patch.patch_sender_layer_source(previous)

    assert "WPP.whatsapp?.MediaGatingUtils" in migrated
    assert "1 * 1024 * 1024 * 1024" in migrated
    assert "__winzappUploadLimitPatched" in migrated


def test_sender_patch_migrates_the_leaking_unguarded_upload_limit_wrap():
    """LEGACY_PATCHED_SEND_FILE_V2 is the exact text every existing install
    already has on disk from before the __winzappUploadLimitPatched guard
    existed. Without this migration, re-running setup_api.py on an
    already-patched machine would leave the leak in place forever, since
    none of the other ALL_PATCHES pairs match already-patched text."""
    assert (
        sender_patch.LEGACY_PATCHED_SEND_FILE_V2,
        sender_patch.PATCHED_SEND_FILE,
    ) in sender_patch.ALL_PATCHES
    assert "__winzappUploadLimitPatched" not in sender_patch.LEGACY_PATCHED_SEND_FILE_V2

    migrated = sender_patch.LEGACY_PATCHED_SEND_FILE_V2
    for original, replacement in sender_patch.ALL_PATCHES:
        migrated = migrated.replace(original, replacement)

    assert migrated == sender_patch.PATCHED_SEND_FILE


def test_sender_patch_guards_upload_limit_wrap_against_repeated_wrapping():
    """The getUploadLimit() override must install at most once per page
    load — re-wrapping it on every document send chains one more closure
    onto a singleton (WPP.whatsapp.MediaGatingUtils) that lives for the
    whole session, leaking memory in the browser process forever."""
    patched = sender_patch.PATCHED_SEND_FILE

    assert patched.count("__winzappUploadLimitPatched = true") == 2
    assert patched.count("&& !mediaGating.__winzappUploadLimitPatched") == 2
    assert "&& !mediaGating.__winzappUploadLimitPatched" in sender_patch._BROWSER_DOCUMENT_LIMIT_PATCH


def test_large_documents_use_bounded_browser_transfers_and_a_1gb_browser_limit():
    patched = sender_patch.PATCHED_SEND_FILE

    assert "createReadStream(largeFilePath" in patched
    assert "highWaterMark: 3 * 1024 * 1024" in patched
    assert "new File(chunks" in patched
    assert "__winzappFileTransfers.delete(id)" in patched
    assert "if (largeFilePath)" in patched
    assert "WPP.whatsapp?.MediaGatingUtils" in patched
    assert "1 * 1024 * 1024 * 1024" in patched


def test_document_limits_match_the_1gb_whatsapp_ceiling():
    conversations = (ROOT / "client" / "ui" / "conversations.py").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "client" / "main.py").read_text(encoding="utf-8")

    assert "_MAX_ATTACHMENT_BYTES = 1 * 1024 * 1024 * 1024" in conversations
    assert "MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024" in main


def test_media_and_document_ceilings_match():
    """Image/video/audio used to be capped at 70MB in the UI's own
    pre-check, well under what sender.layer.js's bounded transfer can now
    actually move (see wppconnect_sender_layer_patch.py) — that gap is what
    used to force a 500 for any media send past 70MB."""
    conversations = (ROOT / "client" / "ui" / "conversations.py").read_text(
        encoding="utf-8"
    )

    assert "_MAX_ATTACHMENT_MB    = 1024" in conversations
    assert "70  * 1024 * 1024" not in conversations


def test_wpp_only_sets_the_effective_file_size_limit():
    websocket_client = (ROOT / "client" / "core" / "websocket_client.py").read_text(
        encoding="utf-8"
    )
    method = websocket_client.split("    def _set_wpp_limits(self):", 1)[1].split(
        "    def ", 1
    )[0]

    assert '"type": "maxFileSize"' in method
    assert '"type": "maxMediaSize"' not in method


def test_sender_patch_widens_bounded_transfer_to_every_attachment_type():
    """PATCHED_FILE_LOADING_V1 (document-only) must still migrate an
    already-patched sender.layer.js to the widened PATCHED_FILE_LOADING —
    otherwise a machine that already has the old patch applied never picks
    up the fix on an ordinary restart (see
    tests/test_reapply_node_modules_patches.py for why that reapply path
    matters)."""
    assert (sender_patch.PATCHED_FILE_LOADING_V1, sender_patch.PATCHED_FILE_LOADING) in sender_patch.ALL_PATCHES
    for kind in ("document", "image", "video", "audio"):
        assert f"'{kind}'" in sender_patch.PATCHED_FILE_LOADING
    assert "options.type === 'document'" not in sender_patch.PATCHED_FILE_LOADING
