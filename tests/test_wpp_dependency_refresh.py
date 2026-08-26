"""Regression tests for WPPConnect dependency refresh policy."""

import json
from pathlib import Path
import subprocess

import setup_api

from core.wpp_dependency_setup import (
    PATCHED_DEPENDENCY_KEYS,
    merge_dependency_patches,
    reset_dependency_state,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_merge_preserves_upstream_wppconnect_dependencies(tmp_path):
    api_dir = tmp_path / "api"
    patches_dir = tmp_path / "patches"
    api_dir.mkdir()
    patches_dir.mkdir()
    _write_json(
        api_dir / "package.json",
        {
            "version": "2.10.1",
            "dependencies": {
                "@wppconnect-team/wppconnect": "^2.3.1",
                "@wppconnect/wa-js": "^4.6.0",
                "express": "4.22.2",
            },
        },
    )
    _write_json(
        patches_dir / "package.json",
        {
            "version": "old",
            "dependencies": {
                "@ffmpeg-installer/ffmpeg": "^1.1.0",
                "prom-client": "^14.2.0",
                "zod": "^4.3.6",
                "@wppconnect-team/wppconnect": "git+https://example.invalid/repo.git",
            },
        },
    )

    assert merge_dependency_patches(str(api_dir), str(patches_dir)) == 3

    merged = json.loads((api_dir / "package.json").read_text(encoding="utf-8"))
    assert merged["version"] == "2.10.1"
    assert merged["dependencies"]["@wppconnect-team/wppconnect"] == "^2.3.1"
    assert merged["dependencies"]["@wppconnect/wa-js"] == "^4.6.0"
    assert merged["dependencies"]["express"] == "4.22.2"
    assert set(PATCHED_DEPENDENCY_KEYS) <= set(merged["dependencies"])


def test_reset_removes_generated_locks_and_modules(tmp_path):
    api_dir = tmp_path / "api"
    modules_dir = api_dir / "node_modules" / "package"
    modules_dir.mkdir(parents=True)
    (modules_dir / "index.js").write_text("", encoding="utf-8")
    for name in ("yarn.lock", "package-lock.json", "npm-shrinkwrap.json"):
        (api_dir / name).write_text("stale", encoding="utf-8")
    (api_dir / "package.json").write_text("{}", encoding="utf-8")

    removed = reset_dependency_state(str(api_dir))

    assert set(removed) == {
        "yarn.lock",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "node_modules",
    }
    assert (api_dir / "package.json").is_file()
    assert not (api_dir / "node_modules").exists()


def test_tracked_patch_manifest_does_not_override_wppconnect():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "client/api_patches/package.json").read_text(encoding="utf-8")
    )
    forbidden = {
        "@wppconnect-team/wppconnect",
        "@wppconnect-team/wa-js",
        "@wppconnect-team/wa-version",
        "@wppconnect/wa-js",
        "@wppconnect/wa-version",
    }

    assert forbidden.isdisjoint(manifest.get("dependencies", {}))
    assert forbidden.isdisjoint(manifest.get("devDependencies", {}))
    assert set(PATCHED_DEPENDENCY_KEYS) <= set(manifest.get("dependencies", {}))
    assert "packageManager" not in manifest
    assert "resolutions" not in manifest



def test_recover_restores_package_from_checked_out_revision(tmp_path, monkeypatch):
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=api_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=api_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=api_dir, check=True)
    original = {
        "version": "2.10.1",
        "dependencies": {"@wppconnect-team/wppconnect": "^2.2.7"},
    }
    _write_json(api_dir / "package.json", original)
    subprocess.run(["git", "add", "package.json"], cwd=api_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=api_dir, check=True)
    _write_json(
        api_dir / "package.json",
        {"dependencies": {"@wppconnect-team/wa-js": "git+https://example.invalid"}},
    )
    monkeypatch.setattr(setup_api, "CLIENT_API_DIR", str(api_dir))

    setup_api._recover_upstream_package_json()

    recovered = json.loads((api_dir / "package.json").read_text(encoding="utf-8"))
    assert recovered == original
