---
paths:
  - "neonize_bridge/neonize_patches/**"
  - "neonize_bridge/neonize_upstream.json"
  - "neonize_bridge/neonize_upstream.py"
  - "neonize_bridge/build_neonize.py"
  - "neonize_bridge/prepare.py"
  - ".github/workflows/neonize-dll.yml"
---

# Neonize build

**Read `docs/reference/neonize-build.md` before changing these files.** Short form:

The bridge's neonize is official neonize at `neonize_upstream.json`'s approved release plus `neonize_patches/` (neonize, whatsmeow, meowcaller). Never hand-edit a patch or site-packages: change the checkout in `neonize_build/`, commit, `build_neonize.py export`. Generated protobuf code is never in a patch. A new upstream release goes through `check` then `approve`. A bridge handler for a WinZapp-only event registers behind `hasattr(nev, ...)`. `install` needs WinZapp closed (the bridge holds the DLL). A release tag starts with `neonize-` and never says `alpha` (the updater reads this repository's releases).
