"""The small helpers every module of this package repeated, defined once.

model_store, cuda_runtime, whisper_cpp_runtime, whisper_cpp_backend,
faster_whisper_backend, external_models and audio_prep each carried their own
copy of these. They import them under their old private names where that reads
the same — only that a fix to one (say, the cancellation wording) can no longer
miss another.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile

from core.transcription import errors


def check_cancel(should_cancel) -> None:
    """Raise CANCELLED if the user asked to stop."""
    if should_cancel is not None and should_cancel():
        raise errors.TranscriptionError(errors.CANCELLED, "cancelled by the user")


def report(progress, done, total) -> None:
    if progress is not None:
        progress(done, total)


def unlink(path) -> bool:
    """Remove a file; True if it went, False if it was not there or would not."""
    if not path:
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def remove_empty_dir(directory) -> None:
    """rmdir, which is a no-op on any directory that still holds a file."""
    try:
        os.rmdir(directory)
    except OSError:
        pass


def kill_process(process, program) -> None:
    """Kill a child and reap it; log, never raise, when that is not possible."""
    try:
        process.kill()
        process.wait(timeout=5)
    except Exception as exc:
        # Gone already, or refusing to die; nothing more can be done from
        # inside an `except` that has its own error to re-raise. Not
        # exc_info=True: a TimeoutExpired prints the whole command line, and
        # that holds the media file's path, named after the message id.
        logging.warning("[transcription] could not stop %s: %s",
                        program, errors.exception_report(exc))


@contextlib.contextmanager
def private_temp_dir(prefix):
    """A temporary folder removed on exit; a failure to remove it is logged.

    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) swallowed it, and a
    folder holding the audio's transcript is worth one warning. Basename only:
    the full path has the user's name in it.
    """
    path = tempfile.mkdtemp(prefix=prefix)
    try:
        yield path
    finally:
        failed = []
        shutil.rmtree(path, onexc=lambda _func, _p, exc: failed.append(exc))
        if failed or os.path.exists(path):
            logging.warning(
                "[transcription] could not remove the temporary folder %s (%s)",
                os.path.basename(path),
                type(failed[0]).__name__ if failed else "still present",
            )
