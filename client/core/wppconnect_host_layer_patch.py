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

* v2 — current fix: a 60-second reuse cooldown instead of a permanent
  latch. `linkCodeIssuedAt` is only set AFTER loginByCode() actually
  succeeds (not before), and a separate `linkCodeInFlight` flag (not a
  timestamp) guards against overlapping concurrent calls — so a rejected
  attempt simply leaves `linkCodeIssuedAt` at its old value and the very
  next `auth_code_change` tick retries, with no permanent stuck state
  either way. Upstream still has no proper fix for this (it needs an
  explicit expiry/refresh signal from wa-js that doesn't exist yet — see
  https://github.com/wppconnect-team/wa-js/pull/3554), so this is a
  WinZapp-local stopgap, not a port of an upstream patch.
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
PATCHED_CHECK_QR_CODE = (
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

PATCHED_LOGIN_BY_CODE = (
    "    async loginByCode(phone) {\n"
    "        const outcome = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ phone }) => {\n"
    "            try {\n"
    "                return { code: JSON.parse(JSON.stringify(await WPP.conn.genLinkDeviceCodeForPhoneNumber(phone))) };\n"
    "            }\n"
    "            catch (error) {\n"
    "                return {\n"
    "                    __winzappError: {\n"
    "                        name: String(error?.name || 'Error'),\n"
    "                        message: String(error?.message ?? error?.reason ?? error?.text ?? error),\n"
    "                        stack: String(error?.stack || ''),\n"
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
        notes.append("checkQrCode: already at v4.")
    elif V3_CHECK_QR_CODE in content:
        content = content.replace(V3_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: upgraded v3 -> v4 — a pairing-code failure is now "
            "reported to the client, not just written to wppconnect.log."
        )
    elif V2_CHECK_QR_CODE in content:
        content = content.replace(V2_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: upgraded v2 -> v4 — a failing loginByCode() is now "
            "caught, reported and logged instead of escaping as an unhandled "
            "rejection."
        )
    elif V1_CHECK_QR_CODE in content:
        content = content.replace(V1_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append("checkQrCode: upgraded v1 (unsafe, could freeze forever) -> v4.")
    elif ORIGINAL_CHECK_QR_CODE in content:
        content = content.replace(ORIGINAL_CHECK_QR_CODE, PATCHED_CHECK_QR_CODE, 1)
        notes.append(
            "checkQrCode: patched (v4) — pairing code no longer regenerates on "
            "every QR rotation (60s reuse cooldown), failures are reported."
        )
    else:
        notes.append("checkQrCode: DID NOT MATCH any known source text — left untouched.")

    # loginByCode: real browser-side error detail instead of minified "t: t".
    if PATCHED_LOGIN_BY_CODE in content:
        notes.append("loginByCode: error-detail patch already applied.")
    elif ORIGINAL_LOGIN_BY_CODE in content:
        content = content.replace(ORIGINAL_LOGIN_BY_CODE, PATCHED_LOGIN_BY_CODE, 1)
        notes.append(
            "loginByCode: patched — a failed pairing-code request now reports "
            "the real browser-side error instead of the minified 't: t'."
        )
    else:
        notes.append("loginByCode: DID NOT MATCH the known source text — left untouched.")

    ok = not any("DID NOT MATCH" in note for note in notes)
    return content, notes, ok
