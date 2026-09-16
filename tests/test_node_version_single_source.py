"""One Node.js version, named in one place: client/node_download_config.py.

WPPConnect Server pins ``engines.node`` exactly and was last tested on 22.x.
The app's own download (node_download.py) followed node_download_config.py,
but the build workflows carried their own NODE_VERSION, and CI went on
bundling 24.15.0 into every release — which is what users actually run: the
app's runtime gate only ever replaces a Node *older* than the homologated one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_workflow_carries_its_own_node_version():
    offenders = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if re.search(r"NODE_VERSION\s*:|node-v\d+\.\d+\.\d+|nodejs\.org/dist/v\d", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "read the version from client/node_download_config.py instead: "
        f"{offenders}"
    )


def test_the_build_workflow_downloads_what_node_download_config_names():
    source = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    assert "client/node_download_config.py')['NODE_VERSION']" in source


def test_local_builds_read_the_same_config():
    source = (ROOT / "build.py").read_text(encoding="utf-8")
    assert '"node_download_config.py"' in source
    assert "NODE_VERSION     = _node_config.NODE_VERSION" in source


# Upstream's engines.node is compared against NODE_VERSION by
# .github/scripts/audit_wpp_upgrade.py; api_patches/package.json's own copy is
# never merged into client/api/ (see _PATCHED_DEPENDENCY_KEYS), so it is not
# asserted on here.
