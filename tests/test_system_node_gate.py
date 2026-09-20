"""Tests for Node-version decisions shared by WinZapp build tooling.

setup_api.py no longer exposes the old _gate_system_node/portable npm helper
API.  The reusable version rules live in winzapp_tools.build_env, so the suite
tests that real current boundary directly.
"""

from types import SimpleNamespace

from winzapp_tools import build_env


def test_node_major_reads_normal_and_v_prefixed_versions():
    assert build_env.node_major("22.22.2") == 22
    assert build_env.node_major("v26.7.0") == 26


def test_node_major_returns_none_for_unreadable_values():
    assert build_env.node_major("") is None
    assert build_env.node_major("not-a-version") is None
    assert build_env.node_major(None) is None


def test_system_node_accepts_the_homologated_major():
    assert build_env.system_node_is_refused("22.22.2", "22.22.2") is False
    assert build_env.system_node_is_refused("22.0.0", "22.22.2") is False


def test_system_node_refuses_a_different_known_major():
    assert build_env.system_node_is_refused("26.7.0", "22.22.2") is True
    assert build_env.system_node_is_refused("20.11.0", "22.22.2") is True


def test_unknown_node_version_is_not_a_refusal():
    assert build_env.system_node_is_refused("", "22.22.2") is False
    assert build_env.system_node_is_refused("garbage", "22.22.2") is False
    assert build_env.system_node_is_refused("22.22.2", "") is False


def test_portable_node_build_pin_requires_an_exact_version_match():
    assert build_env.portable_node_needs_replacing("22.22.2", "22.22.2") is False
    assert build_env.portable_node_needs_replacing("22.22.1", "22.22.2") is True
    assert build_env.portable_node_needs_replacing("24.0.0", "22.22.2") is True


def test_portable_node_version_strips_v_prefix(tmp_path):
    node = tmp_path / "node.exe"
    node.write_bytes(b"")

    def run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="v22.22.2\n")

    assert build_env.portable_node_version(str(node), run=run) == "22.22.2"


def test_portable_node_version_fails_open_when_probe_errors(tmp_path):
    node = tmp_path / "node.exe"
    node.write_bytes(b"")

    def run(*args, **kwargs):
        raise OSError("cannot execute")

    assert build_env.portable_node_version(str(node), run=run) == ""


def test_missing_portable_node_has_no_version(tmp_path):
    assert build_env.portable_node_version(str(tmp_path / "missing.exe")) == ""
