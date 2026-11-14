"""Getting whisper-cli.exe onto the machine without trusting more than the digest.

The program is a zip from a GitHub release, downloaded the first time the user
asks for it, and three things about it are pinned here:

* **Which build a machine is offered.** The CUDA build of this release has no
  Blackwell kernels: offered to an sm_120 card it downloads 671 MB and then
  cannot run. `cuda_build_supported()` is the whole rule, and it is pure.

* **A zip is not trusted with paths.** Its digest is checked before it is
  opened, and still every member is checked for "..", absolute paths, drives
  and symlinks — and the extraction is refused, leaving nothing behind, when
  one fails. The layout inside the zip was never verified, so whisper-cli.exe
  is looked for anywhere, and a zip without it is refused clearly.

* **Installed means the manifest says so.** The tree is published by one
  rename with a manifest inside, so half an install never reads as whole, an
  earlier pin reads as outdated, and removing deletes exactly what the
  manifest names.

Synthetic zips of a few bytes stand in for the real ones, served by a fake
session. The tests that reach GitHub — the pinned URLs' sizes, and the CPU zip
downloaded, hashed and searched for whisper-cli.exe, which is also the cheapest
confirmation of its layout — are marked `network` and skipped unless
WINZAPP_RUN_NETWORK_TESTS is set.
"""

import dataclasses
import hashlib
import io
import json
import os
import re
import stat
import zipfile

import pytest
import requests

from coord_locks import LockTimeout
from core import tls_trust
from core.transcription import errors, model_store, whisper_cpp_builds as builds
from core.transcription import whisper_cpp_runtime as runtime

_NETWORK_OPT_IN_ENV = "WINZAPP_RUN_NETWORK_TESTS"

_LAYOUT = {
    "Release/whisper-cli.exe": b"MZ the program",
    "Release/whisper.dll": b"MZ whisper" * 50,
    "Release/ggml.dll": b"MZ ggml" * 80,
}


def _zip(members, symlink=None):
    """A zip holding `members` ({name: bytes}), plus an optional symlink entry."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../outside")
    return buffer.getvalue()


def _build(data, build_id="cpu", archive="whisper-bin-x64.zip"):
    return builds.RuntimeBuild(
        id=build_id,
        archive=archive,
        archive_bytes=len(data),
        archive_sha256=hashlib.sha256(data).hexdigest(),
        uses_cuda=False,
    )


class _Response:
    def __init__(self, session, url):
        self._session = session
        self._url = url
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        if self._url in self._session.failures:
            raise self._session.failures[self._url]

    def iter_content(self, chunk_size=None):
        body = self._session.bodies[self._url]
        step = max(1, len(body) // 4)
        for start in range(0, len(body), step):
            yield body[start:start + step]

    def close(self):
        pass


class _Session:
    def __init__(self, bodies, failures=None):
        self.bodies = dict(bodies)
        self.failures = dict(failures or {})
        self.requested = []

    def get(self, url, stream=False, timeout=None, headers=None):
        self.requested.append(url)
        return _Response(self, url)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def lock_dir(tmp_path, monkeypatch):
    """Keep the lock files of these tests out of the real global folder."""
    directory = tmp_path / "global"
    directory.mkdir()
    monkeypatch.setattr(model_store, "global_dir", lambda *parts: str(directory))
    return directory


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "runtime")


def _install(root, data, build=None, **kwargs):
    build = build or _build(data)
    session = kwargs.pop("session", None) or _Session({build.url: data})
    return build, runtime.install_build(build, root, session=session, **kwargs)


def _tree(directory):
    found = []
    for folder, _dirs, files in os.walk(directory):
        for name in files:
            found.append(os.path.relpath(os.path.join(folder, name), directory))
    return sorted(path.replace(os.sep, "/") for path in found)


# ── Which build is offered ───────────────────────────────────────────────────


class TestWhichBuildIsOffered:
    @pytest.mark.parametrize("capability, offered", [
        (None, False),          # NVML could not describe the card, or none
        ((3, 7), False),        # Kepler: CUDA 12 dropped it
        ((5, 0), True),
        ((7, 5), True),
        ((8, 9), True),
        ((9, 0), True),
        ((11, 9), True),
        ((12, 0), False),       # Blackwell: no kernels in this release
        ((12, 1), False),
        ((13, 0), False),
    ])
    def test_the_cuda_build_only_where_it_can_run(self, capability, offered):
        assert builds.cuda_build_supported(capability) is offered

    def test_the_cpu_build_is_always_offered(self):
        for capability in (None, (8, 6), (12, 0)):
            assert builds.builds_offered(capability)[0] is builds.BUILD_CPU
        assert builds.builds_offered((12, 0)) == (builds.BUILD_CPU,)
        assert builds.builds_offered((8, 6)) == (builds.BUILD_CPU, builds.BUILD_CUDA)

    def test_the_pins_are_whole_and_name_the_tag(self):
        for build in builds.BUILDS:
            assert re.fullmatch(r"[0-9a-f]{64}", build.archive_sha256)
            assert build.url == (
                "https://github.com/ggml-org/whisper.cpp/releases/download/"
                f"b4938/{build.archive}"
            )
        assert builds.BUILD_CPU.archive == "whisper-bin-x64.zip"
        assert builds.BUILD_CUDA.archive == "whisper-cublas-12.4.0-bin-x64.zip"
        assert builds.BUILD_CUDA.uses_cuda and not builds.BUILD_CPU.uses_cuda


# ── Zip safety, pure ─────────────────────────────────────────────────────────


class TestMemberPaths:
    @pytest.mark.parametrize("name, expected", [
        ("Release/whisper-cli.exe", "Release/whisper-cli.exe"),
        ("Release\\ggml.dll", "Release/ggml.dll"),
        ("./whisper-cli.exe", "whisper-cli.exe"),
        ("a//b.dll", "a/b.dll"),
    ])
    def test_ordinary_names_become_relative_paths(self, name, expected):
        assert builds.safe_member_path(name) == expected

    @pytest.mark.parametrize("name", [
        "", "/", "/etc/passwd", "\\Windows\\x.dll", "../x.dll", "a/../../x.dll",
        "Release/..", "C:x.dll", "C:/Windows/x.dll", "x.dll:stream", ".", "./",
    ])
    def test_anything_that_could_leave_the_folder_is_refused(self, name):
        assert builds.safe_member_path(name) is None

    @pytest.mark.parametrize("name", [
        "Release/ggml.dll.", "Release/ggml.dll ", "Release ./x.dll", "Release./x.dll",
        "NUL", "nul.dll", "Release/CON", "con.txt", "PRN", "aux.dll", "COM1",
        "com9.dll", "LPT1.txt", "Release/lpt9", "CONIN$", "conout$.txt", "COM0",
        "lpt0.dll", "COM¹", "lpt³.txt",
    ])
    def test_names_windows_would_not_create_as_written_are_refused(self, name):
        # A trailing dot or space is trimmed by Windows (two names, one file);
        # a device name is not a file at all.
        assert builds.safe_member_path(name) is None

    @pytest.mark.parametrize("name", ["console.dll", "com10.dll", "null.dll", "auxiliary.dll",
                                      "Release/.hidden"])
    def test_names_that_only_resemble_them_pass(self, name):
        assert builds.safe_member_path(name) == name


class TestLocatingTheProgram:
    def test_it_is_found_wherever_it_is(self):
        assert builds.locate_executable(["a/b/whisper-cli.exe"]) == "a/b/whisper-cli.exe"
        assert builds.locate_executable(["whisper-cli.exe"]) == "whisper-cli.exe"

    def test_the_case_of_the_name_does_not_matter(self):
        assert builds.locate_executable(["Release/Whisper-CLI.EXE"]) == "Release/Whisper-CLI.EXE"

    def test_the_shallowest_copy_wins(self):
        paths = ["x/y/whisper-cli.exe", "Release/whisper-cli.exe", "z/whisper-cli.exe"]
        assert builds.locate_executable(paths) == "Release/whisper-cli.exe"

    def test_an_old_main_exe_is_not_taken_for_it(self):
        assert builds.locate_executable(["Release/main.exe", "Release/whisper.dll"]) is None
        assert builds.locate_executable(["Release/not-whisper-cli.exe"]) is None


class TestVerifyingTheProgramBeforeLaunch:
    def test_an_untouched_program_passes(self, root):
        build, _executable = _install(root, _zip(_LAYOUT))
        runtime.verify_executable(build, root)

    def test_a_program_swapped_for_another_of_the_same_size_is_refused(self, root):
        build, executable = _install(root, _zip(_LAYOUT))
        body = _LAYOUT["Release/whisper-cli.exe"]
        with open(executable, "wb") as handle:
            handle.write(b"X" * len(body))
        # Same size, so the cheap state still says installed: that is the gap.
        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.verify_executable(build, root)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED

    def test_a_program_that_changes_after_passing_is_checked_again(self, root):
        build, executable = _install(root, _zip(_LAYOUT))
        runtime.verify_executable(build, root)
        body = _LAYOUT["Release/whisper-cli.exe"]
        with open(executable, "wb") as handle:
            handle.write(b"Y" * len(body))
        os.utime(executable, ns=(1, 1))
        with pytest.raises(errors.TranscriptionError):
            runtime.verify_executable(build, root)

    @pytest.mark.parametrize("planted", ["Release/ggml-cpu-evil.dll", "Release/EXTRA.EXE",
                                         "Release/sub/helper.dll"])
    def test_a_code_file_the_manifest_does_not_list_is_refused(self, root, planted):
        """ggml scans the program's folder for its CPU backends and Windows
        loads DLLs from there first: an unlisted one would run unseen."""
        build, _executable = _install(root, _zip(_LAYOUT))
        path = os.path.join(root, "cpu", *planted.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"MZ")
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.verify_executable(build, root)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        # Named by the file's own name only, never by the folder.
        assert root not in caught.value.detail

    def test_other_unlisted_files_are_harmless(self, root):
        build, _executable = _install(root, _zip(_LAYOUT))
        with open(os.path.join(root, "cpu", "Release", "notes.txt"), "w") as handle:
            handle.write("x")
        runtime.verify_executable(build, root)

    def test_no_manifest_is_refused(self, root):
        build, _executable = _install(root, _zip(_LAYOUT))
        os.remove(os.path.join(root, "cpu", runtime.MANIFEST_FILENAME))
        with pytest.raises(errors.TranscriptionError):
            runtime.verify_executable(build, root)

    def test_a_dll_swapped_for_another_of_the_same_size_is_refused(self, root):
        build, _executable = _install(root, _zip(_LAYOUT))
        dll = os.path.join(root, "cpu", "Release", "whisper.dll")
        with open(dll, "wb") as handle:
            handle.write(b"X" * len(_LAYOUT["Release/whisper.dll"]))
        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.verify_executable(build, root)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED

    def test_a_forged_manifest_cannot_vouch_for_a_swapped_file(self, root):
        data = _zip(_LAYOUT)
        build, executable = _install(root, data)
        pinned = dataclasses.replace(build, pinned_files=tuple(
            (name, hashlib.sha256(body).hexdigest()) for name, body in _LAYOUT.items()
        ))
        runtime.verify_executable(pinned, root)
        evil = b"E" * len(_LAYOUT["Release/whisper-cli.exe"])
        with open(executable, "wb") as handle:
            handle.write(evil)
        path = os.path.join(root, "cpu", runtime.MANIFEST_FILENAME)
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        for entry in manifest["files"]:
            if entry[0] == "Release/whisper-cli.exe":
                entry[2] = hashlib.sha256(evil).hexdigest()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        # Agrees with itself, so the build that trusts the manifest passes...
        runtime.verify_executable(build, root)
        # ...and the one holding the files to pinned digests does not.
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.verify_executable(pinned, root)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED

    def test_a_manifest_that_drops_a_pinned_file_is_refused(self, root):
        build, _executable = _install(root, _zip(_LAYOUT))
        pinned = dataclasses.replace(build, pinned_files=tuple(
            (name, hashlib.sha256(body).hexdigest()) for name, body in _LAYOUT.items()
        ))
        path = os.path.join(root, "cpu", runtime.MANIFEST_FILENAME)
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["files"] = [e for e in manifest["files"] if e[0] != "Release/ggml.dll"]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        with pytest.raises(errors.TranscriptionError):
            runtime.verify_executable(pinned, root)

    def test_a_swap_that_keeps_size_and_mtime_is_the_accepted_limit(self, root):
        # Documented, not wanted: once a file has passed, the cache keys on
        # (path, size, mtime_ns), and os.utime can restore all three.
        build, executable = _install(root, _zip(_LAYOUT))
        runtime.verify_executable(build, root)
        before = os.stat(executable)
        with open(executable, "wb") as handle:
            handle.write(b"Z" * before.st_size)
        os.utime(executable, ns=(before.st_atime_ns, before.st_mtime_ns))
        runtime.verify_executable(build, root)

    def test_the_pinned_builds_pin_the_program_and_every_dll(self):
        for build in builds.BUILDS:
            pinned = dict(build.pinned_files)
            assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in pinned.values())
            assert builds.locate_executable(list(pinned)) in pinned
            assert any(name.endswith("/whisper.dll") for name in pinned)


# ── Installing ───────────────────────────────────────────────────────────────


class TestInstalling:
    def test_the_program_is_extracted_and_found(self, root):
        data = _zip(_LAYOUT)
        build, executable = _install(root, data)

        assert executable == os.path.join(root, "cpu", "Release", "whisper-cli.exe")
        with open(executable, "rb") as handle:
            assert handle.read() == _LAYOUT["Release/whisper-cli.exe"]
        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED
        assert runtime.executable_path(build, root) == executable
        # The zip and the staging folder are scratch: nothing else is left.
        assert sorted(os.listdir(root)) == ["cpu"]
        assert _tree(os.path.join(root, "cpu")) == sorted(
            list(_LAYOUT) + [runtime.MANIFEST_FILENAME]
        )

    def test_the_manifest_records_every_file_with_size_and_digest(self, root):
        data = _zip(_LAYOUT)
        _install(root, data)
        with open(os.path.join(root, "cpu", runtime.MANIFEST_FILENAME), encoding="utf-8") as fh:
            manifest = json.load(fh)
        assert manifest["release"] == builds.RELEASE_TAG
        assert manifest["executable"] == "Release/whisper-cli.exe"
        assert sorted(manifest["files"]) == sorted(
            [name, len(body), hashlib.sha256(body).hexdigest()] for name, body in _LAYOUT.items()
        )

    def test_a_flat_zip_works_as_well(self, root):
        data = _zip({"whisper-cli.exe": b"MZ", "ggml.dll": b"MZ g"})
        _build_, executable = _install(root, data)
        assert executable == os.path.join(root, "cpu", "whisper-cli.exe")

    def test_progress_is_one_bar_that_only_moves_forward(self, root):
        data = _zip(_LAYOUT)
        seen = []
        _install(root, data, progress=lambda done, total: seen.append((done, total)))
        totals = {total for _done, total in seen}
        assert totals == {2 * len(data)}
        dones = [done for done, _total in seen]
        assert dones == sorted(dones)
        assert seen[-1] == (2 * len(data), 2 * len(data))

    def test_an_installed_build_is_not_downloaded_again(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        session = _Session({build.url: data})
        runtime.install_build(build, root, session=session)
        assert session.requested == []

    def test_a_wrong_digest_is_refused_and_leaves_nothing(self, root):
        data = _zip(_LAYOUT)
        build = _build(data)
        tampered = data[:-1] + bytes([data[-1] ^ 1])
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, tampered, build=build)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        assert not os.path.exists(root)

    @pytest.mark.parametrize("bad", ["../evil.dll", "/abs.dll", "C:/x.dll", "Release/x.dll:ads"])
    def test_a_member_that_escapes_is_refused_before_anything_is_written(self, root, bad):
        data = _zip(dict(_LAYOUT, **{bad: b"evil"}))
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        assert not os.path.exists(root)
        assert not os.path.exists(os.path.join(os.path.dirname(root), "evil.dll"))

    def test_a_symlink_member_is_refused(self, root):
        data = _zip(_LAYOUT, symlink="Release/link.dll")
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        assert not os.path.exists(root)

    def test_a_zip_without_the_program_is_refused_clearly(self, root):
        data = _zip({"Release/main.exe": b"MZ", "Release/ggml.dll": b"MZ"})
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        assert "whisper-cli.exe" in caught.value.detail
        assert not os.path.exists(root)

    def test_a_dropped_connection_is_a_download_failure(self, root):
        data = _zip(_LAYOUT)
        build = _build(data)
        session = _Session({build.url: data},
                           failures={build.url: requests.ConnectionError("reset")})
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.install_build(build, root, session=session)
        assert caught.value.code == errors.WHISPER_CPP_DOWNLOAD_FAILED

    def test_cancelling_leaves_nothing_behind(self, root):
        data = _zip(_LAYOUT)
        reports = []
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data, progress=lambda done, total: reports.append(done),
                     should_cancel=lambda: len(reports) >= 2)
        assert caught.value.code == errors.CANCELLED
        assert not os.path.exists(root)

    def test_no_room_is_said_before_the_first_byte(self, root, monkeypatch):
        data = _zip(_LAYOUT)
        build = _build(data)
        monkeypatch.setattr(model_store, "free_bytes", lambda _path: 0)
        session = _Session({build.url: data})
        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.install_build(build, root, session=session)
        assert caught.value.code == errors.NO_DISK_SPACE
        assert session.requested == []

    def test_the_cuda_build_is_refused_where_it_cannot_run(self, root):
        data = _zip(_LAYOUT)
        build = builds.RuntimeBuild("cuda-12.4", "whisper-cublas-12.4.0-bin-x64.zip",
                                     len(data), hashlib.sha256(data).hexdigest(), True)
        for capability in (None, (12, 0), (12, 1), (3, 7)):
            session = _Session({build.url: data})
            with pytest.raises(errors.TranscriptionError) as caught:
                runtime.install_build(build, root, session=session,
                                      compute_capability=capability)
            assert caught.value.code == errors.CUDA_UNAVAILABLE
            # Refused before a byte: 671 MB is the cost being protected.
            assert session.requested == []
        with pytest.raises(errors.TranscriptionError):
            runtime.repair_build(build, root, session=_Session({build.url: data}))
        executable = runtime.install_build(build, root, session=_Session({build.url: data}),
                                           compute_capability=(8, 6))
        assert os.path.isfile(executable)

    def test_a_file_held_open_is_retried_then_said_to_be_busy_not_a_download(
        self, root, monkeypatch
    ):
        data = _zip(_LAYOUT)
        build = _build(data)
        real_replace = os.replace
        attempts = []

        def _held(source, target):
            if os.path.basename(source).startswith("cpu-"):
                attempts.append(source)
                raise PermissionError(13, "Access is denied")
            return real_replace(source, target)

        monkeypatch.setattr(runtime.os, "replace", _held)
        monkeypatch.setattr(runtime.time, "sleep", lambda _s: None)
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data, build=build)
        assert caught.value.code == errors.WHISPER_CPP_BUSY
        assert len(attempts) == runtime._REPLACE_ATTEMPTS
        assert not os.path.exists(os.path.join(root, build.archive))

    def test_a_hold_that_lets_go_in_time_costs_nothing(self, root, monkeypatch):
        data = _zip(_LAYOUT)
        real_replace = os.replace
        refusals = [PermissionError(13, "Access is denied")] * 2

        def _briefly_held(source, target):
            if os.path.basename(source).startswith("cpu-") and refusals:
                raise refusals.pop()
            return real_replace(source, target)

        monkeypatch.setattr(runtime.os, "replace", _briefly_held)
        monkeypatch.setattr(runtime.time, "sleep", lambda _s: None)
        _build_, executable = _install(root, data)
        assert os.path.isfile(executable)

    def test_an_access_error_anywhere_is_busy_not_a_failed_download(self):
        failure = runtime._as_runtime_error(PermissionError(13, "denied"), builds.BUILD_CPU)
        assert failure.code == errors.WHISPER_CPP_BUSY
        failure = runtime._as_runtime_error(OSError(1, "not permitted"), builds.BUILD_CPU)
        assert failure.code == errors.WHISPER_CPP_BUSY

    def test_another_window_holding_the_folder_is_busy(self, root, monkeypatch):
        class _Busy:
            def acquire(self):
                raise LockTimeout("held elsewhere")

            def release(self):  # pragma: no cover - never acquired
                raise AssertionError

        monkeypatch.setattr(model_store, "_LOCK_TIMEOUT_SECONDS", 0.0)
        monkeypatch.setattr(model_store, "models_lock", lambda *a, **kw: _Busy())
        data = _zip(_LAYOUT)
        with pytest.raises(errors.TranscriptionError) as caught:
            _install(root, data)
        assert caught.value.code == errors.WHISPER_CPP_BUSY


# ── What is on disk ──────────────────────────────────────────────────────────


class TestInstalledState:
    def test_nothing_there_is_absent(self, root):
        build = _build(b"x")
        assert runtime.installation_state(build, root).state == runtime.STATE_ABSENT
        assert runtime.executable_path(build, root) is None

    def test_a_missing_file_is_incomplete_and_an_install_repairs_it(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        os.remove(os.path.join(root, "cpu", "Release", "ggml.dll"))

        state = runtime.installation_state(build, root)
        assert state.state == runtime.STATE_INCOMPLETE
        assert state.missing == ("Release/ggml.dll",)
        assert runtime.executable_path(build, root) is None

        _install(root, data, build=build)
        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED

    def test_an_earlier_release_reads_as_outdated_and_is_replaced(self, root):
        old = _zip({"bin/whisper-cli.exe": b"MZ old", "bin/old.dll": b"MZ"})
        build_old, _executable = _install(root, old)
        manifest_path = os.path.join(root, "cpu", runtime.MANIFEST_FILENAME)
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["release"] = "b1000"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        new = _zip(_LAYOUT)
        build = _build(new)
        state = runtime.installation_state(build, root)
        assert state.state == runtime.STATE_INCOMPLETE
        assert state.installed_release == "b1000"

        _install(root, new, build=build)
        assert _tree(os.path.join(root, "cpu")) == sorted(
            list(_LAYOUT) + [runtime.MANIFEST_FILENAME]
        )

    def test_a_stray_file_in_the_build_folder_never_blocks_an_install(self, root):
        # The scenario: install, a file nobody's manifest names,
        # remove (which leaves it), then install and repair must still work.
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        with open(os.path.join(root, "cpu", "stray.txt"), "w") as handle:
            handle.write("left by something else")
        runtime.remove_build(build, root)
        assert os.listdir(os.path.join(root, "cpu")) == ["stray.txt"]

        _install(root, data, build=build)
        runtime.repair_build(build, root, session=_Session({build.url: data}))

        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED
        assert _tree(os.path.join(root, "cpu")) == sorted(
            list(_LAYOUT) + [runtime.MANIFEST_FILENAME]
        )
        # The folder renamed aside is gone too.
        assert sorted(os.listdir(root)) == ["cpu"]

    def test_an_aside_folder_that_could_not_go_is_swept_next_time(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        leftover = os.path.join(root, "cpu.old-1", "Release")
        os.makedirs(leftover)
        with open(os.path.join(leftover, "ggml.dll"), "wb") as handle:
            handle.write(b"was held open last time")
        runtime.remove_build(build, root)
        assert not os.path.exists(os.path.join(root, "cpu.old-1"))

    def test_only_an_aside_folder_of_ours_can_be_deleted_recursively(self, root, tmp_path):
        os.makedirs(root)
        for path in (str(tmp_path), os.path.join(root, "cpu"), os.path.join(root, "x.old-1"),
                     os.path.join(root, "cpu.old-1", "inner")):
            with pytest.raises(ValueError):
                runtime._discard_aside(root, builds.BUILD_CPU, path)

    def test_a_root_spelled_with_a_trailing_separator_still_clears_its_aside_folder(self, root):
        os.makedirs(os.path.join(root, "cpu.old-1", "inner"))
        spelled = runtime._resolve(root + os.sep)
        runtime._discard_aside(spelled, builds.BUILD_CPU, os.path.join(spelled, "cpu.old-1"))
        assert not os.path.exists(os.path.join(root, "cpu.old-1"))

    def test_a_manifest_naming_a_path_outside_is_not_believed(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        manifest_path = os.path.join(root, "cpu", runtime.MANIFEST_FILENAME)
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["files"].append(["../../elsewhere.txt", 1, "0" * 64])
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        assert runtime.installation_state(build, root).state == runtime.STATE_INCOMPLETE


class TestVerifyRepairRemove:
    def test_same_size_wrong_bytes_is_caught_by_verify_and_cured_by_repair(self, root):
        data = _zip(_LAYOUT)
        build, executable = _install(root, data)
        with open(executable, "wb") as handle:
            handle.write(b"X" * len(_LAYOUT["Release/whisper-cli.exe"]))
        assert runtime.installation_state(build, root).state == runtime.STATE_INSTALLED

        with pytest.raises(errors.TranscriptionError) as caught:
            runtime.verify_build(build, root)
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED

        runtime.repair_build(build, root, session=_Session({build.url: data}))
        runtime.verify_build(build, root)

    def test_remove_deletes_what_the_manifest_names_and_nothing_else(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        stranger = os.path.join(root, "cpu", "Release", "notes.txt")
        with open(stranger, "w") as handle:
            handle.write("not ours")

        assert runtime.remove_build(build, root) == ()

        assert _tree(os.path.join(root, "cpu")) == ["Release/notes.txt"]
        assert runtime.installation_state(build, root).state != runtime.STATE_INSTALLED

    def test_removing_everything_leaves_no_folder_of_ours(self, root):
        data = _zip(_LAYOUT)
        build, _executable = _install(root, data)
        runtime.remove_build(build, root)
        assert not os.path.exists(os.path.join(root, "cpu"))
        assert runtime.installation_state(build, root).state == runtime.STATE_ABSENT


# ── The tests that reach GitHub ──────────────────────────────────────────────


class TestThePinnedBinariesAreStillThere:
    """The pinned release still serves exactly the pinned zips.

    Skipped unless asked for — run it by hand whenever the pin changes. The CPU
    zip is small enough (8 MB) to fetch whole, which also answers the question
    nothing else here can: whether whisper-cli.exe is in it, and where.
    """

    pytestmark = [
        pytest.mark.network,
        pytest.mark.skipif(
            os.environ.get(_NETWORK_OPT_IN_ENV, "").strip() in ("", "0", "false", "False"),
            reason=f"reaches github.com - set {_NETWORK_OPT_IN_ENV}=1 to run it",
        ),
    ]

    @pytest.mark.parametrize("build", builds.BUILDS, ids=[b.id for b in builds.BUILDS])
    def test_the_url_serves_exactly_the_pinned_size(self, build):
        with tls_trust.create_session() as session:
            response = session.head(
                build.url, allow_redirects=True, timeout=30,
                headers={"Accept-Encoding": "identity"},
            )
        assert response.status_code == 200, f"{build.url} answered {response.status_code}"
        reported = response.headers.get("Content-Length")
        assert reported is not None, f"{build.url} reported no size at all"
        assert int(reported) == build.archive_bytes

    def test_the_cpu_zip_hashes_to_its_pin_and_holds_the_program(self):
        with tls_trust.create_session() as session:
            response = session.get(builds.BUILD_CPU.url, timeout=120)
            response.raise_for_status()
            data = response.content
        assert hashlib.sha256(data).hexdigest() == builds.BUILD_CPU.archive_sha256
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
        relative = [builds.safe_member_path(name) for name in names]
        assert None not in relative, names
        assert builds.locate_executable(relative) is not None, names
