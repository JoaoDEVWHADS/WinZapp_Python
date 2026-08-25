"""WinZapp must launch chrome-headless-shell, and history sync must survive it.

Two separate guarantees, because they failed in two different ways.

1. The shell has to actually be the binary that gets launched.

   start.js was switched to chrome-headless-shell (smaller, faster, and with no
   windowing layer compiled in at all — nothing can ever flash a window at a
   blind user). But the switch silently never took effect on any machine that
   had run an older build, and the reason is worth keeping:

     * The search walked client/api/.cache once, matching the shell's and full
       Chrome's filenames in the same loop, and returned whatever the directory
       walk reached first.
     * A machine upgrading from an older WinZapp has
       .cache/puppeteer/chrome/win64-*/chrome-win64/chrome.exe sitting there
       from before, and an EMPTY .cache/chrome-headless-shell/ directory.
     * So the walk found full Chrome, `hasChrome` came back true, and the
       "install chrome-headless-shell" branch never ran. Forever: the empty
       directory was never the thing being checked.

   Measured on this repo before the fix: the only executable under .cache/ was
   chrome.exe, and .cache/chrome-headless-shell/ was empty. WPPConnect was
   being handed full Chrome on every launch.

   The fix is a two-pass search — every shell name anywhere under the cache
   first, full Chrome only as a fallback — plus keying the installer off the
   shell specifically rather than off "any Chrome-ish binary".

2. The shell must not cost anything history sync depends on.

   chrome-headless-shell is Chrome's *old* headless implementation, a separate
   binary rather than a mode. That is exactly the kind of substitution that
   quietly removes an API a page depends on, and WhatsApp Web's history
   pipeline depends on several: it runs its storage/decode backend in workers,
   keeps everything in IndexedDB, and needs a persistent storage bucket or the
   browser may evict that database. Chrome's auto-grant heuristic for
   persistent storage also keys off the notifications permission, so a build
   without the Notification API can never get a persistent bucket.

   TestTheShellKeepsWhatWhatsAppWebNeeds launches the real shell with
   start.js's real flag list and probes each of those directly, rather than
   trusting that "headless is headless".
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "client" / "api"
PATCHES = ROOT / "client" / "api_patches"
CACHE = API / ".cache"

SHELL_NAMES = ("chrome-headless-shell.exe", "chrome-headless-shell")


def _find(names):
    if not CACHE.is_dir():
        return None
    for path in CACHE.rglob("*"):
        if path.is_file() and path.name in names:
            return path
    return None


def _node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    return node


def _run_node(script, tmp_path, timeout=300):
    harness = tmp_path / "probe.js"
    harness.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(harness), str(API)], capture_output=True, text=True, timeout=timeout
    )
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return json.loads(line[len("__RESULT__"):])
    raise AssertionError(
        f"probe produced no result.\nexit={proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


class TestTheSelectionPrefersTheShell:
    """Source-level, so these run on a bare checkout too."""

    def test_the_shell_is_searched_before_full_chrome(self):
        src = (PATCHES / "start.js").read_text(encoding="utf-8")
        assert "HEADLESS_SHELL_NAMES" in src and "FULL_CHROME_NAMES" in src, (
            "the two candidate sets must be separate lists, or the search "
            "collapses back into one pass whose winner is decided by directory "
            "layout rather than by preference — see this module's docstring"
        )
        assert "findHeadlessShell() || findExecutable(puppeteerCacheDir, FULL_CHROME_NAMES" in src, (
            "full Chrome must only ever be reached after the shell search fails"
        )

    def test_the_installer_is_keyed_off_the_shell_not_off_any_chrome(self):
        """`if (!hasChrome)` was the bug: a leftover full Chrome made it false
        and the shell was never fetched."""
        src = (PATCHES / "start.js").read_text(encoding="utf-8")
        assert "if (!findHeadlessShell())" in src, (
            "the auto-install must trigger when the *shell* is missing, not when "
            "any Chrome-like binary is missing"
        )
        # The old flag's name survives in the comment explaining the bug, so
        # only real code lines count.
        code = [
            line for line in src.splitlines()
            if not line.lstrip().startswith(("//", "*"))
        ]
        assert not [line for line in code if "hasChrome" in line], (
            "the old any-Chrome-will-do flag must be gone from the code"
        )

    def test_only_the_shell_is_ever_installed(self):
        src = (PATCHES / "start.js").read_text(encoding="utf-8")
        assert "browsers install chrome-headless-shell" in src
        assert "browsers install chrome'" not in src, "must never fetch GUI-capable Chrome"

    def test_the_in_app_installer_downloads_the_shell_too(self):
        """ApiSetupDialog is the flow every end user goes through just by
        running WinZapp. It used to fetch full "chrome", which is precisely how
        a machine ends up with a GUI-capable Chrome under .cache/ and no shell
        — the state that made the old search hand WPPConnect full Chrome."""
        src = (ROOT / "client" / "ui" / "dialogs" / "api_setup.py").read_text(encoding="utf-8")
        assert '"install", "chrome-headless-shell"' in src, (
            "the in-app installer must download chrome-headless-shell, not full Chrome"
        )
        assert '"install", "chrome"' not in src

    def test_every_install_path_uses_the_cache_dir_start_js_searches(self):
        """start.js searches (and exports as PUPPETEER_CACHE_DIR)
        client/api/.cache. An installer writing into .cache/puppeteer instead
        downloads a browser into a tree the server is not the one looking in."""
        for rel in ("client/ui/dialogs/api_setup.py", "client/main.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            offenders = [
                line.strip() for line in src.splitlines()
                if 'resource_path("api", ".cache", "puppeteer")' in line
            ]
            assert not offenders, f"{rel} still points at the .cache/puppeteer subtree: {offenders}"
        start = (PATCHES / "start.js").read_text(encoding="utf-8")
        assert "const puppeteerCacheDir = path.join(__dirname, '.cache');" in start

    def test_a_gui_browser_can_never_be_launched(self):
        """headless and useChrome are both pinned in start.js rather than left
        to upstream defaults. useChrome in particular is not cosmetic: when
        true, WPPConnect's initBrowser() locates the *system* Chrome and
        overwrites puppeteerOptions.executablePath with it, discarding the
        shell we selected — with no log line saying so."""
        src = (PATCHES / "start.js").read_text(encoding="utf-8")
        assert "headless: true," in src
        assert "useChrome: false," in src


class TestTheLaunchConfigStartJsBuilds:
    """Runs the real start.js and inspects the config it hands initServer()."""

    HARNESS = r"""
'use strict';
const path = require('path');
const Module = require('module');
const apiDir = process.argv[2];
const out = { launch: null };

const distConfig = path.join(apiDir, 'dist', 'config');
const distIndex = path.join(apiDir, 'dist', 'index');
const origLoad = Module._load;
Module._load = function (request) {
  if (request === distConfig) return { default: { createOptions: {}, webhook: {}, log: {} } };
  if (request === distIndex) {
    return { initServer: (cfg) => {
      const co = (cfg && cfg.createOptions) || {};
      out.launch = {
        headless: co.headless,
        useChrome: co.useChrome,
        executablePath: (co.puppeteerOptions || {}).executablePath || null,
        browserArgs: co.browserArgs || [],
      };
    } };
  }
  return origLoad.apply(this, arguments);
};

require(path.join(apiDir, 'start.js'));
console.log('__RESULT__' + JSON.stringify(out));
"""

    @pytest.fixture(scope="class")
    @classmethod
    def launch(cls, tmp_path_factory):
        if not (API / "start.js").exists():
            pytest.skip("client/api/ not set up here")
        if not (API / "node_modules" / "@wppconnect-team" / "wppconnect").exists():
            pytest.skip("client/api/node_modules not installed here")
        if _find(SHELL_NAMES) is None:
            # Requiring start.js with no shell present triggers a ~90MB
            # download; never do that from a test.
            pytest.skip("chrome-headless-shell not installed in client/api/.cache")
        result = _run_node(cls.HARNESS, tmp_path_factory.mktemp("launch"))
        assert result["launch"] is not None, "start.js never called initServer()"
        return result["launch"]

    def test_the_selected_binary_is_the_headless_shell(self, launch):
        exe = launch["executablePath"]
        assert exe, "no executablePath was pinned — puppeteer would pick its own browser"
        assert pathlib.Path(exe).name in SHELL_NAMES, (
            f"start.js selected {exe!r} instead of chrome-headless-shell. A leftover "
            f"full Chrome under .cache/ must never win the search."
        )

    def test_headless_and_use_chrome_are_pinned(self, launch):
        assert launch["headless"] is True
        assert launch["useChrome"] is False, (
            "useChrome=true makes WPPConnect replace our executablePath with the "
            "system-installed Chrome"
        )

    def test_no_flag_removes_part_of_the_worker_or_notification_surface(self, launch):
        """WhatsApp Web runs its storage/decode backend in workers, and the
        persistent-storage auto-grant keys off the notifications permission."""
        for flag in ("--disable-shared-workers", "--disable-workers", "--disable-notifications"):
            assert flag not in launch["browserArgs"], f"{flag} must not be launched with"


class TestTheShellKeepsWhatWhatsAppWebNeeds:
    """Launches the real chrome-headless-shell with start.js's real flag list.

    Every probe here corresponds to something the history pipeline actually
    uses; a shell build missing any of them would lose messages rather than
    fail loudly.
    """

    HARNESS = r"""
'use strict';
const path = require('path');
const http = require('http');
const fs = require('fs');
const apiDir = process.argv[2];
const puppeteer = require(require.resolve('puppeteer', { paths: [apiDir] }));

const SHELL = ['chrome-headless-shell.exe', 'chrome-headless-shell'];
function find(dir, names, d) {
  if (d > 6) return null;
  let e; try { e = fs.readdirSync(dir, { withFileTypes: true }); } catch (x) { return null; }
  const subs = [];
  for (const en of e) { const f = path.join(dir, en.name);
    if (en.isDirectory()) subs.push(f); else if (names.includes(en.name)) return f; }
  for (const s of subs) { const f = find(s, names, d + 1); if (f) return f; }
  return null;
}

// Reuse start.js's real flag list rather than a copy of it.
const startJs = fs.readFileSync(path.join(apiDir, 'start.js'), 'utf8');
const bs = startJs.indexOf('const optimizedBrowserArgs = [');
const args = [...startJs.slice(bs, startJs.indexOf('];', bs)).matchAll(/'(--[^']+)'/g)].map((m) => m[1]);

const out = { caps: null, worker: null, error: null };

// Two ports = two origins, so the cross-origin path is exercised offline.
function servers() {
  return new Promise((resolve) => {
    const b = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/javascript', 'Access-Control-Allow-Origin': '*' });
      res.end('export const value = 42;');
    });
    b.listen(0, '127.0.0.1', () => {
      const portB = b.address().port;
      const a = http.createServer((req, res) => {
        if (req.url === '/sw.js') {
          res.writeHead(200, { 'Content-Type': 'application/javascript' });
          res.end('self.addEventListener("install",()=>{});');
          return;
        }
        if (req.url === '/worker.js') {
          res.writeHead(200, { 'Content-Type': 'application/javascript' });
          // What WAWebBackendWorker does at boot: a module worker importing
          // its bundles cross-origin, then a CORS fetch.
          res.end(`self.onmessage = async () => { const log = [];
            try { const m = await import('http://127.0.0.1:${portB}/mod.js'); log.push('import:' + m.value); }
            catch (e) { log.push('import-err:' + e.message); }
            try { const r = await fetch('http://127.0.0.1:${portB}/mod.js', {mode:'cors'}); log.push('fetch:' + r.status); }
            catch (e) { log.push('fetch-err:' + e.message); }
            self.postMessage(log.join('|')); };`);
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html><title>caps</title><script>
          const w = new Worker('/worker.js', { type: 'module' });
          window.__w = new Promise((res) => { w.onmessage = (e) => res(e.data); });
          w.postMessage('go');
        </script>`);
      });
      a.listen(0, '127.0.0.1', () => resolve({ a, b, portA: a.address().port }));
    });
  });
}

(async () => {
  const { a, b, portA } = await servers();
  let browser = null;
  try {
    const executable = find(path.join(apiDir, '.cache'), SHELL, 0);
    if (!executable) throw new Error('chrome-headless-shell not installed');
    browser = await puppeteer.launch({ headless: true, executablePath: executable, args });
    const page = await browser.newPage();
    const origin = 'http://127.0.0.1:' + portA;
    // The same grant createSessionUtil.ts performs, over a CDP session kept alive.
    const cdp = await page.createCDPSession();
    await cdp.send('Browser.grantPermissions', { origin, permissions: ['durableStorage', 'notifications'] });
    await page.goto(origin + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    out.caps = await page.evaluate(async () => {
      const o = {};
      o.notificationApi = typeof Notification;
      try { o.persistedBefore = await navigator.storage.persisted();
            if (!o.persistedBefore) await navigator.storage.persist();
            o.persisted = await navigator.storage.persisted(); }
      catch (e) { o.persisted = 'err:' + e.message; }
      try { await new Promise((res, rej) => { const r = indexedDB.open('probe', 1);
              r.onsuccess = () => res(); r.onerror = () => rej(r.error); });
            o.indexedDB = 'ok'; } catch (e) { o.indexedDB = 'err:' + e.message; }
      o.worker = typeof Worker;
      o.sharedWorker = typeof SharedWorker;
      try { await navigator.serviceWorker.register('/sw.js'); o.serviceWorker = 'ok'; }
      catch (e) { o.serviceWorker = 'err:' + e.message; }
      o.wasm = typeof WebAssembly;
      o.subtleCrypto = typeof crypto.subtle;
      return o;
    });
    out.worker = await page.evaluate((ms) => Promise.race([
      window.__w, new Promise((r) => setTimeout(() => r('HANG'), ms)),
    ]), 15000);
  } catch (e) { out.error = String((e && e.stack) || e); }
  finally {
    if (browser) { try { await browser.close(); } catch (e) {} }
    a.close(); b.close();
    console.log('__RESULT__' + JSON.stringify(out));
    process.exit(0);
  }
})();
"""

    @pytest.fixture(scope="class")
    @classmethod
    def probe(cls, tmp_path_factory):
        if _find(SHELL_NAMES) is None:
            pytest.skip("chrome-headless-shell not installed in client/api/.cache")
        if not (API / "node_modules" / "puppeteer").exists():
            pytest.skip("puppeteer not installed in client/api/node_modules")
        result = _run_node(cls.HARNESS, tmp_path_factory.mktemp("caps"))
        assert result["error"] is None, result["error"]
        return result

    def test_a_module_worker_can_import_and_fetch_cross_origin(self, probe):
        """The single most important one. WhatsApp Web boots its entire
        storage/decode backend in a module worker that imports its bundles from
        another origin, and every history-sync chunk handler waits on that
        worker's bridge before decoding. If this hangs, chats show only their
        newest messages and nothing anywhere reports an error."""
        assert probe["worker"] == "import:42|fetch:200", (
            f"module worker cross-origin path degraded under chrome-headless-shell: "
            f"{probe['worker']!r}"
        )

    def test_persistent_storage_is_granted(self, probe):
        """Without a persistent bucket WhatsApp Web's IndexedDB is evictable,
        and the decoded history can be thrown away between runs."""
        caps = probe["caps"]
        assert caps["notificationApi"] == "function", (
            "Chrome's auto-grant heuristic for persistent storage keys off the "
            "notifications permission — with the API gone, persist() can only "
            "ever return false"
        )
        assert caps["persisted"] is True

    def test_the_storage_and_worker_surface_is_intact(self, probe):
        caps = probe["caps"]
        assert caps["indexedDB"] == "ok"
        assert caps["worker"] == "function"
        assert caps["sharedWorker"] == "function"
        assert caps["serviceWorker"] == "ok"
        assert caps["wasm"] == "object"
        assert caps["subtleCrypto"] == "object"
