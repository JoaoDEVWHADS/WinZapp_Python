"""Fetching the CUDA library CTranslate2 opens by name, and proving it works.

Part 4a made "the GPU is counted but cuBLAS is nowhere on this machine" a
measured veto with a reason of its own. This is the other half — the download
that answers it — and the failures it has to survive are all failures the user
cannot see:

* **The wheel is pinned, whole.** URL, byte count and sha256 describe one
  published artifact, and the 12.9 series is not a taste: Blackwell (sm_120),
  the card the issue was reported from, needs cuBLAS kernels from 12.8 or
  newer. A URL that followed "the latest" would change the bytes under a digest
  that no longer describes them, and the only symptom would be the same silent
  fall back to the processor. The first class here fails if anyone loosens it.

* **1.3 GB has to be gated before the first byte.** The wheel and everything
  unpacked out of it are on disk at the same moment, so the gate counts the
  sum. Finding out afterwards means a full disk and a half-written install.

* **Nothing may be believed that was not checked.** The wheel is verified while
  the bytes go past; each extracted library is verified against the wheel's own
  RECORD; and no file appears under its final name before that. A cancelled or
  failed install leaves neither a `.part` nor a published file, because half a
  gigabyte of scratch in the shared global folder is invisible to the user and
  nothing else would ever collect it.

* **"It downloaded" is not the answer.** What comes back is
  `device.probe_cuda_libraries()`'s own verdict, measured after the directory is
  registered with the loader — a DLL that is present and will not load is
  exactly the state part 4a already vetoes the GPU for.

* **An install from last week has to be registered at startup**, or the user
  who paid for the download is silently back on the processor with nothing
  anywhere mentioning it.

The network is never touched: a synthetic wheel is built in the test and served
by a fake session. The one test that does reach PyPI — the safety net for "the
pinned link is still there" — is marked `network` and skipped unless
WINZAPP_RUN_NETWORK_TESTS is set.
"""

import base64
import errno
import hashlib
import io
import os
import zipfile

from tests.locales import load_strings, registered_locale_codes
import pytest

import app_paths
from coord_locks import LockTimeout
from core import tls_trust
from core.transcription import cuda_runtime, device, errors

_NETWORK_OPT_IN_ENV = "WINZAPP_RUN_NETWORK_TESTS"


LOCALES = registered_locale_codes()

# What the probe says on a machine that has not got the libraries yet.
_MISSING = (False, ("cublas64_12.dll",), "could not load cublas64_12.dll")
_LOADABLE = (True, (), None)


# ── A synthetic wheel ────────────────────────────────────────────────────────


def _record_digest(data):
    """A file's digest in RECORD's own spelling: sha256=<urlsafe b64, unpadded>."""
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
    return "sha256=" + encoded.rstrip(b"=").decode("ascii")


class _Wheel:
    """A few kilobytes shaped exactly like the 553 MB one.

    The member names are read off the module's own pins rather than restated,
    so this follows a repin instead of quietly testing the previous one; the
    pins themselves are checked literally, once, in TestThePinnedWheel.

    Deliberately carries files nothing installs — a Fortran BLAS shim, a
    package `__init__`, the license — because "extract only what is loaded" is
    a property that cannot be observed in an archive holding only what is
    loaded.
    """

    def __init__(self, contents=None, record_lines=None):
        self.libraries = {
            name: data
            for (name, _member), data in zip(
                cuda_runtime._LIBRARY_MEMBERS,
                # Different lengths and different bytes, so a swapped pair or a
                # digest checked against the wrong entry cannot pass.
                (b"A" * 2_000_003, b"B" * 1_500_007),
                # strict: a third library added to the pin has to fail here
                # rather than be quietly left out of every test in the file.
                strict=True,
            )
        }
        self.members = {
            member: self.libraries[name]
            for name, member in cuda_runtime._LIBRARY_MEMBERS
        }
        self.members["nvidia/cublas/bin/nvblas64_12.dll"] = b"N" * 4096
        self.members["nvidia/cublas/__init__.py"] = b"# nothing\n"
        # Under the pinned dist-info, because that prefix is how an install
        # left by a *previous* pin is recognised on disk.
        self.members[cuda_runtime._DIST_INFO_PREFIX + "METADATA"] = b"Name: cublas\n"
        self.members[cuda_runtime._DIST_INFO_PREFIX + "LICENSE"] = b"license text\n"
        if contents is not None:
            self.members.update(contents)

        lines = record_lines
        if lines is None:
            lines = [
                f"{member},{_record_digest(data)},{len(data)}"
                for member, data in self.members.items()
            ]
            # A RECORD never lists a digest for itself, which is why the
            # wheel's own sha256 is what makes it trustworthy.
            lines.append(f"{cuda_runtime._RECORD_MEMBER},,")
        self.record = ("\n".join(lines) + "\n").encode("utf-8")
        self.members[cuda_runtime._RECORD_MEMBER] = self.record

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, data in self.members.items():
                archive.writestr(member, data)
        self.bytes = buffer.getvalue()

    @property
    def extracted_bytes(self):
        return sum(len(data) for data in self.libraries.values())


def _pin(monkeypatch, wheel):
    """Point the module's pins at the synthetic wheel instead of the real one.

    Every one of these is a constant the real code reads at run time, so the
    download, the digest check and the space gate all measure the same object
    the fake session is serving.
    """
    monkeypatch.setattr(cuda_runtime, "WHEEL_BYTES", len(wheel.bytes))
    monkeypatch.setattr(
        cuda_runtime, "WHEEL_SHA256", hashlib.sha256(wheel.bytes).hexdigest()
    )
    monkeypatch.setattr(cuda_runtime, "EXTRACTED_BYTES", wheel.extracted_bytes)
    monkeypatch.setattr(
        cuda_runtime, "INSTALL_BYTES", len(wheel.bytes) + wheel.extracted_bytes
    )


@pytest.fixture
def wheel():
    return _Wheel()


@pytest.fixture(autouse=True)
def _no_memoized_cuda_answer_between_tests(monkeypatch):
    """device.py's memoized probe answer is module state.

    This file's whole point is that installing and removing move it, so a test
    that leaves one behind would decide the next one — and, on a machine that
    really has cuBLAS, would leak into every other file in the suite.
    """
    monkeypatch.setattr(device, "_cuda_library_answer", None)
    monkeypatch.setattr(device, "_cuda_library_generation", 0)


# ── The fake network ─────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, session, body):
        self._session = session
        self._body = body
        self.status_code = 200
        self.headers = {}
        self.closed = False

    def raise_for_status(self):
        if self._session.failure is not None:
            raise self._session.failure

    def iter_content(self, chunk_size=None):
        self._session.chunk_sizes.append(chunk_size)
        # A fixed number of slices rather than the real 1 MB chunk: the
        # synthetic wheel is kilobytes, so honouring the chunk size would make
        # the whole transfer one piece and never exercise cancelling between
        # them. The size actually asked for is pinned separately.
        step = max(1, -(-len(self._body) // self._session.slices))
        for start in range(0, len(self._body), step):
            yield self._body[start:start + step]

    def close(self):
        self.closed = True


class _FakeSession:
    """The slice of requests.Session this module uses, answering from bytes.

    Records every request so a test can assert what was *not* fetched — which
    is how "already installed" and "the space gate runs before the first byte"
    are checked.
    """

    def __init__(self, body, failure=None, slices=4):
        self.body = body
        self.failure = failure
        self.slices = slices
        self.requested = []
        self.streamed = []
        self.timeouts = []
        self.chunk_sizes = []
        self.responses = []
        self.closed = False

    def get(self, url, stream=False, timeout=None):
        self.requested.append(url)
        self.streamed.append(stream)
        self.timeouts.append(timeout)
        response = _FakeResponse(self, self.body)
        self.responses.append(response)
        return response

    def close(self):
        self.closed = True


class _CancelAfter:
    """Cancels once `limit` aggregate bytes have been reported.

    Counting reported bytes rather than callback invocations makes "cancel
    while the libraries are being extracted" a fixed point of the test instead
    of a guess about how many chunks the fake produced.
    """

    def __init__(self, limit):
        self.limit = limit
        self.done = 0
        self.reports = []

    def progress(self, done, total):
        self.done = done
        self.reports.append((done, total))

    def __call__(self):
        return self.done >= self.limit


# ── The loader, recorded instead of performed ────────────────────────────────


class _FakeLoader:
    """device's two side-effecting halves.

    Both are patched in every install test on purpose: the real
    `register_cuda_library_directory()` puts a temporary directory on this
    process's DLL search path for the rest of the session, and the real probe
    maps ~600 MB of cuBLAS on a machine that may or may not have it — neither
    of which is a question about this module.

    `forget_cuda_library_answer()` is deliberately **not** among them: it only
    touches device.py's memo, it is what keeps a removed library from being
    remembered as loadable, and a fake would make the tests that pin that agree
    with a stand-in instead of with the module.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.registered = []
        self.probed = 0

    def register(self, path):
        self.registered.append(path)
        return True

    def probe(self, directories=None):
        self.probed += 1
        return self.answers[min(self.probed - 1, len(self.answers) - 1)]


def _loader(monkeypatch, answers=(_MISSING,)):
    loader = _FakeLoader(answers)
    monkeypatch.setattr(device, "register_cuda_library_directory", loader.register)
    monkeypatch.setattr(device, "probe_cuda_libraries", loader.probe)
    return loader


class _RecordingLock:
    """Stands in for coord_locks.models_lock and records when it is held."""

    def __init__(self, events, key):
        self.events = events
        self.key = key

    def acquire(self):
        self.events.append(("acquire", self.key))

    def release(self):
        self.events.append(("release", self.key))


def _recording_locks(monkeypatch):
    events = []
    monkeypatch.setattr(
        cuda_runtime,
        "models_lock",
        lambda key, lock_dir, timeout=None: _RecordingLock(events, key),
    )
    return events


class _AlwaysBusyLock:
    """A lock another process never lets go of."""

    def __init__(self, key):
        self.key = key

    def acquire(self):
        raise LockTimeout(f"held by another process: {self.key}")

    def release(self):  # pragma: no cover - never acquired
        raise AssertionError("released a lock that was never acquired")


def _busy_locks(monkeypatch):
    """Make the lock unavailable, and stop waiting immediately.

    The real deadline is twelve hours — a backstop against a lock nobody will
    release, not a policy — so a test that waited for it would be a test nobody
    ever finishes.
    """
    monkeypatch.setattr(cuda_runtime, "_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        cuda_runtime,
        "models_lock",
        lambda key, lock_dir, timeout=None: _AlwaysBusyLock(key),
    )


def _install(directory, wheel, monkeypatch, loader=None, session=None, **kwargs):
    """Run a full install against the synthetic wheel, with nothing real."""
    _pin(monkeypatch, wheel)
    _recording_locks(monkeypatch)
    if loader is None:
        _loader(monkeypatch)
    session = _FakeSession(wheel.bytes) if session is None else session
    return cuda_runtime.install_cuda_runtime(
        str(directory), session=session, **kwargs
    )


def _names_in(directory):
    return sorted(os.listdir(directory))


def _write_manifest_of_another_pin(directory):
    """Rewrite the installed RECORD as the previous pin would have left it.

    Same libraries, same sizes, same digests — only the dist-info it names is
    another version's, which is the one signal on disk that says which wheel
    this directory came out of.
    """
    path = os.path.join(str(directory), "RECORD")
    with io.open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace(
        cuda_runtime._DIST_INFO_PREFIX, "nvidia_cublas_cu12-11.0.0.0.dist-info/"
    )
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# ── The pins ─────────────────────────────────────────────────────────────────


class TestThePinnedWheel:
    """One published artifact, named four ways, and all four must agree.

    Restated literally rather than derived from the module, which is the whole
    point: this fails the moment somebody replaces the pin with "the latest
    release", which is the change that would silently install bytes no digest
    here describes.
    """

    def test_the_version_is_the_series_blackwell_needs(self):
        # cuBLAS kernels for sm_120 exist from 12.8; the reporter's own card is
        # sm_120, so an older series installs cleanly and still cannot run.
        assert cuda_runtime.WHEEL_VERSION == "12.9.2.10"
        assert tuple(int(part) for part in cuda_runtime.WHEEL_VERSION.split(".")[:2]) >= (12, 8)

    def test_the_url_size_and_digest_describe_one_file(self):
        assert cuda_runtime.WHEEL_URL == (
            "https://files.pythonhosted.org/packages/20/e2/"
            "fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
            "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl"
        )
        assert cuda_runtime.WHEEL_BYTES == 553_162_896
        assert cuda_runtime.WHEEL_SHA256 == (
            "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"
        )

    def test_the_url_ends_in_the_pinned_file_name(self):
        assert cuda_runtime.WHEEL_URL.endswith(cuda_runtime.WHEEL_FILENAME)
        assert cuda_runtime.WHEEL_VERSION in cuda_runtime.WHEEL_FILENAME
        assert cuda_runtime.WHEEL_FILENAME.endswith("win_amd64.whl")

    def test_the_manifest_inside_the_wheel_moves_with_the_pin(self):
        assert cuda_runtime._RECORD_MEMBER == (
            "nvidia_cublas_cu12-12.9.2.10.dist-info/RECORD"
        )
        assert cuda_runtime.WHEEL_VERSION in cuda_runtime._RECORD_MEMBER

    def test_only_the_libraries_that_are_actually_loaded_are_installed(self):
        """cuBLAS is opened by name; cuBLASLt is in its import table.

        nvblas64_12.dll is a Fortran BLAS shim nothing here calls, and cuDNN is
        not in this wheel at all — nor needed, which part 4a measured twice.
        """
        assert cuda_runtime.INSTALLED_FILES == (
            "cublas64_12.dll", "cublasLt64_12.dll", "RECORD",
        )
        members = [member for _name, member in cuda_runtime._LIBRARY_MEMBERS]
        assert members == [
            "nvidia/cublas/bin/cublas64_12.dll",
            "nvidia/cublas/bin/cublasLt64_12.dll",
        ]
        assert not any("nvblas" in member or "cudnn" in member for member in members)

    def test_every_library_the_device_module_vetoes_the_gpu_over_is_installed(self):
        """The two modules' lists have to stay one list.

        device._CUDA_RUNTIME_LIBRARIES is what decides the GPU is unusable; a
        name there that this module does not install is a veto with no way out,
        which is precisely the state part 4b exists to end.
        """
        installed = {name for name, _member in cuda_runtime._LIBRARY_MEMBERS}
        assert set(device._CUDA_RUNTIME_LIBRARIES) <= installed

    def test_the_space_gate_counts_the_wheel_and_what_comes_out_of_it(self):
        """Both are on disk at the same instant, so the peak is the sum."""
        assert cuda_runtime.INSTALL_BYTES == (
            cuda_runtime.WHEEL_BYTES + cuda_runtime.EXTRACTED_BYTES
        )
        # Measured at 772.2 MB unpacked; the gate must not be counting the
        # compressed size twice or the libraries not at all.
        assert cuda_runtime.EXTRACTED_BYTES > cuda_runtime.WHEEL_BYTES

    def test_the_libraries_live_install_wide_not_per_account(self):
        """770 MB downloaded once per account is not a cost anyone accepts."""
        assert cuda_runtime.default_cuda_runtime_dir() == app_paths.global_dir(
            cuda_runtime.CUDA_RUNTIME_DIRNAME
        )
        assert not cuda_runtime.default_cuda_runtime_dir().startswith(
            app_paths.accounts_root()
        )


# ── Installing ───────────────────────────────────────────────────────────────


class TestInstalling:
    def test_it_extracts_only_the_libraries_it_needs(self, tmp_path, wheel, monkeypatch):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        assert _names_in(str(directory)) == [
            "RECORD", "cublas64_12.dll", "cublasLt64_12.dll",
        ]
        for name, data in wheel.libraries.items():
            with open(os.path.join(str(directory), name), "rb") as handle:
                assert handle.read() == data

    def test_the_wheel_is_deleted_once_the_libraries_are_out_of_it(
        self, tmp_path, wheel, monkeypatch
    ):
        """Half a gigabyte of scratch nobody can see is not an end state."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        leftovers = [name for name in _names_in(str(directory)) if ".whl" in name]
        assert leftovers == []

    def test_nothing_is_ever_published_before_it_is_verified(
        self, tmp_path, wheel, monkeypatch
    ):
        """Every write lands under `.part` first, so a crash cannot leave a
        file the cheap install check would believe."""
        directory = tmp_path / "cuda"
        seen = []

        real_replace = os.replace

        def _watch(source, target):
            seen.append((os.path.basename(source), os.path.basename(target)))
            return real_replace(source, target)

        monkeypatch.setattr(cuda_runtime.os, "replace", _watch)
        _install(directory, wheel, monkeypatch)

        assert seen == [
            ("cublas64_12.dll.part", "cublas64_12.dll"),
            ("cublasLt64_12.dll.part", "cublasLt64_12.dll"),
            # The manifest last: it is the commit, and without it the install
            # reads as incomplete rather than as complete-and-wrong.
            ("RECORD.part", "RECORD"),
        ]

    def test_the_transfer_is_streamed_rather_than_read_whole(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        session = _FakeSession(wheel.bytes)
        _install(directory, wheel, monkeypatch, session=session)

        assert session.streamed == [True]
        assert session.chunk_sizes == [cuda_runtime._CHUNK_BYTES]
        assert session.timeouts == [cuda_runtime._HTTP_TIMEOUT]
        assert session.requested == [cuda_runtime.WHEEL_URL]
        assert session.responses[0].closed is True

    def test_progress_is_one_bar_over_the_download_and_the_extraction(
        self, tmp_path, wheel, monkeypatch
    ):
        """One wait for the user, so one bar — and it ends at the total.

        The pinned extracted size is a measurement rounded up, so the reports
        must be clamped: a bar that overshoots its own total is what a
        percentage read aloud turns into "one hundred and four percent".
        """
        directory = tmp_path / "cuda"
        watcher = _CancelAfter(limit=10 ** 12)
        _install(directory, wheel, monkeypatch, progress=watcher.progress)

        total = cuda_runtime.INSTALL_BYTES
        assert watcher.reports[0] == (0, total)
        assert all(reported == total for _done, reported in watcher.reports)
        assert all(0 <= done <= total for done, _total in watcher.reports)
        # The download half is reported before the extraction half starts.
        assert any(done >= cuda_runtime.WHEEL_BYTES for done, _t in watcher.reports)
        assert watcher.reports[-1] == (total, total)

    def test_the_directory_is_held_against_the_other_accounts(
        self, tmp_path, wheel, monkeypatch
    ):
        """Two account processes asking at once would write each other's
        `.part` files. Keyed on this directory, so it never contends with a
        model download."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        events = _recording_locks(monkeypatch)
        _loader(monkeypatch)

        cuda_runtime.install_cuda_runtime(
            str(directory), session=_FakeSession(wheel.bytes)
        )

        assert events == [("acquire", str(directory)), ("release", str(directory))]

    def test_another_window_busy_with_it_is_its_own_error(
        self, tmp_path, wheel, monkeypatch
    ):
        """Not MODELS_BUSY: a user who clicked "download the CUDA libraries"
        and is told another window is busy with the *models* has been sent to
        look at the wrong thing."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _loader(monkeypatch)
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_BUSY

    def test_the_session_goes_through_the_system_trust_store(
        self, tmp_path, wheel, monkeypatch
    ):
        """A machine whose HTTPS is intercepted locally (an antivirus is
        enough) downloads nothing at all through a bare requests session."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        made = []

        def _create_session():
            session = _FakeSession(wheel.bytes)
            made.append(session)
            return session

        monkeypatch.setattr(tls_trust, "create_session", _create_session)
        cuda_runtime.install_cuda_runtime(str(directory))

        assert len(made) == 1
        assert made[0].closed is True


class TestNotSpendingTheDownload:
    def test_libraries_that_already_load_are_not_downloaded_again(
        self, tmp_path, wheel, monkeypatch
    ):
        """Covers both an install from an earlier session and a machine with
        the CUDA Toolkit installed system-wide — in either case the answer is
        already yes, and 553 MB would buy nothing."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_LOADABLE,))
        session = _FakeSession(wheel.bytes)

        answer = cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert answer == _LOADABLE
        assert session.requested == []

    def test_an_install_this_module_already_made_is_registered_first(
        self, tmp_path, wheel, monkeypatch
    ):
        """The directory is on no search path when the process starts, so the
        probe has to be asked *after* it is registered or a completed install
        reads as missing and is fetched all over again."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        loader = _loader(monkeypatch, answers=(_LOADABLE,))
        session = _FakeSession(wheel.bytes)
        cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert loader.registered == [str(directory)]
        assert session.requested == []


class TestTheAnswerIsTheProbe:
    def test_a_finished_download_that_still_will_not_load_says_so(
        self, tmp_path, wheel, monkeypatch
    ):
        """"I downloaded it" is not an answer a caller can use.

        A library that is present and will not load is exactly the state part
        4a vetoes the GPU for, so reporting success on the bytes would put the
        user back where they started with a cheerier message.
        """
        directory = tmp_path / "cuda"
        loader = _loader(monkeypatch, answers=(_MISSING,))
        answer = _install(directory, wheel, monkeypatch, loader=loader)

        assert answer == _MISSING
        # The bytes did land: this is the probe's verdict, not a failed install.
        assert cuda_runtime.is_installed(str(directory)) is True

    def test_a_successful_install_answers_with_the_probe_too(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        loader = _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        answer = _install(directory, wheel, monkeypatch, loader=loader)

        assert answer == _LOADABLE
        # Registered once, after the download: the first attempt had nothing in
        # the directory to register, and an empty folder of ours has no
        # business on the process's DLL search path.
        assert loader.registered == [str(directory)]
        # Probed twice — once to find out whether the download was needed at
        # all, once to answer with. The second is a real measurement because
        # registering invalidates device.py's memo.
        assert loader.probed == 2


class TestTheSpaceGate:
    def test_not_enough_room_is_refused_before_the_first_byte(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        monkeypatch.setattr(
            cuda_runtime.model_store, "free_bytes", lambda _path: 1024
        )
        session = _FakeSession(wheel.bytes)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert caught.value.code == errors.NO_DISK_SPACE
        assert session.requested == []
        assert not os.path.exists(str(directory))

    def test_the_gate_is_measured_against_the_wheel_plus_the_unpacked_size(
        self, tmp_path, wheel, monkeypatch
    ):
        """Room for the download alone is not room for the install: the wheel
        is still on disk while the libraries come out of it."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        asked = []
        monkeypatch.setattr(
            cuda_runtime.model_store,
            "ensure_free_space",
            lambda root, needed: asked.append((root, needed)),
        )

        cuda_runtime.install_cuda_runtime(
            str(directory), session=_FakeSession(wheel.bytes)
        )

        assert asked == [
            (str(directory), len(wheel.bytes) + wheel.extracted_bytes)
        ]

    def test_a_volume_filling_up_mid_transfer_is_still_a_space_problem(
        self, tmp_path, wheel, monkeypatch
    ):
        """The gate ran before the transfer, but 1.3 GB takes long enough for
        something else on the machine to fill the volume meanwhile."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)

        real_open = io.open

        def _full_disk(path, *args, **kwargs):
            if str(path).endswith(".part"):
                raise OSError(28, "No space left on device")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _full_disk)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.NO_DISK_SPACE


class TestVerifiedOnTheWayIn:
    def test_a_wheel_that_hashes_differently_is_refused(
        self, tmp_path, wheel, monkeypatch
    ):
        """A digest checked after the fact would already have unpacked
        whatever arrived."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        monkeypatch.setattr(cuda_runtime, "WHEEL_SHA256", "00" * 32)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED
        assert not os.path.exists(str(directory))

    def test_a_wheel_of_the_wrong_length_is_refused(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        monkeypatch.setattr(cuda_runtime, "WHEEL_BYTES", len(wheel.bytes) + 1)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED

    def test_a_library_that_disagrees_with_the_record_is_refused(
        self, tmp_path, monkeypatch
    ):
        """The whole-wheel digest covers RECORD; RECORD covers each file.

        A zip whose central directory and whose manifest disagree is the case
        the second half exists for — without it, the wheel's own digest would
        have signed off on a library nobody checked.
        """
        wheel = _Wheel()
        tampered = dict(wheel.members)
        member = cuda_runtime._LIBRARY_MEMBERS[1][1]
        tampered[member] = tampered[member] + b"tail"
        # Rebuild with the original RECORD lines, so the manifest still
        # describes the file as it was before the tail was added.
        broken = _Wheel(
            contents=tampered,
            record_lines=wheel.record.decode("utf-8").splitlines(),
        )

        directory = tmp_path / "cuda"
        _pin(monkeypatch, broken)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(broken.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED
        assert not os.path.exists(str(directory))

    def test_a_manifest_that_does_not_describe_the_libraries_is_refused(
        self, tmp_path, monkeypatch
    ):
        """A repinned wheel whose layout moved: better a loud failure than two
        DLLs installed with nothing able to check them again."""
        wheel = _Wheel(record_lines=["nvidia/cublas/bin/nvblas64_12.dll,sha256=x,1"])
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED


class TestNothingIsWrittenOutsideTheDirectory:
    def test_a_member_that_climbs_out_of_the_archive_is_never_extracted(
        self, tmp_path, monkeypatch
    ):
        """Zip slip, pinned rather than left to construction.

        Today only two named members are ever read, so a `../evil.dll` in the
        wheel cannot land anywhere — but "extract everything RECORD lists"
        would be a natural-looking simplification, and it would reintroduce the
        whole class with no test failing. The manifest names the traversal
        member too, so a RECORD-driven extraction really would follow it.
        """
        wheel = _Wheel(contents={"../evil.dll": b"pwned"})
        assert "../evil.dll" in zipfile.ZipFile(io.BytesIO(wheel.bytes)).namelist()

        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        assert _names_in(str(directory)) == [
            "RECORD", "cublas64_12.dll", "cublasLt64_12.dll",
        ]
        assert _names_in(str(tmp_path)) == ["cuda"]


class TestRepairing:
    """The state the "already loads" shortcut must not answer for.

    An install can be complete, absent, or half there — and the third one is
    reachable without anything exotic: a removal that could not unlink the
    mapped DLLs but did unlink the manifest, a crash between the second library
    and the manifest, or a repin, where the previous version's libraries load
    perfectly well and are the wrong ones. The probe says True in every one of
    those, so a shortcut on the probe alone makes the repair button do nothing.
    """

    def test_a_lost_manifest_is_repaired_rather_than_declared_fine(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        os.remove(os.path.join(str(directory), "RECORD"))

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        # The libraries themselves are still there and still load.
        _loader(monkeypatch, answers=(_LOADABLE,))
        session = _FakeSession(wheel.bytes)

        cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert session.requested == [cuda_runtime.WHEEL_URL]
        assert cuda_runtime.is_installed(str(directory)) is True

    def test_an_install_left_by_another_pin_is_replaced(
        self, tmp_path, wheel, monkeypatch
    ):
        """The pin exists because sm_120 needs cuBLAS 12.8 or newer.

        Nothing else in the feature checks the version, so if the shortcut
        answered on the probe alone the mechanism that guarantees the right one
        would be the single thing an already-installed user never crosses.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)

        assert cuda_runtime.is_installed(str(directory)) is False

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_LOADABLE,))
        session = _FakeSession(wheel.bytes)

        cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert session.requested == [cuda_runtime.WHEEL_URL]
        assert cuda_runtime.is_installed(str(directory)) is True

    def test_a_complete_install_still_takes_the_shortcut(
        self, tmp_path, wheel, monkeypatch
    ):
        """The two legitimate cases have to survive the repair condition: our
        own complete install, and a machine with the CUDA Toolkit (nothing of
        ours on disk at all)."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_LOADABLE,))
        session = _FakeSession(wheel.bytes)

        cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert session.requested == []


class TestRepairingTheOneStateInstallingCannotReach:
    """Right sizes, wrong bytes — and every check but the hash agrees.

    A DLL that a disk fault or another installer overwrote in place keeps its
    exact size, so `installation_state()` — cheap on purpose, names and sizes
    only — calls the directory INSTALLED. The install's own "is it already
    here?" gate then fetches nothing, while the probe answers False because the
    library will not load, so `install_cuda_runtime()` reports that the GPU
    still does not work having downloaded not one byte.
    `verify_installation()` can name that state and cannot undo it. This is the
    way out, and it is the same shape `model_store.repair_model()` has, for the
    same reason.
    """

    def _corrupt_in_place(self, directory):
        """Overwrite the start of a library, keeping its length exactly."""
        path = os.path.join(str(directory), "cublas64_12.dll")
        before = os.path.getsize(path)
        with open(path, "r+b") as handle:
            handle.write(b"Z" * 64)
        assert os.path.getsize(path) == before
        return path

    def test_installing_alone_cannot_get_out_of_it(
        self, tmp_path, wheel, monkeypatch
    ):
        """The dead end, pinned first, so the repair below is measured against
        it rather than against an assumption about it."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        self._corrupt_in_place(directory)

        assert cuda_runtime.is_installed(str(directory)) is True

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING,))
        session = _FakeSession(wheel.bytes)

        answer = cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert session.requested == []
        assert answer[0] is False

    def test_repairing_downloads_it_again(self, tmp_path, wheel, monkeypatch):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        corrupted = self._corrupt_in_place(directory)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        # False while the bad bytes are there, True once they have been
        # replaced: the answer is the probe's, never this module's claim about
        # what it wrote.
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        session = _FakeSession(wheel.bytes)

        answer = cuda_runtime.repair_cuda_runtime(str(directory), session=session)

        assert session.requested == [cuda_runtime.WHEEL_URL]
        assert answer[0] is True
        with open(corrupted, "rb") as handle:
            assert handle.read() == wheel.libraries["cublas64_12.dll"]
        # The expensive check, which is what said the directory was bad, now
        # passes — a size-only assertion here would agree with the bug.
        cuda_runtime.verify_installation(str(directory))

    def test_the_delete_and_the_download_are_one_hold_of_the_lock(
        self, tmp_path, wheel, monkeypatch
    ):
        """A window between them is a window another account downloads into.

        The nested acquisitions inside remove/install are the same hold — the
        lock is re-entrant within the process — so what this asserts is that
        the depth never falls back to zero until the repair is over.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        self._corrupt_in_place(directory)

        _pin(monkeypatch, wheel)
        events = _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))

        cuda_runtime.repair_cuda_runtime(
            str(directory), session=_FakeSession(wheel.bytes)
        )

        assert {key for _kind, key in events} == {str(directory)}
        assert events[0][0] == "acquire"
        depth = 0
        depths = []
        for kind, _key in events:
            depth += 1 if kind == "acquire" else -1
            depths.append(depth)
        assert depths[-1] == 0, "the repair ended still holding the lock"
        assert min(depths[:-1]) > 0, "the lock was let go mid-repair"

    def test_another_window_busy_with_it_is_reported_before_anything_is_deleted(
        self, tmp_path, wheel, monkeypatch
    ):
        """Its own code, and it has to arrive while the install is still there.

        Taking the lock twice would let the busy answer come *after* the
        removal, which is the worst of both: the user is told to wait and their
        libraries are already gone.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        self._corrupt_in_place(directory)
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.repair_cuda_runtime(str(directory))

        assert caught.value.code == errors.CUDA_RUNTIME_BUSY
        assert set(cuda_runtime.INSTALLED_FILES).issubset(_names_in(str(directory)))

    def test_repairing_a_directory_with_nothing_in_it_simply_installs(
        self, tmp_path, wheel, monkeypatch
    ):
        """The repair button is reachable from a state the user misread, and
        deleting nothing before downloading is not a failure."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        session = _FakeSession(wheel.bytes)

        answer = cuda_runtime.repair_cuda_runtime(str(directory), session=session)

        assert session.requested == [cuda_runtime.WHEEL_URL]
        assert answer[0] is True
        assert cuda_runtime.is_installed(str(directory)) is True


class TestTellingAnOutdatedInstallFromAnInterruptedOne:
    """Both are INCOMPLETE, and they need different sentences.

    "Finish the download that stopped" and "update the libraries to the version
    your card needs" are different instructions and different waits — the
    second is 553 MB the user was not expecting. The only clue used to be
    `missing`, and for an install left by another pin `missing` is empty: every
    file is there, at exactly the size its own manifest states.
    """

    def test_another_pin_names_the_version_it_left(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)

        state = cuda_runtime.installation_state(str(directory))

        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert state.installed_version == "11.0.0.0"
        # Unchanged, and exactly why the version had to be exposed instead: on
        # its own the caller has nothing to say.
        assert state.missing == ()

    def test_an_interrupted_install_names_no_version(self, tmp_path):
        directory = tmp_path / "cuda"
        os.makedirs(str(directory))
        with open(os.path.join(str(directory), "cublas64_12.dll.part"), "wb") as fh:
            fh.write(b"half a library")

        state = cuda_runtime.installation_state(str(directory))

        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert state.installed_version is None
        assert state.missing

    def test_a_complete_install_names_no_version_either(
        self, tmp_path, wheel, monkeypatch
    ):
        """The field means "a previous pin left this", not "what is here".

        A state of its own was the other option and would have been a bug:
        install_cuda_runtime()'s shortcut is written as `!= STATE_INCOMPLETE`,
        so a fourth state would send an outdated install down the "already
        fine" branch and the repin would reach nobody.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        state = cuda_runtime.installation_state(str(directory))

        assert state.state == cuda_runtime.STATE_INSTALLED
        assert state.installed_version is None

    def test_an_empty_directory_names_no_version(self, tmp_path):
        state = cuda_runtime.installation_state(str(tmp_path / "nothing"))
        assert state.state == cuda_runtime.STATE_ABSENT
        assert state.installed_version is None

    def test_an_unreadable_manifest_names_no_version(
        self, tmp_path, wheel, monkeypatch
    ):
        """Unparsable is not "another version": nothing on disk says which."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        with open(os.path.join(str(directory), "RECORD"), "wb") as handle:
            handle.write(b"\xff\xfe not a manifest")

        state = cuda_runtime.installation_state(str(directory))

        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert state.installed_version is None

    def test_an_interrupted_download_of_the_old_pin_sets_both_and_missing_wins(
        self, tmp_path, wheel, monkeypatch
    ):
        """The state the field's own comment used to say was unreachable.

        A download of the *previous* pin that stopped half way leaves that
        pin's manifest — so `installed_version` is filled — beside an
        incomplete set of libraries, so `missing` is filled too. Whichever the
        caller reads first is the sentence the user gets, and "update your CUDA
        libraries" for a half-written install sends them to the wrong button.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)
        os.remove(os.path.join(str(directory), "cublas64_12.dll"))

        state = cuda_runtime.installation_state(str(directory))

        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert state.installed_version == "11.0.0.0"
        assert "cublas64_12.dll" in state.missing

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_sentence_the_version_exists_for_is_translated(self, locale):
        """The field's whole justification is a sentence somebody can read.

        Without the key I18n.t() renders its own name — a screen reader then
        says "transcription cuda runtime outdated" letter group by letter
        group — which is the failure this repository has already shipped twice.
        """
        table = load_strings(locale)
        assert cuda_runtime.OUTDATED_I18N_KEY in table, locale
        assert table[cuda_runtime.OUTDATED_I18N_KEY].strip(), locale


class TestALibraryThisProcessHasAlreadyMapped:
    """The 553 MB the wrong error code costs, and where it is caught instead.

    Windows neither unlinks nor replaces a DLL that is mapped into the process,
    and after one transcription on the GPU that is exactly what these two
    files are. The sequence measured on a real install: repair → the removal
    leaves the DLLs and takes the manifest → the install sees no manifest with
    files present, calls it INCOMPLETE, and so misses its own "already fine"
    shortcut → 553 MB downloaded and verified → `os.replace()` raises
    PermissionError → reported as CUDA_RUNTIME_DOWNLOAD_FAILED → a blind user
    hears "check your connection" on a perfect connection, and tries again for
    another half gigabyte.

    Nothing in the process can fix it; only a restart can. So it gets a code of
    its own, and the removal's return value — documented as the names that
    resisted, which is precisely this — is read before the download rather than
    thrown away.
    """

    def _refuse(self, monkeypatch, name, errnum=errno.EACCES):
        """Make `name` behave the way a mapped DLL does: no unlink, no replace."""
        target = os.path.normcase(name)
        real_remove = os.remove
        real_replace = os.replace

        def _remove(path, *args, **kwargs):
            if os.path.normcase(os.path.basename(str(path))) == target:
                raise PermissionError(errnum, "The process cannot access the file")
            return real_remove(path, *args, **kwargs)

        def _replace(src, dst, *args, **kwargs):
            if os.path.normcase(os.path.basename(str(dst))) == target:
                raise PermissionError(errnum, "The process cannot access the file")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(cuda_runtime.os, "remove", _remove)
        monkeypatch.setattr(cuda_runtime.os, "replace", _replace)

    def test_repairing_says_so_before_spending_the_download(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        session = _FakeSession(wheel.bytes)
        self._refuse(monkeypatch, "cublas64_12.dll")

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.repair_cuda_runtime(str(directory), session=session)

        assert caught.value.code == errors.CUDA_RUNTIME_IN_USE
        assert session.requested == [], "the download ran anyway"

    def test_the_names_travel_in_the_detail_and_never_in_the_sentence(
        self, tmp_path, wheel, monkeypatch
    ):
        """Same split as everywhere else: the file names are for log.log.

        `wx.MessageBox(str(exc), ...)` is an idiom this repository already
        uses, so anything __str__ returns is one careless handler away from
        being read out character by character.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        self._refuse(monkeypatch, "cublas64_12.dll")

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.repair_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert "cublas64_12.dll" in caught.value.detail
        assert str(caught.value) == errors.CUDA_RUNTIME_IN_USE
        assert caught.value.i18n_key == "transcription_error_cuda_runtime_in_use"

    def test_a_repin_over_a_mapped_install_is_not_a_failed_download(
        self, tmp_path, wheel, monkeypatch
    ):
        """The path with no removal in it, which no pre-check can reach.

        An install of the previous pin the user has already transcribed with:
        `install_cuda_runtime()` fetches the new wheel and dies publishing over
        a file the loader is holding. There is nothing here to have refused
        earlier — the answer has to be read off the errno.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        self._refuse(monkeypatch, "cublas64_12.dll")

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_IN_USE

    @pytest.mark.parametrize("errnum", [errno.EACCES, errno.EPERM])
    def test_both_permission_errnos_are_the_same_answer(
        self, tmp_path, wheel, monkeypatch, errnum
    ):
        """Windows reports a sharing violation as EACCES through Python, but
        the mapping is the platform's and not worth betting one code on."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)

        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING, _LOADABLE))
        self._refuse(monkeypatch, "cublas64_12.dll", errnum=errnum)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory), session=_FakeSession(wheel.bytes)
            )

        assert caught.value.code == errors.CUDA_RUNTIME_IN_USE

    def test_a_genuinely_failed_transfer_still_says_so(
        self, tmp_path, wheel, monkeypatch
    ):
        """The other half of the split: nothing was mapped, and the download is
        what broke. Reading everything as "in use" would send a user with a
        dropped connection to restart WinZapp forever."""
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch, answers=(_MISSING,))
        session = _FakeSession(wheel.bytes, failure=OSError("connection reset"))

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert caught.value.code == errors.CUDA_RUNTIME_DOWNLOAD_FAILED

    def test_the_removal_alone_still_only_reports_what_resisted(
        self, tmp_path, wheel, monkeypatch
    ):
        """`remove_cuda_runtime()` is unchanged and still does not raise.

        Both buttons the settings tab wires up reach this state, but they need
        different things from it: Remove has already done everything it can and
        answers with the names, while Repair cannot go on at all. Turning the
        removal itself into a raise would take the names away from the caller
        that wants them.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _recording_locks(monkeypatch)
        self._refuse(monkeypatch, "cublas64_12.dll")

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == (
            "cublas64_12.dll",
        )


class TestCancelling:
    def test_cancelling_the_download_leaves_nothing_behind(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        watcher = _CancelAfter(limit=1)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory),
                progress=watcher.progress,
                should_cancel=watcher,
                session=_FakeSession(wheel.bytes),
            )

        assert caught.value.code == errors.CANCELLED
        # Not even the directory: nothing of ours may be left in a folder the
        # app created and then failed to use.
        assert not os.path.exists(str(directory))

    @pytest.mark.parametrize("after_libraries", [0, 1])
    def test_cancelling_the_extraction_leaves_neither_a_part_nor_a_library(
        self, tmp_path, wheel, monkeypatch, after_libraries
    ):
        """The nastier half, in both of its shapes.

        Cancelling inside the first library leaves a `.part`. Cancelling after
        it has been published leaves a whole, verified library on disk with no
        manifest beside it — which is exactly the state publishing RECORD last
        exists for, and the one a cleanup that only swept `.part` files would
        walk straight past.
        """
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        published = sum(
            len(wheel.libraries[name])
            for name, _member in cuda_runtime._LIBRARY_MEMBERS[:after_libraries]
        )
        watcher = _CancelAfter(limit=len(wheel.bytes) + published + 1)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.install_cuda_runtime(
                str(directory),
                progress=watcher.progress,
                should_cancel=watcher,
                session=_FakeSession(wheel.bytes),
            )

        assert caught.value.code == errors.CANCELLED
        assert not os.path.exists(str(directory))

    def test_a_cancelled_install_does_not_empty_a_directory_that_was_there(
        self, tmp_path, wheel, monkeypatch
    ):
        """Only a directory this install created is removed with it."""
        directory = tmp_path / "cuda"
        os.makedirs(str(directory))
        with open(os.path.join(str(directory), "notes.txt"), "w") as handle:
            handle.write("someone else's file")
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        watcher = _CancelAfter(limit=1)

        with pytest.raises(errors.TranscriptionError):
            cuda_runtime.install_cuda_runtime(
                str(directory),
                progress=watcher.progress,
                should_cancel=watcher,
                session=_FakeSession(wheel.bytes),
            )

        assert _names_in(str(directory)) == ["notes.txt"]

    def test_a_cancelled_verification_stops_reading(self, tmp_path, wheel, monkeypatch):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        watcher = _CancelAfter(limit=1)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.verify_installation(
                str(directory), progress=watcher.progress, should_cancel=watcher
            )

        assert caught.value.code == errors.CANCELLED


# ── What is on disk ──────────────────────────────────────────────────────────


class TestInstallationState:
    def test_an_empty_directory_is_absent(self, tmp_path):
        state = cuda_runtime.installation_state(str(tmp_path / "nothing"))
        assert state.state == cuda_runtime.STATE_ABSENT
        assert set(state.missing) == set(cuda_runtime.INSTALLED_FILES)

    def test_a_finished_install_is_installed(self, tmp_path, wheel, monkeypatch):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        state = cuda_runtime.installation_state(str(directory))
        assert state.state == cuda_runtime.STATE_INSTALLED
        assert state.missing == ()
        assert cuda_runtime.is_installed(str(directory)) is True

    def test_a_library_of_the_wrong_size_is_incomplete_not_installed(
        self, tmp_path, wheel, monkeypatch
    ):
        """The check is cheap on purpose — names and exact sizes, no hashing —
        which is only sound because RECORD pins an exact size for each."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        with open(os.path.join(str(directory), "cublas64_12.dll"), "ab") as handle:
            handle.write(b"x")

        state = cuda_runtime.installation_state(str(directory))
        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert state.missing == ("cublas64_12.dll",)

    def test_libraries_with_no_manifest_beside_them_are_not_installed(
        self, tmp_path, wheel, monkeypatch
    ):
        """Nothing on disk can be checked without RECORD, so the libraries
        next to it are unusable however healthy they look."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        os.remove(os.path.join(str(directory), "RECORD"))

        state = cuda_runtime.installation_state(str(directory))
        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert "RECORD" in state.missing
        assert cuda_runtime.is_installed(str(directory)) is False

    def test_an_unreadable_manifest_is_not_installed_either(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        with open(os.path.join(str(directory), "RECORD"), "wb") as handle:
            handle.write(b"\xff\xfe not a manifest")

        assert cuda_runtime.is_installed(str(directory)) is False

    def test_a_manifest_from_another_pin_is_not_an_installation(
        self, tmp_path, wheel, monkeypatch
    ):
        """Every size agrees with the manifest beside it and the version is
        still wrong, which is the whole difficulty: nothing but the dist-info
        the manifest names distinguishes the two."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)

        state = cuda_runtime.installation_state(str(directory))
        assert state.state == cuda_runtime.STATE_INCOMPLETE
        assert cuda_runtime.is_installed(str(directory)) is False

    def test_an_interrupted_install_is_incomplete_rather_than_absent(self, tmp_path):
        """The two offer the user different buttons, so they are two states."""
        directory = tmp_path / "cuda"
        os.makedirs(str(directory))
        with open(os.path.join(str(directory), "cublas64_12.dll.part"), "wb") as fh:
            fh.write(b"half a library")

        state = cuda_runtime.installation_state(str(directory))
        assert state.state == cuda_runtime.STATE_INCOMPLETE


class TestVerifying:
    def test_a_finished_install_verifies(self, tmp_path, wheel, monkeypatch):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        cuda_runtime.verify_installation(str(directory))  # does not raise

    def test_a_library_of_the_right_size_and_the_wrong_bytes_is_caught(
        self, tmp_path, wheel, monkeypatch
    ):
        """The one state the cheap check cannot see, which is the reason this
        expensive one exists at all."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        path = os.path.join(str(directory), "cublasLt64_12.dll")
        with open(path, "r+b") as handle:
            handle.write(b"Z")

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.verify_installation(str(directory))

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED

    def test_verifying_nothing_says_it_is_not_installed(self, tmp_path):
        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.verify_installation(str(tmp_path / "nothing"))

        assert caught.value.code == errors.CUDA_RUNTIME_CORRUPTED

    def test_the_detail_never_carries_a_sentence_for_the_user(
        self, tmp_path, wheel, monkeypatch
    ):
        """`str(exc)` is one careless wx.MessageBox away from being read out,
        so it stays the code. The log keeps the whole diagnosis, folder
        included: it names no message, and which install was checked is half
        of what the line is for (errors.scrub_media_names())."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        os.remove(os.path.join(str(directory), "RECORD"))

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.verify_installation(str(directory))

        assert str(caught.value) == errors.CUDA_RUNTIME_CORRUPTED
        assert str(directory) not in str(caught.value)
        assert str(directory) in caught.value.log_line


# ── Startup registration ─────────────────────────────────────────────────────


class TestRegisteringAtStartup:
    def test_an_install_from_an_earlier_session_is_registered(
        self, tmp_path, wheel, monkeypatch
    ):
        """Without this the user who paid for the download last week is
        silently back on the processor today, with nothing anywhere saying so."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        loader = _loader(monkeypatch)

        assert cuda_runtime.register_installed_runtime(str(directory)) is True
        assert loader.registered == [str(directory)]

    def test_nothing_installed_registers_nothing(self, tmp_path, monkeypatch):
        """An empty directory of ours has no business on the process's DLL
        search path."""
        loader = _loader(monkeypatch)

        assert cuda_runtime.register_installed_runtime(str(tmp_path / "cuda")) is False
        assert loader.registered == []

    def test_it_registers_the_directory_the_libraries_are_actually_in(
        self, tmp_path, wheel, monkeypatch
    ):
        """The loader resolves cuBLASLt out of the same folder as cuBLAS, so
        the flattened layout and the registered path have to be the one folder."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        loader = _loader(monkeypatch)
        cuda_runtime.register_installed_runtime(str(directory))

        registered = loader.registered[0]
        for name, _member in cuda_runtime._LIBRARY_MEMBERS:
            assert os.path.isfile(os.path.join(registered, name))


class TestTheLoaderIsToldWhenTheLibrariesGoAway:
    """The half of a removal that the disk cannot see.

    device.py memoizes "do the CUDA libraries load?" for the process, and
    registering a directory is the *only* event that invalidates it. Deleting
    the libraries is the same event pointing the other way, and it has none —
    so a True measured by the transcription that ran an hour ago outlives the
    files it was about. Measured before this was closed: probe True, files
    gone, resolve_device() still answering ("cuda", "cuda_selected"), and every
    transcription loading the model onto the card and dying on
    "Could not load library cublas64_12.dll" until the app is restarted.
    """

    def test_removing_the_libraries_forgets_that_they_loaded(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _recording_locks(monkeypatch)
        # As a transcription that ran on the GPU would have left it.
        monkeypatch.setattr(device, "_cuda_library_answer", _LOADABLE)

        cuda_runtime.remove_cuda_runtime(str(directory))

        assert device._cuda_library_answer is None

    def test_installing_with_nothing_to_register_forgets_it_too(
        self, tmp_path, wheel, monkeypatch
    ):
        """The same staleness read from the other end.

        With nothing on disk there is nothing to register, so nothing
        invalidates — and the shortcut would then be decided by a True that
        belongs to libraries which are no longer there, returning "already
        fine" for a directory holding nothing at all.
        """
        directory = tmp_path / "cuda"
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        monkeypatch.setattr(device, "_cuda_library_answer", _LOADABLE)
        session = _FakeSession(wheel.bytes)

        cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert device._cuda_library_answer is None
        assert session.requested == [cuda_runtime.WHEEL_URL]

    def test_an_install_that_swept_a_published_library_forgets_it_too(
        self, tmp_path, wheel, monkeypatch
    ):
        """The third place this module takes libraries off the disk.

        The first two were the removal and the nothing-to-register branch. This
        one is the failure path of an upgrade that had already published a
        library: the sweep takes it, and without this the memoized True from
        before the attempt outlives it exactly as it did there.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)   # so the upgrade runs
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        monkeypatch.setattr(device, "_cuda_library_answer", _LOADABLE)
        # Fails after the wheel is on disk and one library has been published.
        session = _FakeSession(wheel.bytes)
        real_write_part = cuda_runtime._write_part
        published = []

        def _fail_after_the_first_library(directory_, name, *args, **kwargs):
            if published and name != cuda_runtime.WHEEL_FILENAME:
                raise OSError("the disk went away")
            done = real_write_part(directory_, name, *args, **kwargs)
            if name in cuda_runtime.INSTALLED_FILES:
                published.append(name)
            return done

        monkeypatch.setattr(cuda_runtime, "_write_part", _fail_after_the_first_library)

        with pytest.raises(errors.TranscriptionError):
            cuda_runtime.install_cuda_runtime(str(directory), session=session)

        assert published, "the test never reached the state it is about"
        assert device._cuda_library_answer is None


class TestAFailedUpgradeKeepsWhatWasWorking:
    """A download that fails must not cost the user the install they had.

    Since the manifest carries the pin, a previous version's install reads as
    INCOMPLETE — which is what lets the repair path reach it, and also what
    walks it into the failure sweep. Cancel is a button part 5 puts in front of
    the user during a 553 MB download; pressing it must not leave them without
    a GPU until a full download succeeds.
    """

    def test_a_failure_before_anything_is_published_leaves_the_old_install(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _write_manifest_of_another_pin(directory)
        before = _names_in(str(directory))
        _pin(monkeypatch, wheel)
        _recording_locks(monkeypatch)
        _loader(monkeypatch)
        session = _FakeSession(wheel.bytes, failure=OSError("connection reset"))

        with pytest.raises(errors.TranscriptionError):
            cuda_runtime.install_cuda_runtime(str(directory), session=session)

        # The libraries and the old manifest are all still there; only the
        # partial wheel went.
        assert _names_in(str(directory)) == before
        assert not [n for n in _names_in(str(directory)) if n.endswith(".part")]


# ── Uninstalling ─────────────────────────────────────────────────────────────


class TestRemoving:
    def test_it_deletes_everything_it_installed(self, tmp_path, wheel, monkeypatch):
        """770 MB the user cannot get rid of is not an acceptable end state."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == ()
        assert not os.path.exists(str(directory))

    def test_a_stranger_in_the_same_folder_survives_and_so_does_the_folder(
        self, tmp_path, wheel, monkeypatch
    ):
        """Never shutil.rmtree(): a recursive delete only has to be wrong once,
        and os.rmdir() refuses a directory that still holds anything."""
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        stranger = os.path.join(str(directory), "someone_elses.txt")
        with open(stranger, "w") as handle:
            handle.write("not ours")

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == ()
        assert _names_in(str(directory)) == ["someone_elses.txt"]

    def test_removing_the_leftovers_of_an_interrupted_install_works_too(
        self, tmp_path, monkeypatch
    ):
        directory = tmp_path / "cuda"
        os.makedirs(str(directory))
        for name in ("cublas64_12.dll.part", cuda_runtime.WHEEL_FILENAME + ".part"):
            with open(os.path.join(str(directory), name), "wb") as handle:
                handle.write(b"scratch")
        _recording_locks(monkeypatch)

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == ()
        assert not os.path.exists(str(directory))

    def test_a_part_left_by_an_earlier_pin_is_swept_too(self, tmp_path, monkeypatch):
        """The wheel's `.part` carries the version in its name.

        Iterating the *current* pin's names would stop recognising it the day
        the pin moves, and half a gigabyte would sit in the shared global
        folder under a name nothing looks for any more.
        """
        directory = tmp_path / "cuda"
        os.makedirs(str(directory))
        stale = "nvidia_cublas_cu12-11.0.0.0-py3-none-win_amd64.whl.part"
        with open(os.path.join(str(directory), stale), "wb") as handle:
            handle.write(b"half a wheel from the previous pin")
        _recording_locks(monkeypatch)

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == ()
        assert not os.path.exists(str(directory))

    def test_a_library_windows_will_not_unlink_is_named_in_the_answer(
        self, tmp_path, wheel, monkeypatch
    ):
        """The expected outcome after a transcription has run on the GPU.

        A mapped DLL cannot be unlinked on Windows, and a bare "something was
        removed" leaves part 5 unable to say which files are still there or
        that WinZapp has to be restarted to finish.
        """
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        _recording_locks(monkeypatch)
        stuck = os.path.join(str(directory), "cublas64_12.dll")
        real_remove = os.remove

        def _mapped(path, *args, **kwargs):
            if os.path.normcase(str(path)) == os.path.normcase(stuck):
                raise PermissionError(32, "The process cannot access the file")
            return real_remove(path, *args, **kwargs)

        monkeypatch.setattr(cuda_runtime.os, "remove", _mapped)

        assert cuda_runtime.remove_cuda_runtime(str(directory)) == (
            "cublas64_12.dll",
        )
        # The folder stays, because it still holds the file that resisted.
        assert _names_in(str(directory)) == ["cublas64_12.dll"]

    def test_removing_nothing_leaves_nothing_behind(self, tmp_path, monkeypatch):
        _recording_locks(monkeypatch)
        assert cuda_runtime.remove_cuda_runtime(str(tmp_path / "cuda")) == ()

    def test_the_removal_is_held_against_the_other_accounts(
        self, tmp_path, wheel, monkeypatch
    ):
        directory = tmp_path / "cuda"
        _install(directory, wheel, monkeypatch)
        events = _recording_locks(monkeypatch)

        cuda_runtime.remove_cuda_runtime(str(directory))

        assert events == [("acquire", str(directory)), ("release", str(directory))]

    def test_another_window_busy_with_it_is_its_own_error(self, tmp_path, monkeypatch):
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as caught:
            cuda_runtime.remove_cuda_runtime(str(tmp_path / "cuda"))

        assert caught.value.code == errors.CUDA_RUNTIME_BUSY


# ── The one test that reaches PyPI ───────────────────────────────────────────


class TestThePinnedWheelIsStillThere:
    """The pinned URL must still serve exactly the pinned number of bytes.

    The same safety net the model catalogue has, for the same reason: a wheel
    yanked from the index or republished under another path is a broken link
    the fake session cannot possibly see, and the user's only symptom would be
    a download that never succeeds. Skipped unless asked for — run it by hand
    whenever the pin changes.
    """

    pytestmark = [
        pytest.mark.network,
        pytest.mark.skipif(
            os.environ.get(_NETWORK_OPT_IN_ENV, "").strip() in ("", "0", "false", "False"),
            reason=f"reaches pypi.org - set {_NETWORK_OPT_IN_ENV}=1 to run it",
        ),
    ]

    def test_the_url_serves_exactly_the_pinned_size(self):
        # Through the same session the download itself uses, not a bare
        # requests.head(): on a machine whose TLS is intercepted (an antivirus
        # scanning HTTPS is enough) certifi does not know the injected root and
        # this fails with CERTIFICATE_VERIFY_FAILED — which reads exactly like
        # the broken link this test exists to catch.
        with tls_trust.create_session() as session:
            response = session.head(
                cuda_runtime.WHEEL_URL,
                allow_redirects=True,
                timeout=30,
                # The question is how many bytes the file HAS, not how many the
                # server would choose to send.
                headers={"Accept-Encoding": "identity"},
            )

        assert response.status_code == 200, (
            f"{cuda_runtime.WHEEL_URL} answered {response.status_code}"
        )
        reported = response.headers.get("Content-Length")
        assert reported is not None, "the pinned wheel reported no size at all"
        assert int(reported) == cuda_runtime.WHEEL_BYTES
