"""The transcription settings that act on the process, not on one run.

Two of them change what the process itself holds, and so have to be put into
effect when the settings are read at startup — not only when Settings is
applied — or a restart silently forgets them:

* `transcription.keep_model_loaded` (core/transcription/residency.py), without
  which the model is released five minutes after every run;
* the reused CUDA / whisper.cpp folders (core/transcription/reused_runtimes.py),
  without which a folder the user chose is ignored until Apply is pressed
  again. They must be in effect before the first device decision.

`apply(settings, app_settings)` is that one call. It never raises: it runs in
the middle of MainWindow.load_settings().
"""

import logging

from core.transcription import residency, reused_runtimes


def apply(settings, app_settings) -> None:
    try:
        residency.residency.configure(residency.keep_loaded_from_settings(settings))
    except Exception as exc:
        logging.warning("[transcription] could not apply keep_model_loaded: %s",
                        type(exc).__name__)
    reused_runtimes.configure_from(app_settings)
