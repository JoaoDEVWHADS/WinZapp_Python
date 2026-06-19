#!/usr/bin/env python3
"""
baileys_apply_patch_lid_resolution.py
--------------------------------------
Patches the Evolution API to resolve LID numbers (@lid) to phone numbers (@s.whatsapp.net)
in fetchProfile responses.

Usage:
    python baileys_apply_patch_lid_resolution.py           # apply patch
    python baileys_apply_patch_lid_resolution.py --revert  # restore originals
"""

import argparse
import shutil
import sys
import re
from pathlib import Path

BASE = Path(__file__).parent / "client" / "api"

# ---------------------------------------------------------------------------
# TypeScript source patch
# ---------------------------------------------------------------------------
TS_ORIGINAL_CLEAN = b"""    if (!onWhatsapp.exists) {
      throw new BadRequestException(onWhatsapp);
    }

    try {
      if (number) {
        const info = (await this.whatsappNumber({ numbers: [jid] }))?.shift();
        const picture = await this.profilePicture(info?.jid);
        const status = await this.getStatus(info?.jid);
        const business = await this.fetchBusinessProfile(info?.jid);

        return {
          wuid: info?.jid || jid,
          name: info?.name,"""

TS_ORIGINAL_V1 = b"""    if (!onWhatsapp.exists) {
      throw new BadRequestException(onWhatsapp);
    }

    let phoneJid = jid;
    if (jid.endsWith('@lid')) {
      try {
        const mapped = await this.client.signalRepository.lidMapping.getPNForLID(jid);
        if (mapped) {
          phoneJid = mapped;
        }
      } catch (err) {
        this.logger.error(`Error resolving LID mapping for ${jid}: ${err.message}`);
      }
    }

    try {
      if (number) {
        const info = (await this.whatsappNumber({ numbers: [jid] }))?.shift();
        const picture = await this.profilePicture(info?.jid);
        const status = await this.getStatus(info?.jid);
        const business = await this.fetchBusinessProfile(info?.jid);
        const contact = await this.prismaRepository.contact.findFirst({
          where: { remoteJid: jid, instanceId: this.instanceId }
        });

        return {
          jid: phoneJid,
          wuid: info?.jid || jid,
          name: contact?.pushName || info?.name || null,"""

TS_ORIGINAL_V2 = b"""    if (!onWhatsapp.exists) {
      throw new BadRequestException(onWhatsapp);
    }

    let phoneJid = jid;
    if (jid.endsWith('@lid')) {
      try {
        const mapped = await this.client.signalRepository.lidMapping.getPNForLID(jid);
        if (mapped) {
          phoneJid = mapped;
        }
      } catch (err) {
        this.logger.error(`Error resolving LID mapping for ${jid}: ${err.message}`);
      }
    }

    try {
      if (number) {
        const info = (await this.whatsappNumber({ numbers: [jid] }))?.shift();
        const picture = await this.profilePicture(info?.jid);
        const status = await this.getStatus(info?.jid);
        const business = await this.fetchBusinessProfile(info?.jid);
        const contact = await this.prismaRepository.contact.findFirst({
          where: { remoteJid: phoneJid, instanceId: this.instanceId }
        });
        let resolvedName = contact?.pushName || info?.name || null;
        if (!resolvedName) {
          try {
            const lastMsg = await this.prismaRepository.message.findFirst({
              where: {
                instanceId: this.instanceId,
                pushName: { not: null },
                OR: [
                  { key: { path: ['remoteJid'], equals: phoneJid } },
                  { key: { path: ['remoteJid'], equals: jid } }
                ]
              },
              orderBy: { messageTimestamp: 'desc' }
            });
            if (lastMsg && lastMsg.pushName) {
              resolvedName = lastMsg.pushName;
            }
          } catch (e) {
            this.logger.error(`Error fetching pushName from message history: ${e.message}`);
          }
        }

        return {
          jid: phoneJid,
          wuid: info?.jid || jid,
          name: resolvedName,"""

TS_ORIGINAL_V3 = b"""    if (!onWhatsapp.exists) {
      throw new BadRequestException(onWhatsapp);
    }

    try {
      if (number) {
        const info = (await this.whatsappNumber({ numbers: [jid] }))?.shift();
        let phoneJid = jid;
        if (jid.endsWith('@lid')) {
          try {
            const mapped = await this.client.signalRepository.lidMapping.getPNForLID(jid);
            if (mapped) {
              phoneJid = mapped;
            }
          } catch (err) {
            this.logger.error(`Error resolving LID mapping for ${jid}: ${err.message}`);
          }
        }
        const picture = await this.profilePicture(info?.jid);
        const status = await this.getStatus(info?.jid);
        const business = await this.fetchBusinessProfile(info?.jid);
        const contact = await this.prismaRepository.contact.findFirst({
          where: { remoteJid: phoneJid, instanceId: this.instanceId }
        });
        let resolvedName = contact?.pushName || info?.name || null;
        if (!resolvedName) {
          try {
            const lastMsg = await this.prismaRepository.message.findFirst({
              where: {
                instanceId: this.instanceId,
                pushName: { not: null },
                OR: [
                  { key: { path: ['remoteJid'], equals: phoneJid } },
                  { key: { path: ['remoteJid'], equals: jid } }
                ]
              },
              orderBy: { messageTimestamp: 'desc' }
            });
            if (lastMsg && lastMsg.pushName) {
              resolvedName = lastMsg.pushName;
            }
          } catch (e) {
            this.logger.error(`Error fetching pushName from message history: ${e.message}`);
          }
        }

        return {
          jid: phoneJid,
          wuid: info?.jid || jid,
          name: resolvedName,"""

TS_PATCHED = b"""    if (!onWhatsapp.exists) {
      throw new BadRequestException(onWhatsapp);
    }

    try {
      if (number) {
        const info = (await this.whatsappNumber({ numbers: [jid] }))?.shift();
        
        // 1. Fetch metadata first using the original JID (which could be a @lid).
        // This prompts the WhatsApp server to respond with metadata, populating Baileys' lidMapping cache.
        const picture = await this.profilePicture(info?.jid);
        const status = await this.getStatus(info?.jid);
        const business = await this.fetchBusinessProfile(info?.jid);

        let phoneJid = jid;
        if (jid.endsWith('@lid')) {
          try {
            // 2. Fetch the resolved phone JID from cache which has now been populated by the metadata requests.
            let mapped = await this.client.signalRepository.lidMapping.getPNForLID(jid);
            if (!mapped) {
              const res = await this.client.onWhatsApp(jid);
              if (res && res.length > 0) {
                mapped = res[0].jid;
              }
            }
            if (mapped) {
              phoneJid = mapped;
            }
          } catch (err) {
            this.logger.error(`Error resolving LID mapping for ${jid}: ${err.message}`);
          }
        }

        // 3. Search for the contact in the address book (Contact table) using either phoneJid or original jid.
        let resolvedName = null;
        const contact = await this.prismaRepository.contact.findFirst({
          where: {
            instanceId: this.instanceId,
            OR: [
              { remoteJid: phoneJid },
              { remoteJid: jid }
            ]
          }
        });
        if (contact && contact.pushName) {
          resolvedName = contact.pushName;
        }

        // 4. If not found in Contact table, check the Message history table for previous pushName records.
        if (!resolvedName || resolvedName.includes('@lid') || resolvedName === 'Voc\xc3\xaa') {
          try {
            const lastMsg = await this.prismaRepository.message.findFirst({
              where: {
                instanceId: this.instanceId,
                pushName: { not: null },
                OR: [
                  { key: { path: ['remoteJid'], equals: phoneJid } },
                  { key: { path: ['remoteJid'], equals: jid } }
                ]
              },
              orderBy: { messageTimestamp: 'desc' }
            });
            if (lastMsg && lastMsg.pushName && lastMsg.pushName !== 'Voc\xc3\xaa') {
              resolvedName = lastMsg.pushName;
            }
          } catch (e) {
            this.logger.error(`Error fetching pushName from message history: ${e.message}`);
          }
        }

        // 5. Fallback to info?.name only if no historical name could be resolved
        if (!resolvedName) {
          resolvedName = info?.name || null;
        }

        return {
          jid: phoneJid,
          wuid: info?.jid || jid,
          name: resolvedName,"""

# ---------------------------------------------------------------------------
# Regex for Compiled main.js / main.mjs
# ---------------------------------------------------------------------------
JS_REGEX = re.compile(
    r"\(await this\.whatsappNumber\(\{numbers:\[([a-zA-Z0-9_$]+)\]\}\)\)\?\.shift\(\);if\(!([a-zA-Z0-9_$]+)\.exists\)throw new ([a-zA-Z0-9_$]+)\(\2\);try\{"
)

# Return mapping replacement regex: we need to insert `jid:phoneJid,` into the returned object.
# The original compiled return is:
# return{wuid:n?.jid||o,name:n?.name,...} -> return{jid:phoneJid,wuid:n?.jid||o,name:n?.name,...}
# Let's match the return block following the try statement.
# To be robust, we'll locate `return{wuid:` and replace it with `return{jid:phoneJid,wuid:`
JS_RETURN_REGEX = re.compile(r"return\{wuid:")

BACKUP_SUFFIX = ".lid_resolution_patch_backup"


def patch_typescript_file(path: Path) -> bool:
    if not path.exists():
        print(f"[SKIP]  TypeScript source: file not found -- {path}")
        return True

    data = path.read_bytes()
    # Normalize CRLF to LF for consistent matching
    has_crlf = b"\r\n" in data
    normalized_data = data.replace(b"\r\n", b"\n")

    if TS_PATCHED in normalized_data:
        print(f"[OK]    TypeScript source: already patched ({path.name})")
        return True

    target_original = None
    if TS_ORIGINAL_CLEAN in normalized_data:
        target_original = TS_ORIGINAL_CLEAN
        print(f"  Found clean original code in {path.name}")
    elif TS_ORIGINAL_V1 in normalized_data:
        target_original = TS_ORIGINAL_V1
        print(f"  Found previous patch v1 in {path.name}")
    elif TS_ORIGINAL_V2 in normalized_data:
        target_original = TS_ORIGINAL_V2
        print(f"  Found previous patch v2 in {path.name}")
    elif TS_ORIGINAL_V3 in normalized_data:
        target_original = TS_ORIGINAL_V3
        print(f"  Found previous patch v3 in {path.name}")
    else:
        print(f"[WARN]  TypeScript source: expected patterns not found -- patch may be outdated ({path.name})")
        return False

    # Perform the replacement on normalized (LF) content
    patched_data = normalized_data.replace(target_original, TS_PATCHED, 1)

    # Convert back to CRLF if the original file had it
    if has_crlf:
        patched_data = patched_data.replace(b"\n", b"\r\n")

    # Create backup
    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  Backup created: {backup.name}")

    path.write_bytes(patched_data)
    print(f"[DONE]  TypeScript source: patched {path.name}")
    return True


def patch_compiled_file(path: Path, label: str) -> bool:
    if not path.exists():
        print(f"[SKIP]  {label}: file not found -- {path}")
        return True

    content = path.read_text(encoding="utf-8")

    # Check if already patched
    if "let phoneJid=" in content and "jid:phoneJid" in content:
        print(f"[OK]    {label}: already patched ({path.name})")
        return True

    # Search for the function header using Regex
    match = JS_REGEX.search(content)
    if not match:
        print(f"[WARN]  {label}: expected function pattern not found ({path.name})")
        return True # Don't fail the build for compiled files as we rebuilt them

    jid_var = match.group(1)
    exists_var = match.group(2)
    err_class = match.group(3)

    # Construct the patched try-block header
    patched_header = (
        f"(await this.whatsappNumber({{numbers:[{jid_var}]}}))?.shift();"
        f"if(!{exists_var}.exists)throw new {err_class}({exists_var});"
        f"let phoneJid={jid_var};"
        f"if({jid_var}.endsWith(\"@lid\")){{try{{let a=await this.client.signalRepository.lidMapping.getPNForLID({jid_var});a&&(phoneJid=a)}}catch(a){{this.logger.error(`Error resolving LID mapping for {{{jid_var}}}: ${{a.message}}`)}}}}try{{"
    )

    # Perform function header replacement
    patched_content = JS_REGEX.sub(patched_header, content, count=1)

    # Now we need to insert `jid:phoneJid,` into the returned object structure `return{wuid:`
    # We find the next return{wuid: after our patch
    patched_index = patched_content.find("let phoneJid=")
    if patched_index != -1:
        # Search and replace only after that index
        rest = patched_content[patched_index:]
        if "return{wuid:" in rest:
            rest_patched = rest.replace("return{wuid:", "return{jid:phoneJid,wuid:", 1)
            patched_content = patched_content[:patched_index] + rest_patched
        else:
            print(f"[WARN]  {label}: return pattern not found after function header ({path.name})")
            return True

    # Create backup
    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  Backup created: {backup.name}")

    path.write_text(patched_content, encoding="utf-8")
    print(f"[DONE]  {label}: patched {path.name}")
    return True


def apply_patches() -> bool:
    ts_path = BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts"
    return patch_typescript_file(ts_path)


def revert_patches() -> bool:
    ts_path = BASE / "src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts"
    backup = ts_path.with_suffix(ts_path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        print(f"[SKIP]  TypeScript source: no backup found -- {backup.name}")
        return True
    shutil.copy2(backup, ts_path)
    backup.unlink()
    print(f"[DONE]  TypeScript source: restored {ts_path.name}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--revert", action="store_true", help="Restore original files from backups"
    )
    args = parser.parse_args()

    if args.revert:
        print("Reverting LID resolution patch...")
        success = revert_patches()
    else:
        print("Applying LID resolution patch...")
        success = apply_patches()

    if not success:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
