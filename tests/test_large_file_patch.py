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
        "                        if (options.type === 'document' && mediaGating?.getUploadLimit) {\n"
        "                            const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
        "                            mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
        "                                ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
        "                                : getUploadLimit(type, origin, isVcard);\n"
        "                        }\n",
        "",
    ).replace(
        "                    const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
        "                    if (options.type === 'document' && mediaGating?.getUploadLimit) {\n"
        "                        const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
        "                        mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
        "                            ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
        "                            : getUploadLimit(type, origin, isVcard);\n"
        "                    }\n",
        "",
    )

    migrated = sender_patch.patch_sender_layer_source(previous)

    assert "WPP.whatsapp?.MediaGatingUtils" in migrated
    assert "1 * 1024 * 1024 * 1024" in migrated


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


class TestTheUploadLimitOverrideInstallsItselfOnlyOnce:
    """The getUploadLimit override lives inside the per-send page callback, so
    it runs again on every document sent. Its first version guarded on
    `mediaGating?.getUploadLimit` — but a wrapper IS a getUploadLimit, so that
    guard is true forever after the first wrap. Each send then captured the
    previous wrapper and layered another one on top, with nothing ever
    resetting it: an unbounded closure chain for as long as the WhatsApp Web
    page lived, walked in full on every call.

    `__winzappUploadLimitPatched` on the object is what makes it once-per-page.
    Being source-text assertions, these can't run the JS — what they pin down
    is that the marker is both TESTED before wrapping and SET after, in every
    copy of the block. A version that only sets it, or only tests it, would
    read as fixed and behave exactly like the leak."""

    def _blocks(self, text):
        """Each copy of the override block, split off at its opening line."""
        parts = text.split("const mediaGating = WPP.whatsapp?.MediaGatingUtils;")
        return parts[1:]

    def test_every_copy_of_the_block_tests_and_sets_the_marker(self):
        blocks = self._blocks(sender_patch.PATCHED_SEND_FILE)
        assert len(blocks) == 2, (
            "expected the override in both the chunked and the base64 branch; "
            f"found {len(blocks)}"
        )
        for block in blocks:
            head = block.split("const result")[0]
            assert "!mediaGating.__winzappUploadLimitPatched" in head, (
                "the guard must consult the marker, not just getUploadLimit's "
                "existence — a wrapper satisfies that check forever"
            )
            assert "mediaGating.__winzappUploadLimitPatched = true;" in head, (
                "the marker must be set, or the guard can never become false"
            )

    def test_the_injected_block_carries_the_marker_too(self):
        """The block injected into a node_modules that predates the override
        entirely is a separate constant from the two inline copies."""
        head = sender_patch._BROWSER_DOCUMENT_LIMIT_PATCH
        assert "!mediaGating.__winzappUploadLimitPatched" in head
        assert "mediaGating.__winzappUploadLimitPatched = true;" in head

    def test_the_unmarked_variant_is_migrated_not_left_alone(self):
        """A machine patched by the build that shipped the leaking version has
        the unmarked block in node_modules. It matches no ALL_PATCHES pair, so
        without an explicit migration every later setup run would leave it
        exactly as it is — the same trap the intermediate chunked variant fell
        into."""
        legacy = sender_patch._LEGACY_DOCUMENT_LIMIT_PATCH
        stale = (
            "        let sendResult;\n"
            + legacy
            + "                    const result = await WPP.chat.sendFileMessage(to, base64, {\n"
        )

        migrated = sender_patch.patch_sender_layer_source(stale)

        assert "__winzappUploadLimitPatched" in migrated
        assert legacy not in migrated

    def test_the_unmarked_variant_is_migrated_at_the_deeper_indentation_too(self):
        """The chunked branch carries the same block one nesting level in."""
        legacy_deep = sender_patch._deepen(sender_patch._LEGACY_DOCUMENT_LIMIT_PATCH)
        stale = (
            "        let sendResult;\n"
            + legacy_deep
            + "                        const result = await WPP.chat.sendFileMessage(to, file, {\n"
        )

        migrated = sender_patch.patch_sender_layer_source(stale)

        assert "__winzappUploadLimitPatched" in migrated
        assert legacy_deep not in migrated

    def test_migrating_an_already_marked_source_changes_nothing(self):
        current = sender_patch.PATCHED_SEND_FILE + "\n    }\n    /**"

        once = sender_patch.patch_sender_layer_source(current)
        twice = sender_patch.patch_sender_layer_source(once)

        assert once == twice
        assert once.count("__winzappUploadLimitPatched = true;") == 2, (
            "re-running the migration must not duplicate the marker assignment"
        )
