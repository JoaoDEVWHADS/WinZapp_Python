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
