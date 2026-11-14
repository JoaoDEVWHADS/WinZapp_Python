"""The one CUDA library CTranslate2 opens by name, fetched on demand.

`device._CUDA_RUNTIME_LIBRARIES` explains *why* this module exists: the
ctranslate2 wheel does not ship cuBLAS, ctranslate2.dll opens it by name the
first time a model goes on the GPU, and on a machine with an NVIDIA driver and
no CUDA Toolkit — which is nearly every machine that installs a release — the
device is counted, "cuda" is chosen, and the model load dies with "Could not
load library cublas64_12.dll". Part 4a made that a measured veto with a reason
of its own. This is the answer to it: telling a user that something is missing
without telling them how to get it is only half a fix.

The decisions worth more than the code:

* **The wheel is pinned, whole, by digest — never "the latest".** NVIDIA
  publishes cuBLAS on PyPI as a plain wheel, which is a zip. The URL, the byte
  count and the sha256 below were read off the published file, and the series
  (12.9) is not an arbitrary "recent": Blackwell (sm_120) needs cuBLAS kernels
  from 12.8 or newer, and sm_120 is the card the whole feature was reported
  from. A URL that followed the newest release would change the bytes under a
  digest that no longer describes them, and the only symptom a user would get
  is the same silent fall back to the processor.

* **Only the DLLs that are actually loaded are installed.** The wheel is
  772 MB unpacked across 14 files; two of them matter. cublas64_12.dll is what
  CTranslate2 opens, and cublasLt64_12.dll is in *its* import table, so the
  Windows loader resolves the second out of the same directory. nvblas64_12.dll
  is a Fortran BLAS shim nothing here calls, and cuDNN is not in this wheel at
  all — nor is it needed (see `device._CUDA_RUNTIME_LIBRARIES`, where that was
  measured twice rather than assumed).

* **The wheel's own RECORD is the manifest, copied verbatim.** Every wheel
  carries `dist-info/RECORD`, listing the sha256 and the exact size of every
  file inside it, and the wheel's own digest — checked while the bytes go
  past — is what makes that list trustworthy. So the extracted DLLs are checked
  against it, and it is written next to them so the *installed* state stays
  checkable later, cheaply by size and expensively by hash, without this module
  hardcoding a second copy of numbers the wheel already states.

* **RECORD is written last, and that is the commit.** Every other file is
  published only after its digest matched, and RECORD landing last means an
  interrupted install can never look complete: `installation_state()` needs the
  manifest and both libraries, so a crash between the two DLLs leaves
  INCOMPLETE rather than a directory that lies.

* **Nothing is resumed, and that is deliberate**, unlike model_store's
  multi-gigabyte weights. The wheel is scratch — it is deleted the moment the
  DLLs are published — and a failed or cancelled install sweeps every `.part`
  it wrote, so there is never a prefix left to resume from. Cleaning up and
  resuming are the same decision made two ways; the requirement here is the
  cleanup, because half a gigabyte of dead `.part` in the shared global folder
  is invisible to the user and nothing else would ever collect it. The digest
  settles it from the other side too: it is computed as the bytes go past, so
  resuming would mean reading the whole prefix back off the disk to rebuild the
  hash before asking for the rest.

* **The answer is not "downloaded", it is "the GPU works now".** Installing
  ends by registering the directory with the Windows loader and re-asking
  `device.probe_cuda_libraries()`, and *that* is what comes back. A caller has
  no use for "the bytes arrived" — a DLL that is present and will not load is
  exactly the state part 4a already vetoes the GPU for.

* **Being under `global_dir()` means being shared**, so every mutation takes
  the same cross-process lock the models do: two account processes asking for
  this at the same moment would otherwise write one another's `.part` files.

No user-facing text lives here: failures travel as TranscriptionError codes and
the UI layer turns them into a sentence.
"""

from __future__ import annotations

import base64
import contextlib
import csv
import errno
import glob
import hashlib
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass

from app_paths import global_dir
from coord_locks import LockTimeout, models_lock
from core import tls_trust
from core.transcription import device, errors, model_store
from core.transcription._fileops import (
    check_cancel as _check_cancel,
    remove_empty_dir as _remove_empty_dir,
    report as _report,
    unlink as _unlink,
)

# Subdirectory of the global data dir holding the installed libraries.
CUDA_RUNTIME_DIRNAME = "cuda_runtime"

# The published NVIDIA cuBLAS wheel for CUDA 12, pinned as one unit: version,
# file name, size, digest and URL all describe the same artifact, and changing
# any one of them without the others is how a "small update" starts failing as
# a corrupted download.
WHEEL_VERSION = "12.9.2.10"
WHEEL_FILENAME = f"nvidia_cublas_cu12-{WHEEL_VERSION}-py3-none-win_amd64.whl"
WHEEL_BYTES = 553_162_896
WHEEL_SHA256 = "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"
WHEEL_URL = (
    "https://files.pythonhosted.org/packages/20/e2/"
    "fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
    + WHEEL_FILENAME
)

# The wheel's own metadata directory, and the manifest inside it. Both carry
# the pinned version, so they move with the pin rather than being searched for
# - and that is also how a directory installed by a *previous* pin is
# recognised: the manifest left on disk names its own dist-info, so it says
# which wheel it came out of. Without that, an install of the previous version
# is indistinguishable from a current one (the libraries are there, the sizes
# match the manifest beside them) and nobody who already installed 12.8 would
# ever be given the 12.9 kernels sm_120 needs.
_DIST_INFO_PREFIX = f"nvidia_cublas_cu12-{WHEEL_VERSION}.dist-info/"
_RECORD_MEMBER = _DIST_INFO_PREFIX + "RECORD"
RECORD_FILENAME = "RECORD"

# The same directory name with the version left open, so a manifest written by
# a pin that is not this one can still say which pin it was. Anchored, and the
# version is everything up to ".dist-info/", which is what a wheel's own
# escaping guarantees is there.
_DIST_INFO_RE = re.compile(r"^nvidia_cublas_cu12-(.+?)\.dist-info/")

# (name on disk, path inside the wheel) for every file installed, RECORD aside.
# Flattened out of nvidia/cublas/bin/ on purpose: the directory registered with
# the loader has to be the one holding the DLLs themselves, and a folder of two
# files is also what makes the uninstall able to name everything it deletes.
_LIBRARY_MEMBERS = (
    ("cublas64_12.dll", "nvidia/cublas/bin/cublas64_12.dll"),
    # Not opened by name from anywhere — it is in cuBLAS's import table, so the
    # loader resolves it out of this same directory. Leaving it behind would
    # make cublas64_12.dll present and unloadable, which is the one state that
    # looks installed and is not.
    ("cublasLt64_12.dll", "nvidia/cublas/bin/cublasLt64_12.dll"),
)

#: Names this module puts on disk, and the only names it ever deletes.
INSTALLED_FILES = tuple(name for name, _member in _LIBRARY_MEMBERS) + (
    RECORD_FILENAME,
)

# The wheel unpacked whole: 772.2 MB over 14 files, measured on the pinned
# artifact. Deliberately the whole figure rather than just the two libraries
# (771.5 MB of it), and deliberately not exact to the byte: the exact sizes are
# in RECORD, which cannot be read until the wheel is on disk, while the space
# gate has to answer before the first byte. Over-counting by 0.7 MB is the safe
# direction for a gate.
EXTRACTED_BYTES = 772_200_000

# What the whole install costs at its peak, and the total every progress report
# is against: the wheel is still on disk while the libraries are extracted out
# of it, so the two are added rather than maxed.
INSTALL_BYTES = WHEEL_BYTES + EXTRACTED_BYTES

# Same three states model_store uses, and for the same reason: an interrupted
# install offers the user a different button than a missing one.
STATE_ABSENT = "absent"
STATE_INCOMPLETE = "incomplete"
STATE_INSTALLED = "installed"

#: The sentence `RuntimeState.installed_version` exists to make possible, and
#: the whole of its justification: an install of an earlier pin loads perfectly
#: and is still the wrong version, so it needs to be told from an interrupted
#: download in words. Declared here rather than left to the settings tab
#: because a field whose entire argument is a sentence nobody wrote yet has no
#: argument — I18n.t() would render the missing key by reading its own name out
#: loud, which is the failure this repository has already shipped twice.
OUTDATED_I18N_KEY = "transcription_cuda_runtime_outdated"

_PART_SUFFIX = ".part"

_CHUNK_BYTES = 1024 * 1024

# (connect, read) — as in model_store: the read timeout is per read and has to
# survive a stalled CDN, not bound the transfer.
_HTTP_TIMEOUT = (30, 300)

# See model_store._hold_models_lock() for why the wait is sliced and why the
# deadline is this far out; the reasoning is the same lock and the same user.
_LOCK_TIMEOUT_SECONDS = 12 * 60 * 60.0
_LOCK_POLL_SECONDS = 2.0


@dataclass(frozen=True)
class RuntimeState:
    """What a directory currently holds. `missing` names what is wrong.

    Absent *or* the wrong size is one condition, not two: RECORD pins an exact
    size for every file, so "present and 4 KB short" is an interrupted install
    and nothing else.
    """

    state: str
    missing: tuple[str, ...] = ()
    #: The version a *previous pin's* install left behind, when that is what is
    #: on disk; None in every other case. Not a state of its own, deliberately:
    #: install_cuda_runtime()'s shortcut is written as `!= STATE_INCOMPLETE`, so
    #: a fourth state would make an outdated install take the "already fine"
    #: branch and the repin would never reach anyone — which is exactly the bug
    #: the manifest's version check was added to catch. What it buys is a
    #: sentence — `OUTDATED_I18N_KEY`: a complete install of the old version
    #: and an install interrupted half way are both INCOMPLETE, but "update the
    #: CUDA libraries" and "finish the interrupted download" are different
    #: instructions, and one of them is a 553 MB wait the user did not expect.
    #: `missing` takes precedence over this field; see installation_state().
    installed_version: str | None = None


def default_cuda_runtime_dir() -> str:
    """Where the libraries live: install-wide, next to the Whisper models.

    Global rather than per account for the same reason the models are — 770 MB
    downloaded once per account would be a bug, and the files are read-only and
    carry nothing account-specific. Unlike the models root this one is not
    user-movable: nothing points a loader at it but this module.
    """
    return global_dir(CUDA_RUNTIME_DIRNAME)


def installation_state(directory=None) -> RuntimeState:
    """The cheap answer to "are the libraries here?" — names and exact sizes.

    No hashing: this is asked before a device decision, and hashing 770 MB
    there would cost more than the transcription it is deciding about.
    `verify_installation()` is the expensive answer.
    """
    directory = _resolve(directory)
    record, installed_version = _read_installed_record(directory)
    if record is None:
        # Without the manifest nothing on disk can be checked at all, so the
        # libraries beside it are unusable however healthy they look. Whether
        # that reads as ABSENT or INCOMPLETE is decided by what is there.
        present = [
            name for name in INSTALLED_FILES
            if os.path.exists(os.path.join(directory, name))
        ]
        missing = tuple(name for name in INSTALLED_FILES if name not in present)
        if not present and not _has_parts(directory):
            return RuntimeState(STATE_ABSENT, missing)
        # `installed_version` is set whenever a manifest is there and names
        # another pin, which is not only the complete-but-outdated case: a
        # download of the *old* pin that was interrupted leaves the old
        # manifest and an incomplete set of libraries, so both signals are
        # present at once. **`missing` wins.** "Finish the interrupted
        # download" describes that directory and "update your CUDA libraries"
        # does not, and a caller that read the version first would offer an
        # update for a half-written install. The version is the answer only
        # when `missing` is empty, which is the case that would otherwise
        # leave the caller with no clue at all.
        return RuntimeState(STATE_INCOMPLETE, missing, installed_version)

    missing = []
    for name, member in _LIBRARY_MEMBERS:
        entry = record.get(member)
        if entry is None:
            # A manifest that does not describe the file next to it: the wheel
            # was repinned and this directory is from the previous one.
            missing.append(name)
            continue
        try:
            actual = os.path.getsize(os.path.join(directory, name))
        except OSError:
            missing.append(name)
            continue
        if actual != entry.size:
            missing.append(name)

    if not missing:
        return RuntimeState(STATE_INSTALLED, ())
    # Never ABSENT down here: the manifest is on disk, or `record` would have
    # been None, so there is something of ours to repair.
    return RuntimeState(STATE_INCOMPLETE, tuple(missing))


def is_installed(directory=None) -> bool:
    """Whether every file is present at exactly the size RECORD states.

    Strictly stronger than `device.cuda_runtime_present_in()`, which asks only
    whether the names exist: this is what decides against spending the
    download, so it has to be the check that cannot be satisfied by the
    leftovers of an interrupted one.
    """
    return installation_state(directory).state == STATE_INSTALLED


def register_installed_runtime(directory=None) -> bool:
    """Make an install from an earlier session loadable. Call this at startup.

    **This is the half that is easy to forget and expensive to miss.** The
    directory is not on any loader search path when the process starts, so
    without this call a user who paid for 550 MB last week is silently back on
    the processor today — `probe_cuda_libraries()` would answer False, part 4a
    would veto the GPU, and nothing anywhere would mention the download that
    already happened.

    Must therefore run **before the first device decision**, i.e. before
    anything calls `device.probe_hardware()` or `device.resolve_device()`.
    Cheap (one `os.path.isfile` per library plus an `add_dll_directory`), never
    raises, and False simply means there is nothing installed to register.
    """
    directory = _resolve(directory)
    # Presence, not the full state check: registering costs nothing and an
    # empty directory of ours has no business on the process's DLL search path,
    # but a directory whose sizes are off is still worth registering — the
    # probe that follows is what decides, and it decides by loading.
    if not device.cuda_runtime_present_in(directory):
        return False
    return device.register_cuda_library_directory(directory)


def install_cuda_runtime(directory=None, progress=None, should_cancel=None,
                         session=None):
    """Put the CUDA libraries on this machine. Returns whether the GPU works.

    The return value is `device.probe_cuda_libraries()`'s own `(ok, missing,
    error)` — measured after the directory is registered with the loader, never
    a claim of this module's about the bytes it wrote. "It downloaded" is not
    an answer a caller can use.

    `progress(done, total)` counts the whole operation against `INSTALL_BYTES`:
    the download and the extraction are one bar, because to the user they are
    one wait. It is reported per 1 MB chunk, i.e. ~1300 times — part 5 has to
    throttle before any `wx.CallAfter` or spoken percentage.

    `should_cancel()` is consulted between chunks, during the extraction and
    while waiting for the shared lock. `session` exists so the transfer can be
    driven from a test without a network.
    """
    directory = _resolve(directory)

    # An earlier session's install has to be registered before the probe can
    # see it. When there is nothing to register the memo is what has to go:
    # registering is the *only* thing that invalidates it, so a True measured
    # earlier in this session — before the user removed the libraries, or
    # before anything else took them away — would otherwise send this call
    # straight out of the shortcut below without downloading a byte.
    if not register_installed_runtime(directory):
        device.forget_cuda_library_answer()

    answer = device.probe_cuda_libraries()
    if answer[0] and installation_state(directory).state != STATE_INCOMPLETE:
        # Loadable, and nothing here is half installed: either the CUDA Toolkit
        # is on the machine (ABSENT — there is nothing of ours to repair) or
        # our own install is complete. An INCOMPLETE directory deliberately
        # falls through even though the libraries load, because that is exactly
        # the state a repair has to reach and the probe cannot see: a manifest
        # lost to a partial removal or to a crash, and — the case that matters
        # most — the previous pin's libraries, which load perfectly well and
        # are the wrong version. Answering "already fine" there is how the
        # repair button does nothing and how a repin never reaches anyone.
        logging.info("[transcription] the CUDA libraries already load; not downloading")
        return answer

    root_created = not os.path.isdir(directory)
    try:
        with _hold_runtime_lock(directory, should_cancel):
            # Re-asked under the lock: another account's process may have
            # finished this very download while we waited for it.
            if not is_installed(directory):
                _install_locked(directory, root_created, progress, should_cancel,
                                session)
    except LockTimeout as exc:
        raise errors.TranscriptionError(errors.CUDA_RUNTIME_BUSY, str(exc)) from exc

    if not register_installed_runtime(directory):
        # Registering is what invalidates the loader's memoized answer, so a
        # registration that did not happen — the files went away between the
        # extraction and here — would leave the probe below answering from a
        # cache describing a directory that no longer holds them.
        device.forget_cuda_library_answer()
    answer = device.probe_cuda_libraries()
    logging.info("[transcription] CUDA libraries installed; probe says %s", answer[0])
    return answer


def repair_cuda_runtime(directory=None, progress=None, should_cancel=None,
                        session=None):
    """Delete whatever is installed and fetch it again. Returns the probe.

    The only way out of the state `install_cuda_runtime()` cannot fix, and it
    is the same shape as `model_store.repair_model()`'s: every file present at
    exactly the size RECORD states, and the bytes behind them wrong (a silent
    corruption, or a DLL something else on the machine overwrote). The cheap
    check calls that installed, so the install's own "is it already here?" gate
    fetches nothing; the probe meanwhile answers False, because the library
    does not load. The user is left with a button that reports failure without
    ever downloading, and `verify_installation()` can name the problem but not
    undo it.

    Both halves run under **one** hold of the shared lock — it is re-entrant
    within the process, so the nested acquisitions inside `remove` and
    `install` are the same hold — which is what keeps another account's process
    from starting its own download into the directory in the window between the
    delete and the fetch. Two separate holds would also mean two chances to
    report "another window is busy", and the second would arrive after the
    files were already gone.

    One outcome the caller has to be ready for, and it is the same one
    `remove_cuda_runtime()` documents: Windows will not unlink a DLL that a
    transcription has already mapped into this process, so a repair after a GPU
    run cannot replace those files. Nothing here can fix that from inside the
    running process — WinZapp has to be restarted first — but the removal
    *names* the files that resisted, and that answer arrives before a single
    byte is spent. Left unread it would be found again 553 MB later, as a
    PermissionError out of `_write_part()`'s publish, reported as a download
    that failed: the user hears "check your connection" with a perfect
    connection, half a gigabyte gone, and tries again for another one.
    """
    directory = _resolve(directory)
    try:
        with _hold_runtime_lock(directory, should_cancel):
            logging.info("[transcription] repairing the CUDA libraries in %s",
                         directory)
            stuck = remove_cuda_runtime(directory, should_cancel=should_cancel)
            if stuck:
                # The names are the detail, i.e. the log; the sentence the user
                # gets is the code's, and it is the only one that tells them to
                # restart. Raised rather than downloaded through, because the
                # download would finish and then fail at the publish anyway.
                raise errors.TranscriptionError(
                    errors.CUDA_RUNTIME_IN_USE,
                    f"{directory}: still mapped: {', '.join(stuck)}",
                )
            return install_cuda_runtime(
                directory,
                progress=progress,
                should_cancel=should_cancel,
                session=session,
            )
    except LockTimeout as exc:
        raise errors.TranscriptionError(errors.CUDA_RUNTIME_BUSY, str(exc)) from exc


def verify_installation(directory=None, progress=None, should_cancel=None) -> None:
    """The expensive check: every installed library's sha256, against RECORD.

    Separate from `installation_state()` because it reads 770 MB, which is also
    why it takes a progress callback and a cancel check: a user who asked for a
    check has to be able to change their mind and to hear how far it got.
    """
    directory = _resolve(directory)
    state = installation_state(directory)
    if state.state != STATE_INSTALLED:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED,
            f"{directory}: missing or wrong size: {', '.join(state.missing)}",
        )

    record, _version = _read_installed_record(directory)
    total = sum(record[member].size for _name, member in _LIBRARY_MEMBERS)
    done = 0
    for name, member in _LIBRARY_MEMBERS:
        entry = record[member]
        path = os.path.join(directory, name)
        digest, done = _hash_file(path, done, total, progress, should_cancel)
        if digest != entry.digest:
            raise errors.TranscriptionError(
                errors.CUDA_RUNTIME_CORRUPTED,
                f"{name}: {digest}, expected {entry.digest}",
            )


def remove_cuda_runtime(directory=None, should_cancel=None) -> tuple:
    """Delete the installed libraries — and nothing else. Returns what resisted.

    770 MB the user can never get rid of is not an acceptable end state, and
    neither is `shutil.rmtree()` on a directory somebody else's file may have
    ended up in: only the names in `INSTALLED_FILES` (plus any `.part` this
    module could have written) are unlinked, and the directory itself goes
    through `os.rmdir()`, which refuses to remove one that still holds
    anything.

    An empty result means the directory holds none of our files, whether or not
    there was anything to remove; the caller that needs to tell those apart
    asks `installation_state()` first. A non-empty one is **the expected
    outcome after a transcription has run on the GPU**: Windows will not unlink
    a DLL that is mapped into this process, so those names come back and part 5
    has to say that WinZapp must be restarted to finish. Nothing retries on its
    own — a startup sweep cannot tell a leftover from a healthy install, since
    the files are identical and no record of the request survives the process.

    The loader registration is not undone: closing the cookie is device.py's
    own state, and a registered directory that is now empty simply makes
    `probe_cuda_libraries()` answer False, which is the truth.
    """
    directory = _resolve(directory)
    try:
        with _hold_runtime_lock(directory, should_cancel):
            remaining = _remove_install_files(directory)
            # The libraries have left the disk and nothing in this process
            # would otherwise notice: registering a directory is the only event
            # that invalidates device.py's memoized probe answer, and a removal
            # has no such event. A True measured earlier in the session would
            # outlive the files, `cuda_usable()` would keep choosing the GPU,
            # and every transcription until the app restarts would load the
            # model onto the card and die on the missing library.
            device.forget_cuda_library_answer()
            _remove_empty_dir(directory)
            return remaining
    except LockTimeout as exc:
        raise errors.TranscriptionError(errors.CUDA_RUNTIME_BUSY, str(exc)) from exc


# ── Internals ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _RecordEntry:
    """One line of a wheel's RECORD: `<path>,<algorithm>=<digest>,<size>`."""

    digest: str
    size: int


def _resolve(directory) -> str:
    return str(directory) if directory else default_cuda_runtime_dir()


@contextlib.contextmanager
def _hold_runtime_lock(directory, should_cancel=None):
    """Hold the cross-process lock on `directory`, still answering Cancel.

    `models_lock()` is a lock keyed on a directory rather than a lock about
    models, so this is the same mechanism keyed on ours — a second, independent
    critical section, never contending with a model download. Waited for in
    slices for the reason spelled out at model_store._hold_models_lock(): the
    underlying wait cannot be interrupted, so between attempts is the only
    place a user's Cancel can be noticed.
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        # The lock FILE goes in the global dir, not inside `directory`: the
        # flock fallback creates it, and a file of ours in there would defeat
        # the "leave no directory of ours behind" cleanup below.
        lock = models_lock(directory, global_dir(), timeout=_LOCK_POLL_SECONDS)
        try:
            lock.acquire()
            break
        except LockTimeout:
            _check_cancel(should_cancel)
            if time.monotonic() >= deadline:
                raise
    try:
        yield lock
    finally:
        lock.release()


def _install_locked(directory, root_created, progress, should_cancel, session):
    """install_cuda_runtime()'s body, with the lock already held."""
    # Before a single byte: the peak is the wheel and everything unpacked out
    # of it at once, and the point of a gate is to fail while the user still
    # has the disk they would have needed.
    model_store.ensure_free_space(directory, INSTALL_BYTES)

    wheel_path = os.path.join(directory, WHEEL_FILENAME + _PART_SUFFIX)
    owned_session = session is None
    # Through tls_trust, so a machine whose HTTPS is intercepted locally (an
    # antivirus, a corporate proxy) can download this at all — see that module.
    session = tls_trust.create_session() if owned_session else session
    # Filled by _extract_libraries() as each library reaches its final name, so
    # the failure path below can tell "this attempt published something" from
    # "the final names still hold whatever was there before".
    published = []
    try:
        try:
            os.makedirs(directory, exist_ok=True)
            _report(progress, 0, INSTALL_BYTES)
            _download_wheel(session, wheel_path, progress, should_cancel)
            _extract_libraries(
                wheel_path, directory, progress, should_cancel, published
            )
            _report(progress, INSTALL_BYTES, INSTALL_BYTES)
        except Exception as exc:
            # Everything *this attempt* wrote goes. Published files only if it
            # got as far as publishing one: half an upgrade is a mismatched
            # pair nothing else would collect, but a download that failed
            # before that point has written nothing but .part files, and the
            # final names may still be a complete previous-pin install the user
            # is transcribing with. See _remove_install_files().
            _remove_install_files(directory, published=bool(published))
            # And the loader has to be told, exactly as remove_cuda_runtime()
            # tells it: if this sweep took a published library away, the
            # memoized "yes, they load" from before the attempt outlives the
            # files and every transcription for the rest of the session loads
            # the model onto a card that can no longer run it.
            if published:
                device.forget_cuda_library_answer()
            if root_created:
                _remove_empty_dir(directory)
            raise _as_transcription_error(exc, errors.CUDA_RUNTIME_DOWNLOAD_FAILED)
    finally:
        if owned_session:
            session.close()

    logging.info("[transcription] CUDA libraries extracted to %s", directory)


def _download_wheel(session, part_path, progress, should_cancel) -> None:
    """Stream the pinned wheel into `part_path`, verified as it arrives.

    The digest is computed while the bytes go past rather than in a second
    pass: 553 MB re-read for a number the transfer already had in its hands is
    a minute of disk the user waits through twice.

    The file keeps its `.part` name for its whole life — it is never published,
    only read from and deleted — so the "a file under its final name has been
    verified" rule holds here by construction.
    """
    logging.info("[transcription] downloading the CUDA libraries (%d bytes)",
                 WHEEL_BYTES)
    digest = hashlib.sha256()
    written = 0
    response = session.get(WHEEL_URL, stream=True, timeout=_HTTP_TIMEOUT)
    try:
        response.raise_for_status()
        with open(part_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                _check_cancel(should_cancel)
                if not chunk:
                    continue
                fh.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                _report(progress, written, INSTALL_BYTES)
            fh.flush()
            # The zip is opened from this same path immediately, so this is not
            # about a rename — it is about a power cut leaving a file the next
            # launch would find and, without a digest of its own, believe.
            os.fsync(fh.fileno())
    finally:
        response.close()

    if written != WHEEL_BYTES:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED,
            f"{WHEEL_FILENAME}: expected {WHEEL_BYTES} bytes, got {written}",
        )
    actual = digest.hexdigest()
    if actual != WHEEL_SHA256:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED,
            f"{WHEEL_FILENAME}: sha256 {actual}, expected {WHEEL_SHA256}",
        )


def _extract_libraries(
    wheel_path, directory, progress, should_cancel, published=None
) -> None:
    """Unpack the libraries this module needs, and only those, then commit.

    Two of fourteen files: the rest of the wheel is a Fortran BLAS shim, the
    Python package metadata around it and the license, none of which anything
    here loads. Publishing RECORD last is what makes the install atomic enough
    to be checkable — see the module docstring.
    """
    done = WHEEL_BYTES
    with zipfile.ZipFile(wheel_path) as archive:
        raw_record = _read_member(archive, _RECORD_MEMBER)
        record = _parse_record(raw_record)
        for name, member in _LIBRARY_MEMBERS:
            entry = record.get(member)
            if entry is None:
                raise errors.TranscriptionError(
                    errors.CUDA_RUNTIME_CORRUPTED,
                    f"{WHEEL_FILENAME}: RECORD does not describe {member}",
                )
            _check_cancel(should_cancel)
            logging.info("[transcription] extracting %s (%d bytes)", name, entry.size)
            # Closed explicitly rather than left to the collector: a generator
            # abandoned part way — which is exactly what a cancellation does —
            # keeps the zip's member reader alive, and Windows will not delete
            # a file that still has an open handle. Without this the cleanup
            # below silently fails to remove the wheel, and half a gigabyte
            # stays in the global folder until the next install overwrites it.
            with contextlib.closing(_member_chunks(archive, member)) as chunks:
                done = _write_part(
                    directory, name, chunks, entry, done, progress, should_cancel
                )
            # Recorded after the rename, never before: the caller's cleanup
            # decision turns on whether a *final* name now holds our bytes.
            if published is not None:
                published.append(name)
        # The manifest itself, verbatim and last. It has no digest of its own —
        # a RECORD never lists itself — but the wheel's sha256, checked above,
        # covers it, and the files it describes have just been checked against
        # it one by one.
        _write_part(
            directory, RECORD_FILENAME, [raw_record],
            None, done, progress, should_cancel,
        )

    _unlink(wheel_path)


def _read_member(archive, member) -> bytes:
    """One small member of the wheel, whole, or a corrupted-wheel error."""
    try:
        return archive.read(member)
    except KeyError as exc:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED, f"{WHEEL_FILENAME}: no {member}"
        ) from exc


def _member_chunks(archive, member):
    """A member of the wheel as a chunk iterator, shaped like iter_content().

    Streamed rather than `archive.read(member)`: cublasLt is 669 MB, and
    decompressing that into one bytes object is 669 MB of address space on top
    of the file being written, for no benefit.
    """
    with archive.open(member) as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk


def _write_part(directory, name, chunks, entry, done, progress, should_cancel) -> int:
    """Stream `chunks` into `<name>.part`, check them, and only then publish.

    `entry` is the RECORD line to check against, or None for RECORD itself,
    whose guarantee is the wheel's own digest. Returns the new aggregate byte
    count for the progress bar.
    """
    part_path = os.path.join(directory, name + _PART_SUFFIX)
    digest = hashlib.sha256()
    written = 0
    with open(part_path, "wb") as fh:
        for chunk in chunks:
            _check_cancel(should_cancel)
            if not chunk:
                continue
            fh.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            _report(progress, min(done + written, INSTALL_BYTES), INSTALL_BYTES)
        fh.flush()
        # NTFS journals the rename, not the data behind it: without this a
        # power cut between the two leaves a file of exactly the right size
        # full of zeros under the final name, which the cheap install check
        # believes forever.
        os.fsync(fh.fileno())

    if entry is not None:
        if written != entry.size:
            raise errors.TranscriptionError(
                errors.CUDA_RUNTIME_CORRUPTED,
                f"{name}: expected {entry.size} bytes, got {written}",
            )
        actual = _record_digest(digest)
        if actual != entry.digest:
            raise errors.TranscriptionError(
                errors.CUDA_RUNTIME_CORRUPTED,
                f"{name}: {actual}, expected {entry.digest}",
            )

    os.replace(part_path, os.path.join(directory, name))
    return done + written


def _record_digest(hasher) -> str:
    """A hasher's digest in RECORD's own spelling.

    PEP 376 writes it as `sha256=<urlsafe base64, unpadded>`, not as hex — the
    two look similar enough in a debugger to waste an afternoon, so the
    conversion lives here and both the extraction and verify_installation()
    compare through it.
    """
    encoded = base64.urlsafe_b64encode(hasher.digest()).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def _parse_record(raw):
    """{path inside the wheel: _RecordEntry} for the lines that carry a digest.

    RECORD is CSV, so it is read as CSV rather than split on commas: a path
    containing one is quoted, and a hand-rolled split would silently mis-key it.
    Lines with no digest or no size (RECORD's own line, and any directory entry)
    are skipped rather than rejected — they are legal, and nothing here asks
    about them.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED, f"{RECORD_FILENAME}: {exc}"
        ) from exc

    entries = {}
    for row in csv.reader(text.splitlines()):
        if len(row) < 3:
            continue
        path, digest, size = row[0], row[1].strip(), row[2].strip()
        # Only sha256 is accepted. Nothing else appears in a modern wheel, and
        # an algorithm this module cannot compute would otherwise be read as a
        # mismatch and reported as corruption of a perfectly good file.
        if not path or not digest.startswith("sha256=") or not size.isdigit():
            continue
        entries[path] = _RecordEntry(digest=digest, size=int(size))
    if not entries:
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED, f"{RECORD_FILENAME}: no usable entries"
        )
    return entries


def _read_installed_record(directory):
    """(manifest, version) for the libraries on disk. Either may be None.

    The manifest is None for absent, unreadable, unparsable **and left by
    another pin** alike: all four mean the files beside it cannot be checked
    against the wheel this version installs, which is the only thing the
    callers do with it. The last of those is the one that is easy to miss — the
    previous pin's libraries are present, and its manifest describes them at
    exactly the sizes they have, so every check agrees while the version is
    wrong.

    The version is whichever one the manifest names, and it is returned rather
    than only logged precisely so that fourth case can be told from the other
    three: they are all INCOMPLETE, and the sentence a user needs for "your
    libraries are one version behind" is not the sentence for "your download
    stopped half way".
    """
    try:
        with open(os.path.join(directory, RECORD_FILENAME), "rb") as handle:
            entries = _parse_record(handle.read())
    except (OSError, errors.TranscriptionError):
        return None, None
    version = _record_version(entries)
    # Every wheel's dist-info holds METADATA and WHEEL, both with a digest, so
    # a manifest from the pinned wheel always has an entry under this prefix.
    if not any(key.startswith(_DIST_INFO_PREFIX) for key in entries):
        logging.info(
            "[transcription] the installed CUDA manifest is %s's, not %s's",
            version or "an unknown version", WHEEL_VERSION,
        )
        return None, version
    return entries, version


def _record_version(entries):
    """The wheel version a manifest's own dist-info names, or None.

    Read off the entries rather than off a file name, because the dist-info
    directory is the only thing in a RECORD that carries the version at all —
    the libraries it lists are named the same in every release of the series.
    """
    for key in entries:
        match = _DIST_INFO_RE.match(key)
        if match:
            return match.group(1)
    return None


def _hash_file(path, done, total, progress, should_cancel):
    """(digest in RECORD's spelling, new aggregate count) for one file."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK_BYTES), b""):
                _check_cancel(should_cancel)
                digest.update(chunk)
                done += len(chunk)
                _report(progress, done, total)
    except OSError as exc:
        # A file that cannot be read cannot be transcribed with, and the way
        # out of it is the same as for a bad digest.
        raise errors.TranscriptionError(
            errors.CUDA_RUNTIME_CORRUPTED, f"{path}: {exc}"
        ) from exc
    return _record_digest(digest), done


def _has_parts(directory) -> bool:
    """Whether an interrupted install left any `.part` here."""
    return bool(_part_paths(directory))


def _part_paths(directory) -> list:
    """Every `.part` in `directory`, by glob rather than by the current names.

    The wheel's `.part` carries the pinned version in its name, so a crash
    leaves a file that stops being recognised the day the pin moves — half a
    gigabyte in the shared global folder, under a name nothing looks for any
    more, which is precisely what this module promises not to do. The directory
    is ours by construction (nothing but this module writes into it), so a glob
    here cannot reach anything that is not.
    """
    try:
        return sorted(glob.glob(os.path.join(directory, "*" + _PART_SUFFIX)))
    except OSError:
        return []


def _remove_install_files(directory, published=True) -> tuple:
    """Unlink everything this module writes. Returns the names that resisted.

    Published files and partial ones alike, including the `.part` of a pin that
    is no longer the current one. A name comes back only if it is still on disk
    afterwards — on Windows a DLL already mapped into this process by a
    transcription cannot be unlinked at all, and that is the *expected* outcome
    of a removal after a GPU run rather than an exotic failure.

    `published=False` restricts it to the partial files, and exists for one
    caller: an install that failed *before* publishing anything. What is under
    the final names at that moment is not this attempt's work — it is whatever
    was installed before, which since the pin became part of the manifest check
    can be a complete and perfectly loadable install of the previous version.
    Sweeping it would mean a cancelled or dropped upgrade costs a user their
    working GPU, and Cancel is a button part 5 puts in front of them during a
    553 MB download. Once a library *has* been published the blanket sweep is
    right again: a new cublas beside an old cublasLt is a mismatched pair
    nothing else would ever collect.
    """
    names = INSTALLED_FILES + (WHEEL_FILENAME,) if published else ()
    paths = [os.path.join(directory, name) for name in names]
    paths += [
        os.path.join(directory, name) + _PART_SUFFIX
        for name in INSTALLED_FILES + (WHEEL_FILENAME,)
    ]
    paths += _part_paths(directory)

    remaining = []
    for path in dict.fromkeys(paths):
        if not os.path.exists(path):
            continue
        _unlink(path)
        if os.path.exists(path):
            remaining.append(os.path.basename(path))
    return tuple(remaining)


def _as_transcription_error(exc, fallback):
    """Map whatever went wrong onto the closed set of codes.

    Nothing escapes unclassified: a code the UI cannot translate is a code
    I18n.t() renders as its own key name, which NVDA then reads out letter by
    letter instead of a sentence.
    """
    if isinstance(exc, errors.TranscriptionError):
        return exc
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        # The gate ran before the transfer, but 1.3 GB takes long enough for
        # something else on the machine to fill the volume meanwhile.
        return errors.TranscriptionError(errors.NO_DISK_SPACE, str(exc))
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        # `os.replace()` over a DLL this process has already mapped, which is
        # what a repin lands on when a transcription ran on the GPU first —
        # there is no removal in that path for repair_cuda_runtime()'s
        # pre-check to have caught, so this is the only place it can be told
        # apart from a transfer that genuinely failed. "Check your connection"
        # for a file the loader is holding open sends the user to retry the
        # 553 MB, and the retry cannot succeed either.
        return errors.TranscriptionError(errors.CUDA_RUNTIME_IN_USE, str(exc))
    return errors.TranscriptionError(fallback, str(exc))
