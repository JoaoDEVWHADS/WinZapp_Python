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

PATCHED_SEND_FILE = (
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

ALL_PATCHES = ((ORIGINAL_SEND_FILE, PATCHED_SEND_FILE),)
