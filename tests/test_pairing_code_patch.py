"""Tests for the pairing-code-rotation patch (GitHub issue #8) and its
v1 -> v2 correction.

Timeline:

* v0 (upstream bug, wppconnect-team/wppconnect#2836): host.layer.js's
  checkQrCode() dedupes the QR-image branch against `this.urlCode` before
  re-emitting it, but the phoneNumber (pairing-code) branch returns
  straight into loginByCode() with no equivalent guard — so every
  ~20-60s WhatsApp-side QR rotation generates a BRAND NEW pairing code,
  faster than a screen-reader user can read an 8-character code.

* v1 (WinZapp's first fix, shipped, then found unsafe): a
  `linkCodeGenerated` latch set to True BEFORE loginByCode() actually
  produced a code, cleared only on a successful login. Reported live: the
  fast rotation stopped, but the code then never updated again even after
  10 minutes — because the latch never gets reset if a refresh is ever
  legitimately needed (or if the very first loginByCode() call failed).

* v2 (current): a 60-second reuse cooldown instead of a permanent latch,
  with the "issued" timestamp only recorded AFTER a code is actually
  produced, so a failed attempt self-recovers on the next tick instead of
  freezing forever.

Both setup_api.py and ApiSetupDialog (client/ui/dialogs/api_setup.py) apply
the same patch (see the "why two places" comment in api_setup.py) by
importing the shared source-text constants from
client/core/wppconnect_host_layer_patch.py, so this file exercises that
shared module plus the idempotency/upgrade logic in each of the two
patch-applying entry points.
"""

import importlib.util
import os

import pytest

from core.wppconnect_host_layer_patch import (
    ORIGINAL_CHECK_QR_CODE, V1_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE,
)

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


@pytest.fixture
def fake_wppconnect_dist(tmp_path):
    """.../node_modules/@wppconnect-team/wppconnect/dist/api/layers/host.layer.js"""
    layers_dir = tmp_path / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
    layers_dir.mkdir(parents=True)
    host_layer = layers_dir / "host.layer.js"
    return tmp_path, host_layer


def _write(host_layer, checkqrcode_text):
    """Wrap the (v0/v1/v2) checkQrCode() body in enough surrounding class
    boilerplate to look like the real compiled file, without needing the
    other unrelated methods."""
    host_layer.write_text(
        "class HostLayer {\n"
        "    urlCode = '';\n"
        "    attempt = 0;\n"
        + checkqrcode_text +
        "    async loginByCode(phone) {\n"
        "        const code = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {\n"
        "            return JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone)));\n"
        "        }, { phone });\n"
        "        this.catchLinkCode?.(code);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )


class TestSharedPatchTextsAreDistinct:
    """Guards against a future accidental edit collapsing two of the three
    variants back to identical text, which would silently break the
    idempotency/upgrade detection all the tests below rely on."""

    def test_all_three_variants_are_different(self):
        assert ORIGINAL_CHECK_QR_CODE != V1_CHECK_QR_CODE
        assert V1_CHECK_QR_CODE != PATCHED_CHECK_QR_CODE
        assert ORIGINAL_CHECK_QR_CODE != PATCHED_CHECK_QR_CODE

    def test_v2_never_permanently_latches(self):
        """The core correctness property distinguishing v2 from the unsafe
        v1: the "issued" flag must only be set AFTER loginByCode() returns,
        never before it — so a rejected call can't freeze the code forever."""
        issued_at_assignment = PATCHED_CHECK_QR_CODE.index("this.linkCodeIssuedAt = Date.now();")
        login_by_code_call = PATCHED_CHECK_QR_CODE.index("await this.loginByCode(this.options.phoneNumber);")
        assert login_by_code_call < issued_at_assignment

    def test_v2_uses_a_bounded_cooldown_not_an_unconditional_return(self):
        assert "linkCodeIssuedAt" in PATCHED_CHECK_QR_CODE
        assert "60000" in PATCHED_CHECK_QR_CODE

    def test_v1_is_the_unsafe_pre_set_latch_reported_live(self):
        """Documents exactly what made v1 unsafe: the latch write happens
        BEFORE the loginByCode() call, so a rejected/failed call still
        leaves the latch set — this is what froze the pairing code."""
        latch_set = V1_CHECK_QR_CODE.index("this.linkCodeGenerated = true;")
        login_by_code_call = V1_CHECK_QR_CODE.index("return this.loginByCode(this.options.phoneNumber);")
        assert latch_set < login_by_code_call


class TestSetupApiPatch:
    """setup_api.py's _patch_wppconnect_host_layer(client_api_dir)."""

    def test_patches_a_pristine_file_to_v2(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is True
        assert PATCHED_CHECK_QR_CODE in host_layer.read_text(encoding="utf-8")

    def test_upgrades_an_existing_v1_installation_to_v2(self, fake_wppconnect_dist):
        """The exact scenario from the live report: a machine that already
        got the unsafe v1 patch must be automatically upgraded to v2 on
        its next npm install / setup_api.py run, not left stuck."""
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V1_CHECK_QR_CODE)

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert "linkCodeGenerated" not in content

    def test_is_idempotent_once_v2_is_applied(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        setup_api._patch_wppconnect_host_layer(str(api_dir))
        first_pass = host_layer.read_text(encoding="utf-8")
        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))
        second_pass = host_layer.read_text(encoding="utf-8")

        assert ok is True
        assert first_pass == second_pass

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
        content = host_layer.read_text(encoding="utf-8")
        assert "linkCodeIssuedAt" not in content
        assert "linkCodeGenerated" not in content


class TestApiSetupDialogPatch:
    """ApiSetupDialog's copy — a wx.Dialog subclass, but the patch method
    is a @staticmethod that touches no wx widgets, so it's callable
    directly without a running wx.App."""

    def _wppconnect_api_dir(self, api_dir):
        return str(api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api")

    def test_patches_a_pristine_file_to_v2(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        ok = ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))

        assert ok is True
        assert PATCHED_CHECK_QR_CODE in host_layer.read_text(encoding="utf-8")

    def test_upgrades_an_existing_v1_installation_to_v2(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V1_CHECK_QR_CODE)

        ok = ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert "linkCodeGenerated" not in content

    def test_is_idempotent_once_v2_is_applied(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))
        first_pass = host_layer.read_text(encoding="utf-8")
        ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))
        assert host_layer.read_text(encoding="utf-8") == first_pass

    def test_apply_node_modules_patches_also_copies_decrypt_js(self, fake_wppconnect_dist):
        """_apply_node_modules_patches() is the entry point actually wired
        into the end-user install flow — it must copy decrypt.js into
        node_modules AND apply the host.layer.js patch, since previously
        neither ever reached node_modules for a real end-user install."""
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)
        (api_dir / "decrypt.js").write_text("// patched decrypt.js\n", encoding="utf-8")

        ApiSetupDialog._apply_node_modules_patches(str(api_dir))

        decrypt_dest = (
            api_dir / "node_modules" / "@wppconnect-team" / "wppconnect"
            / "dist" / "api" / "helpers" / "decrypt.js"
        )
        assert decrypt_dest.is_file()
        assert decrypt_dest.read_text(encoding="utf-8") == "// patched decrypt.js\n"
        assert PATCHED_CHECK_QR_CODE in host_layer.read_text(encoding="utf-8")

    def test_apply_node_modules_patches_never_raises_when_nothing_is_there(self, tmp_path):
        from ui.dialogs.api_setup import ApiSetupDialog
        # No decrypt.js, no node_modules at all — must not raise.
        ApiSetupDialog._apply_node_modules_patches(str(tmp_path))


class TestBothEntryPointsAgree:
    """setup_api.py and ApiSetupDialog must patch to byte-identical text —
    the whole reason wppconnect_host_layer_patch.py exists as a shared
    module instead of two hand-duplicated copies (which is exactly how the
    v1 -> v2 correction risked applying to only one of the two paths)."""

    def test_both_produce_the_same_output_from_a_pristine_file(self, tmp_path):
        from ui.dialogs.api_setup import ApiSetupDialog
        setup_api = _load_setup_api()

        api_dir_a = tmp_path / "a"
        layers_a = api_dir_a / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
        layers_a.mkdir(parents=True)
        host_layer_a = layers_a / "host.layer.js"
        _write(host_layer_a, ORIGINAL_CHECK_QR_CODE)

        api_dir_b = tmp_path / "b"
        layers_b = api_dir_b / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
        layers_b.mkdir(parents=True)
        host_layer_b = layers_b / "host.layer.js"
        _write(host_layer_b, ORIGINAL_CHECK_QR_CODE)

        setup_api._patch_wppconnect_host_layer(str(api_dir_a))
        ApiSetupDialog._patch_wppconnect_host_layer(
            str(api_dir_b / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api")
        )

        assert host_layer_a.read_text(encoding="utf-8") == host_layer_b.read_text(encoding="utf-8")
