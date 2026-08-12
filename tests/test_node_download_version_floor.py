"""Regression guard for the portable Node.js version node_download.py
downloads when client/node/node.exe is missing.

Node 18.20.4 (this module's value until 2026-08-13) let `npm install`
succeed but broke `sharp` at runtime the moment something used it (sending/
receiving a WhatsApp sticker): sharp dropped Node 18 support going from
0.34.5 (wppconnect-server 2.10.1) to 0.35.x (wppconnect-server 2.10.4, whose
`sharp` now declares `engines.node: ">=20.9.0"`), and this dialog is the
only Node source for any user whose install predates Node being bundled by
the installer. Confirmed live: `npm install` exits 0 either way (npm's
engine check only warns), but `require('sharp')` throws
"Could not load the sharp module using the win32-x64 runtime" under Node 18.
"""

from packaging.version import Version

from ui.dialogs.node_download import _NODE_VERSION

# The real floor sharp>=0.35 imposes — see the module-level comment next to
# _NODE_VERSION in node_download.py for how this was confirmed.
_SHARP_MINIMUM_NODE = Version("20.9.0")


class TestNodeDownloadVersionFloor:
    def test_pinned_version_clears_sharps_minimum(self):
        assert Version(_NODE_VERSION) >= _SHARP_MINIMUM_NODE
