"""Which transcription downloads may run without a window.

Settings > General > "download updates in the background" (install-wide, off by
default, `update_background.SETTING`) already decides whether a WinZapp update
or a WPPConnect Server update holds the user in a modal progress dialog. The
Transcription tab follows the same choice for what it downloads: a model, the
CUDA libraries, the whisper.cpp program. They are the same kind of wait — up
to several gigabytes — and a user who asked not to be held for the one should
not be held for the other.

Only the actions that fetch bytes qualify. Verifying, removing and moving the
models folder are not downloads: they are short or they must finish before the
tab offers anything else, so they keep their dialog.

Pure, no wx: `runs_in_background()` is a decision, and the machinery that acts
on it is main_window/transcription_background.py.
"""

from core.transcription import management

#: The six actions that spend the user's bandwidth. A repair is a download too.
BACKGROUND_ACTIONS = (
    management.ACTION_DOWNLOAD_MODEL,
    management.ACTION_REPAIR_MODEL,
    management.ACTION_INSTALL_CUDA_RUNTIME,
    management.ACTION_REPAIR_CUDA_RUNTIME,
    management.ACTION_INSTALL_WHISPER_CPP,
    management.ACTION_REPAIR_WHISPER_CPP,
)


def runs_in_background(action, background_enabled) -> bool:
    """Whether `action` runs without the progress dialog.

    `background_enabled` is the answer of update_background.
    background_downloads_enabled(settings) — only an explicit True counts,
    which that function guarantees.
    """
    return bool(background_enabled) and action in BACKGROUND_ACTIONS
