"""Getting the Whisper models onto disk without lying about what is there.

Every failure this file pins has the same shape from the user's side: they ask
for a transcription and get an error, or nothing, after having waited for a
multi-gigabyte download. The mechanisms behind that are specific, and all of
them are cheap to reproduce with a handful of synthetic bytes:

* **A half-written file under its final name is indistinguishable from a good
  one.** "Is this model installed?" runs before every transcription and every
  time the model list is drawn, so it can only afford names and exact sizes —
  which means anything wearing the catalogue's name and size *will* be
  believed. Cancel a download at the wrong moment, or leave a `.part` behind
  under the wrong name, and the model looks installed while CTranslate2 refuses
  to load it. So the tests below cancel, fail and interrupt mid-file and then
  assert on the install check itself, not merely on the exception.

* **The pinned revision is the entire integrity story.** The catalogue's sizes
  and model.bin digest were measured at one commit; a URL that followed `main`
  would fetch bytes nothing here can vouch for, and would accept different
  weights for any file whose size happened to match. There is a test that fails
  the moment a URL stops naming the revision.

* **A "does it fit?" gate that runs late is not a gate.** NO_DISK_SPACE has to
  be raised before the first byte, while the user can still choose a smaller
  model.

* **A user-chosen directory is not ours to empty.** Part 5 lets the user put
  the models wherever they like, including a folder that already holds their
  own files. `remove_model()` deletes the catalogue's own names and nothing
  else, and the test that matters here is the one asserting a stranger's file
  survived.

* **Moving the folder must never leave both roots incomplete.** The move copies
  and verifies before it deletes, so an interruption leaves every model whole
  in exactly one of the two roots.

The network is never touched: a fake session answers from a table of bytes. The
one test that does reach Hugging Face — the safety net for "no model may offer
a broken link" — is marked `network` and skipped unless
WINZAPP_RUN_NETWORK_TESTS is set.
"""

import hashlib
import math
import os
import subprocess
import sys

import pytest
import requests

import app_paths
from coord_locks import LockTimeout
from core import tls_trust
from core.transcription import errors, model_catalog, model_store, whisper_cpp_catalog

_NETWORK_OPT_IN_ENV = "WINZAPP_RUN_NETWORK_TESTS"


# ── Synthetic catalogue ──────────────────────────────────────────────────────


def _synthetic_model(model_id, weights):
    """A catalogue entry of a few kilobytes, plus the bytes behind it.

    The real catalogue is 5.5 GB of weights sitting behind a network, and
    everything in model_store is about names, sizes and digests — which these
    bytes exercise exactly as well and in milliseconds. The file list keeps the
    tiny..medium shape (`vocabulary.txt`, no `preprocessor_config.json`), since
    the store never assumes a shape either way.
    """
    contents = {
        "config.json": b'{"model_type": "whisper"}',
        "model.bin": weights,
        "tokenizer.json": b'{"added_tokens": []}',
        "vocabulary.txt": b"one\ntwo\nthree\n",
    }
    files = tuple((name, len(data)) for name, data in contents.items())
    total = sum(size for _name, size in files)
    model = model_catalog.WhisperModel(
        id=model_id,
        repo=f"example-org/faster-whisper-{model_id}",
        # Shaped like a real commit sha, so a test asserting the URL carries a
        # 40-hex revision has something to bite on.
        revision=("%s" % model_id).encode().hex().ljust(40, "0")[:40],
        model_bin_sha256=hashlib.sha256(weights).hexdigest(),
        files=files,
        model_bin_bytes=len(weights),
        download_bytes=total,
        disk_bytes=total,
        size_class=model_catalog.SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
    )
    return model, contents


@pytest.fixture
def entry(monkeypatch):
    """One synthetic model standing in for the whole catalogue.

    MODELS is patched rather than the model merely passed around, because
    list_installed() and remove_model() look the id up in the catalogue
    themselves — remove_model() deliberately refuses to delete anything it
    cannot name from there.
    """
    model, contents = _synthetic_model("alpha", b"A" * 4096)
    monkeypatch.setattr(model_catalog, "MODELS", (model,))
    return model, contents


@pytest.fixture
def two_entries(monkeypatch):
    """Two synthetic models, the second twice the size of the first."""
    first = _synthetic_model("alpha", b"A" * 4096)
    second = _synthetic_model("beta", b"B" * 8192)
    monkeypatch.setattr(model_catalog, "MODELS", (first[0], second[0]))
    return first, second


def _bodies(model, contents, overrides=None):
    """The fake session's URL -> bytes table, with per-file substitutions."""
    merged = dict(contents)
    merged.update(overrides or {})
    return {
        model_store.file_url(model, name): data for name, data in merged.items()
    }


def _write_model(root, model, contents):
    """Put a complete, valid model on disk without going through a download."""
    directory = model_store.model_dir(root, model.id)
    os.makedirs(directory, exist_ok=True)
    for name, data in contents.items():
        with open(os.path.join(directory, name), "wb") as fh:
            fh.write(data)
    return directory


def _names_in(directory):
    return sorted(os.listdir(directory))


# ── The fake network ─────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, session, url, start=0, status_code=200, served_from=None):
        self._session = session
        self._url = url
        self._start = start
        self.status_code = status_code
        self.headers = {}
        if status_code == 206:
            total = len(session.bodies[url])
            # What the server claims it is sending, which is not always where
            # it actually starts — see _FakeSession(pretend_range=True).
            claimed = start if served_from is None else served_from
            self.headers["Content-Range"] = f"bytes {claimed}-{total - 1}/{total}"
        self.closed = False

    def raise_for_status(self):
        error = self._session.failures.get(self._url)
        if error is not None:
            raise error

    def iter_content(self, chunk_size=None):
        self._session.chunk_sizes.append(chunk_size)
        body = self._session.bodies[self._url][self._start:]
        # Split into a fixed number of pieces rather than by chunk_size: the
        # real chunk is 1 MB, so honouring it would mean either megabytes of
        # synthetic weights or a single-chunk transfer that never exercises
        # cancelling between chunks. The size actually asked for is pinned
        # separately, by test_the_transfer_is_streamed_in_chunks.
        step = max(1, math.ceil(len(body) / self._session.slices))
        for start in range(0, len(body), step):
            chunk = body[start:start + step]
            self._session.served += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


class _FakeSession:
    """The slice of requests.Session the store uses, answering from bytes.

    Records every request so a test can assert what was *not* fetched — which
    is how "already complete files are skipped" and "the space gate runs before
    the first byte" are checked.
    """

    def __init__(self, bodies, failures=None, slices=4, honour_range=True,
                 pretend_range=False):
        self.bodies = dict(bodies)
        self.failures = dict(failures or {})
        self.slices = slices
        # Hugging Face serves byte ranges; a proxy or a mirror may not, and
        # answering 200 to a Range request is the case that would concatenate
        # a second copy onto the first if nothing noticed. `pretend_range` is
        # the nastier one: a 206 label on a body that starts at zero.
        self.honour_range = honour_range
        self.pretend_range = pretend_range
        self.requested = []
        self.streamed = []
        self.timeouts = []
        self.chunk_sizes = []
        self.ranges = []
        self.responses = []
        self.served = 0
        self.closed = False

    def get(self, url, stream=False, timeout=None, headers=None):
        self.requested.append(url)
        self.streamed.append(stream)
        self.timeouts.append(timeout)
        wanted = (headers or {}).get("Range")
        self.ranges.append(wanted)
        start, status, served_from = 0, 200, None
        if wanted and self.honour_range:
            start = int(wanted.split("=")[1].split("-")[0])
            status = 206
        elif wanted and self.pretend_range:
            status = 206  # the label of a range, the body of the whole file
            served_from = 0
        response = _FakeResponse(
            self, url, start=start, status_code=status, served_from=served_from
        )
        self.responses.append(response)
        return response

    def close(self):
        self.closed = True


class _CancelAfter:
    """Cancels once `limit` bytes of the transfer have been reported.

    Counting reported bytes rather than callback invocations makes "cancel in
    the middle of the big file" a fixed point of the test instead of a guess
    about how many chunks the fake produced.
    """

    def __init__(self, limit):
        self.limit = limit
        self.done = 0

    def progress(self, done, _total):
        self.done = done

    def __call__(self):
        return self.done >= self.limit


class _RecordingLock:
    """Stands in for coord_locks.models_lock and records when it is held."""

    def __init__(self, events, root):
        self.events = events
        self.root = root

    def acquire(self):
        self.events.append(("acquire", self.root))

    def release(self):
        self.events.append(("release", self.root))


def _recording_locks(monkeypatch):
    events = []
    monkeypatch.setattr(
        model_store,
        "models_lock",
        lambda root, lock_dir, timeout=None: _RecordingLock(events, root),
    )
    return events


class _AlwaysBusyLock:
    """A lock another process never lets go of."""

    def __init__(self, root):
        self.root = root

    def acquire(self):
        raise LockTimeout(f"held by another process: {self.root}")

    def release(self):  # pragma: no cover - never acquired
        raise AssertionError("released a lock that was never acquired")


def _busy_locks(monkeypatch):
    """Make every models lock unavailable, and stop waiting immediately.

    The real deadline is twelve hours — a backstop against a lock nobody will
    release, not a policy — so a test that waited for it would be a test nobody
    ever finishes.
    """
    monkeypatch.setattr(model_store, "_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        model_store,
        "models_lock",
        lambda root, lock_dir, timeout=None: _AlwaysBusyLock(root),
    )


def _link_directory(target, link):
    """(created, detail) — a directory link by whatever route is permitted.

    os.symlink needs SeCreateSymbolicLinkPrivilege, which an ordinary Windows
    account does not have; a junction needs nothing at all, resolves through
    realpath exactly the same way, and is what somebody actually does to park a
    3 GB model on another drive. Skipping instead of linking is what left the
    guard below deletable with the suite green.
    """
    if sys.platform == "win32":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True, text=True,
        )
        return done.returncode == 0, (done.stdout or "") + (done.stderr or "")
    try:
        os.symlink(target, link, target_is_directory=True)
        return True, ""
    except OSError as exc:
        return False, str(exc)


class _Progress:
    """Collects every (done, total) pair the store reports."""

    def __init__(self):
        self.calls = []

    def __call__(self, done, total):
        self.calls.append((done, total))


# ── Tests ────────────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("model", model_catalog.list_models(), ids=lambda m: m.id)
    def test_every_file_url_is_built_from_the_repo_and_revision(self, model):
        for name, _size in model.files:
            assert model_store.file_url(model, name) == (
                f"https://huggingface.co/{model.repo}/resolve/{model.revision}/{name}"
            )

    @pytest.mark.parametrize("model", model_catalog.list_models(), ids=lambda m: m.id)
    def test_no_url_follows_a_branch_instead_of_the_pinned_revision(self, model):
        """Swapping the revision for `main` is the regression this catches.

        It would keep working for as long as upstream leaves the files alone,
        and then start serving bytes whose size and digest nothing here has
        ever measured — silently accepting different weights for any file whose
        size happened to be unchanged.
        """
        for name, _size in model.files:
            url = model_store.file_url(model, name)
            assert "/resolve/main/" not in url
            assert f"/resolve/{model.revision}/" in url
            assert len(model.revision) == 40
            assert all(c in "0123456789abcdef" for c in model.revision)


class TestWhereModelsLive:
    def test_the_default_root_is_global_not_per_account(self):
        """A 3 GB model duplicated for every account is not a cost anyone
        would accept, and WinZapp runs one account per process."""
        assert model_store.default_models_dir() == app_paths.global_dir(
            model_store.MODELS_DIRNAME
        )
        assert not model_store.default_models_dir().startswith(
            app_paths.accounts_root()
        )

    def test_a_model_lives_in_its_own_subdirectory_of_the_root(self, entry, tmp_path):
        model, _contents = entry
        assert model_store.model_dir(str(tmp_path), model.id) == os.path.join(
            str(tmp_path), model.id
        )


class TestInstallationState:
    def test_an_empty_root_reports_absent(self, entry, tmp_path):
        model, _contents = entry
        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_ABSENT
        assert set(state.missing) == {name for name, _ in model.files}
        assert state.present_bytes == 0
        assert model_store.is_installed(str(tmp_path), model) is False
        assert model_store.list_installed(str(tmp_path)) == ()

    def test_a_complete_model_reports_installed(self, entry, tmp_path):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_INSTALLED
        assert state.missing == ()
        assert state.present_bytes == model.disk_bytes
        assert model_store.list_installed(str(tmp_path)) == (model.id,)

    def test_a_truncated_file_is_incomplete_not_installed(self, entry, tmp_path):
        """The state an interrupted download leaves behind. Reporting it as
        installed is what makes CTranslate2 fail with "internal error"."""
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "tokenizer.json"), "wb") as fh:
            fh.write(contents["tokenizer.json"][:-1])

        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_INCOMPLETE
        assert state.missing == ("tokenizer.json",)
        assert model_store.is_installed(str(tmp_path), model) is False
        assert model_store.list_installed(str(tmp_path)) == ()

    def test_a_missing_file_is_incomplete_while_others_remain(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        os.remove(os.path.join(directory, "model.bin"))

        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_INCOMPLETE
        assert state.missing == ("model.bin",)
        assert state.present_bytes == model.disk_bytes - model.model_bin_bytes

    def test_a_lone_truncated_file_is_still_an_interrupted_download(
        self, entry, tmp_path
    ):
        """Zero correct bytes is not the same as nothing being there — a
        directory holding one bad file has something to repair."""
        model, _contents = entry
        directory = model_store.model_dir(str(tmp_path), model.id)
        os.makedirs(directory)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(b"A")

        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_INCOMPLETE
        assert state.present_bytes == 0

    def test_a_part_file_alone_is_an_interrupted_download(self, entry, tmp_path):
        """Not ABSENT: the two states offer the user different buttons, and a
        2 GB `.part` waiting to be resumed is not nothing being there."""
        model, contents = entry
        directory = model_store.model_dir(str(tmp_path), model.id)
        os.makedirs(directory)
        for name, data in contents.items():
            with open(os.path.join(directory, name + ".part"), "wb") as fh:
                fh.write(data)

        state = model_store.installation_state(str(tmp_path), model)
        assert state.state == model_store.STATE_INCOMPLETE
        assert model_store.is_installed(str(tmp_path), model) is False


class TestFreeSpace:
    def test_free_space_is_measured_from_the_nearest_existing_ancestor(self, tmp_path):
        """The models directory does not exist yet the first time this is
        asked, and a gate answering "unknown" there blocks every first
        download."""
        missing = str(tmp_path / "not" / "created" / "yet")
        assert model_store.free_bytes(missing) is not None
        assert model_store.free_bytes(missing) > 0

    def test_a_download_that_only_just_fits_is_refused(self, entry, tmp_path, monkeypatch):
        model, _contents = entry
        monkeypatch.setattr(
            model_store,
            "free_bytes",
            lambda _path: model.download_bytes + model_store._FREE_SPACE_SLACK_BYTES - 1,
        )
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.ensure_free_space(str(tmp_path), model.download_bytes)
        assert excinfo.value.code == errors.NO_DISK_SPACE

    def test_the_slack_is_enough_to_pass(self, entry, tmp_path, monkeypatch):
        model, _contents = entry
        monkeypatch.setattr(
            model_store,
            "free_bytes",
            lambda _path: model.download_bytes + model_store._FREE_SPACE_SLACK_BYTES,
        )
        model_store.ensure_free_space(str(tmp_path), model.download_bytes)

    def test_an_unmeasurable_volume_does_not_block_the_download(self, tmp_path, monkeypatch):
        """Refusing because disk_usage() failed would make transcription
        unavailable on a setup that works perfectly well."""
        monkeypatch.setattr(model_store, "free_bytes", lambda _path: None)
        model_store.ensure_free_space(str(tmp_path), 10**12)


class TestDownload:
    def test_a_download_writes_exactly_the_catalogued_files(self, entry, tmp_path):
        model, contents = entry
        session = _FakeSession(_bodies(model, contents))

        directory = model_store.download_model(model, str(tmp_path), session=session)

        assert _names_in(directory) == sorted(contents)
        for name, size in model.files:
            with open(os.path.join(directory, name), "rb") as fh:
                data = fh.read()
            assert len(data) == size
            assert data == contents[name]
        assert model_store.is_installed(str(tmp_path), model) is True
        assert model_store.list_installed(str(tmp_path)) == (model.id,)

    def test_every_file_is_fetched_from_its_pinned_url(self, entry, tmp_path):
        model, contents = entry
        session = _FakeSession(_bodies(model, contents))
        model_store.download_model(model, str(tmp_path), session=session)
        assert sorted(session.requested) == sorted(
            model_store.file_url(model, name) for name, _size in model.files
        )

    def test_the_transfer_is_streamed_in_chunks(self, entry, tmp_path):
        """A non-streaming GET would pull 3 GB into memory before writing a
        byte of it."""
        model, contents = entry
        session = _FakeSession(_bodies(model, contents))
        model_store.download_model(model, str(tmp_path), session=session)
        assert session.streamed == [True] * len(model.files)
        assert session.chunk_sizes == [model_store._CHUNK_BYTES] * len(model.files)
        assert session.timeouts == [model_store._HTTP_TIMEOUT] * len(model.files)
        assert all(response.closed for response in session.responses)

    def test_progress_never_goes_backwards_and_ends_at_the_total(self, entry, tmp_path):
        """One bar for the whole model, not six in a row — the caller is
        drawing a gauge and announcing a percentage."""
        model, contents = entry
        progress = _Progress()
        session = _FakeSession(_bodies(model, contents))

        model_store.download_model(
            model, str(tmp_path), progress=progress, session=session
        )

        assert progress.calls
        assert all(total == model.download_bytes for _done, total in progress.calls)
        done = [d for d, _t in progress.calls]
        assert done == sorted(done)
        assert done[-1] == model.download_bytes
        assert done[0] == 0

    def test_the_digest_is_taken_from_the_stream_not_from_a_second_read(
        self, entry, tmp_path, monkeypatch
    ):
        """Re-reading model.bin to hash it would double the I/O of every
        download for a number the transfer already had in its hands."""
        model, contents = entry
        reads = []
        monkeypatch.setattr(
            model_store, "_hash_file", lambda *args, **kwargs: reads.append(args)
        )
        session = _FakeSession(_bodies(model, contents))

        model_store.download_model(model, str(tmp_path), session=session)

        assert reads == []

    def test_a_file_of_the_wrong_size_is_corruption(self, entry, tmp_path):
        model, contents = entry
        session = _FakeSession(
            _bodies(model, contents, {"model.bin": contents["model.bin"][:-8]})
        )

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(model, str(tmp_path), session=session)

        assert excinfo.value.code == errors.MODEL_CORRUPTED
        assert model_store.is_installed(str(tmp_path), model) is False
        assert not os.path.exists(
            os.path.join(model_store.model_dir(str(tmp_path), model.id), "model.bin")
        )

    def test_the_right_number_of_wrong_bytes_is_still_corruption(self, entry, tmp_path):
        """The one thing a size check cannot see, and the reason model.bin
        carries a digest at all."""
        model, contents = entry
        swapped = b"Z" * len(contents["model.bin"])
        assert len(swapped) == model.model_bin_bytes
        session = _FakeSession(_bodies(model, contents, {"model.bin": swapped}))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(model, str(tmp_path), session=session)

        assert excinfo.value.code == errors.MODEL_CORRUPTED
        assert model_store.is_installed(str(tmp_path), model) is False
        # The size is right, so a file left under its final name would pass the
        # install check forever — this is the case the `.part` rename order
        # exists for.
        assert not os.path.exists(
            os.path.join(model_store.model_dir(str(tmp_path), model.id), "model.bin")
        )

    def test_a_failed_request_is_a_download_failure(self, entry, tmp_path):
        model, contents = entry
        session = _FakeSession(
            _bodies(model, contents),
            failures={
                model_store.file_url(model, "model.bin"): requests.HTTPError("404")
            },
        )

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(model, str(tmp_path), session=session)

        assert excinfo.value.code == errors.MODEL_DOWNLOAD_FAILED
        # The technical detail is for the log only; str() is what a careless
        # wx.MessageBox would read out loud.
        assert str(excinfo.value) == errors.MODEL_DOWNLOAD_FAILED
        assert "404" in excinfo.value.log_line
        assert model_store.is_installed(str(tmp_path), model) is False

    def test_a_failure_on_the_first_file_leaves_no_directory_behind(
        self, entry, tmp_path
    ):
        model, contents = entry
        session = _FakeSession(
            _bodies(model, contents),
            failures={
                model_store.file_url(model, "config.json"): requests.HTTPError("500")
            },
        )

        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(model, str(tmp_path), session=session)

        assert not os.path.exists(model_store.model_dir(str(tmp_path), model.id))

    def test_no_part_file_survives_a_failure(self, entry, tmp_path):
        model, contents = entry
        session = _FakeSession(
            _bodies(model, contents, {"model.bin": contents["model.bin"][:-8]})
        )

        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(model, str(tmp_path), session=session)

        directory = model_store.model_dir(str(tmp_path), model.id)
        assert [n for n in os.listdir(directory) if n.endswith(".part")] == []

    def test_the_space_gate_runs_before_the_first_byte(
        self, entry, tmp_path, monkeypatch
    ):
        """Failing half way into a 3 GB download is failing after the choice
        the user could have made differently."""
        model, contents = entry
        monkeypatch.setattr(model_store, "free_bytes", lambda _path: model.download_bytes)
        session = _FakeSession(_bodies(model, contents))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(model, str(tmp_path), session=session)

        assert excinfo.value.code == errors.NO_DISK_SPACE
        assert session.requested == []
        assert not os.path.exists(model_store.model_dir(str(tmp_path), model.id))

    def test_cancelling_mid_file_leaves_nothing_that_looks_installed(
        self, entry, tmp_path
    ):
        """The whole point of the `.part` discipline: the install check trusts
        a name and a size, so a cancelled transfer must never own one — while
        the prefix itself is kept, under a name nothing believes, because that
        is what the next attempt resumes from."""
        model, contents = entry
        cancel = _CancelAfter(len(contents["config.json"]) + 1)
        session = _FakeSession(_bodies(model, contents))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(
                model,
                str(tmp_path),
                progress=cancel.progress,
                should_cancel=cancel,
                session=session,
            )

        assert excinfo.value.code == errors.CANCELLED
        directory = model_store.model_dir(str(tmp_path), model.id)
        assert model_store.is_installed(str(tmp_path), model) is False
        assert not os.path.exists(os.path.join(directory, "model.bin"))
        assert os.path.getsize(os.path.join(directory, "model.bin.part")) > 0
        # The file that did finish stays under its own name.
        assert "config.json" in _names_in(directory)

    def test_cancelling_before_anything_arrives_removes_the_new_directory(
        self, entry, tmp_path
    ):
        model, contents = entry
        session = _FakeSession(_bodies(model, contents))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(
                model, str(tmp_path), should_cancel=lambda: True, session=session
            )

        assert excinfo.value.code == errors.CANCELLED
        assert not os.path.exists(model_store.model_dir(str(tmp_path), model.id))

    def test_resuming_after_a_cancellation_refetches_only_what_is_missing(
        self, entry, tmp_path
    ):
        """Re-downloading 3 GB because the user cancelled at 99% is the
        difference between a feature and one nobody uses twice."""
        model, contents = entry
        cancel = _CancelAfter(len(contents["config.json"]) + 1)
        first = _FakeSession(_bodies(model, contents))
        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(
                model,
                str(tmp_path),
                progress=cancel.progress,
                should_cancel=cancel,
                session=first,
            )

        second = _FakeSession(_bodies(model, contents))
        model_store.download_model(model, str(tmp_path), session=second)

        assert model_store.file_url(model, "config.json") not in second.requested
        assert model_store.file_url(model, "model.bin") in second.requested
        assert model_store.is_installed(str(tmp_path), model) is True

    def test_a_file_of_the_wrong_size_is_fetched_again_not_kept(
        self, entry, tmp_path
    ):
        """Repairing an incomplete model is the same call as downloading it.

        "Already there" has to mean the exact size, not merely a file with that
        name: a truncated model.bin left by a process that was killed would
        otherwise be skipped by every future download, and the model would stay
        broken with nothing offering to fix it.
        """
        model, contents = entry
        directory = model_store.model_dir(str(tmp_path), model.id)
        os.makedirs(directory)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(contents["model.bin"][:100])
        session = _FakeSession(_bodies(model, contents))

        model_store.download_model(model, str(tmp_path), session=session)

        assert model_store.file_url(model, "model.bin") in session.requested
        assert model_store.is_installed(str(tmp_path), model) is True
        model_store.verify_model(str(tmp_path), model)

    def test_a_completed_model_sweeps_a_stale_part_from_an_older_attempt(
        self, entry, tmp_path
    ):
        """Nothing else on this path would: up to 3 GB of dead weight left by
        an attempt whose file has since arrived by other means."""
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "model.bin.part"), "wb") as fh:
            fh.write(b"A" * 128)

        model_store.download_model(model, str(tmp_path), session=_FakeSession({}))

        assert _names_in(directory) == sorted(contents)

    def test_a_second_download_of_a_complete_model_fetches_nothing(
        self, entry, tmp_path
    ):
        model, contents = entry
        model_store.download_model(
            model, str(tmp_path), session=_FakeSession(_bodies(model, contents))
        )

        progress = _Progress()
        again = _FakeSession({})
        model_store.download_model(
            model, str(tmp_path), progress=progress, session=again
        )

        assert again.requested == []
        assert progress.calls == [(model.download_bytes, model.download_bytes)]
        assert model_store.is_installed(str(tmp_path), model) is True

    def test_an_interrupted_model_bin_resumes_from_a_byte_range(
        self, entry, tmp_path
    ):
        """model.bin is 95-99% of a model, so "resuming costs the remainder"
        is only true if the *file* resumes. Cancelling large-v3 at 90% used to
        cost the whole 3 GB again."""
        model, contents = entry
        cancel = _CancelAfter(len(contents["config.json"]) + 1)
        first = _FakeSession(_bodies(model, contents))
        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(
                model,
                str(tmp_path),
                progress=cancel.progress,
                should_cancel=cancel,
                session=first,
            )
        part = os.path.join(
            model_store.model_dir(str(tmp_path), model.id), "model.bin.part"
        )
        carried = os.path.getsize(part)
        assert 0 < carried < model.model_bin_bytes

        progress = _Progress()
        second = _FakeSession(_bodies(model, contents))
        model_store.download_model(
            model, str(tmp_path), progress=progress, session=second
        )

        assert f"bytes={carried}-" in second.ranges
        assert second.served == (
            model.download_bytes - len(contents["config.json"]) - carried
        )
        assert model_store.is_installed(str(tmp_path), model) is True
        # The digest was re-seeded from the prefix rather than restarted, which
        # is the only way a streamed hash can survive an interruption.
        model_store.verify_model(str(tmp_path), model)

        done = [d for d, _t in progress.calls]
        assert done == sorted(done)
        assert done[-1] == model.download_bytes

    def test_a_server_that_ignores_the_range_starts_the_file_over(
        self, entry, tmp_path
    ):
        """Answering 200 to a Range request means the whole file is coming;
        appending it to the prefix would build a file out of duplicated bytes,
        which only model.bin's digest would ever catch."""
        model, contents = entry
        cancel = _CancelAfter(len(contents["config.json"]) + 1)
        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(
                model,
                str(tmp_path),
                progress=cancel.progress,
                should_cancel=cancel,
                session=_FakeSession(_bodies(model, contents)),
            )

        second = _FakeSession(_bodies(model, contents), honour_range=False)
        model_store.download_model(model, str(tmp_path), session=second)

        assert second.ranges[0] is not None  # it did ask
        assert model_store.is_installed(str(tmp_path), model) is True
        model_store.verify_model(str(tmp_path), model)

    def test_a_part_longer_than_the_file_is_not_resumed_from(self, entry, tmp_path):
        """A prefix is only a prefix while it is shorter. A `.part` at or past
        the expected size is a leftover from something else, and resuming from
        it would produce the right length out of the wrong bytes."""
        model, contents = entry
        directory = model_store.model_dir(str(tmp_path), model.id)
        os.makedirs(directory)
        with open(os.path.join(directory, "model.bin.part"), "wb") as fh:
            fh.write(b"Z" * (model.model_bin_bytes + 10))
        session = _FakeSession(_bodies(model, contents))

        model_store.download_model(model, str(tmp_path), session=session)

        assert session.ranges == [None] * len(model.files)
        model_store.verify_model(str(tmp_path), model)

    def test_an_auxiliary_part_is_never_resumed_from(self, entry, tmp_path):
        """Only a file with a digest may resume, and this is why.

        For config.json / tokenizer.json / vocabulary.* the only check is
        `written == expected_bytes`, and a stale `.part` that is NOT a prefix
        of the current file satisfies it exactly: the result has the catalogued
        size, so installation_state, is_installed, ensure_ready — and
        verify_model, which hashes only model.bin — all call the model healthy,
        and CTranslate2 then dies on the tokenizer with nothing but "internal
        error" for the user. A power cut or a kill leaves exactly that kind of
        `.part`, since fsync only runs at the end of the file.
        """
        model, contents = entry
        directory = model_store.model_dir(str(tmp_path), model.id)
        os.makedirs(directory)
        stale = b"#" * 8  # the right length to splice, the wrong bytes
        assert 0 < len(stale) < len(contents["tokenizer.json"])
        with open(os.path.join(directory, "tokenizer.json.part"), "wb") as fh:
            fh.write(stale)
        # And the figure the free-space gate counts agrees: a `.part` that
        # will be fetched again from byte 0 is not bytes already downloaded.
        assert model_store.remaining_download_bytes(str(tmp_path), model) == model.download_bytes
        session = _FakeSession(_bodies(model, contents))

        model_store.download_model(model, str(tmp_path), session=session)

        assert session.ranges == [None] * len(model.files)
        with open(os.path.join(directory, "tokenizer.json"), "rb") as fh:
            assert fh.read() == contents["tokenizer.json"]

    def test_a_206_that_starts_somewhere_else_is_not_appended(
        self, entry, tmp_path
    ):
        """206 says *a* range is coming, not *which* one. A body that starts at
        zero under a 206 label would be appended to the prefix and produce a
        file too long — or, with a stale prefix, the right length and the wrong
        bytes."""
        model, contents = entry
        cancel = _CancelAfter(len(contents["config.json"]) + 1)
        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(
                model,
                str(tmp_path),
                progress=cancel.progress,
                should_cancel=cancel,
                session=_FakeSession(_bodies(model, contents)),
            )

        liar = _FakeSession(
            _bodies(model, contents), honour_range=False, pretend_range=True
        )
        model_store.download_model(model, str(tmp_path), session=liar)

        assert liar.ranges[0] is not None  # it did ask for a range
        assert model_store.is_installed(str(tmp_path), model) is True
        model_store.verify_model(str(tmp_path), model)

    def test_the_bytes_reach_the_disk_before_the_rename(
        self, entry, tmp_path, monkeypatch
    ):
        """NTFS journals the rename, not the data: without the flush a power
        cut can leave a file of exactly the right size full of zeros under the
        final name, which the install check then believes forever."""
        model, contents = entry
        events = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(
            os, "replace", lambda src, dst: (events.append("replace"), real_replace(src, dst))[1]
        )

        model_store.download_model(
            model, str(tmp_path), session=_FakeSession(_bodies(model, contents))
        )

        assert events == ["fsync", "replace"] * len(model.files)

    def test_the_download_is_held_under_the_shared_models_lock(
        self, entry, tmp_path, monkeypatch
    ):
        """The root is global so every account process shares it: two of them
        downloading large-v3 at once open the same `model.bin.part`, interleave
        their writes and each one's cleanup deletes the other's file."""
        model, contents = entry
        events = _recording_locks(monkeypatch)

        model_store.download_model(
            model,
            str(tmp_path),
            progress=lambda done, total: events.append(("progress", done)),
            session=_FakeSession(_bodies(model, contents)),
        )

        assert events[0] == ("acquire", str(tmp_path))
        assert events[-1] == ("release", str(tmp_path))
        assert any(event[0] == "progress" for event in events[1:-1])

    def test_a_failure_does_not_leave_a_root_the_app_created(
        self, entry, tmp_path, monkeypatch
    ):
        """The user picks that folder in part 5; failing to use it is no
        reason to leave an empty directory of ours in their filesystem."""
        model, contents = entry
        root = str(tmp_path / "brand" / "new")
        session = _FakeSession(
            _bodies(model, contents),
            failures={model_store.file_url(model, "config.json"): requests.HTTPError("500")},
        )

        with pytest.raises(errors.TranscriptionError):
            model_store.download_model(model, root, session=session)

        assert not os.path.exists(root)

    def test_a_caller_supplied_session_is_left_open(self, entry, tmp_path):
        """It belongs to the caller — closing it would break the next call."""
        model, contents = entry
        session = _FakeSession(_bodies(model, contents))
        model_store.download_model(model, str(tmp_path), session=session)
        assert session.closed is False


class TestAnOverlongAnswerIsCutShort:
    """A server that keeps sending is stopped at the expected size.

    Measured only at the end, the excess would be written first — for a 3 GB
    file, a misbehaving mirror could fill the disk before the size check ran.
    """

    def test_the_transfer_stops_once_it_passes_the_catalogued_size(self, entry, tmp_path):
        model, contents = entry
        root = str(tmp_path)
        too_long = contents["model.bin"] * 4
        session = _FakeSession(_bodies(model, contents, {"model.bin": too_long}), slices=8)

        with pytest.raises(errors.TranscriptionError) as caught:
            model_store.download_model(model, root, session=session)

        assert caught.value.code == errors.MODEL_CORRUPTED
        # Everything before model.bin, plus at most one chunk past its size.
        before = sum(len(contents[name]) for name, _s in model.files[:1])
        assert session.served - before <= len(contents["model.bin"]) + len(too_long) // 8
        directory = model_store.model_dir(root, model.id)
        assert not os.path.exists(os.path.join(directory, "model.bin"))
        assert not os.path.exists(os.path.join(directory, "model.bin.part"))


class TestVerifyModel:
    def test_a_good_model_verifies(self, entry, tmp_path):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        model_store.verify_model(str(tmp_path), model)

    def test_verification_reports_progress_over_the_weights(self, entry, tmp_path):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        progress = _Progress()

        model_store.verify_model(str(tmp_path), model, progress=progress)

        assert progress.calls[-1] == (model.model_bin_bytes, model.model_bin_bytes)

    def test_swapped_weights_of_the_same_length_are_caught(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(b"Z" * model.model_bin_bytes)

        # The cheap check still says installed, which is exactly why the
        # expensive one exists.
        assert model_store.is_installed(str(tmp_path), model) is True
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.verify_model(str(tmp_path), model)
        assert excinfo.value.code == errors.MODEL_CORRUPTED

    def test_an_absent_model_is_not_installed_rather_than_corrupted(
        self, entry, tmp_path
    ):
        """Two different answers for the user: download it, versus download it
        again because what is there is broken."""
        model, _contents = entry
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.verify_model(str(tmp_path), model)
        assert excinfo.value.code == errors.MODEL_NOT_INSTALLED

    def test_an_incomplete_model_is_corrupted(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        os.remove(os.path.join(directory, "vocabulary.txt"))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.verify_model(str(tmp_path), model)
        assert excinfo.value.code == errors.MODEL_CORRUPTED
        assert "vocabulary.txt" in excinfo.value.log_line

    def test_verification_can_be_cancelled(self, entry, tmp_path):
        """Up to 3 GB of reading. A user who changed their mind has to be able
        to say so and be believed."""
        model, contents = entry
        _write_model(str(tmp_path), model, contents)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.verify_model(
                str(tmp_path), model, should_cancel=lambda: True
            )
        assert excinfo.value.code == errors.CANCELLED


class TestRemoveModel:
    def test_only_the_catalogue_names_are_deleted(self, entry, tmp_path):
        """Part 5 lets the user choose the models folder, and somebody will
        choose one that already holds their own files. A shutil.rmtree() there
        only has to be wrong once."""
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        stranger = os.path.join(directory, "notes-of-my-own.txt")
        with open(stranger, "wb") as fh:
            fh.write(b"something the user put here")

        assert model_store.remove_model(str(tmp_path), model.id) is True

        assert _names_in(directory) == ["notes-of-my-own.txt"]
        with open(stranger, "rb") as fh:
            assert fh.read() == b"something the user put here"
        assert model_store.is_installed(str(tmp_path), model) is False

    def test_an_emptied_directory_is_removed(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        model_store.remove_model(str(tmp_path), model.id)
        assert not os.path.exists(directory)

    def test_leftover_part_files_go_too(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "model.bin.part"), "wb") as fh:
            fh.write(b"A" * 10)

        model_store.remove_model(str(tmp_path), model.id)
        assert not os.path.exists(directory)

    def test_removing_what_is_not_there_is_not_an_error(self, entry, tmp_path):
        model, _contents = entry
        assert model_store.remove_model(str(tmp_path), model.id) is False

    def test_the_removal_is_held_under_the_shared_models_lock(
        self, entry, tmp_path, monkeypatch
    ):
        """Deleting a model another process is downloading into is exactly
        what the lock is for."""
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        events = _recording_locks(monkeypatch)

        assert model_store.remove_model(str(tmp_path), model.id) is True

        assert events == [("acquire", str(tmp_path)), ("release", str(tmp_path))]

    def test_an_unknown_id_deletes_nothing(self, entry, tmp_path):
        """The names to delete are exactly what the catalogue no longer knows,
        so there is nothing that can be removed safely."""
        directory = os.path.join(str(tmp_path), "retired-model")
        os.makedirs(directory)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(b"A" * 16)

        assert model_store.remove_model(str(tmp_path), "retired-model") is False
        assert _names_in(directory) == ["model.bin"]


class TestRepairModel:
    """The one state a re-download cannot fix, and the only way out of it."""

    def test_a_download_cannot_replace_weights_of_the_right_size(
        self, entry, tmp_path
    ):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(b"Z" * model.model_bin_bytes)

        idle = _FakeSession(_bodies(model, contents))
        model_store.download_model(model, str(tmp_path), session=idle)

        # Nothing was fetched and the call reported success: installation_state
        # calls this installed, so every file is "already there".
        assert idle.requested == []
        with pytest.raises(errors.TranscriptionError):
            model_store.verify_model(str(tmp_path), model)

    def test_repair_deletes_first_and_downloads_everything_again(
        self, entry, tmp_path
    ):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        with open(os.path.join(directory, "model.bin"), "wb") as fh:
            fh.write(b"Z" * model.model_bin_bytes)
        session = _FakeSession(_bodies(model, contents))

        assert model_store.repair_model(model, str(tmp_path), session=session) == directory

        assert sorted(session.requested) == sorted(
            model_store.file_url(model, name) for name, _size in model.files
        )
        model_store.verify_model(str(tmp_path), model)

    def test_repair_reports_progress_over_the_whole_model(self, entry, tmp_path):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        progress = _Progress()

        model_store.repair_model(
            model,
            str(tmp_path),
            progress=progress,
            session=_FakeSession(_bodies(model, contents)),
        )

        assert progress.calls[-1] == (model.download_bytes, model.download_bytes)

    def test_repair_holds_the_lock_across_the_delete_and_the_download(
        self, entry, tmp_path, monkeypatch
    ):
        """Between the two is the window another process could start its own
        download into the directory this one just emptied."""
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        events = _recording_locks(monkeypatch)

        model_store.repair_model(
            model,
            str(tmp_path),
            progress=lambda done, total: events.append(("progress", done)),
            session=_FakeSession(_bodies(model, contents)),
        )

        assert events[0] == ("acquire", str(tmp_path))
        assert events[-1] == ("release", str(tmp_path))
        # The inner calls re-enter the same lock rather than taking a new one.
        assert any(event[0] == "progress" for event in events[1:-1])


class TestEnsureReady:
    """What part 3 calls right before handing a path to CTranslate2.

    The two failures are different sentences for the user — download it, versus
    repair it — and choosing between them may not cost 3 GB of hashing before a
    transcription that has not started.
    """

    def test_a_complete_model_answers_with_its_directory(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        assert model_store.ensure_ready(str(tmp_path), model.id) == directory

    def test_an_absent_model_is_not_installed(self, entry, tmp_path):
        model, _contents = entry
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.ensure_ready(str(tmp_path), model.id)
        assert excinfo.value.code == errors.MODEL_NOT_INSTALLED

    def test_an_incomplete_model_is_corrupted(self, entry, tmp_path):
        model, contents = entry
        directory = _write_model(str(tmp_path), model, contents)
        os.remove(os.path.join(directory, "config.json"))
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.ensure_ready(str(tmp_path), model.id)
        assert excinfo.value.code == errors.MODEL_CORRUPTED
        assert "config.json" in excinfo.value.log_line

    def test_an_id_the_catalogue_dropped_is_not_installed(self, entry, tmp_path):
        """A settings file naming a model a later version retired. "Not
        installed" is the one answer the UI can act on."""
        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.ensure_ready(str(tmp_path), "retired-model")
        assert excinfo.value.code == errors.MODEL_NOT_INSTALLED

    def test_it_does_not_read_the_weights(self, entry, tmp_path, monkeypatch):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        monkeypatch.setattr(
            model_store, "_hash_file", lambda *args, **kwargs: pytest.fail("hashed")
        )
        model_store.ensure_ready(str(tmp_path), model.id)


class TestUnknownDirs:
    """A model retired by an update becomes invisible and undeletable.

    remove_model() will not delete names the catalogue cannot look up, and
    nothing lists it, so the user's 3 GB sits there with no screen mentioning
    it. This is what part 5 shows.
    """

    def test_a_retired_model_directory_is_reported(self, entry, tmp_path):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        os.makedirs(os.path.join(str(tmp_path), "retired-model"))

        assert model_store.list_unknown_dirs(str(tmp_path)) == ("retired-model",)

    def test_files_beside_the_models_are_not_reported_as_directories(
        self, entry, tmp_path
    ):
        with open(os.path.join(str(tmp_path), "notes-of-my-own.txt"), "wb") as fh:
            fh.write(b"something the user put here")
        assert model_store.list_unknown_dirs(str(tmp_path)) == ()

    def test_a_root_that_does_not_exist_is_empty_not_an_error(self, tmp_path):
        assert model_store.list_unknown_dirs(str(tmp_path / "nothing")) == ()


class TestABusyModelsDirectory:
    """Another window holding the folder is not a download failure.

    The models root is global so every account process shares it, and waiting
    behind another window multi-gigabyte download is correct behaviour — but it
    has to be *said* correctly. MODEL_DOWNLOAD_FAILED tells the user to check a
    connection that is fine, and remove_model() answering False for it told them
    nothing was deleted without saying whether their 3 GB is still there.
    """

    def test_a_download_says_the_folder_is_busy(self, entry, tmp_path, monkeypatch):
        model, contents = entry
        _busy_locks(monkeypatch)
        session = _FakeSession(_bodies(model, contents))

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.download_model(model, str(tmp_path), session=session)

        assert excinfo.value.code == errors.MODELS_BUSY
        assert session.requested == []

    def test_a_removal_raises_instead_of_answering_nothing_was_there(
        self, entry, tmp_path, monkeypatch
    ):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.remove_model(str(tmp_path), model.id)

        assert excinfo.value.code == errors.MODELS_BUSY
        # And nothing was touched, which is what a False return could not have
        # distinguished itself from.
        assert model_store.is_installed(str(tmp_path), model) is True

    def test_a_repair_says_the_folder_is_busy(self, entry, tmp_path, monkeypatch):
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.repair_model(
                model, str(tmp_path), session=_FakeSession(_bodies(model, contents))
            )

        assert excinfo.value.code == errors.MODELS_BUSY

    def test_a_move_says_the_folder_is_busy(self, entry, tmp_path, monkeypatch):
        model, contents = entry
        old_root = str(tmp_path / "old")
        _write_model(old_root, model, contents)
        _busy_locks(monkeypatch)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.move_models(old_root, str(tmp_path / "new"))

        assert excinfo.value.code == errors.MODELS_BUSY
        assert model_store.list_installed(old_root) == (model.id,)

    def test_waiting_for_the_lock_is_still_cancellable(
        self, entry, tmp_path, monkeypatch
    ):
        """The Cancel button is the real bound on the wait — the deadline is a
        backstop against a lock nobody will ever release, twelve hours out."""
        model, contents = entry
        _write_model(str(tmp_path), model, contents)
        monkeypatch.setattr(
            model_store,
            "models_lock",
            lambda root, lock_dir, timeout=None: _AlwaysBusyLock(root),
        )

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.remove_model(
                str(tmp_path), model.id, should_cancel=lambda: True
            )

        assert excinfo.value.code == errors.CANCELLED
        assert model_store.is_installed(str(tmp_path), model) is True


class TestCatalogueFileNames:
    """Catalogue names are joined onto a user-chosen directory and deleted by
    name, so a nested layout ("snapshots/<sha>/model.bin", the shape these
    repositories use internally) or a ".." would have remove_model() reach
    outside the models root."""

    @pytest.mark.parametrize("model", model_catalog.list_models(), ids=lambda m: m.id)
    def test_every_catalogued_name_is_a_bare_basename(self, model):
        for name, _size in model.files:
            assert os.path.basename(name) == name
            assert name not in (".", "..")
            assert "/" not in name and "\\" not in name

    @pytest.mark.parametrize(
        "bad", ["snapshots/abc/model.bin", "..\\model.bin", "..", "/model.bin", ""]
    )
    def test_a_name_that_is_not_a_basename_is_refused(self, bad):
        with pytest.raises(AssertionError):
            model_catalog._model(
                "synthetic",
                "example-org/synthetic",
                "0" * 40,
                "0" * 64,
                ((bad, 1), ("model.bin", 2)),
                model_catalog.SIZE_SMALL,
                min_vram_mb=1024,
                min_ram_mb=2048,
            )


class TestMoveModels:
    def test_every_installed_model_ends_up_at_the_new_root(self, two_entries, tmp_path):
        (first, first_contents), (second, second_contents) = two_entries
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, first, first_contents)
        _write_model(old_root, second, second_contents)

        moved = model_store.move_models(old_root, new_root)

        assert moved == (first.id, second.id)
        assert model_store.list_installed(new_root) == (first.id, second.id)
        assert model_store.list_installed(old_root) == ()
        with open(os.path.join(new_root, second.id, "model.bin"), "rb") as fh:
            assert fh.read() == second_contents["model.bin"]

    def test_the_move_reports_progress_to_the_total(self, two_entries, tmp_path):
        (first, first_contents), (second, second_contents) = two_entries
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, first, first_contents)
        _write_model(old_root, second, second_contents)
        progress = _Progress()

        model_store.move_models(old_root, new_root, progress=progress)

        total = first.disk_bytes + second.disk_bytes
        assert all(t == total for _d, t in progress.calls)
        done = [d for d, _t in progress.calls]
        assert done == sorted(done)
        assert done[-1] == total

    def test_an_interrupted_move_leaves_every_model_whole_somewhere(
        self, two_entries, tmp_path, monkeypatch
    ):
        """The reason this is a copy-verify-delete and not a shutil.move() per
        file: a move empties the source as it fills the destination, so an
        interruption leaves both roots incomplete and the user with nothing
        that loads."""
        (first, first_contents), (second, second_contents) = two_entries
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, first, first_contents)
        _write_model(old_root, second, second_contents)
        # The copy path is the one with an invariant to keep; a same-volume
        # move is a single rename and has no half way through.
        monkeypatch.setattr(model_store, "_try_rename", lambda *_args: False)
        cancel = _CancelAfter(first.disk_bytes + len(second_contents["config.json"]) + 1)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.move_models(
                old_root, new_root, progress=cancel.progress, should_cancel=cancel
            )

        assert excinfo.value.code == errors.CANCELLED
        assert model_store.list_installed(new_root) == (first.id,)
        assert model_store.list_installed(old_root) == (second.id,)
        second_dir = model_store.model_dir(new_root, second.id)
        if os.path.isdir(second_dir):
            assert [n for n in os.listdir(second_dir) if n.endswith(".part")] == []

    def test_a_destination_that_cannot_be_written_keeps_the_source(
        self, two_entries, tmp_path
    ):
        (first, first_contents), (second, second_contents) = two_entries
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, first, first_contents)
        _write_model(old_root, second, second_contents)
        # A plain file where the first model's directory would go.
        os.makedirs(new_root)
        blocker = os.path.join(new_root, first.id)
        with open(blocker, "wb") as fh:
            fh.write(b"in the way")

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.move_models(old_root, new_root)

        # Its own code: after a failed move nothing is corrupted — the models
        # are whole in the folder they were already in — and MODEL_CORRUPTED
        # would tell the user to download 3 GB again when the way out is to
        # pick a different folder.
        assert excinfo.value.code == errors.MODEL_MOVE_FAILED
        assert model_store.list_installed(old_root) == (first.id, second.id)
        with open(blocker, "rb") as fh:
            assert fh.read() == b"in the way"

    def test_a_model_already_at_the_destination_is_not_copied_again(
        self, entry, tmp_path
    ):
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)
        _write_model(new_root, model, contents)

        moved = model_store.move_models(old_root, new_root)

        assert moved == (model.id,)
        assert model_store.list_installed(new_root) == (model.id,)
        assert not os.path.exists(model_store.model_dir(old_root, model.id))

    def test_moving_a_root_onto_itself_does_nothing(self, entry, tmp_path):
        model, contents = entry
        root = str(tmp_path / "models")
        _write_model(root, model, contents)

        assert model_store.move_models(root, root) == ()
        assert model_store.list_installed(root) == (model.id,)

    def test_a_destination_without_room_keeps_the_source_untouched(
        self, entry, tmp_path, monkeypatch
    ):
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)
        monkeypatch.setattr(model_store, "_try_rename", lambda *_args: False)
        monkeypatch.setattr(model_store, "free_bytes", lambda _path: model.disk_bytes)

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.move_models(old_root, new_root)

        assert excinfo.value.code == errors.NO_DISK_SPACE
        assert model_store.list_installed(old_root) == (model.id,)
        assert not os.path.exists(new_root)

    def test_a_failure_part_way_still_says_which_models_crossed(
        self, two_entries, tmp_path, monkeypatch
    ):
        """Every model stays whole in exactly one root either way — but "the
        first one is in the new folder and the second is not" is the only thing
        part 5 can tell the user, and a bare error code loses it."""
        (first, first_contents), (second, second_contents) = two_entries
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, first, first_contents)
        _write_model(old_root, second, second_contents)
        monkeypatch.setattr(model_store, "_try_rename", lambda *_args: False)
        # Room for the first model and none for the second.
        answers = [10 ** 9, 0]
        monkeypatch.setattr(
            model_store, "free_bytes", lambda _path: answers.pop(0) if answers else 0
        )

        with pytest.raises(errors.TranscriptionError) as excinfo:
            model_store.move_models(old_root, new_root)

        assert excinfo.value.code == errors.NO_DISK_SPACE
        assert excinfo.value.moved == (first.id,)
        assert first.id in excinfo.value.log_line
        assert model_store.list_installed(new_root) == (first.id,)
        assert model_store.list_installed(old_root) == (second.id,)

    def test_a_same_volume_move_is_a_rename_and_needs_no_free_space(
        self, entry, tmp_path, monkeypatch
    ):
        """Moving 5 GB to another folder on the same disk was refused with
        5.4 GB free, for a rename that is atomic, instant and costs nothing."""
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)
        monkeypatch.setattr(model_store, "free_bytes", lambda _path: 0)

        assert model_store.move_models(old_root, new_root) == (model.id,)

        assert model_store.list_installed(new_root) == (model.id,)
        assert not os.path.exists(model_store.model_dir(old_root, model.id))

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="two spellings are one directory only on a case-folding filesystem",
    )
    def test_two_spellings_of_one_root_are_not_a_move(self, entry, tmp_path):
        """The reproduced data-loss bug: os.path.abspath normalises separators
        and "..", but it does not fold case and does not resolve junctions or
        subst drives — the filesystem does. So the models were found already at
        the destination, because they ARE the destination, and then deleted as
        pure duplication of themselves: up to 3 GB, reported as a completed
        move. canonical_dir() is the repository's existing answer to exactly
        this, and coord_locks has carried it since multi-account shipped."""
        model, contents = entry
        root = str(tmp_path / "Whisper_Models")
        _write_model(root, model, contents)
        other_spelling = str(tmp_path / "whisper_models")

        assert model_store.move_models(root, other_spelling) == ()

        assert model_store.list_installed(root) == (model.id,)
        assert model_store.list_installed(other_spelling) == (model.id,)
        model_store.verify_model(root, model)

    def test_a_linked_model_directory_is_not_deleted_as_a_duplicate(
        self, entry, tmp_path
    ):
        """Two roots can canonicalise apart and still share one model folder —
        a user who linked a single 3 GB model onto another disk. The
        already-at-the-destination branch reads the same files through the link,
        answers "installed", and would then delete the source as pure
        duplication of itself."""
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        source = _write_model(old_root, model, contents)
        os.makedirs(new_root)
        created, detail = _link_directory(
            source, model_store.model_dir(new_root, model.id)
        )
        assert created, f"could not create a directory link: {detail}"

        assert model_store.move_models(old_root, new_root) == (model.id,)

        assert model_store.list_installed(new_root) == (model.id,)
        assert model_store.list_installed(old_root) == (model.id,)
        model_store.verify_model(old_root, model)

    def test_an_incomplete_model_travels_and_arrives_as_incomplete(
        self, entry, tmp_path, monkeypatch
    ):
        """Left behind, it would sit in a directory no screen in part 5 ever
        looks at again — invisible, and undeletable from inside the app."""
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        directory = _write_model(old_root, model, contents)
        os.remove(os.path.join(directory, "tokenizer.json"))
        with open(os.path.join(directory, "vocabulary.txt"), "wb") as fh:
            fh.write(contents["vocabulary.txt"][:-2])  # a half-written file
        monkeypatch.setattr(model_store, "_try_rename", lambda *_args: False)

        assert model_store.move_models(old_root, new_root) == (model.id,)

        state = model_store.installation_state(new_root, model)
        assert state.state == model_store.STATE_INCOMPLETE
        assert sorted(state.missing) == ["tokenizer.json", "vocabulary.txt"]
        assert _names_in(model_store.model_dir(new_root, model.id)) == [
            "config.json", "model.bin", "vocabulary.txt",
        ]
        assert not os.path.exists(model_store.model_dir(old_root, model.id))

    def test_the_move_is_held_under_both_roots_locks(
        self, entry, tmp_path, monkeypatch
    ):
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)
        events = _recording_locks(monkeypatch)

        model_store.move_models(old_root, new_root)

        # A set, not a list: the inner remove_model_files() re-enters the same lock
        # on the real one, and how many times is not what this pins.
        held = {root for action, root in events if action == "acquire"}
        assert held == {old_root, new_root}
        assert [action for action, _root in events[-2:]] == ["release", "release"]

    def test_the_old_root_itself_is_left_alone(self, entry, tmp_path):
        """It may be a folder the user made and pointed WinZapp at; moving
        files out of a directory is not permission to delete it."""
        model, contents = entry
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)

        model_store.move_models(old_root, new_root)

        assert os.path.isdir(old_root)


# ── Both catalogues share the root ───────────────────────────────────────────


def _synthetic_ggml(model_id, data):
    """A GGML entry of a few bytes — one file, as every whisper.cpp model is."""
    return whisper_cpp_catalog.GgmlFile(
        id=model_id,
        repo="example-org/whisper.cpp",
        revision=model_id.encode().hex().ljust(40, "0")[:40],
        filename=f"{model_id}.bin",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        base_model="tiny",
        quantization=whisper_cpp_catalog.QUANT_Q5_1,
        size_class=model_catalog.SIZE_SMALL,
    ), {f"{model_id}.bin": data}


@pytest.fixture
def shared_root(entry, monkeypatch):
    """The faster-whisper `entry`, one GGML file and the voice-activity model,
    standing in for both catalogues."""
    ggml = _synthetic_ggml("ggml-gamma-q5_1", b"G" * 2048)
    vad = _synthetic_ggml("ggml-silero-test", b"V" * 512)
    monkeypatch.setattr(whisper_cpp_catalog, "MODELS", (ggml[0],))
    monkeypatch.setattr(whisper_cpp_catalog, "VAD_MODEL", vad[0])
    return entry, ggml, vad


class TestBothCataloguesShareTheRoot:
    """The GGML files and the filter's model live in the faster-whisper models
    root. Whatever walks or deletes in there and only knew one catalogue would
    call the other's folders strangers — or leave them behind on a move, where
    nothing lists them again."""

    def test_an_id_is_found_in_either_catalogue(self, shared_root):
        (model, _contents), (ggml, _g), (vad, _v) = shared_root
        assert model_store.find_entry(model.id) is model
        assert model_store.find_entry(ggml.id) is ggml
        assert model_store.find_entry(vad.id) is vad
        assert model_store.find_entry("retired-model") is None

    def test_every_entry_is_listed_with_the_filter_last(self, shared_root):
        (model, _contents), (ggml, _g), (vad, _v) = shared_root
        assert model_store.all_entries() == (model, ggml, vad)

    def test_ggml_and_filter_folders_are_not_strangers(self, shared_root, tmp_path):
        (model, contents), (ggml, ggml_contents), (vad, vad_contents) = shared_root
        root = str(tmp_path)
        _write_model(root, model, contents)
        _write_model(root, ggml, ggml_contents)
        _write_model(root, vad, vad_contents)
        os.makedirs(os.path.join(root, "ggml-retired"))

        # A ggml- name the catalogue dropped is still a stranger: the prefix
        # alone says nothing about which files are safe to delete.
        assert model_store.list_unknown_dirs(root) == ("ggml-retired",)

    def test_a_move_carries_the_ggml_files_and_the_filter(self, shared_root, tmp_path):
        (model, contents), (ggml, ggml_contents), (vad, vad_contents) = shared_root
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, model, contents)
        _write_model(old_root, ggml, ggml_contents)
        _write_model(old_root, vad, vad_contents)

        moved = model_store.move_models(old_root, new_root)

        assert moved == (model.id, ggml.id, vad.id)
        for entry_moved in (model, ggml, vad):
            assert model_store.is_installed(new_root, entry_moved)
            assert not os.path.exists(model_store.model_dir(old_root, entry_moved.id))

    def test_a_copied_ggml_file_leaves_nothing_at_the_source(
        self, shared_root, tmp_path, monkeypatch
    ):
        """The copy path deletes the source by the entry it already holds;
        a removal by id that only knew faster-whisper's catalogue would have
        refused, leaving a duplicate GGML file in the old folder."""
        _entry, (ggml, ggml_contents), _vad = shared_root
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        _write_model(old_root, ggml, ggml_contents)
        monkeypatch.setattr(model_store, "_try_rename", lambda *_args: False)

        assert model_store.move_models(old_root, new_root) == (ggml.id,)

        assert model_store.is_installed(new_root, ggml)
        assert not os.path.exists(model_store.model_dir(old_root, ggml.id))

    def test_a_ggml_duplicate_already_at_the_destination_is_removed_at_the_source(
        self, shared_root, tmp_path
    ):
        _entry, (ggml, ggml_contents), _vad = shared_root
        old_root = str(tmp_path / "old")
        new_root = str(tmp_path / "new")
        source = _write_model(old_root, ggml, ggml_contents)
        stranger = os.path.join(source, "notes-of-my-own.txt")
        with open(stranger, "wb") as fh:
            fh.write(b"something the user put here")
        _write_model(new_root, ggml, ggml_contents)

        assert model_store.move_models(old_root, new_root) == (ggml.id,)

        # Only the catalogued file went; the user's own stays.
        assert _names_in(source) == ["notes-of-my-own.txt"]

    def test_a_ggml_model_is_removed_by_its_id(self, shared_root, tmp_path):
        _entry, (ggml, ggml_contents), _vad = shared_root
        directory = _write_model(str(tmp_path), ggml, ggml_contents)

        assert model_store.remove_model(str(tmp_path), ggml.id) is True

        assert not os.path.exists(directory)


# ── The one test that reaches Hugging Face ───────────────────────────────────

_CATALOGUE_FILES = [
    (model, name, size)
    for model in model_catalog.list_models()
    for name, size in model.files
]
_CATALOGUE_IDS = [f"{model.id}-{name}" for model, name, _size in _CATALOGUE_FILES]


class TestTheCatalogueUrlsAreLive:
    """Every URL the catalogue offers must serve exactly the bytes it claims.

    "No model may offer a broken link" is an explicit requirement, and it is
    not something the fake session can answer: a wrong repo name, an unpublished
    revision or a file renamed upstream all look perfectly fine from here. This
    is the only test in the suite that talks to a remote host, so it is skipped
    unless asked for — run it by hand whenever the catalogue changes.
    """

    pytestmark = [
        pytest.mark.network,
        pytest.mark.skipif(
            os.environ.get(_NETWORK_OPT_IN_ENV, "").strip() in ("", "0", "false", "False"),
            reason=f"reaches huggingface.co - set {_NETWORK_OPT_IN_ENV}=1 to run it",
        ),
    ]

    @pytest.mark.parametrize("model, name, size", _CATALOGUE_FILES, ids=_CATALOGUE_IDS)
    def test_the_url_serves_exactly_the_catalogued_size(self, model, name, size):
        url = model_store.file_url(model, name)
        # Through the same session the download itself uses, not a bare
        # requests.head(): on a machine whose TLS is intercepted (an antivirus
        # scanning HTTPS is enough) certifi does not know the injected root and
        # every one of these fails with CERTIFICATE_VERIFY_FAILED — which reads
        # exactly like the broken link this test exists to catch. Measured here:
        # bare requests failed all 26 while curl fetched all 26 fine.
        with tls_trust.create_session() as session:
            # Accept-Encoding: identity because the question here is how many
            # bytes the file HAS, not how many the server would send. requests
            # advertises gzip/deflate/zstd by default, and Hugging Face answers
            # a compressible JSON with no Content-Length at all — which is not a
            # broken link, but reads as one. The LFS weights were unaffected
            # (already compressed), so this only ever hid the small files.
            response = session.head(
                url,
                allow_redirects=True,
                timeout=30,
                headers={"Accept-Encoding": "identity"},
            )

        assert response.status_code == 200, f"{url} answered {response.status_code}"
        # Followed to the CDN, an LFS file answers with the real Content-Length;
        # answered by Hugging Face itself, the pointer's own length is returned
        # and the real one comes back in x-linked-size.
        reported = response.headers.get("Content-Length") or response.headers.get(
            "x-linked-size"
        )
        assert reported is not None, f"{url} reported no size at all"
        assert int(reported) == size, f"{url} is {reported} bytes, catalogue says {size}"
