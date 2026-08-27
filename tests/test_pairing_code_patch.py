"""Tests for the pairing-code-rotation patch (GitHub issue #8) and its
later corrections.

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

* v2: a 60-second reuse cooldown instead of a permanent latch, with the
  "issued" timestamp only recorded AFTER a code is actually produced, so a
  failed attempt self-recovers on the next tick instead of freezing forever.

* v3: v2 plus a catch around the loginByCode() call, and a companion patch to
  loginByCode() itself. v2's try/finally had no catch, so a rejected
  loginByCode() escaped checkQrCode() — which is called fire-and-forget — as
  an unhandled rejection, and the underlying browser error had already been
  flattened to the minified "t: t" by crossing the CDP exception boundary.
  Observed live: pairing simply never produced a code, the Python side sat
  out its full 90-second wait, and the only trace anywhere was "Unhandled
  Rejection: t: t" in wppconnect.log.

* v4 (current): v3 plus a `catchLinkCodeError` hook, so the caught error
  actually reaches the person trying to pair. v3 made the failure real and
  non-fatal, but it still only ever landed in wppconnect.log — the user was
  left with the same generic "no pairing code received" after 90 seconds.
  The end-to-end path is covered by tests/test_pairing_code_error_reporting.py.

Both setup_api.py and ApiSetupDialog (client/ui/dialogs/api_setup.py) apply
the same patch (see the "why two places" comment in api_setup.py). Since v3
both delegate the actual search-and-replace to patch_host_layer_source() in
client/core/wppconnect_host_layer_patch.py, so this file exercises that
shared module plus each of the two patch-applying entry points.
"""

import importlib.util
import os

import pytest

from core.wppconnect_host_layer_patch import (
    ORIGINAL_CHECK_QR_CODE, V1_CHECK_QR_CODE, V2_CHECK_QR_CODE,
    V3_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE,
    ORIGINAL_LOGIN_BY_CODE, PATCHED_LOGIN_BY_CODE,
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


def _write(host_layer, checkqrcode_text, loginbycode_text=ORIGINAL_LOGIN_BY_CODE):
    """Wrap the (v0/v1/v2/v3) checkQrCode() body in enough surrounding class
    boilerplate to look like the real compiled file, without needing the
    other unrelated methods.

    loginByCode() comes from the shared constants verbatim rather than being
    paraphrased here: the patcher rewrites that method too, so an
    approximate copy would make every test in this file see a spurious
    "DID NOT MATCH" for a file the real patcher handles fine."""
    host_layer.write_text(
        "class HostLayer {\n"
        "    urlCode = '';\n"
        "    attempt = 0;\n"
        + checkqrcode_text
        + loginbycode_text +
        "}\n",
        encoding="utf-8",
    )


class TestSharedPatchTextsAreDistinct:
    """Guards against a future accidental edit collapsing two of the known
    variants back to identical text, which would silently break the
    idempotency/upgrade detection all the tests below rely on."""

    def test_the_known_variants_are_all_different(self):
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

    def test_patches_a_pristine_file_to_the_current_version(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is True
        assert PATCHED_CHECK_QR_CODE in host_layer.read_text(encoding="utf-8")

    def test_upgrades_an_existing_v1_installation(self, fake_wppconnect_dist):
        """The exact scenario from the live report: a machine that already
        got the unsafe v1 patch must be automatically upgraded to the
        current version on its next npm install / setup_api.py run, not
        left stuck."""
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V1_CHECK_QR_CODE)

        ok = setup_api._patch_wppconnect_host_layer(str(api_dir))

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert "linkCodeGenerated" not in content

    def test_is_idempotent_once_applied(self, fake_wppconnect_dist):
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

    def test_patches_a_pristine_file_to_the_current_version(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        ok = ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))

        assert ok is True
        assert PATCHED_CHECK_QR_CODE in host_layer.read_text(encoding="utf-8")

    def test_upgrades_an_existing_v1_installation(self, fake_wppconnect_dist):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V1_CHECK_QR_CODE)

        ok = ApiSetupDialog._patch_wppconnect_host_layer(self._wppconnect_api_dir(api_dir))

        assert ok is True
        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert "linkCodeGenerated" not in content

    def test_is_idempotent_once_applied(self, fake_wppconnect_dist):
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


class TestV3CatchesPairingCodeFailures:
    """v3's addition to v2: the `await this.loginByCode(...)` inside
    checkQrCode() is wrapped in a catch.

    Without it a rejected loginByCode() propagated straight out of
    checkQrCode() — which host.layer.js calls fire-and-forget, both from its
    own initialize path and from the exposed `conn.auth_code_change`
    handler, with nobody awaiting or catching it. Observed live: a bare
    "Unhandled Rejection: t: t" in wppconnect.log, that checkQrCode() tick
    killed before it could do anything else, and the Python side left to sit
    out its full 90-second _phone_code_event wait before reporting the
    generic "no pairing code received" with nothing in log.log explaining
    why.
    """

    def test_v3_catches_a_failing_login_by_code(self):
        assert "catch (error) {" in PATCHED_CHECK_QR_CODE
        assert "Could not generate the pairing code" in PATCHED_CHECK_QR_CODE

    def test_v2_had_no_catch_at_all(self):
        """Documents precisely what v3 fixes — v2 has the try/finally but no
        catch, which is what let the rejection escape."""
        assert "try {" in V2_CHECK_QR_CODE
        assert "finally {" in V2_CHECK_QR_CODE
        # Not a bare "catch": v2 legitimately contains catchQR?.() and the
        # needsToScan(...).catch(() => null) chain — neither of which handles
        # a rejected loginByCode().
        assert "catch (" not in V2_CHECK_QR_CODE

    def test_v3_still_never_permanently_latches(self):
        """v3 must not regress v2's core self-recovery property: the
        "issued" timestamp is still only written AFTER loginByCode()
        succeeds, so a caught failure leaves it untouched and the next
        auth_code_change tick retries."""
        issued_at = PATCHED_CHECK_QR_CODE.index("this.linkCodeIssuedAt = Date.now();")
        login_call = PATCHED_CHECK_QR_CODE.index("await this.loginByCode(this.options.phoneNumber);")
        catch_block = PATCHED_CHECK_QR_CODE.index("catch (error) {")
        assert login_call < issued_at < catch_block

    def test_every_checkqrcode_generation_is_distinct(self):
        """Each generation is a rung on the migration ladder — two of them
        collapsing to identical text would silently break the upgrade
        detection every test here relies on."""
        variants = [
            ORIGINAL_CHECK_QR_CODE, V1_CHECK_QR_CODE,
            V2_CHECK_QR_CODE, V3_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE,
        ]
        assert len(set(variants)) == 5


class TestV4ReportsTheFailureToTheClient:
    """v4's addition to v3: the caught error is also handed to a
    `catchLinkCodeError` callback, so it can reach the person trying to pair
    instead of dying in wppconnect.log."""

    def test_v4_calls_the_hook_with_the_real_error(self):
        assert "this.options.catchLinkCodeError?.(" in PATCHED_CHECK_QR_CODE
        assert "name: String(error?.name || 'Error')," in PATCHED_CHECK_QR_CODE
        assert "message: String(error?.message || error)," in PATCHED_CHECK_QR_CODE

    def test_v3_had_no_hook(self):
        assert "catchLinkCodeError" not in V3_CHECK_QR_CODE

    def test_the_hook_is_optional(self):
        """Read through `?.` off this.options: WPPConnect knows nothing about
        this key, so anything not passing it (an older createSessionUtil, or a
        direct wppconnect user) must be an ordinary no-op, never a TypeError
        inside the catch block that is itself handling an error."""
        hook = PATCHED_CHECK_QR_CODE[
            PATCHED_CHECK_QR_CODE.index("catchLinkCodeError")
            - len("this.options.") :
        ]
        assert hook.startswith("this.options.catchLinkCodeError?.(")

    def test_v4_still_logs_as_well_as_reports(self):
        """The log line is the record that survives a closed dialog — the hook
        does not replace it."""
        assert "Could not generate the pairing code" in PATCHED_CHECK_QR_CODE

    def test_v4_still_never_permanently_latches(self):
        issued_at = PATCHED_CHECK_QR_CODE.index("this.linkCodeIssuedAt = Date.now();")
        login_call = PATCHED_CHECK_QR_CODE.index("await this.loginByCode(this.options.phoneNumber);")
        catch_block = PATCHED_CHECK_QR_CODE.index("catch (error) {")
        assert login_call < issued_at < catch_block


class TestUpgradeFromV3:
    """The realistic upgrade path for anyone who ran the build that shipped
    v3: checkQrCode must move v3 -> v4 while loginByCode, already patched, is
    left exactly as it is."""

    def test_v3_install_is_upgraded_to_v4(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V3_CHECK_QR_CODE, PATCHED_LOGIN_BY_CODE)

        assert setup_api._patch_wppconnect_host_layer(str(api_dir)) is True

        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert V3_CHECK_QR_CODE not in content
        assert PATCHED_LOGIN_BY_CODE in content

    def test_both_entry_points_agree_on_the_v3_upgrade(self, tmp_path):
        from ui.dialogs.api_setup import ApiSetupDialog
        setup_api = _load_setup_api()

        outputs = []
        for name in ("setup_api", "api_setup"):
            api_dir = tmp_path / name
            layers = api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
            layers.mkdir(parents=True)
            host_layer = layers / "host.layer.js"
            _write(host_layer, V3_CHECK_QR_CODE, PATCHED_LOGIN_BY_CODE)

            if name == "setup_api":
                setup_api._patch_wppconnect_host_layer(str(api_dir))
            else:
                ApiSetupDialog._patch_wppconnect_host_layer(
                    str(api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api")
                )
            outputs.append(host_layer.read_text(encoding="utf-8"))

        assert outputs[0] == outputs[1]


class TestLoginByCodeErrorDetail:
    """The pairing-code request itself must report the real browser-side
    error instead of the minified "t: t" that a page-context exception
    crossing the CDP boundary raw degrades into — same root cause and same
    fix as the sendFile() error-detail patch in
    wppconnect_sender_layer_patch.py."""

    def test_patched_catches_inside_the_page_and_returns_plain_data(self):
        """The fix only works if the error is caught INSIDE the page
        callback and RETURNED (structured cloning preserves plain string
        properties) rather than thrown across the CDP exception boundary."""
        assert "__winzappError" in PATCHED_LOGIN_BY_CODE
        page_callback_start = PATCHED_LOGIN_BY_CODE.index("async ({ phone }) => {")
        page_callback_end = PATCHED_LOGIN_BY_CODE.index("}, { phone });")
        page_body = PATCHED_LOGIN_BY_CODE[page_callback_start:page_callback_end]
        assert "catch (error) {" in page_body
        assert "return {" in page_body

    def test_patched_rethrows_a_real_error_on_the_node_side(self):
        assert "new Error(outcome.__winzappError.message)" in PATCHED_LOGIN_BY_CODE
        assert "throw failure;" in PATCHED_LOGIN_BY_CODE

    def test_original_had_no_error_handling_at_all(self):
        # "catch (" rather than "catch": the unpatched method already ends in
        # this.catchLinkCode?.(code), which is not error handling.
        assert "catch (" not in ORIGINAL_LOGIN_BY_CODE
        assert "__winzappError" not in ORIGINAL_LOGIN_BY_CODE

    def test_patched_still_delivers_the_code_on_success(self):
        """The happy path must be unchanged: catchLinkCode still receives
        the generated code."""
        assert "this.catchLinkCode?.(code);" in PATCHED_LOGIN_BY_CODE
        assert "const code = outcome?.code;" in PATCHED_LOGIN_BY_CODE

    def test_login_by_code_is_actually_patched_by_both_entry_points(self, tmp_path):
        from ui.dialogs.api_setup import ApiSetupDialog
        setup_api = _load_setup_api()

        results = {}
        for name, apply in (
            ("setup_api", lambda d: setup_api._patch_wppconnect_host_layer(str(d))),
            ("api_setup", lambda d: ApiSetupDialog._patch_wppconnect_host_layer(
                str(d / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api"))),
        ):
            api_dir = tmp_path / name
            layers = api_dir / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist" / "api" / "layers"
            layers.mkdir(parents=True)
            host_layer = layers / "host.layer.js"
            _write(host_layer, ORIGINAL_CHECK_QR_CODE)

            assert apply(api_dir) is True
            content = host_layer.read_text(encoding="utf-8")
            assert PATCHED_LOGIN_BY_CODE in content
            assert ORIGINAL_LOGIN_BY_CODE not in content
            results[name] = content

        assert results["setup_api"] == results["api_setup"]


class TestUpgradeFromAnAlreadyPatchedInstall:
    """The realistic upgrade path: an existing user's machine already
    carries v2 + an unpatched loginByCode (exactly what shipped before this
    change), and the next setup run must migrate both halves."""

    def test_v2_install_is_upgraded_to_v3_with_login_by_code_patched(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, V2_CHECK_QR_CODE)

        assert setup_api._patch_wppconnect_host_layer(str(api_dir)) is True

        content = host_layer.read_text(encoding="utf-8")
        assert PATCHED_CHECK_QR_CODE in content
        assert V2_CHECK_QR_CODE not in content
        assert PATCHED_LOGIN_BY_CODE in content

    def test_a_fully_patched_install_is_left_byte_identical(self, fake_wppconnect_dist):
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        _write(host_layer, ORIGINAL_CHECK_QR_CODE)

        setup_api._patch_wppconnect_host_layer(str(api_dir))
        first = host_layer.read_text(encoding="utf-8")
        setup_api._patch_wppconnect_host_layer(str(api_dir))
        assert host_layer.read_text(encoding="utf-8") == first

    def test_an_unrecognised_file_is_reported_and_left_untouched(self, fake_wppconnect_dist):
        """A future upstream release that rewrites these methods must not be
        silently corrupted — the patcher returns False and writes nothing."""
        setup_api = _load_setup_api()
        api_dir, host_layer = fake_wppconnect_dist
        host_layer.write_text("class HostLayer { /* upstream moved on */ }\n", encoding="utf-8")
        before = host_layer.read_text(encoding="utf-8")

        assert setup_api._patch_wppconnect_host_layer(str(api_dir)) is False
        assert host_layer.read_text(encoding="utf-8") == before
