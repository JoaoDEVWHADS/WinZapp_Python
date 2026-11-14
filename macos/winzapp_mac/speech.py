"""macOS speech outputs in accessible_output2's shape.

WinZapp builds ``outputs.auto.Auto()`` and wraps it in AccessibleSpeechOutput,
which only needs ``.outputs``, ``.get_first_available_output()`` and, on
each output, ``speak``/``silence``/``is_active``/``is_system_output``.

accessible_output2's own VoiceOver output drives VoiceOver over AppleScript,
which silently does nothing unless "Allow VoiceOver to be controlled with
AppleScript" is on. VoiceOverAnnounce instead posts an NSAccessibility
announcement from the app itself — the documented way for an app to have
VoiceOver speak — with no setting to enable. SystemVoice is the equivalent
of Windows' SAPI fallback, used only when VoiceOver is off and the user
left "SAPI fallback" enabled.
"""

import threading

import wx


def _on_main(fn):
    if threading.current_thread() is threading.main_thread():
        fn()
    else:
        wx.CallAfter(fn)


class VoiceOverAnnounce:
    name = "VoiceOver"

    def is_system_output(self):
        return False

    def is_active(self):
        try:
            from AppKit import NSWorkspace
            return bool(NSWorkspace.sharedWorkspace().isVoiceOverEnabled())
        except Exception:
            return False

    def speak(self, text, interrupt=False, **_):
        text = str(text or "").strip()
        if not text:
            return

        def post(queued=False):
            from AppKit import (
                NSApp,
                NSAccessibilityAnnouncementKey,
                NSAccessibilityAnnouncementRequestedNotification,
                NSAccessibilityPostNotificationWithUserInfo,
                NSAccessibilityPriorityHigh,
                NSAccessibilityPriorityKey,
                NSAccessibilityPriorityMedium,
            )
            app = NSApp()
            target = app.mainWindow() or app.keyWindow() or app
            priority = NSAccessibilityPriorityMedium if queued else NSAccessibilityPriorityHigh
            NSAccessibilityPostNotificationWithUserInfo(
                target,
                NSAccessibilityAnnouncementRequestedNotification,
                {NSAccessibilityAnnouncementKey: text,
                 NSAccessibilityPriorityKey: priority},
            )

        # Right after a chat open, vo_focus_mac holds the announcement until
        # VoiceOver has been pointed at the message field, then queues it
        # behind the field's own announcement instead of cutting it off.
        from . import vo_focus_mac
        _on_main(lambda: vo_focus_mac.route_announcement(post))

    output = speak

    def braille(self, text, **_):
        pass

    def silence(self):
        # There is no API to cut VoiceOver off; an empty announcement is a
        # no-op, so this deliberately does nothing.
        pass


class SystemVoice:
    name = "System voice"

    def __init__(self):
        self._synth = None

    def is_system_output(self):
        return True

    def is_active(self):
        return True

    def _get(self):
        if self._synth is None:
            from AppKit import NSSpeechSynthesizer
            self._synth = NSSpeechSynthesizer.alloc().initWithVoice_(None)
        return self._synth

    def speak(self, text, interrupt=False, **_):
        text = str(text or "").strip()
        if not text:
            return

        def run():
            synth = self._get()
            if interrupt or synth.isSpeaking():
                synth.stopSpeaking()
            synth.startSpeakingString_(text)
        _on_main(run)

    output = speak

    def braille(self, text, **_):
        pass

    def silence(self):
        _on_main(lambda: self._synth and self._synth.stopSpeaking())


class MacAuto:
    """Drop-in for accessible_output2.outputs.auto.Auto."""

    def __init__(self):
        self.outputs = [VoiceOverAnnounce(), SystemVoice()]

    def get_first_available_output(self):
        for output in self.outputs:
            if output.is_active():
                return output
        return None

    def speak(self, *args, **kwargs):
        output = self.get_first_available_output()
        if output:
            output.speak(*args, **kwargs)

    output = speak

    def braille(self, *args, **kwargs):
        pass

    def silence(self):
        output = self.get_first_available_output()
        if output:
            output.silence()

    def is_system_output(self):
        output = self.get_first_available_output()
        return output.is_system_output() if output else False


def install():
    from accessible_output2.outputs import auto
    auto.Auto = MacAuto
