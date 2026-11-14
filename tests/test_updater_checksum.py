"""Tests for updater.py's current SHA256 release-asset verification."""

import hashlib

import pytest

import updater


class _FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def tmp_file(tmp_path):
    path = tmp_path / "WinZapp.zip"
    path.write_bytes(b"pretend this is a WinZapp.zip release asset")
    return str(path)


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        h.update(stream.read())
    return h.hexdigest()


def test_find_sha256sums_asset_is_case_insensitive():
    assets = [
        {"name": "WinZapp.zip", "browser_download_url": "https://x/WinZapp.zip"},
        {"name": "sha256sums.TXT", "browser_download_url": "https://x/SHA256SUMS.txt"},
    ]
    assert updater._find_sha256sums_asset(assets) == "https://x/SHA256SUMS.txt"


class TestVerifySha256sums:
    """Exercises the plain checksum-only path — signing NOT configured — in
    isolation, by passing empty key lists explicitly rather than relying on
    _verify_sha256sums()'s defaults (core/release_keys.py's real committed
    keys). Signature enforcement itself is covered separately, with its own
    generated keys, by tests/test_release_signature.py; conflating the two
    is what broke here once real keys were committed — see that module's own
    docstring, and CLAUDE.md's "Release integrity" section, for why every
    build made after the keys exist enforces them unconditionally.

    The manifest fetch is patched on `updater.tls_trust`, not on `requests`.
    updater.py stopped calling `requests.get` directly when the downloads moved
    onto core/tls_trust.py (HTTPS verified against the Windows certificate
    store, so a locally intercepted connection can still reach GitHub).
    Patching `updater.requests` here would now patch nothing at all — and a
    test that quietly starts talking to the real network is worse than one that
    fails.
    """


    def test_matching_checksum_passes(self, tmp_file, monkeypatch):
        expected = _sha256_of(tmp_file)
        manifest = f"{expected}  WinZapp.zip\nsomeotherhash  WinZappInstaller.exe\n"
        monkeypatch.setattr(updater.tls_trust, "get", lambda *a, **kw: _FakeResponse(manifest))


def test_matching_checksum_passes(tmp_file, monkeypatch):
    expected = _sha256_of(tmp_file)
    manifest = f"{expected}  WinZapp.zip\n"
    monkeypatch.setattr(
        updater.requests, "get", lambda *a, **kw: _FakeResponse(manifest)
    )

    def test_mismatched_checksum_fails_closed(self, tmp_file, monkeypatch):
        manifest = "0000000000000000000000000000000000000000000000000000000000000000  WinZapp.zip\n"
        monkeypatch.setattr(updater.tls_trust, "get", lambda *a, **kw: _FakeResponse(manifest))


def test_mismatched_checksum_fails_closed(tmp_file, monkeypatch):
    manifest = f"{'0' * 64}  WinZapp.zip\n"
    monkeypatch.setattr(
        updater.requests, "get", lambda *a, **kw: _FakeResponse(manifest)
    )

    def test_missing_entry_for_filename_fails_closed(self, tmp_file, monkeypatch):
        """The manifest exists (so this ISN'T an old pre-feature release)
        but doesn't mention our filename at all — suspicious, not silently
        accepted."""
        manifest = "abc123  SomeOtherFile.zip\n"
        monkeypatch.setattr(updater.tls_trust, "get", lambda *a, **kw: _FakeResponse(manifest))

    assert ok is False
    assert "mismatch" in detail.lower()


    def test_manifest_fetch_failure_fails_closed(self, tmp_file, monkeypatch):
        def _raise(*a, **kw):
            raise Exception("network error")
        monkeypatch.setattr(updater.tls_trust, "get", _raise)

    ok, detail = updater._verify_sha256sums(
        tmp_file, "WinZapp.zip", "https://x/SHA256SUMS.txt"
    )

    assert ok is False
    assert "no checksum entry" in detail.lower()

    def test_ignores_asterisk_binary_mode_marker(self, tmp_file, monkeypatch):
        """sha256sum's own output format prefixes the filename with '*' for
        binary mode (e.g. "<hash> *WinZapp.zip") — must still match."""
        expected = _sha256_of(tmp_file)
        manifest = f"{expected} *WinZapp.zip\n"
        monkeypatch.setattr(updater.tls_trust, "get", lambda *a, **kw: _FakeResponse(manifest))

def test_manifest_fetch_failure_fails_closed(tmp_file, monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr(updater.requests, "get", fail)

    ok, detail = updater._verify_sha256sums(
        tmp_file, "WinZapp.zip", "https://x/SHA256SUMS.txt"
    )

        manifest = "abc123  SomeOtherFile.zip\n"
        monkeypatch.setattr(updater.tls_trust, "get", lambda *a, **kw: _FakeResponse(manifest))


def test_binary_mode_marker_is_accepted(tmp_file, monkeypatch):
    expected = _sha256_of(tmp_file)
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _FakeResponse(f"{expected} *WinZapp.zip\n"),
    )

    ok, detail = updater._verify_sha256sums(
        tmp_file, "WinZapp.zip", "https://x/SHA256SUMS.txt"
    )
    assert ok is True, detail


def test_comments_and_blank_lines_are_ignored(tmp_file, monkeypatch):
    expected = _sha256_of(tmp_file)
    manifest = f"\n# generated by CI\n{expected}  WinZapp.zip\n"
    monkeypatch.setattr(
        updater.requests, "get", lambda *a, **kw: _FakeResponse(manifest)
    )

    ok, detail = updater._verify_sha256sums(
        tmp_file, "WinZapp.zip", "https://x/SHA256SUMS.txt"
    )
    assert ok is True, detail
