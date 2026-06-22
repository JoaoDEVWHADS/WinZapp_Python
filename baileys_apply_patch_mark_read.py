#!/usr/bin/env python3
"""
baileys_apply_patch_mark_read.py
---------------------------------
Patches the Evolution API to properly sync "mark as read" across all of the
user's devices (phone, tablet, other linked devices).

Background
----------
The default Evolution API `markMessageAsRead` endpoint calls Baileys
`readMessages()`, which only sends individual read receipts to message senders.
This is insufficient for multi-device sync: WhatsApp requires a separate
`chatModify({ markRead: true })` app-state patch so the phone and other linked
devices update their unread counts.

This patch modifies the `markMessageAsRead` handler in the Evolution API to
ALSO call `chatModify({ markRead: true })` after `readMessages()`.  The
chatModify call is best-effort: if it fails (e.g. the last message has no
participant for a group), it is silently ignored so the API response is
unaffected.

The patch also forwards the optional `participant` field from the WinZapp
client so that group-message receipts are properly attributed.

Files patched
-------------
- client/api/src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts
  (TypeScript source -- for future npm run build)
- client/api/dist/main.js   (compiled CJS bundle)
- client/api/dist/main.mjs  (compiled ESM bundle)

Usage
-----
    python baileys_apply_patch_mark_read.py           # apply patch
    python baileys_apply_patch_mark_read.py --revert  # restore originals
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).parent / "client" / "api"

# ---------------------------------------------------------------------------
# TypeScript source patch (original -> patched)
# ---------------------------------------------------------------------------
TS_ORIGINAL = b"""\
  public async markMessageAsRead(data: ReadMessageDto) {
    try {
      const keys: proto.IMessageKey[] = [];
      data.readMessages.forEach((read) => {
        if (!isJidBroadcast(read.remoteJid) && !isJidNewsletter(read.remoteJid)) {
          keys.push({ remoteJid: read.remoteJid, fromMe: read.fromMe, id: read.id });
        }
      });
      await this.client.readMessages(keys);
      return { message: 'Read messages', read: 'success' };
    } catch (error) {
      throw new InternalServerErrorException('Read messages fail', error.toString());
    }
  }"""

TS_PATCHED = b"""\
  public async markMessageAsRead(data: ReadMessageDto) {
    try {
      const keys: proto.IMessageKey[] = [];
      (data.readMessages as any[]).forEach((read) => {
        if (!isJidBroadcast(read.remoteJid) && !isJidNewsletter(read.remoteJid)) {
          const key: proto.IMessageKey = { remoteJid: read.remoteJid, fromMe: read.fromMe, id: read.id };
          if (read.participant) {
            key.participant = read.participant;
          }
          keys.push(key);
        }
      });
      await this.client.readMessages(keys);

      // Sync read state across own devices via chatModify (multi-device protocol).
      // readMessages alone only sends receipts to senders; chatModify is needed
      // so the phone and other linked devices update their unread counts.
      const jids = [...new Set(keys.map((k) => k.remoteJid).filter(Boolean))] as string[];
      await Promise.allSettled(
        jids.map(async (jid) => {
          try {
            const lastMsg = await this.getLastMessage(jid);
            await this.client.chatModify({ markRead: true, lastMessages: [lastMsg] }, jid);
          } catch (_) {
            // non-fatal: chatModify failure must not break the API response
          }
        }),
      );

      return { message: 'Read messages', read: 'success' };
    } catch (error) {
      throw new InternalServerErrorException('Read messages fail', error.toString());
    }
  }"""

# ---------------------------------------------------------------------------
# Compiled main.js patch (original -> patched)
# ---------------------------------------------------------------------------
JS_ORIGINAL = (
    b"markMessageAsRead(e){try{let t=[];return e.readMessages.forEach(o=>{"
    b"!(0,_.isJidBroadcast)(o.remoteJid)&&!(0,_.isJidNewsletter)(o.remoteJid)"
    b"&&t.push({remoteJid:o.remoteJid,fromMe:o.fromMe,id:o.id})})"
    b",await this.client.readMessages(t),"
    b'{message:"Read messages",read:"success"}}catch(t){'
    b'throw new L("Read messages fail",t.toString())}}'
)

JS_PATCHED = (
    b"markMessageAsRead(e){try{let t=[];e.readMessages.forEach(o=>{"
    b"if(!(0,_.isJidBroadcast)(o.remoteJid)&&!(0,_.isJidNewsletter)(o.remoteJid)){"
    b"let r={remoteJid:o.remoteJid,fromMe:o.fromMe,id:o.id};"
    b"o.participant&&(r.participant=o.participant),t.push(r)}});"
    b"await this.client.readMessages(t);"
    b"const n=[...new Set(t.map(r=>r.remoteJid).filter(Boolean))];"
    b"await Promise.allSettled(n.map(async r=>{"
    b"try{const a=await this.getLastMessage(r);"
    b"await this.client.chatModify({markRead:!0,lastMessages:[a]},r)}catch(a){}}));"
    b'return{message:"Read messages",read:"success"}}catch(t){'
    b'throw new L("Read messages fail",t.toString())}}'
)

# ---------------------------------------------------------------------------
# Compiled main.mjs patch (original -> patched)
# ---------------------------------------------------------------------------
MJS_ORIGINAL = (
    b"markMessageAsRead(e){try{let t=[];return e.readMessages.forEach(o=>{"
    b"!Hc(o.remoteJid)&&!zt(o.remoteJid)"
    b"&&t.push({remoteJid:o.remoteJid,fromMe:o.fromMe,id:o.id})})"
    b",await this.client.readMessages(t),"
    b'{message:"Read messages",read:"success"}}catch(t){'
    b'throw new B("Read messages fail",t.toString())}}'
)

MJS_PATCHED = (
    b"markMessageAsRead(e){try{let t=[];e.readMessages.forEach(o=>{"
    b"if(!Hc(o.remoteJid)&&!zt(o.remoteJid)){"
    b"let r={remoteJid:o.remoteJid,fromMe:o.fromMe,id:o.id};"
    b"o.participant&&(r.participant=o.participant),t.push(r)}});"
    b"await this.client.readMessages(t);"
    b"const n=[...new Set(t.map(r=>r.remoteJid).filter(Boolean))];"
    b"await Promise.allSettled(n.map(async r=>{"
    b"try{const a=await this.getLastMessage(r);"
    b"await this.client.chatModify({markRead:!0,lastMessages:[a]},r)}catch(a){}}));"
    b'return{message:"Read messages",read:"success"}}catch(t){'
    b'throw new B("Read messages fail",t.toString())}}'
)

BACKUP_SUFFIX = ".mark_read_patch_backup"

PATCHES = [
    (
        BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts",
        TS_ORIGINAL,
        TS_PATCHED,
        "TypeScript source",
    ),
    (
        BASE / "dist/main.js",
        JS_ORIGINAL,
        JS_PATCHED,
        "compiled main.js",
    ),
    (
        BASE / "dist/main.mjs",
        MJS_ORIGINAL,
        MJS_PATCHED,
        "compiled main.mjs",
    ),
]


def apply_patches() -> bool:
    ok = True
    for path, original, patched, label in PATCHES:
        if not path.exists():
            print(f"[SKIP]  {label}: file not found -- {path}")
            continue

        data = path.read_bytes()

        if patched in data:
            print(f"[OK]    {label}: already patched ({path.name})")
            continue

        if original not in data:
            print(
                f"[WARN]  {label}: expected pattern not found -- patch may be "
                f"outdated or file has changed ({path.name})"
            )
            ok = False
            continue

        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        shutil.copy2(path, backup)
        path.write_bytes(data.replace(original, patched, 1))
        print(f"[DONE]  {label}: patched {path.name}  (backup -> {backup.name})")

    return ok


def revert_patches() -> bool:
    ok = True
    for path, _original, _patched, label in PATCHES:
        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        if not backup.exists():
            print(f"[SKIP]  {label}: no backup found -- {backup.name}")
            continue
        shutil.copy2(backup, path)
        backup.unlink()
        print(f"[DONE]  {label}: restored {path.name}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--revert", action="store_true", help="Restore original files from backups"
    )
    args = parser.parse_args()

    if args.revert:
        print("Reverting mark-as-read patch...")
        success = revert_patches()
    else:
        print("Applying mark-as-read patch (adds chatModify for multi-device sync)...")
        success = apply_patches()

    if not success:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
