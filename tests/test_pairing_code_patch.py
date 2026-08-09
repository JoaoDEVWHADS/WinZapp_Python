"""Tests for the pairing-code-rotation patch (GitHub issue #8).

Root cause (upstream, wppconnect-team/wppconnect#2836): host.layer.js's
checkQrCode() dedupes the QR-image branch against `this.urlCode` before
re-emitting it, but the phoneNumber (pairing-code) branch returns straight
into loginByCode() with no equivalent guard — so every ~20-60s WhatsApp-side
QR rotation generates a BRAND NEW pairing code, faster than a screen-reader
user can read an 8-character code.

Two copies of the same patch function exist by design (mirroring how this
codebase already duplicates setup_api.py's package.json-merge logic into
ApiSetupDialog — see that class's own docstring): one in setup_api.py (the
developer/CI path, patches client/api/node_modules/...), one in
ApiSetupDialog (client/ui/dialogs/api_setup.py — the real end-user path,
since node_modules isn't shipped in the release ZIP and gets rebuilt by
`npm install` at first launch instead). Both are tested here against a
synthetic host.layer.js so neither test depends on this machine's actual
node_modules being present.
"""

import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_setup_api():
    """setup_api.py lives at the repo root, outside pytest's `client`
    pythonpath — load it directly by file path."""
    spec = importlib.util.spec_from_file_location(
        "setup_api", os.path.join(REPO_ROOT, "setup_api.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORIGINAL_HOST_LAYER_SNIPPET = """    async checkQrCode() {
        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);
        this.isLogged = !needScan;
        if (!needScan) {
            this.attempt = 0;
            return;
        }
        const result = await this.getQrCode();
        if (!result?.urlCode || this.urlCode === result.urlCode) {
            return;
        }
        if (typeof this.options.phoneNumber === 'string') {
            return this.loginByCode(this.options.phoneNumber);
        }
        this.urlCode = result.urlCode;
        this.attempt++;
    }
    async loginByCode(phone) {
        const code = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {
            return JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone)));
        }, { phone });
        this.catchLinkCode?.(code);
    }
"""


@pytest.fixture
def fake_wppconnect_dist(tmp_path):
    """.../node_modules/@wppconnect-team/wppconnect/dist/api/layers/host.layer.js"""
    layers_dir = tmp_path / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
    layers_dir.mkdir(parents=True)
    host_layer = layers_dir / "host.layer.js"
    host_layer.write_text(ORIGINAL_HOST_LAYER_SNIPPET, encoding="utf-8")
    return tmp_path, host_layer


class TestSetupApiPatch:
    """setup_api.py's _patch_wppconnect_host_layer(client_api_dir)."""

    def test_patches_the_reset_and_phone_branch(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert "this.linkCodeGenerated = false;" in content
        assert "this.linkCodeGenerated = true;" in content
        assert "if (this.linkCodeGenerated) {" in content
        # The dedupe guard must sit BEFORE the loginByCode() call it protects.
        guard_pos = content.index("if (this.linkCodeGenerated) {")
        call_pos  = content.index("return this.loginByCode(this.options.phoneNumber);")
        assert guard_pos < call_pos

    def test_is_idempotent(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist

        setup_api._patch_wppconnect_host_layer(str(api_dir))
        first_pass = host_layer.read_text(encoding="utf-8")
        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))
        second_pass = host_layer.read_text(encoding="utf-8")

        assert ok is True
        assert first_pass == second_pass
        assert second_pass.count("linkCodeGenerated") == first_pass.count("linkCodeGenerated")

    def test_missing_file_is_a_safe_no_op(self, tmp_path):
        setup_api = _load_setup_api()
        ok = setup_api._patch_wppconnect_host_layer(str(tmp_path))
        assert ok is False

    def test_unrecognized_source_is_left_untouched(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        host_layer.write_text("// a future wppconnect rewrote this file entirely\n", encoding="utf-8")

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is False
        assert "linkCodeGenerated" not in host_layer.read_text(encoding="utf-8")


class TestApiSetupDialogPatch:
    """ApiSetupDialog's ported copy — a wx.Dialog subclass, but the patch
    method is a @staticmethod that touches no wx widgets, so it's callable
    directly without a running wx.App."""

    def test_patches_the_same_way(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        wppconnect_api_dir = str(api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api")

        ok = ApiSetupDialog._patch_wppconnect_host_layer(wppconnect_api_dir)

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert "this.linkCodeGenerated = true;" in content

    def test_is_idempotent(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        wppconnect_api_dir = str(api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api")

        ApiSetupDialog._patch_wppconnect_host_layer(wppconnect_api_dir)
        first_pass = host_layer.read_text(encoding="utf-8")
        ApiSetupDialog._patch_wppconnect_host_layer(wppconnect_api_dir)
        assert host_layer.read_text(encoding="utf-8") == first_pass

    def test_apply_node_modules_patches_also_copies_decrypt_js(self, fake_wppconnect_dist):
        """_apply_node_modules_patches() is the entry point actually wired
        into the end-user install flow — it must copy decrypt.js into
        node_modules AND apply the host.layer.js patch, since previously
        neither ever reached node_modules for a real end-user install."""
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        (api_dir / "decrypt.js").write_text("// patched decrypt.js\n", encoding="utf-8")

        ApiSetupDialog._apply_node_modules_patches(str(api_dir))

        decrypt_dest = (
            api_dir / "node_modules" / "@wppconnect-team" / "wppconnect"
            / "dist" / "api" / "helpers" / "decrypt.js"
        )
        assert decrypt_dest.is_file()
        assert decrypt_dest.read_text(encoding="utf-8") == "// patched decrypt.js\n"
        assert "linkCodeGenerated" in host_layer.read_text(encoding="utf-8")

    def test_apply_node_modules_patches_never_raises_when_nothing_is_there(self, tmp_path):
        from ui.dialogs.api_setup import ApiSetupDialog
        # No decrypt.js, no node_modules at all — must not raise.
        ApiSetupDialog._apply_node_modules_patches(str(tmp_path))
