"""Patch for @wppconnect-team/wppconnect's compiled controllers/browser.js —
a large account whose WhatsApp Web needs a little over 30 s to become ready
never connects (issue #414).

`injectApi()` injects wa-js and then waits for the page to be usable:

    await page.waitForFunction(() => {
        return (typeof window.WAPI !== 'undefined' &&
            typeof window.Store !== 'undefined' &&
            window.WPP.isReady);
    });

with no timeout of its own, so puppeteer's default of 30 s applies. Reported
on an account with 616 chats and a 25.8 MB IndexedDB store, which needs 32 to
35 s to hydrate: the wait threw `TimeoutError: Waiting failed: 30000ms
exceeded` at 30.0 s, `create()` failed and the session was reset to CLOSED,
and the page reported its WhatsApp Web version 2.7 s later. Nothing in that
loop changes on the next attempt, so the same account fails the same way
every time — on WinZapp's bundled server too, where the failed start leaves
Chrome holding the profile and the next start has to kill it first.

Fix: give that one wait its own timeout, `INJECT_API_READY_TIMEOUT_MS`.
60 s rather than the 90 s the report used: the power-resume path restarts a
session that has made no progress for `_RESUME_INITIALIZING_GRACE` (90 s,
main_window/connection.py), and a start that may legitimately wait 90 s for
this alone would be cut off by it. A profile that never becomes ready still
fails, 30 s later than before — which only stretches each failed cycle the
profile-health tracker counts (core/profile_recovery.py); the pairing-code
route, the faster of the two, does not wait on it.

Only this wait changes. `page.setDefaultTimeout()` would have reached it
without a patch, but it moves every other puppeteer wait on the page with it.

wppconnect 2.3.5 made the wait its own: `injectApi()` takes `injectionTimeout`
(default 120 s, `InjectionTimeoutError`), so there is nothing left to patch and
the file is recognised as STATUS_UPSTREAM, never reported as a mismatch. The
60 s this module chose is then passed as `createOptions.injectionTimeout`
(api_patches/config.json and src/config.ts); wppconnect 2.3.4 ignores that key.

Matched by structure, not by one literal, so indentation and line endings do
not matter. Like the wa-js bundle patch, this module owns the file handling:
the three call sites (setup_api.py, build_api.py and
ApiSetupDialog._apply_node_modules_patches()) pass the outer client/api
directory to patch_browser_controller().
"""

import os
import re

BROWSER_JS_PARTS = (
    "node_modules", "@wppconnect-team", "wppconnect", "dist", "controllers", "browser.js",
)

INJECT_API_READY_TIMEOUT_MS = 60000

#: The marker the patched call carries; also how a patched file is recognised.
_MARKER = "/* WinZapp: injectApi readiness, issue #414 */"

_READY_CHECK = (
    r"return\s*\(\s*typeof window\.WAPI !== 'undefined' &&\s*"
    r"typeof window\.Store !== 'undefined' &&\s*"
    r"window\.WPP\.isReady\s*\);"
)
# `await page.waitForFunction(() => { <ready check> })` with no options.
_UNTIMED_WAIT = re.compile(
    r"(?P<head>await page\.waitForFunction\(\(\) => \{\s*" + _READY_CHECK + r"\s*\})\);"
)

STATUS_APPLIED = "applied"
STATUS_ALREADY = "already"
STATUS_NO_MATCH = "no_match"
#: wppconnect >= 2.3.5: the wait is upstream's own, with an `injectionTimeout` option.
STATUS_UPSTREAM = "upstream"


def patch_browser_source(content: str) -> tuple[str, str]:
    """Return (*content* with the readiness wait given its own timeout, status).

    Idempotent: a patched wait carries options, so it no longer matches the
    untimed pattern, and a second pass reports STATUS_ALREADY. A file holding
    neither form (an upstream rewrite) comes back untouched as
    STATUS_NO_MATCH.
    """
    patched, count = _UNTIMED_WAIT.subn(
        lambda match: (f"{match.group('head')}, "
                       f"{{ timeout: {INJECT_API_READY_TIMEOUT_MS} }} {_MARKER});"),
        content,
    )
    if count:
        return patched, STATUS_APPLIED
    if _MARKER in content:
        return content, STATUS_ALREADY
    if "class InjectionTimeoutError" in content:
        return content, STATUS_UPSTREAM
    return content, STATUS_NO_MATCH


def patch_browser_controller(api_dir: str) -> tuple[bool, str]:
    """Patch browser.js under *api_dir* (the outer client/api directory).
    Returns (ok, note); *ok* is False when the file is missing or holds
    neither form of the wait, and *note* is the line to log.
    """
    path = os.path.join(api_dir, *BROWSER_JS_PARTS)
    if not os.path.isfile(path):
        return False, "browser.js not found — skipping the injectApi readiness timeout patch."

    # newline="" both ways: every byte but the one call stays as npm unpacked it.
    with open(path, encoding="utf-8", newline="") as f:
        content = f.read()

    patched, status = patch_browser_source(content)
    if status == STATUS_APPLIED:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(patched)
        return True, (
            "Patched browser.js — injectApi now waits "
            f"{INJECT_API_READY_TIMEOUT_MS // 1000} s for WhatsApp Web to be "
            "ready instead of puppeteer's 30 s."
        )
    if status == STATUS_ALREADY:
        return True, "browser.js injectApi readiness timeout patch already applied."
    if status == STATUS_UPSTREAM:
        return True, (
            "browser.js: no patch needed — wppconnect 2.3.5 and later bound the "
            "injectApi readiness wait themselves (injectionTimeout)."
        )
    return False, (
        "browser.js: the injectApi readiness wait did not match the expected "
        "upstream source — skipping (the installed @wppconnect-team/wppconnect "
        "version may have changed it)."
    )
