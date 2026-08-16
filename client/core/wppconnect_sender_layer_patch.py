"""Shared source-text constant for patching @wppconnect-team/wppconnect's
compiled sender.layer.js — sendFile() losing the real error when a video
send fails inside the browser page.

Bug: every video sent from WinZapp (message attachment AND status) fails
with an opaque HTTP 500 whose logged "error" is just
{"name":"t","message":"t"} — useless, single-letter, minified junk. Root
cause: `WPP.chat.sendFileMessage()` throws INSIDE the Puppeteer page
context (browser side), and whatever it throws there is not a standard
`Error` instance wa-js's own minified bundle constructs cleanly — Puppeteer
serializes a thrown page-context exception across the CDP boundary via
`Runtime.evaluate`'s `exceptionDetails`, which for a non-standard thrown
value only reliably carries a `className`/`description`, not the real
message/stack. That's what "t"/"t" actually is: the minified class name of
whatever wa-js threw, with no usable text.

Fix: catch the exception INSIDE the page (where the real Error object with
its real message/stack still exists) and RETURN it as plain data instead of
letting it cross the CDP exception boundary raw — `page.evaluate()`'s
return value goes through ordinary JSON-safe structured cloning, which
preserves whatever plain string properties are pulled off the error before
returning, unlike its exception path. The Node side then reconstructs and
throws a real `Error` from that data, so messageController.ts's
returnError() (see client/api_patches/src/controller/messageController.ts)
finally has real text to report instead of "t".

This does not by itself fix WHY the browser-side sendFileMessage() call
fails for video — only what the log says about it. See that module's own
history/comments for the working theory (chrome-headless-shell's video
decode support) once a real message/stack comes back from a live
reproduction.

Both setup_api.py and ApiSetupDialog (client/ui/dialogs/api_setup.py) apply
this patch to node_modules right after every `npm install` — see
client/core/wppconnect_host_layer_patch.py's module docstring for why that
sharing matters and why this can't go through the normal api_patches/
mechanism (sender.layer.js is compiled output of a THIRD-PARTY dependency,
not WPPConnect Server's own source).
"""

ORIGINAL_SEND_FILE = (
    "        const sendResult = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ to, base64, options }) => {\n"
    "            const result = await WPP.chat.sendFileMessage(to, base64, {\n"
    "                waitForAck: true,\n"
    "                ...options,\n"
    "            });\n"
    "            return { ack: result.ack, id: result.id };\n"
    "        }, { to, base64, options: options });\n"
    "        return sendResult;\n"
)

ORIGINAL_FILE_LOADING = (
    "        let base64 = '';\n"
    "        if (pathOrBase64.startsWith('data:')) {\n"
    "            base64 = pathOrBase64;\n"
    "        }\n"
    "        else {\n"
    "            let fileContent = await (0, helpers_1.downloadFileToBase64)(pathOrBase64);\n"
    "            if (!fileContent) {\n"
    "                fileContent = await (0, helpers_1.fileToBase64)(pathOrBase64);\n"
    "            }\n"
    "            if (fileContent) {\n"
    "                base64 = fileContent;\n"
    "            }\n"
    "            if (!options.filename) {\n"
    "                options.filename = path.basename(pathOrBase64);\n"
    "            }\n"
    "        }\n"
    "        if (!base64) {\n"
    "            const error = new Error('Empty or invalid file or base64');\n"
    "            Object.assign(error, {\n"
    "                code: 'empty_file',\n"
    "            });\n"
    "            throw error;\n"
    "        }\n"
)

PATCHED_FILE_LOADING = (
    "        let base64 = '';\n"
    "        let largeFilePath = '';\n"
    "        if (!pathOrBase64.startsWith('data:') && options.type === 'document') {\n"
    "            try {\n"
    "                if (require('fs').statSync(pathOrBase64).size > 8 * 1024 * 1024)\n"
    "                    largeFilePath = pathOrBase64;\n"
    "            }\n"
    "            catch (_) { }\n"
    "        }\n"
    "        if (pathOrBase64.startsWith('data:')) {\n"
    "            base64 = pathOrBase64;\n"
    "        }\n"
    "        else if (!largeFilePath) {\n"
    "            let fileContent = await (0, helpers_1.downloadFileToBase64)(pathOrBase64);\n"
    "            if (!fileContent) {\n"
    "                fileContent = await (0, helpers_1.fileToBase64)(pathOrBase64);\n"
    "            }\n"
    "            if (fileContent) {\n"
    "                base64 = fileContent;\n"
    "            }\n"
    "        }\n"
    "        if (!options.filename && !pathOrBase64.startsWith('data:')) {\n"
    "            options.filename = path.basename(pathOrBase64);\n"
    "        }\n"
    "        if (!base64 && !largeFilePath) {\n"
    "            const error = new Error('Empty or invalid file or base64');\n"
    "            Object.assign(error, {\n"
    "                code: 'empty_file',\n"
    "            });\n"
    "            throw error;\n"
    "        }\n"
)

LEGACY_PATCHED_SEND_FILE = (
    "        const sendResult = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ to, base64, options }) => {\n"
    "            try {\n"
    "                const result = await WPP.chat.sendFileMessage(to, base64, {\n"
    "                    waitForAck: true,\n"
    "                    ...options,\n"
    "                });\n"
    "                return { ack: result.ack, id: result.id };\n"
    "            }\n"
    "            catch (e) {\n"
    "                return {\n"
    "                    __winzappSendFileError: true,\n"
    "                    message: (e && e.message) || String(e),\n"
    "                    name: (e && e.name) || 'Error',\n"
    "                    stack: e && e.stack,\n"
    "                };\n"
    "            }\n"
    "        }, { to, base64, options: options });\n"
    "        if (sendResult && sendResult.__winzappSendFileError) {\n"
    "            const err = new Error(sendResult.message);\n"
    "            err.name = sendResult.name;\n"
    "            if (sendResult.stack)\n"
    "                err.stack = sendResult.stack;\n"
    "            throw err;\n"
    "        }\n"
    "        return sendResult;\n"
)

PATCHED_SEND_FILE = (
    "        let sendResult;\n"
    "        if (largeFilePath) {\n"
    "            const transferId = `winzapp-${Date.now()}-${Math.random()}`;\n"
    "            const mime = options.mimetype || 'application/octet-stream';\n"
    "            await this.page.evaluate((id) => {\n"
    "                window.__winzappFileTransfers = window.__winzappFileTransfers || new Map();\n"
    "                window.__winzappFileTransfers.set(id, []);\n"
    "            }, transferId);\n"
    "            try {\n"
    "                const stream = require('fs').createReadStream(largeFilePath, { highWaterMark: 3 * 1024 * 1024 });\n"
    "                for await (const data of stream) {\n"
    "                    const chunk = data.toString('base64');\n"
    "                    await this.page.evaluate(({ id, chunk }) => {\n"
    "                        const binary = atob(chunk);\n"
    "                        const bytes = new Uint8Array(binary.length);\n"
    "                        for (let i = 0; i < binary.length; i++)\n"
    "                            bytes[i] = binary.charCodeAt(i);\n"
    "                        window.__winzappFileTransfers.get(id).push(bytes);\n"
    "                    }, { id: transferId, chunk });\n"
    "                }\n"
    "                sendResult = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ id, to, mime, options }) => {\n"
    "                    try {\n"
    "                        const chunks = window.__winzappFileTransfers.get(id);\n"
    "                        const file = new File(chunks, options.filename || 'file', { type: mime });\n"
    "                        const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
    "                        if (options.type === 'document' && mediaGating?.getUploadLimit) {\n"
    "                            const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
    "                            mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
    "                                ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
    "                                : getUploadLimit(type, origin, isVcard);\n"
    "                        }\n"
    "                        const result = await WPP.chat.sendFileMessage(to, file, {\n"
    "                            waitForAck: true,\n"
    "                            ...options,\n"
    "                        });\n"
    "                        return { ack: result.ack, id: result.id };\n"
    "                    }\n"
    "                    catch (e) {\n"
    "                        return {\n"
    "                            __winzappSendFileError: true,\n"
    "                            message: (e && e.message) || String(e),\n"
    "                            name: (e && e.name) || 'Error',\n"
    "                            stack: e && e.stack,\n"
    "                        };\n"
    "                    }\n"
    "                }, { id: transferId, to, mime, options: options });\n"
    "            }\n"
    "            finally {\n"
    "                await this.page.evaluate((id) => {\n"
    "                    if (window.__winzappFileTransfers)\n"
    "                        window.__winzappFileTransfers.delete(id);\n"
    "                }, transferId).catch(() => undefined);\n"
    "            }\n"
    "        }\n"
    "        else {\n"
    "            sendResult = await (0, helpers_1.evaluateAndReturn)(this.page, async ({ to, base64, options }) => {\n"
    "                try {\n"
    "                    const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
    "                    if (options.type === 'document' && mediaGating?.getUploadLimit) {\n"
    "                        const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
    "                        mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
    "                            ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
    "                            : getUploadLimit(type, origin, isVcard);\n"
    "                    }\n"
    "                    const result = await WPP.chat.sendFileMessage(to, base64, {\n"
    "                        waitForAck: true,\n"
    "                        ...options,\n"
    "                    });\n"
    "                    return { ack: result.ack, id: result.id };\n"
    "                }\n"
    "                catch (e) {\n"
    "                    return {\n"
    "                        __winzappSendFileError: true,\n"
    "                        message: (e && e.message) || String(e),\n"
    "                        name: (e && e.name) || 'Error',\n"
    "                        stack: e && e.stack,\n"
    "                    };\n"
    "                }\n"
    "            }, { to, base64, options: options });\n"
    "        }\n"
    "        if (sendResult && sendResult.__winzappSendFileError) {\n"
    "            const err = new Error(sendResult.message);\n"
    "            err.name = sendResult.name;\n"
    "            if (sendResult.stack)\n"
    "                err.stack = sendResult.stack;\n"
    "            throw err;\n"
    "        }\n"
    "        return sendResult;\n"
)

ALL_PATCHES = (
    (ORIGINAL_FILE_LOADING, PATCHED_FILE_LOADING),
    (ORIGINAL_SEND_FILE, PATCHED_SEND_FILE),
    (LEGACY_PATCHED_SEND_FILE, PATCHED_SEND_FILE),
)


_BROWSER_DOCUMENT_LIMIT_PATCH = (
    "                    const mediaGating = WPP.whatsapp?.MediaGatingUtils;\n"
    "                    if (options.type === 'document' && mediaGating?.getUploadLimit) {\n"
    "                        const getUploadLimit = mediaGating.getUploadLimit.bind(mediaGating);\n"
    "                        mediaGating.getUploadLimit = (type, origin, isVcard) => type === 'document'\n"
    "                            ? Math.max(getUploadLimit(type, origin, isVcard), 1 * 1024 * 1024 * 1024)\n"
    "                            : getUploadLimit(type, origin, isVcard);\n"
    "                    }\n"
)


def patch_sender_layer_source(source: str) -> str:
    """Apply the current patch and migrate the short-lived chunked variant."""
    for original, patched in ALL_PATCHES:
        source = source.replace(original, patched)

    if "WPP.whatsapp?.MediaGatingUtils" not in source:
        source = source.replace(
            "                    const result = await WPP.chat.sendFileMessage(to, file, {\n",
            _BROWSER_DOCUMENT_LIMIT_PATCH.replace("                    ", "                        ")
            + "                        const result = await WPP.chat.sendFileMessage(to, file, {\n",
        )
        source = source.replace(
            "                    const result = await WPP.chat.sendFileMessage(to, base64, {\n",
            _BROWSER_DOCUMENT_LIMIT_PATCH
            + "                    const result = await WPP.chat.sendFileMessage(to, base64, {\n",
        )

    intermediate_marker = "        if (base64.length > 8 * 1024 * 1024) {\n"
    if intermediate_marker not in source:
        return source

    marker_index = source.index(intermediate_marker)
    block_start = source.rfind("        let sendResult;\n", 0, marker_index)
    block_end = source.find("\n    }\n    /**", marker_index)
    if block_start < 0 or block_end < 0:
        return source
    return source[:block_start] + PATCHED_SEND_FILE + source[block_end:]
