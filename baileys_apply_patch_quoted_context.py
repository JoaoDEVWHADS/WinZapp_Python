"""
Patch Evolution API compiled dist files to preserve reply context (contextInfo /
quotedMessage) when a text-reply message is normalised.

Root cause:
  prepareMessage() converts extendedTextMessage replies to plain 'conversation'
  messages and calls `delete o.message.extendedTextMessage`.  The contextInfo
  that holds quotedMessage / stanzaId lives INSIDE extendedTextMessage, so it
  is silently discarded.  WinZapp then has no quoted-message data to show.

Fix:
  Before the delete, merge extendedTextMessage.contextInfo into the top-level
  o.contextInfo so the reply metadata survives.

Run this script once after every `npm run build` inside client/api/.
It is idempotent: running it again on already-patched files is a no-op.
"""

import os
import shutil
import sys

DIST_DIR = os.path.join(os.path.dirname(__file__), "client", "api", "dist")

OLD = (
    'o.message.extendedTextMessage&&'
    '(o.messageType="conversation",'
    'o.message.conversation=o.message.extendedTextMessage.text,'
    'delete o.message.extendedTextMessage)'
)

NEW = (
    'o.message.extendedTextMessage&&'
    '(o.message.extendedTextMessage.contextInfo&&'
    '(o.message.extendedTextMessage.contextInfo.quotedMessage||'
    'o.message.extendedTextMessage.contextInfo.stanzaId)&&'
    '(o.contextInfo=Object.assign({},o.contextInfo,o.message.extendedTextMessage.contextInfo)),'
    'o.messageType="conversation",'
    'o.message.conversation=o.message.extendedTextMessage.text,'
    'delete o.message.extendedTextMessage)'
)

FILES = ["main.js", "main.mjs"]


def patch_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        content = f.read()

    if NEW in content:
        return "already patched"

    if OLD not in content:
        return "pattern not found — dist may have changed, manual review needed"

    backup = path + ".quoted_patch_backup"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"  Backup -> {backup}")

    patched = content.replace(OLD, NEW, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(patched)
    return "patched"


def main():
    ok = True
    for name in FILES:
        path = os.path.join(DIST_DIR, name)
        if not os.path.exists(path):
            print(f"[SKIP] {name} not found at {path}")
            continue
        result = patch_file(path)
        icon = "OK" if result in ("patched", "already patched") else "WARN"
        print(f"[{icon}] {name}: {result}")
        if icon == "WARN":
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
