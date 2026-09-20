"""Tests for the current filesystem/Git boundary in setup_api.py.

Older versions exposed plan_api_checkout() and directory classification helpers.
The installer now decides mode directly from client/api/.git and node_modules;
these tests cover the surviving helpers without depending on deleted APIs.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _setup_api_module():
    spec = importlib.util.spec_from_file_location(
        "winzapp_setup_api", ROOT / "setup_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_env_returns_empty_when_file_is_missing(tmp_path, monkeypatch):
    module = _setup_api_module()
    monkeypatch.setattr(module, "ROOT_DIR", str(tmp_path))
    assert module._load_env() == {}


def test_load_env_reads_nonempty_assignments(tmp_path, monkeypatch):
    module = _setup_api_module()
    (tmp_path / ".env").write_text(
        "# comment\nWPPCONNECT_TAG_VERSION=v2.10.0\nEMPTY=\nNAME=value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT_DIR", str(tmp_path))

    assert module._load_env() == {
        "WPPCONNECT_TAG_VERSION": "v2.10.0",
        "NAME": "value",
    }


def test_recover_package_json_is_a_noop_without_git(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    api.mkdir()
    package = api / "package.json"
    package.write_text('{"local": true}', encoding="utf-8")
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))

    module._recover_upstream_package_json()

    assert package.read_text(encoding="utf-8") == '{"local": true}'


def test_recover_package_json_restores_head_atomically(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    (api / ".git").mkdir(parents=True)
    package = api / "package.json"
    package.write_text('{"local": true}', encoding="utf-8")
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout=b'{"name":"upstream"}\n'
        ),
    )

    module._recover_upstream_package_json()

    assert package.read_bytes() == b'{"name":"upstream"}\n'


def test_recover_package_json_rejects_failed_git_show(tmp_path, monkeypatch):
    module = _setup_api_module()
    api = tmp_path / "api"
    (api / ".git").mkdir(parents=True)
    monkeypatch.setattr(module, "CLIENT_API_DIR", str(api))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b""),
    )

    import pytest
    with pytest.raises(RuntimeError, match="Could not read package.json"):
        module._recover_upstream_package_json()


def test_main_still_distinguishes_incremental_from_clean_install_by_git_and_modules():
    source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    assert 'already_cloned = os.path.isdir(git_dir)' in source
    assert 'has_node_modules = os.path.isdir(os.path.join(CLIENT_API_DIR, "node_modules"))' in source
    assert 'is_incremental_update = already_cloned and has_node_modules and not args.clean' in source


def test_clean_install_clones_when_client_api_is_not_a_git_checkout():
    source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    assert 'if already_cloned:' in source
    assert '_run(["git", "clone", WPPCONNECT_REPO, CLIENT_API_DIR])' in source
