import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from patch_utils import (
    PatchDef,
    PatchManifest,
    ManifestEntry,
    apply_patches,
    revert_patches,
    check_patches,
    get_status,
    hash_bytes,
    MANIFEST_PATH,
)


class TestPatchManifest:
    def test_create_and_load(self, tmp_path):
        mf_path = tmp_path / ".patches.json"
        mf = PatchManifest(mf_path)
        assert not mf.all_applied()

        entry = ManifestEntry(
            manifest_key="test_patch",
            file_path="/fake/path.ts",
            original_hash="abc",
            patched_hash="def",
            timestamp=time.time(),
            patch_version="1.0.0",
            label="Test patch",
            status="applied",
        )
        mf.register(entry)
        assert mf.has("test_patch")
        assert mf.status("test_patch") == "applied"

        mf2 = PatchManifest(mf_path)
        assert mf2.has("test_patch")
        assert mf2.status("test_patch") == "applied"

    def test_status_tracking(self, tmp_path):
        mf_path = tmp_path / ".patches.json"
        mf = PatchManifest(mf_path)
        assert mf.status("nonexistent") == "missing"

        mf.register(ManifestEntry(
            manifest_key="fail1",
            file_path="/x",
            original_hash="a",
            patched_hash="b",
            timestamp=0,
            patch_version="1.0.0",
            label="Failed patch",
            status="failed",
        ))
        assert mf.status("fail1") == "failed"

    def test_all_applied(self, tmp_path):
        mf_path = tmp_path / ".patches.json"
        mf = PatchManifest(mf_path)
        assert not mf.all_applied()

        mf.register(ManifestEntry(
            manifest_key="p1", file_path="/a", original_hash="a",
            patched_hash="b", timestamp=0, patch_version="1.0.0",
            label="P1", status="applied",
        ))
        assert mf.all_applied()

        mf.register(ManifestEntry(
            manifest_key="p2", file_path="/b", original_hash="c",
            patched_hash="d", timestamp=0, patch_version="1.0.0",
            label="P2", status="failed",
        ))
        assert not mf.all_applied()

    def test_remove_and_clear(self, tmp_path):
        mf_path = tmp_path / ".patches.json"
        mf = PatchManifest(mf_path)
        mf.register(ManifestEntry(
            manifest_key="p1", file_path="/a", original_hash="a",
            patched_hash="b", timestamp=0, patch_version="1.0.0",
            label="P1", status="applied",
        ))
        assert mf.has("p1")
        mf.remove("p1")
        assert not mf.has("p1")

        mf.register(ManifestEntry(
            manifest_key="p2", file_path="/b", original_hash="c",
            patched_hash="d", timestamp=0, patch_version="1.0.0",
            label="P2", status="applied",
        ))
        mf.clear()
        assert not mf.has("p2")
        assert not mf.all_applied()

    def test_corrupted_manifest(self, tmp_path):
        mf_path = tmp_path / ".patches.json"
        mf_path.write_text("{corrupted", encoding="utf-8")
        mf = PatchManifest(mf_path)
        assert not mf.all_applied()
        assert not mf.has("anything")


class TestApplyPatches:
    def test_apply_single_patch(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'const x = "hello";'
        patched = b'const x = "hello patched";'
        target.write_bytes(original)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[original],
                new_bytes=patched,
                label="Test patch",
                manifest_key="test",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert apply_patches(defs, mf_path)
        assert target.read_bytes() == patched

        mf = PatchManifest(mf_path)
        assert mf.status("test") == "applied"

    def test_apply_fallback_candidates(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'old_version_2'
        target.write_bytes(original)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[b'old_version_1', b'old_version_2'],
                new_bytes=b'new_version',
                label="Test fallback",
                manifest_key="test_fallback",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert apply_patches(defs, mf_path)
        assert target.read_bytes() == b'new_version'

    def test_already_patched_is_idempotent(self, tmp_path):
        target = tmp_path / "test.js"
        patched = b'const x = "patched";'
        target.write_bytes(patched)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[b'const x = "hello";'],
                new_bytes=patched,
                label="Test idempotent",
                manifest_key="test_idem",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert apply_patches(defs, mf_path)
        assert target.read_bytes() == patched

    def test_nonexistent_file_skipped(self, tmp_path):
        target = tmp_path / "nonexistent.js"
        defs = [
            PatchDef(
                target=target,
                old_candidates=[b"old"],
                new_bytes=b"new",
                label="Skip test",
                manifest_key="skip",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert apply_patches(defs, mf_path)

    def test_pattern_not_found_reports_failure(self, tmp_path):
        target = tmp_path / "test.js"
        target.write_bytes(b'completely different content')

        defs = [
            PatchDef(
                target=target,
                old_candidates=[b'expected pattern'],
                new_bytes=b'new content',
                label="Fail test",
                manifest_key="fail",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert not apply_patches(defs, mf_path)

        mf = PatchManifest(mf_path)
        assert mf.status("fail") == "failed"

    def test_backup_created(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'original content'
        target.write_bytes(original)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[original],
                new_bytes=b'patched content',
                label="Backup test",
                manifest_key="backup",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        apply_patches(defs, mf_path)

        backup = target.with_suffix(target.suffix + ".bak")
        assert backup.exists()
        assert backup.read_bytes() == original


class TestRevertPatches:
    def test_revert_restores_original(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'original content'
        target.write_bytes(original)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[original],
                new_bytes=b'patched content',
                label="Revert test",
                manifest_key="revert",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        apply_patches(defs, mf_path)
        assert target.read_bytes() == b'patched content'

        revert_patches(defs, mf_path)
        assert target.read_bytes() == original
        backup = target.with_suffix(target.suffix + ".bak")
        assert not backup.exists()

    def test_revert_without_backup_skipped(self, tmp_path):
        target = tmp_path / "test.js"
        target.write_bytes(b'content')

        defs = [
            PatchDef(
                target=target,
                old_candidates=[b'old'],
                new_bytes=b'new',
                label="No backup",
                manifest_key="nobackup",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        assert revert_patches(defs, mf_path)


class TestCheckPatches:
    def test_check_applied(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'old content'
        patched = b'new content'
        target.write_bytes(patched)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[original],
                new_bytes=patched,
                label="Check test",
                manifest_key="check",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        apply_patches(defs, mf_path)

        assert check_patches(defs, mf_path)

    def test_check_fails_if_file_changed_after_patch(self, tmp_path):
        target = tmp_path / "test.js"
        original = b'old content'
        patched = b'new content'
        target.write_bytes(patched)

        defs = [
            PatchDef(
                target=target,
                old_candidates=[original],
                new_bytes=patched,
                label="Check fail",
                manifest_key="checkfail",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        apply_patches(defs, mf_path)

        target.write_bytes(b'something else entirely')
        assert not check_patches(defs, mf_path)


class TestGetStatus:
    def test_status_empty(self, tmp_path):
        target = tmp_path / "test.js"

        defs = [
            PatchDef(
                target=target,
                old_candidates=[b'old'],
                new_bytes=b'new',
                label="Status test",
                manifest_key="status",
            ),
        ]
        mf_path = tmp_path / "manifest.json"
        statuses = get_status(defs, mf_path)
        assert "status" in statuses
        assert not statuses["status"]["file_exists"]
        assert not statuses["status"]["is_patched"]


class TestPairingTimePatch:
    def test_ts_patch(self, tmp_path):
        target = tmp_path / "test.ts"
        original = b'qrTimeout: 45_000,'
        target.write_bytes(original)

        from baileys_apply_patch_pairing_time import PATCHES
        ts_def = [p for p in PATCHES if p.manifest_key == "pairing_time_ts"][0]
        ts_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([ts_def], mf_path)
        assert b"qrTimeout: 120_000," in target.read_bytes()

    def test_compiled_js_patch(self, tmp_path):
        target = tmp_path / "main.js"
        original = b'qrTimeout:45e3,'
        target.write_bytes(original)

        from baileys_apply_patch_pairing_time import PATCHES
        js_def = [p for p in PATCHES if p.manifest_key == "pairing_time_js"][0]
        js_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([js_def], mf_path)
        assert b"qrTimeout:12e4," in target.read_bytes()


class TestMarkReadPatch:
    def test_js_original_matches(self):
        from baileys_apply_patch_mark_read import JS_ORIGINAL, JS_PATCHED
        assert b"readMessages" in JS_ORIGINAL
        assert b"chatModify" in JS_PATCHED
        assert b"markRead" in JS_PATCHED

    def test_js_apply(self, tmp_path):
        from baileys_apply_patch_mark_read import JS_ORIGINAL, JS_PATCHED, PATCHES

        target = tmp_path / "main.js"
        target.write_bytes(b"prefix " + JS_ORIGINAL + b" suffix")

        js_def = [p for p in PATCHES if p.manifest_key == "mark_read_js"][0]
        js_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([js_def], mf_path)
        result = target.read_bytes()
        assert JS_PATCHED in result
        assert b"chatModify" in result
        assert b"markRead" in result

    def test_mjs_original_matches(self):
        from baileys_apply_patch_mark_read import MJS_ORIGINAL, MJS_PATCHED
        assert b"readMessages" in MJS_ORIGINAL
        assert b"chatModify" in MJS_PATCHED

    def test_mjs_apply(self, tmp_path):
        from baileys_apply_patch_mark_read import MJS_ORIGINAL, MJS_PATCHED, PATCHES

        target = tmp_path / "main.mjs"
        target.write_bytes(MJS_ORIGINAL)

        mjs_def = [p for p in PATCHES if p.manifest_key == "mark_read_mjs"][0]
        mjs_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([mjs_def], mf_path)
        result = target.read_bytes()
        assert MJS_PATCHED in result


class TestQuotedContextPatch:
    def test_old_pattern_matches(self):
        from baileys_apply_patch_quoted_context import OLD, NEW
        assert "delete o.message.extendedTextMessage" in OLD
        assert "Object.assign" in NEW
        assert "contextInfo" in NEW

    def test_apply_js(self, tmp_path):
        from baileys_apply_patch_quoted_context import OLD, NEW, PATCHES

        content = (
            b'function prepareMessage(o){'
            + OLD.encode("utf-8")
            + b'}'
        )
        target = tmp_path / "main.js"
        target.write_bytes(content)

        js_def = [p for p in PATCHES if p.manifest_key == "quoted_context_js"][0]
        js_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([js_def], mf_path)
        result = target.read_bytes()
        assert NEW.encode("utf-8") in result

    def test_apply_mjs(self, tmp_path):
        from baileys_apply_patch_quoted_context import OLD, NEW, PATCHES

        content = (
            b'function prepareMessage(o){'
            + OLD.encode("utf-8")
            + b'}'
        )
        target = tmp_path / "main.mjs"
        target.write_bytes(content)

        mjs_def = [p for p in PATCHES if p.manifest_key == "quoted_context_mjs"][0]
        mjs_def.target = target

        mf_path = tmp_path / "manifest.json"
        assert apply_patches([mjs_def], mf_path)
        result = target.read_bytes()
        assert NEW.encode("utf-8") in result


class TestBaileysApplyAll:
    def test_all_patches_load(self):
        from baileys_apply_all import ALL_PATCHES
        assert len(ALL_PATCHES) == 8  # 3 pairing + 3 mark-read + 2 quoted-context

    def test_apply_and_revert_all(self, tmp_path):
        from baileys_apply_patch_pairing_time import PATCHES as PAIRING
        from baileys_apply_patch_mark_read import PATCHES as MARK_READ
        from baileys_apply_patch_quoted_context import PATCHES as QUOTED

        mf_path = tmp_path / "manifest.json"

        from baileys_apply_patch_mark_read import JS_ORIGINAL, MJS_ORIGINAL, TS_ORIGINAL
        from baileys_apply_patch_quoted_context import OLD

        for pdef in PAIRING + MARK_READ + QUOTED:
            fake = tmp_path / pdef.target.name
            pdef.target = fake

        pair_ts = tmp_path / "test.ts"
        pair_ts.write_text("qrTimeout: 45_000,")
        pair_js = tmp_path / "main.js"
        pair_js.write_bytes(b"qrTimeout:45e3,\n" + b"prefix " + JS_ORIGINAL + b"\nfunction prepareMessage(o){" + OLD.encode("utf-8") + b"}")
        pair_mjs = tmp_path / "main.mjs"
        pair_mjs.write_bytes(b"qrTimeout:45e3,\n" + MJS_ORIGINAL + b"\nfunction prepareMessage(o){" + OLD.encode("utf-8") + b"}")
        mark_ts = tmp_path / "whatsapp.baileys.service.ts"
        mark_ts.write_bytes(TS_ORIGINAL)

        from patch_utils import apply_patches, revert_patches
        assert apply_patches(PAIRING + MARK_READ + QUOTED, mf_path)

        mf = PatchManifest(mf_path)
        assert mf.all_applied()

        assert revert_patches(PAIRING + MARK_READ + QUOTED, mf_path)
