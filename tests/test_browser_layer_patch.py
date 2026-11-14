"""Tests for the browser.js patch: a large account whose WhatsApp Web needs a
little over 30 s to become ready never connecting (issue #414).

injectApi() waits for `WAPI && Store && WPP.isReady` on puppeteer's default
30 s. The reporter's account (616 chats, a 25.8 MB IndexedDB store) needed
32-35 s, so every start failed with

    TimeoutError: Waiting failed: 30000ms exceeded

and the page reported itself ready 2.7 s later. injectApi() below is copied
verbatim from @wppconnect-team/wppconnect 2.3.4 (the homologated version) and
run under Node, unpatched and patched, against a page standing in for
puppeteer's: its waitForFunction() honours `options.timeout` and defaults to
30 s, the way puppeteer's does.
"""

import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

from core.wppconnect_browser_layer_patch import (
    BROWSER_JS_PARTS, INJECT_API_READY_TIMEOUT_MS, STATUS_ALREADY, STATUS_APPLIED,
    STATUS_NO_MATCH, STATUS_UPSTREAM, patch_browser_controller, patch_browser_source,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: dist/controllers/browser.js of @wppconnect-team/wppconnect 2.3.4, verbatim.
INJECT_API_2_3_4 = """async function injectApi(page, onLoadingScreenCallBack) {
    const injected = await page
        .evaluate(() => {
        // @ts-ignore
        return (typeof window.WAPI !== 'undefined' &&
            typeof window.Store !== 'undefined');
    })
        .catch(() => false);
    if (injected) {
        return;
    }
    await page.addScriptTag({
        path: require.resolve('@wppconnect/wa-js'),
    });
    await page.evaluate(() => {
        WPP.chat.defaultSendMessageOptions.createChat = true;
        WPP.conn.setKeepAlive(true);
    });
    await page.addScriptTag({
        path: require.resolve(path.join(__dirname, '../../dist/lib/wapi', 'wapi.js')),
    });
    await onLoadingScreen(page, onLoadingScreenCallBack);
    // Make sure WAPI is initialized
    await page.waitForFunction(() => {
        return (typeof window.WAPI !== 'undefined' &&
            typeof window.Store !== 'undefined' &&
            window.WPP.isReady);
    });
}
"""

UNTIMED_WAIT = "            window.WPP.isReady);\n    });\n}"


def _browser_js(inject_api=INJECT_API_2_3_4) -> str:
    return f'"use strict";\nconst before = 1;\n{inject_api}async function initBrowser() {{}}\n'


@pytest.fixture
def fake_api_dir(tmp_path):
    browser_js = tmp_path.joinpath(*BROWSER_JS_PARTS)
    browser_js.parent.mkdir(parents=True)
    browser_js.write_bytes(_browser_js().encode("utf-8"))
    return tmp_path, browser_js


class TestSourcePatch:
    def test_gives_the_readiness_wait_its_own_timeout_and_nothing_else(self):
        content = _browser_js()

        patched, status = patch_browser_source(content)

        assert status == STATUS_APPLIED
        assert UNTIMED_WAIT not in patched
        assert f"}}, {{ timeout: {INJECT_API_READY_TIMEOUT_MS} }}" in patched
        # The other waits in the function keep puppeteer's defaults.
        assert patched.count("timeout") == 1
        assert patched.replace(
            f", {{ timeout: {INJECT_API_READY_TIMEOUT_MS} }} "
            "/* WinZapp: injectApi readiness, issue #414 */", "") == content

    def test_is_idempotent(self):
        once, _ = patch_browser_source(_browser_js())

        twice, status = patch_browser_source(once)

        assert status == STATUS_ALREADY
        assert twice == once

    def test_matches_whatever_line_endings_npm_unpacked(self):
        content = _browser_js().replace("\n", "\r\n")

        patched, status = patch_browser_source(content)

        assert status == STATUS_APPLIED
        assert "\r\n" in patched and patched.count("\n") == patched.count("\r\n")

    def test_a_wait_that_already_has_options_upstream_is_left_alone(self):
        content = _browser_js().replace(UNTIMED_WAIT,
                                        "            window.WPP.isReady);\n    }, { timeout: 0 });\n}")

        patched, status = patch_browser_source(content)

        assert status == STATUS_NO_MATCH
        assert patched == content

    def test_wppconnect_2_3_5_own_injection_timeout_needs_no_patch(self):
        """2.3.5 rewrote injectApi() around an `injectionTimeout` option, so the
        file is recognised as upstream's, not reported as a mismatch."""
        content = _browser_js(
            "class InjectionTimeoutError extends Error {}\n"
            "async function injectApi(page) {\n"
            "    await page.waitForFunction(() => !!window.WPP?.isReady, { timeout: 0 });\n}\n")

        patched, status = patch_browser_source(content)

        assert status == STATUS_UPSTREAM
        assert patched == content

    def test_the_upstream_timeout_is_set_to_the_same_value_in_both_configs(self):
        """2.3.5 defaults to 120 s, past the resume path's grace; 2.3.4 ignores
        the key and gets INJECT_API_READY_TIMEOUT_MS from the patch."""
        config_json = json.loads(
            (ROOT / "client" / "api_patches" / "config.json").read_text(encoding="utf-8"))
        config_ts = (ROOT / "client" / "api_patches" / "src" / "config.ts").read_text(
            encoding="utf-8")

        assert config_json["createOptions"]["injectionTimeout"] == INJECT_API_READY_TIMEOUT_MS
        assert f"injectionTimeout: {INJECT_API_READY_TIMEOUT_MS}," in config_ts

    def test_stays_under_the_resume_paths_no_progress_grace(self):
        """A start may not wait on this alone for as long as the power-resume
        path waits before restarting a session stuck in INITIALIZING."""
        from main_window.connection import ConnectionMixin
        assert 30000 < INJECT_API_READY_TIMEOUT_MS < ConnectionMixin._RESUME_INITIALIZING_GRACE * 1000


def _node():
    bundled = ROOT / "client" / "node" / "node.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("node")


_HARNESS = """
const path = require('path');
require.resolve = (p) => p;
const onLoadingScreen = async () => {};
const page = {
  evaluate: async () => false,
  addScriptTag: async () => {},
  // Puppeteer's waitForFunction(): options.timeout, 30 s by default.
  waitForFunction: async (fn, options) => {
    const timeout = options && options.timeout !== undefined ? options.timeout : 30000;
    if (READY_AFTER_MS > timeout) {
      const error = new Error(`Waiting failed: ${timeout}ms exceeded`);
      error.name = 'TimeoutError';
      throw error;
    }
  },
};
INJECT_API
injectApi(page, null).then(
  () => console.log(JSON.stringify({ ready: true })),
  (error) => console.log(JSON.stringify({ error: `${error.name}: ${error.message}` })),
);
"""


def _run_inject_api(inject_api: str, ready_after_ms: int) -> dict:
    node = _node()
    if not node:
        pytest.skip("node not available")
    script = (_HARNESS.replace("READY_AFTER_MS", str(ready_after_ms))
              .replace("INJECT_API", inject_api))
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout)


class TestInjectApiUnderNode:
    def test_unpatched_fails_on_a_page_ready_after_33_seconds(self):
        """The reported failure, word for word."""
        assert _run_inject_api(INJECT_API_2_3_4, 33000) == {
            "error": "TimeoutError: Waiting failed: 30000ms exceeded"}

    def test_patched_waits_for_it(self):
        patched, _ = patch_browser_source(INJECT_API_2_3_4)

        assert _run_inject_api(patched, 33000) == {"ready": True}

    def test_patched_still_gives_up_on_a_page_that_never_becomes_ready(self):
        patched, _ = patch_browser_source(INJECT_API_2_3_4)

        assert _run_inject_api(patched, 10 ** 9) == {
            "error": f"TimeoutError: Waiting failed: {INJECT_API_READY_TIMEOUT_MS}ms exceeded"}


class TestFile:
    def test_a_2_3_5_file_is_ok_and_left_alone(self, tmp_path):
        browser_js = tmp_path.joinpath(*BROWSER_JS_PARTS)
        browser_js.parent.mkdir(parents=True)
        original = b"class InjectionTimeoutError extends Error {}\n"
        browser_js.write_bytes(original)

        ok, note = patch_browser_controller(str(tmp_path))

        assert ok is True and "no patch needed" in note
        assert browser_js.read_bytes() == original

    def test_patches_the_file_in_place(self, fake_api_dir):
        api_dir, browser_js = fake_api_dir

        ok, note = patch_browser_controller(str(api_dir))

        assert ok is True and "Patched" in note
        assert b"{ timeout: 60000 }" in browser_js.read_bytes()

    def test_a_second_run_is_a_no_op(self, fake_api_dir):
        api_dir, browser_js = fake_api_dir
        patch_browser_controller(str(api_dir))
        first_pass = browser_js.read_bytes()

        ok, note = patch_browser_controller(str(api_dir))

        assert ok is True and "already applied" in note
        assert browser_js.read_bytes() == first_pass

    def test_a_missing_file_is_a_safe_no_op(self, tmp_path):
        ok, note = patch_browser_controller(str(tmp_path))

        assert ok is False and "not found" in note

    def test_a_file_that_moved_upstream_is_reported_and_untouched(self, fake_api_dir):
        api_dir, browser_js = fake_api_dir
        browser_js.write_bytes(b'"use strict";async function injectApi() {}')

        ok, note = patch_browser_controller(str(api_dir))

        assert ok is False and "did not match" in note
        assert browser_js.read_bytes() == b'"use strict";async function injectApi() {}'


def _load_setup_api():
    spec = importlib.util.spec_from_file_location("setup_api", ROOT / "setup_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEveryCallSiteAppliesIt:
    """setup_api.py (dev and CI), ApiSetupDialog (the end-user install and
    every launch) and build_api.py: a patch missing from one ships broken."""

    def test_setup_api(self, fake_api_dir):
        api_dir, browser_js = fake_api_dir

        assert _load_setup_api()._patch_wppconnect_browser(str(api_dir)) is True

        assert b"{ timeout: 60000 }" in browser_js.read_bytes()

    def test_api_setup_dialog(self, fake_api_dir):
        from ui.dialogs.api_setup import ApiSetupDialog
        api_dir, browser_js = fake_api_dir

        ApiSetupDialog._apply_node_modules_patches(str(api_dir))

        assert b"{ timeout: 60000 }" in browser_js.read_bytes()

    def test_build_api(self, fake_api_dir, monkeypatch):
        spec = importlib.util.spec_from_file_location("build_api", ROOT / "build_api.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        api_dir, browser_js = fake_api_dir
        for name in (
            "_patch_wppconnect_host_layer", "_patch_wppconnect_status_layer",
            "_patch_wppconnect_sender_layer", "_patch_wppconnect_welcome_layer",
            "_patch_wa_js_bundle",
        ):
            monkeypatch.setattr(module.canonical_setup, name, lambda path: True)

        module._apply_node_modules_patches(str(api_dir))

        assert b"{ timeout: 60000 }" in browser_js.read_bytes()
