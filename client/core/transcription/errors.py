"""Everything that can go wrong in a transcription, as one closed set of codes.

Transcription fails in a lot of ways that look identical from the outside —
nothing appears — and the user is listening rather than reading a traceback.
So a failure travels as a *code*, and only the UI layer turns it into a
sentence, in the user's own language.

The split between `code` and `detail` is the point of this module.  `detail` is
technical (a CTranslate2 message, an ffmpeg exit code) and belongs in log.log;
it is never spoken and never shown, and never carries a media file's name
either — that name is the message id, and the constructor runs it through
`scrub_media_names()`. Putting a backend string on screen would say nothing
useful to a blind user in Polish, and it is also where file paths and message
ids leak.
"""

from __future__ import annotations

import os
import re
import tempfile
import traceback

# The chosen model is not on disk yet.
MODEL_NOT_INSTALLED = "model_not_installed"
# It is on disk, but a file is missing or the wrong size — an interrupted
# download that was never cleaned up. The promise is checkable because the
# catalogue pins a revision and, with it, an exact size for every file and a
# sha256 for model.bin (see model_catalog).
MODEL_CORRUPTED = "model_corrupted"
NO_DISK_SPACE = "no_disk_space"
# The disk ran out while a message's audio was being decrypted into %TEMP% for
# a transcription. Its own code rather than NO_DISK_SPACE because that
# sentence says "for this download": it is what the model and CUDA downloads
# say, and here nothing was being downloaded — the voice note was already on
# disk. It also names a different place: %TEMP% sits on the system drive by
# default, which need not be the drive holding WinZapp's data, so a user sent
# to free space "for the download" may clear the wrong disk and meet the same
# failure again.
TEMP_NO_DISK_SPACE = "temp_no_disk_space"
CUDA_UNAVAILABLE = "cuda_unavailable"
INSUFFICIENT_VRAM = "insufficient_vram"
INSUFFICIENT_RAM = "insufficient_ram"
UNSUPPORTED_AUDIO_FORMAT = "unsupported_audio_format"
# A video with no sound track at all: ffmpeg read it fine and found only the
# picture. Its own code so the sentence says "this video has no sound" instead
# of blaming a format that was recognised.
NO_AUDIO_TRACK = "no_audio_track"
FFMPEG_FAILED = "ffmpeg_failed"
# The file is there but truncated: a send that died mid-upload, or a media
# file WinZapp wrote while the app was closed.
AUDIO_INCOMPLETE = "audio_incomplete"
# WhatsApp's own media download for this message has not finished, so there is
# no local file to read at all.
MEDIA_NOT_DOWNLOADED = "media_not_downloaded"
CANCELLED = "cancelled"
SAVE_FAILED = "save_failed"
# faster-whisper/CTranslate2 is not installed in this copy of WinZapp.
BACKEND_MISSING = "backend_missing"
MODEL_DOWNLOAD_FAILED = "model_download_failed"
# Moving the models folder failed part way. Deliberately not MODEL_CORRUPTED:
# nothing is corrupted — the move copies and verifies before it deletes, so the
# models are still whole in the folder they were in — and "download it again"
# would be 3 GB of advice for a problem whose answer is to pick another folder.
MODEL_MOVE_FAILED = "model_move_failed"
# A model the user pointed WinZapp at in a folder of their own (another
# program's download, the Hugging Face cache — see external_models) is not
# there any more: an external disk that is unplugged, a cache another program
# pruned or moved to a newer revision. Neither MODEL_NOT_INSTALLED nor
# MODEL_CORRUPTED says that. The first tells somebody who knows perfectly well
# they have the model that they do not; the second says the files are damaged
# and sends them to download 3 GB, when plugging the disk back in is the whole
# fix — and nothing was damaged, nothing is even there to be.
EXTERNAL_MODEL_MISSING = "external_model_missing"
# Such a folder is there, and WinZapp can no longer vouch that it holds the
# model that was checked: a file went missing or changed size, or model.bin was
# rewritten since the digest or the trial load (a script re-converting into the
# same folder does exactly that, at exactly the same size). MODEL_CORRUPTED
# would say "download it again", which for a custom model is impossible and for
# a catalogue one is 3 GB spent on the wrong answer; MODEL_NOT_INSTALLED would
# say "download it before transcribing", the same advice. What resolves it is
# checking the folder again in the Transcription tab, or choosing another model
# — and the file in the folder is the user's, so it may be the new one they
# meant to use.
EXTERNAL_MODEL_CHANGED = "external_model_changed"
# Another account's process is holding the shared models directory. Its own
# code because the alternatives all say something false: the download did not
# fail, the connection is fine, and nothing is corrupted — another window is
# simply busy with the same folder, and the answer is to wait rather than to
# retry anything.
MODELS_BUSY = "models_busy"
# The cuBLAS wheel could not be fetched. Its own code rather than
# MODEL_DOWNLOAD_FAILED because that sentence names the transcription *model*,
# and a user who was told their model failed to download will go and repair a
# model that is perfectly fine.
CUDA_RUNTIME_DOWNLOAD_FAILED = "cuda_runtime_download_failed"
# The installed CUDA libraries are missing, the wrong size or hash differently
# than the wheel's own RECORD says. Same split as MODEL_CORRUPTED against
# MODEL_DOWNLOAD_FAILED: "the files on your disk are damaged, install them
# again" is a different instruction from "the download did not get through".
CUDA_RUNTIME_CORRUPTED = "cuda_runtime_corrupted"
# Another account's process is holding the CUDA libraries directory. Distinct
# from MODELS_BUSY only in which folder it names, which is the whole point: a
# user who clicked "download the CUDA libraries" and is told another window is
# busy with the *models* has been sent to look at the wrong thing.
CUDA_RUNTIME_BUSY = "cuda_runtime_busy"
# The DLLs are mapped into this process by a transcription that already ran on
# the GPU, and Windows neither unlinks nor replaces a mapped DLL. It is not
# corruption, it is not the download, and it is not another window: it is this
# process, and the only way out is a restart. Its own code because the three
# alternatives each send the user somewhere else — "check your connection",
# "install them again", "wait for the other window" — and the wrong one here
# costs 553 MB per attempt, since the download runs to completion and only
# fails when it tries to publish over a file that cannot be replaced.
CUDA_RUNTIME_IN_USE = "cuda_runtime_in_use"
# The whisper.cpp program (whisper-cli.exe and its DLLs, downloaded on demand
# like the CUDA libraries — see whisper_cpp_runtime) is not on this machine.
# Not BACKEND_MISSING: that sentence says the component is missing from "this
# copy of WinZapp", whose fix is reinstalling WinZapp; this one is a download
# away, from the settings.
WHISPER_CPP_NOT_INSTALLED = "whisper_cpp_not_installed"
# The release zip could not be fetched. Its own code for the reason
# CUDA_RUNTIME_DOWNLOAD_FAILED has one: MODEL_DOWNLOAD_FAILED names the model,
# and the CUDA sentence names libraries the CPU build does not even use.
WHISPER_CPP_DOWNLOAD_FAILED = "whisper_cpp_download_failed"
# The zip's digest was wrong, it held no whisper-cli.exe, or the installed
# files are missing, the wrong size, or will not start. "Install it again".
WHISPER_CPP_CORRUPTED = "whisper_cpp_corrupted"
# The whisper.cpp program folder is held: another account's process has its
# lock, or a file in it is open (an antivirus scanning the fresh DLLs, a
# whisper-cli still running) past the retries. Both are "wait and try again",
# and neither is a download to repeat. Its own code so the sentence names that
# folder and not the models or CUDA one.
WHISPER_CPP_BUSY = "whisper_cpp_busy"
# The device refused the precision the model was asked to load with
# (CTranslate2: "Requested float16 compute type, but the target device or
# backend do not support efficient float16 computation"). precision.py
# replaces a choice the probe says cannot run before the load, so this is
# what is left when the probe and the device disagree. Its own code because
# "internal error" sends nobody to the setting that fixes it.
PRECISION_UNSUPPORTED = "precision_unsupported"
# The catch-all: the backend raised something we have no specific answer for.
BACKEND_ERROR = "backend_error"

# Single source of truth for "every code there is" — the i18n map below and the
# test that pins it both derive from this, so a new code cannot be added
# without a translation.
ERROR_CODES = (
    MODEL_NOT_INSTALLED,
    MODEL_CORRUPTED,
    NO_DISK_SPACE,
    TEMP_NO_DISK_SPACE,
    CUDA_UNAVAILABLE,
    INSUFFICIENT_VRAM,
    INSUFFICIENT_RAM,
    UNSUPPORTED_AUDIO_FORMAT,
    NO_AUDIO_TRACK,
    FFMPEG_FAILED,
    AUDIO_INCOMPLETE,
    MEDIA_NOT_DOWNLOADED,
    CANCELLED,
    SAVE_FAILED,
    BACKEND_MISSING,
    MODEL_DOWNLOAD_FAILED,
    MODEL_MOVE_FAILED,
    EXTERNAL_MODEL_MISSING,
    EXTERNAL_MODEL_CHANGED,
    MODELS_BUSY,
    CUDA_RUNTIME_DOWNLOAD_FAILED,
    CUDA_RUNTIME_CORRUPTED,
    CUDA_RUNTIME_BUSY,
    CUDA_RUNTIME_IN_USE,
    WHISPER_CPP_NOT_INSTALLED,
    WHISPER_CPP_DOWNLOAD_FAILED,
    WHISPER_CPP_CORRUPTED,
    WHISPER_CPP_BUSY,
    PRECISION_UNSUPPORTED,
    BACKEND_ERROR,
)

ERROR_I18N_KEYS = {code: f"transcription_error_{code}" for code in ERROR_CODES}

# TEMP_NO_DISK_SPACE's sentence when %TEMP% has no drive letter (a network
# share, see temp_drive()). Its own sentence rather than an empty `{drive}`:
# "no free space on drive  to prepare..." is what a single key read out there,
# and a drive phrase translated on its own and spliced in cannot follow a word
# order that differs in every locale.
TEMP_NO_DISK_SPACE_UNNAMED_I18N_KEY = "transcription_error_temp_no_disk_space_unnamed"


class TranscriptionError(Exception):
    """A transcription failure carrying a code the UI can translate.

    `detail` is for the log only, and neither `str(exc)` nor `exc.args` carries
    it. That is not tidiness: `wx.MessageBox(str(exc), ...)` is an idiom this
    repository already uses (`client/ui/media_viewer.py`), so anything `__str__`
    returns is one careless handler away from being read out, character by
    character, to a blind user — including the file path a backend error message
    usually contains. Logging wants the pair, so logging asks for `log_line`.
    """

    #: Ids a partially completed `move_models()` did manage to move before it
    #: failed. Declared here, empty, rather than only where that path attaches
    #: it: a caller writing `except TranscriptionError as exc: ... exc.moved`
    #: around a move would otherwise hit AttributeError on every *other* way a
    #: move can fail — the busy-folder path raises its own error and never
    #: passes through the attach.
    moved: tuple = ()

    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code = code
        # Cleaned here, once, rather than trusted to every raise: a detail is
        # routinely built from `f"{exc}"`, and the text of an exception about a
        # media file names it after the message id (see scrub_media_names()).
        self.detail = scrub_media_names(detail)

    def __str__(self):
        return str(self.code)

    @property
    def log_line(self) -> str:
        """Code and technical detail on one line — for `logging.*`, only."""
        return f"{self.code}: {self.detail}" if self.detail else str(self.code)

    @property
    def i18n_key(self) -> str:
        """The key alone, not the sentence. TEMP_NO_DISK_SPACE's carries a
        `{drive}` field, so `i18n.t(exc.i18n_key)` would read "{drive}" out
        loud; a sentence is built from `error_i18n_key(code, temp_dir)` and
        `error_i18n_values(code, temp_dir)`, with the same `temp_dir`, never
        from this property on its own."""
        return error_i18n_key(self.code)


# ── Keeping message ids out of the log ───────────────────────────────────────
#
# The text of an exception is the best technical detail there is, and on this
# path it is also where the one private thing a failure can carry rides along:
# a media file is named after the WhatsApp message id (`voice_messages/<id>.msv`,
# `media/<id>.wzmedia`, see message_audio.cached_media_path()), and the id is
# what the issue forbids the log to hold. So the name is replaced and nothing
# else is — one helper, used by every module of the package, rather than each
# growing its own idea of what a media name looks like.
#
# Only the name, never the folder. Folders are what a transcription failure is
# diagnosed with — which drive a model sits on, which spelling of the models
# folder was compared, where a CUDA DLL was looked for — and they identify no
# message: the account folder is `accounts/<uuid4>` and every temporary comes
# out of mkstemp(). The Windows user name in a profile folder is already in
# dozens of lines of log.log outside this package, and in the frames of every
# traceback; hiding it here protected nothing and cost the error codes and
# DLL names that sat on the same line.
#
# A whole file-name token that *ends* in the media suffix, and nothing more: the
# lookbehind keeps it from starting mid-token and the lookahead from matching a
# name that only carries the suffix in its middle (`x.msv.bak` is not a media
# file), while a sentence's closing full stop still ends the name.
_MEDIA_NAME = re.compile(
    r"(?<![\w.-])[\w.-]+(\.(?:wzmedia|msv))(?!\.?[\w-])", re.I
)

MESSAGE_ID_PLACEHOLDER = "<message id>"


def scrub_media_names(text):
    """`text` with every media file name — the message id — replaced.

    The suffix stays, so the log still says whether it was a voice note or
    another attachment; the folder around it and everything else on the line
    (the wording, errno, a DLL name, a model folder) are left exactly as they
    were. Anything that is not a non-empty string comes back unchanged.
    """
    if not isinstance(text, str) or not text:
        return text
    return _MEDIA_NAME.sub(lambda m: MESSAGE_ID_PLACEHOLDER + m.group(1), text)


# traceback's own connecting sentences, so the report reads like the
# `logging.exception()` output it replaces and anyone who knows that output can
# follow the chain without learning a second layout.
_CAUSE_LINE = "\nThe above exception was the direct cause of the following exception:\n\n"
_CONTEXT_LINE = "\nDuring handling of the above exception, another exception occurred:\n\n"


def _one_exception(exc) -> str:
    parts = [type(exc).__name__]
    for name in ("errno", "winerror"):
        value = getattr(exc, name, None)
        if value is not None:
            parts.append(f"{name}={value}")
    # A TranscriptionError's str() is its code alone, on purpose (see its
    # docstring), so a chain link that is one would lose the detail it was
    # raised with; log_line is the reading made for the log, already scrubbed.
    raw = exc.log_line if isinstance(exc, TranscriptionError) else str(exc)
    text = scrub_media_names(raw)
    head = " ".join(parts) + (f": {text}" if text else "")
    frames = "".join(traceback.format_tb(exc.__traceback__))
    return f"{head}\n{frames}" if frames else head


def exception_report(exc) -> str:
    """An unexpected exception for the log: the whole chain, as traceback has it.

    What `logging.exception()` would print, minus what it must not: its lines
    are `str(exc)` verbatim, and the text of anything that touched a media file
    carries that file's name, the message id. Everything else stays — frames,
    folders, `errno`/`winerror` — and so does the chain: a `RuntimeError("model
    load failed") from OSError(2, ...)` whose report dropped the OSError would
    have dropped the only line that says what actually failed.

    The chain is walked the way traceback walks it: `__cause__`, then
    `__context__` unless `__suppress_context__` is set. That last rule is not a
    detail — message_audio.py raises `from None` on purpose, so the exception
    carrying the media path stays behind in `__context__` and never travels;
    printing `__context__` regardless would undo it.
    """
    links = []
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if exc.__cause__ is not None:
            following, connector = exc.__cause__, _CAUSE_LINE
        elif exc.__context__ is not None and not exc.__suppress_context__:
            following, connector = exc.__context__, _CONTEXT_LINE
        else:
            following, connector = None, ""
        links.append((exc, connector))
        exc = following
    # Oldest first, like traceback: the root cause at the top, the exception
    # that was actually caught at the bottom, each preceded by the sentence
    # that ties it to the one above.
    return "".join(
        connector + _one_exception(current) for current, connector in reversed(links)
    )


def error_i18n_key(code, temp_dir=None) -> str:
    """The i18n key for an error code.

    An unrecognised code resolves to the internal-error message rather than to
    a key of its own: I18n.t() falls back to the raw key name, so inventing
    "transcription_error_<whatever>" here would have a screen reader read the
    code out loud instead of a sentence.

    TEMP_NO_DISK_SPACE is the one code with two sentences, picked by whether
    %TEMP% has a drive letter to name (temp_drive()). `temp_dir` must be the
    one error_i18n_values() is given, or the key and its fields disagree.
    """
    if code == TEMP_NO_DISK_SPACE and not temp_drive(temp_dir):
        return TEMP_NO_DISK_SPACE_UNNAMED_I18N_KEY
    return ERROR_I18N_KEYS.get(code, ERROR_I18N_KEYS[BACKEND_ERROR])


def error_i18n_values(code, temp_dir=None) -> dict:
    """The fields error_i18n_key(code)'s sentence is formatted with.

    Beside the key, not inside each caller: every place that turns a code into
    a sentence formats it with these, and a field only one of them passed would
    be a KeyError in the middle of announcing a failure everywhere else.
    """
    if code == TEMP_NO_DISK_SPACE:
        drive = temp_drive(temp_dir)
        # No letter means error_i18n_key() chose the sentence without a field.
        return {"drive": drive} if drive else {}
    return {}


def temp_drive(temp_dir=None) -> str:
    """The drive letter %TEMP% lives on ("C:"), or "" when it has none.

    TEMP_NO_DISK_SPACE names it because %TEMP% sits on the system drive by
    default, which need not be the drive holding WinZapp's data — "free up
    space" without saying where sends the user to clear the wrong disk. The
    letter only, never the folder: the path carries the Windows user name. A
    UNC %TEMP% has no letter and its share name is not ours to read out, so it
    gets "" and error_i18n_key() picks the sentence that names no drive.
    """
    try:
        drive = os.path.splitdrive(temp_dir or tempfile.gettempdir())[0]
    except Exception:
        return ""
    return drive.upper() if re.fullmatch(r"[A-Za-z]:", drive or "") else ""
