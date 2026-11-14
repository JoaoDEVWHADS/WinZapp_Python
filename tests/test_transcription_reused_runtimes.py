"""CUDA libraries and whisper.cpp programs reused from another folder."""

import os

import pytest

import app_settings
from core.transcription import (
    cuda_runtime,
    device,
    reused_runtimes,
    whisper_cpp_backend,
    whisper_cpp_builds,
    whisper_cpp_runtime,
)

CPU, CUDA = whisper_cpp_builds.BUILD_CPU, whisper_cpp_builds.BUILD_CUDA
LIBS = tuple(name for name, _member in cuda_runtime._LIBRARY_MEMBERS)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    whisper_cpp_runtime.set_extra_root(None)
    monkeypatch.setattr(reused_runtimes, "_registered_cuda", "")
    yield
    whisper_cpp_runtime.set_extra_root(None)


def _libs(folder, names=LIBS):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"dll")
    return folder


def _probe(answer):
    calls = []

    def probe(directories):
        calls.append(tuple(directories))
        return answer

    probe.calls = calls
    return probe


class TestTheSettingNames:
    def test_the_keys_are_install_wide_and_spelled_the_same(self):
        for key in (reused_runtimes.CUDA_SETTING, reused_runtimes.WHISPER_CPP_SETTING):
            assert app_settings._DEFAULTS[key] == ""


class TestACudaFolder:
    def test_a_complete_loadable_folder_is_accepted(self, tmp_path):
        folder = _libs(tmp_path / "cuda")
        probe = _probe((True, (), None))
        check = reused_runtimes.check_cuda_folder(str(folder), probe=probe)
        assert check.code == reused_runtimes.OK
        assert check.path == os.path.normpath(str(folder))
        assert probe.calls == [(check.path,)]

    def test_a_missing_library_is_named_and_nothing_is_loaded(self, tmp_path):
        folder = _libs(tmp_path / "cuda", LIBS[:1])
        probe = _probe((True, (), None))
        check = reused_runtimes.check_cuda_folder(str(folder), probe=probe)
        assert check.code == reused_runtimes.MISSING
        assert check.missing == LIBS[1:]
        assert probe.calls == []

    def test_libraries_that_do_not_load_are_refused(self, tmp_path):
        folder = _libs(tmp_path / "cuda")
        check = reused_runtimes.check_cuda_folder(
            str(folder), probe=_probe((False, ("cublas64_12.dll",), "x")))
        assert check.code == reused_runtimes.NOT_LOADABLE

    def test_a_probe_that_cannot_answer_is_not_a_refusal(self, tmp_path):
        folder = _libs(tmp_path / "cuda")
        check = reused_runtimes.check_cuda_folder(str(folder), probe=_probe((None, (), None)))
        assert check.code == reused_runtimes.OK

    @pytest.mark.parametrize("value", ["", None, "   "])
    def test_nothing_or_a_missing_folder_is_not_a_folder(self, tmp_path, value):
        assert reused_runtimes.check_cuda_folder(value).code == reused_runtimes.NOT_A_FOLDER
        gone = str(tmp_path / "gone")
        assert reused_runtimes.check_cuda_folder(gone).code == reused_runtimes.NOT_A_FOLDER


class TestAWhisperCppRoot:
    @pytest.fixture
    def installed(self, monkeypatch):
        """Which (root, build id) pairs count as complete installs."""
        complete = set()

        def state(build, root=None):
            ok = (os.path.normpath(str(root)), build.id) in complete
            return whisper_cpp_runtime.RuntimeState(
                whisper_cpp_runtime.STATE_INSTALLED if ok else whisper_cpp_runtime.STATE_ABSENT)

        monkeypatch.setattr(whisper_cpp_runtime, "installation_state", state)
        return complete

    def test_a_root_with_builds_is_accepted_and_names_them(self, tmp_path, installed):
        root = tmp_path / "runtime"
        root.mkdir()
        installed.update({(str(root), CPU.id), (str(root), CUDA.id)})
        check = reused_runtimes.check_whisper_cpp_folder(str(root))
        assert check.code == reused_runtimes.OK
        assert check.builds == (CPU.id, CUDA.id)

    def test_the_folder_of_one_build_is_read_as_its_parent(self, tmp_path, installed):
        root = tmp_path / "runtime"
        build = root / CPU.id
        build.mkdir(parents=True)
        (build / whisper_cpp_runtime.MANIFEST_FILENAME).write_text("{}")
        installed.add((str(root), CPU.id))
        check = reused_runtimes.check_whisper_cpp_folder(str(build))
        assert (check.code, check.path, check.builds) == (
            reused_runtimes.OK, str(root), (CPU.id,))

    def test_a_folder_without_a_build_winzapp_can_vouch_for_is_refused(self, tmp_path, installed):
        folder = tmp_path / "somewhere"
        folder.mkdir()
        (folder / "whisper-cli.exe").write_bytes(b"MZ")
        assert reused_runtimes.check_whisper_cpp_folder(str(folder)).code == reused_runtimes.NO_BUILD

    def test_a_missing_folder_is_not_a_folder(self, tmp_path, installed):
        check = reused_runtimes.check_whisper_cpp_folder(str(tmp_path / "gone"))
        assert check.code == reused_runtimes.NOT_A_FOLDER

    def test_a_state_that_raises_is_not_installed(self, tmp_path, monkeypatch):
        def boom(build, root=None):
            raise OSError("denied")

        monkeypatch.setattr(whisper_cpp_runtime, "installation_state", boom)
        folder = tmp_path / "r"
        folder.mkdir()
        assert reused_runtimes.check_whisper_cpp_folder(str(folder)).code == reused_runtimes.NO_BUILD


class TestWhichRootABuildRunsFrom:
    @pytest.fixture
    def states(self, monkeypatch, tmp_path):
        own = os.path.normpath(os.path.abspath(str(tmp_path / "own")))
        monkeypatch.setattr(whisper_cpp_runtime, "default_runtime_dir", lambda: own)
        installed = set()

        def state(build, root=None):
            root = os.path.normpath(os.path.abspath(str(root or own)))
            ok = (root, build.id) in installed
            return whisper_cpp_runtime.RuntimeState(
                whisper_cpp_runtime.STATE_INSTALLED if ok else whisper_cpp_runtime.STATE_ABSENT)

        monkeypatch.setattr(whisper_cpp_runtime, "installation_state", state)
        return own, installed

    def test_nothing_installed_anywhere_is_none(self, states):
        assert whisper_cpp_runtime.usable_root(CPU) is None

    def test_winzapps_own_folder_comes_first(self, states, tmp_path):
        own, installed = states
        extra = os.path.normpath(os.path.abspath(str(tmp_path / "extra")))
        whisper_cpp_runtime.set_extra_root(extra)
        installed.update({(own, CPU.id), (extra, CPU.id)})
        assert whisper_cpp_runtime.usable_root(CPU) == own

    def test_the_reused_folder_serves_what_the_own_one_lacks(self, states, tmp_path):
        own, installed = states
        extra = os.path.normpath(os.path.abspath(str(tmp_path / "extra")))
        whisper_cpp_runtime.set_extra_root(extra)
        installed.add((extra, CUDA.id))
        assert whisper_cpp_runtime.usable_root(CUDA) == extra
        assert whisper_cpp_runtime.usable_root(CPU) is None

    def test_forgetting_it_takes_it_away(self, states, tmp_path):
        own, installed = states
        extra = os.path.normpath(os.path.abspath(str(tmp_path / "extra")))
        installed.add((extra, CPU.id))
        whisper_cpp_runtime.set_extra_root(extra)
        assert whisper_cpp_runtime.usable_root(CPU) == extra
        whisper_cpp_runtime.set_extra_root("")
        assert whisper_cpp_runtime.usable_root(CPU) is None

    def test_the_backend_launches_from_the_reused_folder(self, states, tmp_path, monkeypatch):
        own, installed = states
        extra = os.path.normpath(os.path.abspath(str(tmp_path / "extra")))
        whisper_cpp_runtime.set_extra_root(extra)
        installed.add((extra, CPU.id))
        seen = {}

        def executable(build, root=None):
            seen["executable"] = root
            return os.path.join(root, "whisper-cli.exe")

        monkeypatch.setattr(whisper_cpp_runtime, "executable_path", executable)
        monkeypatch.setattr(whisper_cpp_runtime, "verify_executable",
                            lambda build, root=None: seen.setdefault("verified", root))
        backend = whisper_cpp_backend.WhisperCppBackend()
        assert backend.is_available() is True
        assert backend._executable_for("cpu", None) == os.path.join(extra, "whisper-cli.exe")
        assert seen == {"executable": extra, "verified": extra}

    def test_a_backend_given_a_root_keeps_to_it(self, states, tmp_path):
        own, installed = states
        extra = os.path.normpath(os.path.abspath(str(tmp_path / "extra")))
        whisper_cpp_runtime.set_extra_root(extra)
        installed.add((extra, CPU.id))
        pinned = str(tmp_path / "pinned")
        assert whisper_cpp_backend.WhisperCppBackend(runtime_root=pinned).is_available() is False


class TestPuttingItIntoEffect:
    @pytest.fixture
    def registry(self, monkeypatch):
        events = []
        monkeypatch.setattr(device, "register_cuda_library_directory",
                            lambda path: events.append(("register", path)) or True)
        monkeypatch.setattr(device, "unregister_cuda_library_directory",
                            lambda path: events.append(("unregister", path)) or True)
        return events

    def test_both_folders_are_applied(self, tmp_path, registry):
        cuda = _libs(tmp_path / "cuda")
        reused_runtimes.configure(str(cuda), str(tmp_path / "wcpp"))
        assert registry == [("register", os.path.normpath(str(cuda)))]
        assert whisper_cpp_runtime.extra_root() == os.path.normpath(str(tmp_path / "wcpp"))

    def test_choosing_another_cuda_folder_drops_the_old_one(self, tmp_path, registry):
        first, second = _libs(tmp_path / "a"), _libs(tmp_path / "b")
        reused_runtimes.configure(str(first), "")
        reused_runtimes.configure(str(second), "")
        assert registry == [
            ("register", os.path.normpath(str(first))),
            ("unregister", os.path.normpath(str(first))),
            ("register", os.path.normpath(str(second))),
        ]

    def test_forgetting_the_cuda_folder_unregisters_it(self, tmp_path, registry):
        folder = _libs(tmp_path / "a")
        reused_runtimes.configure(str(folder), "")
        reused_runtimes.configure("", "")
        assert registry[-1] == ("unregister", os.path.normpath(str(folder)))

    def test_winzapps_own_folder_is_never_unregistered_as_a_reused_one(
            self, tmp_path, registry, monkeypatch):
        own = tmp_path / "own"
        monkeypatch.setattr(cuda_runtime, "default_cuda_runtime_dir", lambda: str(own))
        reused_runtimes.configure(str(own), "")
        reused_runtimes.configure("", "")
        assert registry == []

    def test_an_unreadable_settings_file_does_not_stop_startup(self):
        class _Broken:
            def get(self, key):
                raise OSError("locked")

        reused_runtimes.configure_from(_Broken())
        reused_runtimes.configure_from(None)

    def test_it_reads_the_two_install_wide_keys(self, tmp_path, registry):
        folder = _libs(tmp_path / "cuda")

        class _Store:
            def get(self, key):
                return {reused_runtimes.CUDA_SETTING: str(folder),
                        reused_runtimes.WHISPER_CPP_SETTING: str(tmp_path / "w")}[key]

        reused_runtimes.configure_from(_Store())
        assert registry == [("register", os.path.normpath(str(folder)))]
        assert whisper_cpp_runtime.extra_root() == os.path.normpath(str(tmp_path / "w"))


class TestWhatTheUserIsTold:
    def test_every_outcome_maps_to_a_key_that_exists(self):
        from tests.locales import load_strings
        table = load_strings("en-US")
        cases = [
            reused_runtimes.cuda_check_message(reused_runtimes.CudaFolderCheck(code, "x", ("a.dll",)))
            for code in (reused_runtimes.OK, reused_runtimes.MISSING,
                         reused_runtimes.NOT_LOADABLE, reused_runtimes.NOT_A_FOLDER)
        ] + [
            reused_runtimes.whisper_cpp_check_message(
                reused_runtimes.WhisperCppFolderCheck(code, "x", ("cpu", "cuda")))
            for code in (reused_runtimes.OK, reused_runtimes.NO_BUILD, reused_runtimes.NOT_A_FOLDER)
        ]
        assert len({key for key, _ in cases}) == 6
        for key, args in cases:
            assert key in table
            table[key].format(**args)

    def test_the_names_are_spelled_out(self):
        key, args = reused_runtimes.cuda_check_message(
            reused_runtimes.CudaFolderCheck(reused_runtimes.MISSING, "x", ("a.dll", "b.dll")))
        assert args == {"files": "a.dll, b.dll"}
        key, args = reused_runtimes.whisper_cpp_check_message(
            reused_runtimes.WhisperCppFolderCheck(reused_runtimes.OK, "x", ("cpu", "cuda")))
        assert args == {"builds": "cpu, cuda"}
        key, args = reused_runtimes.whisper_cpp_check_message(
            reused_runtimes.WhisperCppFolderCheck(reused_runtimes.OK, "x", ("cpu", "cuda")),
            build_name=str.upper)
        assert args == {"builds": "CPU, CUDA"}


class TestUnregisteringADirectory:
    def test_it_comes_off_the_list_and_the_answer_is_forgotten(self, tmp_path, monkeypatch):
        monkeypatch.setattr(device, "_extra_cuda_library_dirs", {})
        folder = tmp_path / "cuda"
        folder.mkdir()
        assert device.register_cuda_library_directory(str(folder)) is True
        assert os.path.abspath(str(folder)) in device.cuda_library_directories()
        assert device.unregister_cuda_library_directory(str(folder)) is True
        assert device.cuda_library_directories() == ()
        assert device.unregister_cuda_library_directory(str(folder)) is False
        assert device.unregister_cuda_library_directory("") is False
