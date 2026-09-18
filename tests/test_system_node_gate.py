"""setup_api.py refuses a system Node.js it has no evidence about.

setup_api.py prefers client/node/node.exe and silently fell back to whatever
`node` was on PATH when that folder was absent — which is every fresh
checkout, since only build.py and CI provision it. Node 26 turns that
fallback into a dead end that never names Node: puppeteer's extract-zip@2.0.1
leaves the promisified stream.pipeline of the first multi-chunk zip entry
unsettled, so the Chromium download stops two files in, throws nothing and
resolves nothing; puppeteer then finds a browser folder with no chrome.exe,
refuses to re-download, and every later run fails on that stub.

The decision is in winzapp_tools.build_env so it is reachable without running
the installer, and _gate_system_node() is the one thing in setup_api.py that
acts on it. Both are pinned here: a gate that is right and unreachable is the
same bug as no gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import setup_api  # noqa: E402
from node_download_config import NODE_VERSION  # noqa: E402
from winzapp_tools import build_env  # noqa: E402


class TestNodeMajor:
    def test_reads_the_major_of_an_ordinary_version(self):
        assert build_env.node_major("22.22.2") == 22
        assert build_env.node_major("26.7.0") == 26

    def test_tolerates_the_v_prefix_node_itself_prints(self):
        assert build_env.node_major("v22.22.2") == 22

    def test_is_none_for_anything_it_cannot_read(self):
        assert build_env.node_major("") is None
        assert build_env.node_major("   ") is None
        assert build_env.node_major("not-a-version") is None
        assert build_env.node_major(None) is None


class TestSystemNodeIsRefused:
    def test_the_homologated_major_is_accepted(self):
        assert build_env.system_node_is_refused("22.22.2", "22.22.2") is False

    def test_another_patch_of_the_same_major_is_accepted(self):
        """Compared by major, not exactly: 22.x is the verified runtime line,
        and refusing 22.20.0 would block a working setup for nothing."""
        assert build_env.system_node_is_refused("22.20.0", "22.22.2") is False
        assert build_env.system_node_is_refused("22.0.0", "22.22.2") is False

    def test_the_major_that_broke_this_is_refused(self):
        """Node 26.7.0, measured: Chromium extraction stopped after 2 of 290
        entries and the install.mjs run reported success."""
        assert build_env.system_node_is_refused("26.7.0", "22.22.2") is True

    def test_any_other_major_is_refused_in_both_directions(self):
        assert build_env.system_node_is_refused("24.15.0", "22.22.2") is True
        assert build_env.system_node_is_refused("20.11.0", "22.22.2") is True

    def test_only_an_answer_refuses(self):
        """A probe that could not speak is not a verdict. portable_node_version()
        returns "" for a missing exe AND for a --version that timed out on a
        cold machine, and a check must not be more fatal than the thing it
        stands in for — the same rule the npm health probe above it was taught
        after a 10s timeout failed a release build."""
        assert build_env.system_node_is_refused("", "22.22.2") is False
        assert build_env.system_node_is_refused("garbage", "22.22.2") is False
        assert build_env.system_node_is_refused("22.22.2", "") is False


class _Gate:
    """_gate_system_node() with its two lookups scripted.

    It resolves a bare command through shutil.which() and then asks
    portable_node_version() — neither of which may touch the real machine, or
    the test would assert on whatever Node the developer happens to have.
    """

    def __init__(self, monkeypatch, version, *, on_path=True, allow=None):
        monkeypatch.setattr(
            setup_api.shutil,
            "which",
            lambda cmd: r"C:\Program Files\nodejs\node.exe" if on_path else None,
        )
        monkeypatch.setattr(setup_api, "portable_node_version", lambda exe: version)
        monkeypatch.delenv(setup_api.ALLOW_SYSTEM_NODE_ENV, raising=False)
        if allow is not None:
            monkeypatch.setenv(setup_api.ALLOW_SYSTEM_NODE_ENV, allow)

    def run(self, node_bin="node"):
        setup_api._gate_system_node(node_bin)


class TestGateSystemNode:
    def test_a_refused_major_exits_nonzero(self, monkeypatch, capsys):
        gate = _Gate(monkeypatch, "26.7.0")
        with pytest.raises(SystemExit) as exit_info:
            gate.run()
        assert exit_info.value.code == 1
        out = capsys.readouterr().out
        assert "26.7.0" in out
        assert NODE_VERSION in out

    def test_the_refusal_names_a_way_out(self, monkeypatch, capsys):
        """A gate that only says no strands whoever hits it. It has to name
        the override, since nothing else in the output points at this file."""
        gate = _Gate(monkeypatch, "26.7.0")
        with pytest.raises(SystemExit):
            gate.run()
        assert setup_api.ALLOW_SYSTEM_NODE_ENV in capsys.readouterr().out

    def test_the_homologated_major_passes_through(self, monkeypatch):
        _Gate(monkeypatch, NODE_VERSION).run()

    def test_an_unreadable_version_warns_and_continues(self, monkeypatch, capsys):
        _Gate(monkeypatch, "").run()
        assert "WARNING" in capsys.readouterr().out

    def test_node_missing_from_path_is_not_a_verdict(self, monkeypatch, capsys):
        """`npm install` fails loudly and legibly a moment later; this gate
        must not pre-empt it with a message about versions."""
        _Gate(monkeypatch, "", on_path=False).run()
        assert "WARNING" in capsys.readouterr().out

    def test_the_override_lets_a_refused_major_through(self, monkeypatch, capsys):
        _Gate(monkeypatch, "26.7.0", allow="1").run()
        assert "WARNING" in capsys.readouterr().out

    def test_an_empty_override_is_not_set(self, monkeypatch):
        """`set WINZAPP_ALLOW_SYSTEM_NODE=` on Windows leaves an empty string
        behind, which means "unset" to the person who typed it."""
        gate = _Gate(monkeypatch, "26.7.0", allow="   ")
        with pytest.raises(SystemExit):
            gate.run()

    def test_an_absolute_node_is_not_resolved_through_path(self, monkeypatch):
        """The unhealthy-portable-npm fallback hands over an absolute path
        shutil.which() already produced; resolving it again could pick a
        different Node than the one about to be run."""
        seen = []
        monkeypatch.setattr(
            setup_api.shutil, "which", lambda cmd: seen.append(cmd) or r"C:\other\node.exe"
        )
        monkeypatch.setattr(setup_api, "portable_node_version", lambda exe: NODE_VERSION)
        monkeypatch.delenv(setup_api.ALLOW_SYSTEM_NODE_ENV, raising=False)
        setup_api._gate_system_node(r"C:\Program Files\nodejs\node.exe")
        assert seen == []


class TestGateIsWired:
    def test_both_paths_to_a_system_node_reach_the_gate(self):
        """There are two: client/node/ absent, and a portable npm that failed
        its health probe. The second sets node_bin from shutil.which() deep
        inside the first's branch, which is exactly where a later edit loses
        it — so assert the flag is cleared there rather than that the call
        exists somewhere."""
        source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
        assert "using_portable_node = True" in source
        assert "using_portable_node = False" in source
        assert "if not using_portable_node:\n            _gate_system_node(node_bin)" in source

    def test_the_gate_runs_before_npm_install(self):
        """Behind it, `npm install` alone is 300+ packages and minutes of
        network before the Chromium download the gate exists to protect."""
        source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
        assert source.index("_gate_system_node(node_bin)") < source.index(
            'print("[INFO] Running npm install...")'
        )

    def test_the_homologated_version_is_not_restated_here(self):
        """client/node_download_config.py is the single source of truth for
        the Node version (tests/test_node_version_single_source.py), and a
        gate carrying its own copy would go on refusing the right runtime the
        day that pin moves."""
        source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
        assert "from node_download_config import NODE_VERSION" in source
        assert NODE_VERSION not in source


class TestSetupApiStillRunsStandalone:
    def test_it_imports_from_a_foreign_working_directory(self, tmp_path):
        """`python setup_api.py` from anywhere has to keep working — the new
        imports reach winzapp_tools/ and client/, neither of which is on the
        path by default. Run out-of-process: an import that only works because
        pytest.ini already set pythonpath would prove nothing."""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, r'{ROOT}'); import setup_api; "
                "print(setup_api.ALLOW_SYSTEM_NODE_ENV)",
            ],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": ""},
        )
        assert completed.returncode == 0, completed.stderr
        assert "WINZAPP_ALLOW_SYSTEM_NODE" in completed.stdout
