"""Speech-output gate for accessible_output2's Auto class, honoring the two
Settings > Acessibilidade toggles (settings["accessibility"]).

self.speak_output (MainWindow) is the one object every spoken announcement in
the app funnels through — MainWindow.output() and every direct
self.speak_output.output(...) / main_window.speak_output.output(...) call
site (main.py, conversations.py, websocket_client.py, connect.py). Wrapping
it here, rather than gating each call site, makes both toggles apply
everywhere at once.
"""


class AccessibleSpeechOutput:
    """Wraps an accessible_output2 Auto instance (or anything exposing the
    same ``.outputs`` list and ``.get_first_available_output()`` method) and
    gates every call on the current accessibility settings.

    - extended_sr_compat_enabled (default True): master switch. When False,
      nothing is ever spoken through here — the user is assumed to rely on
      the visual UI only.
    - sapi_fallback_enabled (default True): when False, only ever speak
      through a real screen reader (``is_system_output() == False`` — NVDA,
      JAWS, ...), never the system SAPI voice that accessible_output2's Auto
      would otherwise always fall back to (SAPI5 reports ``is_active()``
      unconditionally True). Re-evaluated on every call — ``is_active()``
      queries the screen reader live — so turning the screen reader off
      mid-session silences WinZapp immediately instead of keeping whatever
      was active at startup.

    ``suppressed_getter``, when given, is polled on every ``output()`` call:
    while it returns True, the call is dropped silently instead of being
    spoken. This backs Settings > Conteúdo Falado's "silence while recording
    a voice message" toggle — sounds still play (they don't go through this
    class), only speech is muted. ``silence()`` bypasses this check on
    purpose: it exists specifically to cut off speech that's already in
    flight (e.g. the screen reader's own focus announcement on the Enviar
    button when a recording starts), which must run even though the
    suppression window is what triggered it.
    """

    def __init__(self, auto_output, settings_getter, suppressed_getter=None):
        self._auto = auto_output
        self._settings_getter = settings_getter
        self._suppressed_getter = suppressed_getter

    def _resolve_output(self):
        cfg = self._settings_getter().get("accessibility", {})
        if not cfg.get("extended_sr_compat_enabled", True):
            return None
        if cfg.get("sapi_fallback_enabled", True):
            return self._auto.get_first_available_output()
        for output in self._auto.outputs:
            if not output.is_system_output() and output.is_active():
                return output
    def _resolve_silence_output(self):
        cfg = self._settings_getter().get("accessibility", {})
        if cfg.get("sapi_fallback_enabled", True):
            return self._auto.get_first_available_output()
        for output in self._auto.outputs:
            if not output.is_system_output() and output.is_active():
                return output
        return self._auto.get_first_available_output()

    def output(self, text, **options):
        if self._suppressed_getter is not None and self._suppressed_getter():
            return
        output = self._resolve_output()
        if output:
            output.speak(text, **options)

    def speak(self, text, **options):
        self.output(text, **options)

    def silence(self):
        """Immediately cancel whatever the resolved output is currently
        saying or has queued. Used to cut off a screen reader's own focus
        announcement, not just future output() calls."""
        output = self._resolve_silence_output()
        if output and hasattr(output, "silence"):
            try:
                output.silence()
            except Exception:
                pass
