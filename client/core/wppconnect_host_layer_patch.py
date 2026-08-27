"""Shared source-text constants for patching @wppconnect-team/wppconnect's
compiled host.layer.js — the phone-number pairing-code rotation fix
(WinZapp issue #8).

Both setup_api.py (repo root, the developer/CI setup script) and
ApiSetupDialog (client/ui/dialogs/api_setup.py, the real end-user install
flow) need to apply the exact same patch to node_modules right after every
`npm install` — see either call site's own docstring for why this can't go
through the normal api_patches/ mechanism. They used to each carry their
own hand-duplicated copy of these strings; when the patch needed a
correction (v1 -> v2, see below) only one of the two copies actually got
fixed here, which is exactly the kind of drift this shared module exists to
rule out going forward. This module has zero dependencies beyond the
standard library so it's safe for setup_api.py to import via a sys.path
insert of client/ without pulling in wx or any other heavy client code.

History:

* v0 — the original upstream bug (wppconnect-team/wppconnect#2836):
  checkQrCode() is bound to WhatsApp's own QR rotation (`conn.auth_code_change`)
  and dedupes the QR-image branch against `this.urlCode` before re-emitting
  it, but the phoneNumber (pairing-code) branch returns straight into
  loginByCode() with no equivalent guard — so every ~20-60s QR rotation
  regenerates a BRAND NEW pairing code, faster than a screen-reader user can
  read an 8-character code.

* v1 — WinZapp's first fix attempt (shipped, then found unsafe): a
  `linkCodeGenerated` latch set to True BEFORE loginByCode() actually
  produced a code, cleared only on a successful login. If loginByCode()
  ever rejected, or if a legitimately-issued code needed a later refresh,
  the latch never got reset — the displayed code silently froze forever.
  Reported live: "esperei 10 minutos e o código não atualizou nenhuma vez."

* v2 — a 60-second reuse cooldown instead of a permanent latch.
  `linkCodeIssuedAt` is only set AFTER loginByCode() actually succeeds (not
  before), and a separate `linkCodeInFlight` flag (not a timestamp) guards
  against overlapping concurrent calls — so a rejected attempt simply leaves
  `linkCodeIssuedAt` at its old value and the very next `auth_code_change`
  tick retries, with no permanent stuck state either way. This was written as
  a WinZapp-local stopgap because wa-js had no explicit expiry/refresh signal
  at the time (https://github.com/wppconnect-team/wa-js/pull/3554). That PR
  has since landed — see the loginByCode migration further down — so the
  cooldown is now belt-and-braces over a library that dedupes properly. Kept
  for now only because changing one thing at a time is what keeps a
  regression attributable; retiring it is a reasonable follow-up.

* v3 — a `catch` around the loginByCode() call. v2's try/finally had none, so
  a rejection escaped checkQrCode() (called fire-and-forget) as an unhandled
  rejection that killed the tick. Paired with the loginByCode() error-detail
  patch further down, without which the error was the minified "t: t" anyway.

* v4 — hands the caught error to an optional `catchLinkCodeError` hook read
  off `this.options`, so it reaches the user instead of only wppconnect.log.

* v5 — current fix: a doubling backoff, 20s to a 5-minute ceiling, between
  consecutive failures. v2's cooldown only ever gates a success, so through a
  run of failures nothing paced the retries at all and every auth-code
  rotation went straight back into genLinkDeviceCodeForPhoneNumber() —
  measured at one attempt every 20 seconds, indefinitely. See the comment on
  PATCHED_CHECK_QR_CODE for why that likely made the failure it was reacting
  to worse rather than better.

Every generation is kept as its own constant: they are the rungs
patch_host_layer_source() migrates along, so an install at any past version
lands on the current one. Removing one strands whoever is still on it.
"""

ORIGINAL_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            return this.loginByCode(this.options.phoneNumber);\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)

V1_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            this.linkCodeGenerated = false;\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            if (this.linkCodeGenerated) {\n"
    "                return;\n"
    "            }\n"
    "            this.linkCodeGenerated = true;\n"
    "            return this.loginByCode(this.options.phoneNumber);\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)

V2_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            this.linkCodeIssuedAt = 0;\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            if (this.linkCodeInFlight) {\n"
    "                return;\n"
    "            }\n"
    "            const now = Date.now();\n"
    "            if (this.linkCodeIssuedAt && (now - this.linkCodeIssuedAt) < 60000) {\n"
    "                return;\n"
    "            }\n"
    "            this.linkCodeInFlight = true;\n"
    "            try {\n"
    "                await this.loginByCode(this.options.phoneNumber);\n"
    "                this.linkCodeIssuedAt = Date.now();\n"
    "            }\n"
    "            finally {\n"
    "                this.linkCodeInFlight = false;\n"
    "            }\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)

# v3 — v2 plus a `catch` around loginByCode(). v2 awaits loginByCode() inside a
# try/finally with no catch, so a rejection propagates straight out of
# checkQrCode() — and checkQrCode() is called fire-and-forget (`this.checkQrCode()`
# at the end of host.layer.js's own initialize path, and via the exposed
# `conn.auth_code_change` handler), with nobody awaiting or catching it. A failing
# genLinkDeviceCodeForPhoneNumber() therefore surfaced only as a bare
# "Unhandled Rejection: t: t" in wppconnect.log, killed that checkQrCode() tick
# before it could do anything else, and left the Python side to sit through its
# full 90-second _phone_code_event wait and report the generic "no pairing code
# received" — with nothing whatsoever in log.log to say why.
#
# Catching it keeps v2's self-recovery intact (linkCodeIssuedAt is still only set
# on success, so the next auth_code_change tick retries) while making the failure
# visible and non-fatal.
V3_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            this.linkCodeIssuedAt = 0;\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            if (this.linkCodeInFlight) {\n"
    "                return;\n"
    "            }\n"
    "            const now = Date.now();\n"
    "            if (this.linkCodeIssuedAt && (now - this.linkCodeIssuedAt) < 60000) {\n"
    "                return;\n"
    "            }\n"
    "            this.linkCodeInFlight = true;\n"
    "            try {\n"
    "                await this.loginByCode(this.options.phoneNumber);\n"
    "                this.linkCodeIssuedAt = Date.now();\n"
    "            }\n"
    "            catch (error) {\n"
    "                this.log('error', `Could not generate the pairing code: ${error?.name || 'Error'}: ${error?.message || error}`);\n"
    "            }\n"
    "            finally {\n"
    "                this.linkCodeInFlight = false;\n"
    "            }\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)


# v4 — v3 plus a `catchLinkCodeError` hook, so the failure reaches the user
# instead of only wppconnect.log. v3 made the error real and non-fatal, but the
# person actually trying to pair still saw nothing but the generic "no pairing
# code received" after a 90-second wait — the whole point of knowing the error
# is being able to say what it was.
#
# The hook is read off `this.options` rather than a dedicated instance field
# because that needs no change to initializer.js: `create()` builds the client as
# `new Whatsapp(page, session, mergedOptions)` with
# `mergedOptions = { ...defaultOptions, ...options }`, a plain spread, so an
# option key WPPConnect itself knows nothing about survives untouched into
# `this.options`. createSessionUtil.ts passes it in (see that file's own patch);
# the `?.` chain keeps this a silent no-op wherever it isn't.
V4_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            this.linkCodeIssuedAt = 0;\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            if (this.linkCodeInFlight) {\n"
    "                return;\n"
    "            }\n"
    "            const now = Date.now();\n"
    "            if (this.linkCodeIssuedAt && (now - this.linkCodeIssuedAt) < 60000) {\n"
    "                return;\n"
    "            }\n"
    "            this.linkCodeInFlight = true;\n"
    "            try {\n"
    "                await this.loginByCode(this.options.phoneNumber);\n"
    "                this.linkCodeIssuedAt = Date.now();\n"
    "            }\n"
    "            catch (error) {\n"
    "                this.log('error', `Could not generate the pairing code: ${error?.name || 'Error'}: ${error?.message || error}`);\n"
    "                this.options.catchLinkCodeError?.({\n"
    "                    name: String(error?.name || 'Error'),\n"
    "                    message: String(error?.message || error),\n"
    "                    session: this.session,\n"
    "                });\n"
    "            }\n"
    "            finally {\n"
    "                this.linkCodeInFlight = false;\n"
    "            }\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)


# v5 — v4 plus a backoff between failed attempts.
#
# The 60-second cooldown v2 introduced only ever gates a SUCCESS:
# `linkCodeIssuedAt` is written when a code is actually produced, so through a
# run of failures it stays 0 and `if (this.linkCodeIssuedAt && ...)` never
# fires. Every `conn.auth_code_change` tick therefore went straight back into
# genLinkDeviceCodeForPhoneNumber(). Measured on a real failing run: nine
# attempts, a steady one every 20 seconds, with no end in sight — that is
# WhatsApp's own auth-code rotation rate, and nothing was pacing us but it.
#
# That is bad on its own, and probably worse than it looks: CompanionHelloError
# (the failure that exposed this) is plausibly WhatsApp rate-limiting the
# link-device request, in which case hammering it three times a minute is a
# feedback loop that keeps the block alive. Backing off is what lets it clear.
#
# Doubling from 20s to a 5-minute ceiling, counted in consecutive failures and
# reset on any success. Deliberately never gives up: whatever the cause, the
# user may well resolve it (wait out a limit, fix connectivity) and pairing
# should then recover on its own rather than needing a restart.
PATCHED_CHECK_QR_CODE = (
    "    async checkQrCode() {\n"
    "        const needScan = await (0, auth_1.needsToScan)(this.page).catch(() => null);\n"
    "        this.isLogged = !needScan;\n"
    "        if (!needScan) {\n"
    "            this.attempt = 0;\n"
    "            this.linkCodeIssuedAt = 0;\n"
    "            this.linkCodeFailures = 0;\n"
    "            this.linkCodeRetryAfter = 0;\n"
    "            return;\n"
    "        }\n"
    "        if (typeof this.options.phoneNumber === 'string') {\n"
    "            if (this.linkCodeInFlight) {\n"
    "                return;\n"
    "            }\n"
    "            const now = Date.now();\n"
    "            if (this.linkCodeIssuedAt && (now - this.linkCodeIssuedAt) < 60000) {\n"
    "                return;\n"
    "            }\n"
    "            if (this.linkCodeRetryAfter && now < this.linkCodeRetryAfter) {\n"
    "                return;\n"
    "            }\n"
    "            this.linkCodeInFlight = true;\n"
    "            try {\n"
    "                await this.loginByCode(this.options.phoneNumber);\n"
    "                this.linkCodeIssuedAt = Date.now();\n"
    "                this.linkCodeFailures = 0;\n"
    "                this.linkCodeRetryAfter = 0;\n"
    "            }\n"
    "            catch (error) {\n"
    "                this.linkCodeFailures = (this.linkCodeFailures || 0) + 1;\n"
    "                const backoff = Math.min(20000 * Math.pow(2, this.linkCodeFailures - 1), 300000);\n"
    "                this.linkCodeRetryAfter = Date.now() + backoff;\n"
    "                const retryInSeconds = Math.round(backoff / 1000);\n"
    "                this.log('error', `Could not generate the pairing code (attempt ${this.linkCodeFailures}, next retry in ${retryInSeconds}s): ${error?.name || 'Error'}: ${error?.message || error}`);\n"
    "                this.options.catchLinkCodeError?.({\n"
    "                    name: String(error?.name || 'Error'),\n"
    "                    message: String(error?.message || error),\n"
    "                    session: this.session,\n"
    "                    attempt: this.linkCodeFailures,\n"
    "                    retryInSeconds: retryInSeconds,\n"
    "                    stack: String(error?.stack || ''),\n"
    "                    details: error?.winzappDetails || {},\n"
    "                });\n"
    "            }\n"
    "            finally {\n"
    "                this.linkCodeInFlight = false;\n"
    "            }\n"
    "            return;\n"
    "        }\n"
    "        const result = await this.getQrCode();\n"
    "        if (!result?.urlCode || this.urlCode === result.urlCode) {\n"
    "            return;\n"
    "        }\n"
    "        this.urlCode = result.urlCode;\n"
    "        this.attempt++;\n"
    "        let qr = '';\n"
    "        if (this.options.logQR || this.catchQR) {\n"
    "            qr = await (0, auth_1.asciiQr)(this.urlCode);\n"
    "        }\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for QRCode Scan (Attempt ${this.attempt})...:\\n${qr}`, { code: this.urlCode });\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for QRCode Scan: Attempt ${this.attempt}`);\n"
    "        }\n"
    "        this.catchQR?.(result.base64Image, qr, this.attempt, result.urlCode);\n"
    "    }\n"
)


# ── loginByCode: real error detail instead of minified "t: t" ────────────────
#
# Same root cause, and same fix, as the sendFile() error-detail patch in
# wppconnect_sender_layer_patch.py — see that module's docstring for the full
# explanation. In short: WPP.conn.genLinkDeviceCodeForPhoneNumber() throws INSIDE
# the Puppeteer page, and what wa-js's minified bundle throws there is not a
# standard Error. Puppeteer serializes a page-context exception across the CDP
# boundary via Runtime.evaluate's `exceptionDetails`, which for a non-standard
# thrown value reliably carries only a className/description — so the whole
# failure reaches Node as the useless single-letter "t: t" seen in wppconnect.log.
#
# Fixed the same way: catch the exception INSIDE the page, where the real Error
# object still exists, and RETURN it as plain data. page.evaluate()'s return value
# goes through ordinary structured cloning, which preserves plain string
# properties, unlike its exception path. The Node side then reconstructs a real
# Error and throws that, so both wppconnect.log and (via the catch added to
# checkQrCode above) the operator finally get real text.
ORIGINAL_LOGIN_BY_CODE = (
    "    async loginByCode(phone) {\n"
    "        const code = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {\n"
    "            return JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone)));\n"
    "        }, { phone });\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for Login By Code (Code: ${code})\\n`);\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for Login By Code`);\n"
    "        }\n"
    "        this.catchLinkCode?.(code);\n"
    "    }\n"
)

LEGACY_LOGIN_BY_CODE_RAW = (
    "    async loginByCode(phone) {\n"
    "        const outcome = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {\n"
    "            try {\n"
    "                return { code: JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone))) };\n"
    "            }\n"
    "            catch (error) {\n"
    "                const details = {};\n"
    "                try {\n"
    "                    for (const key of Object.getOwnPropertyNames(Object(error))) {\n"
    "                        if (key === 'stack') { continue; }\n"
    "                        const value = error[key];\n"
    "                        const kind = typeof value;\n"
    "                        if (value === null || kind === 'string' || kind === 'number' || kind === 'boolean') {\n"
    "                            details[key] = String(value);\n"
    "                        }\n"
    "                        else if (kind !== 'function') {\n"
    "                            try { details[key] = JSON.stringify(value); } catch (e) { details[key] = '[unserializable]'; }\n"
    "                        }\n"
    "                    }\n"
    "                }\n"
    "                catch (e) { }\n"
    "                return {\n"
    "                    __winzappError: {\n"
    "                        name: String(error?.name || 'Error'),\n"
    "                        message: String(error?.message || error?.reason || error?.text || error),\n"
    "                        stack: String(error?.stack || ''),\n"
    "                        details: details,\n"
    "                    },\n"
    "                };\n"
    "            }\n"
    "        }, { phone });\n"
    "        if (outcome?.__winzappError) {\n"
    "            const failure = new Error(outcome.__winzappError.message);\n"
    "            failure.name = outcome.__winzappError.name;\n"
    "            if (outcome.__winzappError.stack) {\n"
    "                failure.stack = outcome.__winzappError.stack;\n"
    "            }\n"
    "            failure.winzappDetails = outcome.__winzappError.details || {};\n"
    "            throw failure;\n"
    "        }\n"
    "        const code = outcome?.code;\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for Login By Code (Code: ${code})\\n`);\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for Login By Code`);\n"
    "        }\n"
    "        this.catchLinkCode?.(code);\n"
    "    }\n"
)


# ── loginByCode: use wa-js's managed linking lifecycle ───────────────────────
#
# wppconnect calls the low-level `WPP.conn.genLinkDeviceCodeForPhoneNumber()`
# directly. wa-js 4.6.0 also ships a managed flow — `startLinkDeviceCodeForPhoneNumber`
# / `refreshLinkDeviceCode` / `cancelLinkDeviceCode`, plus the events
# `conn.link_code_change` and `conn.link_code_error` — whose own documentation
# describes exactly the behaviour every generation of the checkQrCode patch above
# has been hand-rolling since issue #8:
#
#   "Unlike genLinkDeviceCodeForPhoneNumber, repeated calls for the same phone
#    number reuse the active code. New codes are emitted through
#    conn.link_code_change only when WhatsApp requests a refresh or the current
#    code expires."
#
# That is the "explicit expiry/refresh signal from wa-js" this module's own
# docstring records as not existing yet (wa-js PR #3554). It exists now.
#
# The immediate reason for switching, though, is a failure seen live: on a fresh
# Chrome profile the raw call threw `Invariant Violation: Minified invariant
# #56367` with `messageParams: [""]`. An invariant is an internal assertion, not
# a server refusal — it fires when a function is reached in a state it did not
# expect. The managed entry point is what installs the listeners and state the
# linking flow needs, and calling the low-level function around it is a plausible
# way to land in exactly that state.
#
# Falls back to the raw call when the managed API is absent, so an older
# @wppconnect/wa-js keeps working, and reports which path ran so a log can say
# which one produced a given code or failure.
PATCHED_LOGIN_BY_CODE = (
    "    async loginByCode(phone) {\n"
    "        const outcome = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {\n"
    "            try {\n"
    "                const managed = typeof WPP.conn.startLinkDeviceCodeForPhoneNumber === 'function';\n"
    "                const value = managed\n"
    "                    ? await WPP.conn.startLinkDeviceCodeForPhoneNumber(phone)\n"
    "                    : JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone)));\n"
    "                return { code: String(value), managed: managed };\n"
    "            }\n"
    "            catch (error) {\n"
    "                const details = {};\n"
    "                try {\n"
    "                    for (const key of Object.getOwnPropertyNames(Object(error))) {\n"
    "                        if (key === 'stack') { continue; }\n"
    "                        const value = error[key];\n"
    "                        const kind = typeof value;\n"
    "                        if (value === null || kind === 'string' || kind === 'number' || kind === 'boolean') {\n"
    "                            details[key] = String(value);\n"
    "                        }\n"
    "                        else if (kind !== 'function') {\n"
    "                            try { details[key] = JSON.stringify(value); } catch (e) { details[key] = '[unserializable]'; }\n"
    "                        }\n"
    "                    }\n"
    "                    details.__winzappManagedApi = String(typeof WPP.conn.startLinkDeviceCodeForPhoneNumber === 'function');\n"
    "                }\n"
    "                catch (e) { }\n"
    "                return {\n"
    "                    __winzappError: {\n"
    "                        name: String(error?.name || 'Error'),\n"
    "                        message: String(error?.message || error?.reason || error?.text || error),\n"
    "                        stack: String(error?.stack || ''),\n"
    "                        details: details,\n"
    "                    },\n"
    "                };\n"
    "            }\n"
    "        }, { phone });\n"
    "        if (outcome?.__winzappError) {\n"
    "            const failure = new Error(outcome.__winzappError.message);\n"
    "            failure.name = outcome.__winzappError.name;\n"
    "            if (outcome.__winzappError.stack) {\n"
    "                failure.stack = outcome.__winzappError.stack;\n"
    "            }\n"
    "            failure.winzappDetails = outcome.__winzappError.details || {};\n"
    "            throw failure;\n"
    "        }\n"
    "        const code = outcome?.code;\n"
    "        this.log('info', `Link code obtained via the ${outcome?.managed ? 'managed' : 'legacy raw'} wa-js API.`);\n"
    "        if (this.options.logQR) {\n"
    "            this.log('info', `Waiting for Login By Code (Code: ${code})\\n`);\n"
    "        }\n"
    "        else {\n"
    "            this.log('verbose', `Waiting for Login By Code`);\n"
    "        }\n"
    "        this.catchLinkCode?.(code);\n"
    "    }\n"
)


def patch_host_layer_source(content: str):
    """Apply every host.layer.js patch to *content*, idempotently.

    Returns ``(new_content, notes, ok)``:

    * ``new_content`` — the patched source (identical to *content* when
      everything was already applied),
    * ``notes`` — one short human-readable line per patch, for the caller to
      log in whatever style it uses (setup_api.py prints, ApiSetupDialog
      logs),
    * ``ok`` — False if any patch failed to find a source text it recognises,
      i.e. the installed @wppconnect-team/wppconnect changed the file.

    Both call sites (setup_api.py for dev/CI, ApiSetupDialog for the real
    end-user install) go through this rather than each carrying their own
    copy of the migration ladder — they used to, and only one of the two got
    fixed when the patch was corrected. Same reasoning, and same shape, as
    wppconnect_sender_layer_patch.patch_sender_layer_source().
    """
    notes = []

    # checkQrCode: migrate whichever generation is installed up to v3.
    if PATCHED_CHECK_QR_CODE in content:
        notes.append("checkQrCode: already at v5.")
    elif V4_CHECK_QR_CODE in content:
        content = content.replace(V4_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: upgraded v4 -> v5 — repeated pairing-code failures "
            "now back off instead of retrying every auth-code rotation."
        )
    elif V3_CHECK_QR_CODE in content:
        content = content.replace(V3_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: upgraded v3 -> v5 — a pairing-code failure is now "
            "reported to the client, not just written to wppconnect.log."
        )
    elif V2_CHECK_QR_CODE in content:
        content = content.replace(V2_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: upgraded v2 -> v5 — a failing loginByCode() is now "
            "caught, reported and logged instead of escaping as an unhandled "
            "rejection."
        )
    elif V1_CHECK_QR_CODE in content:
        content = content.replace(V1_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append("checkQrCode: upgraded v1 (unsafe, could freeze forever) -> v5.")
    elif ORIGINAL_CHECK_QR_CODE in content:
        content = content.replace(ORIGINAL_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: patched (v5) — pairing code no longer regenerates on "
            "every QR rotation (60s reuse cooldown), failures are reported."
        )
    else:
        notes.append("checkQrCode: DID NOT MATCH any known source text — left untouched.")

    # loginByCode: real browser-side error detail instead of minified "t: t".
    if PATCHED_LOGIN_BY_CODE in content:
        notes.append("loginByCode: already on the managed wa-js linking API.")
    elif LEGACY_LOGIN_BY_CODE_RAW in content:
        content = content.replace(LEGACY_LOGIN_BY_CODE_RAW, PATCHED_LOGIN_BY_CODE, 1)
        notes.append(
            "loginByCode: switched from the raw genLinkDeviceCodeForPhoneNumber "
            "call to wa-js's managed linking lifecycle."
        )
    elif ORIGINAL_LOGIN_BY_CODE in content:
        content = content.replace(ORIGINAL_LOGIN_BY_CODE, PATCHED_LOGIN_BY_CODE, 1)
        notes.append(
            "loginByCode: patched — uses wa-js's managed linking lifecycle and "
            "reports the real browser-side error instead of the minified 't: t'."
        )
    else:
        notes.append("loginByCode: DID NOT MATCH the known source text — left untouched.")

    ok = not any("DID NOT MATCH" in note for note in notes)
    return content, notes, ok
