"""Tests for MainWindow._on_whats_new (Help > Novidades menu item).

Reuses the same WhatsNewDialog the auto-updater's "Quais as novidades?"
button already shows, but with the *whole* local changelog file rather than
only the entries between two versions — and falls back to a small "no
changelog" dialog (whats_new_none_title/whats_new_none_message) when no
changelog_<lang>.txt ships with this build, which is the case right after a
version with no changelog file yet.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so
_on_whats_new is exercised as a plain function against a small stub — same
approach as the rest of this test suite (see tests/test_sender_names.py).
"""

import updater as updater_module
from main import MainWindow


class _FakeI18n:
    def __init__(self, language="pt-BR"):
        self.language = language

    def t(self, key):
        return key


class _Stub:
    _on_whats_new = MainWindow._on_whats_new

    def __init__(self, language="pt-BR"):
        self.i18n = _FakeI18n(language)


class TestWhatsNewMenu:
    def test_non_empty_changelog_opens_the_whats_new_dialog(self, monkeypatch):
        stub = _Stub()
        seen = {}

        monkeypatch.setattr(updater_module, "load_changelog_text",
                             lambda lang: "V1.0.0.0\nfake entry")

        class _FakeDialog:
            def __init__(self, parent, changelog):
                seen["parent"] = parent
                seen["changelog"] = changelog

            def ShowModal(self):
                seen["shown"] = True

            def Destroy(self):
                seen["destroyed"] = True

        monkeypatch.setattr(updater_module, "WhatsNewDialog", _FakeDialog)
        boxes = []
        monkeypatch.setattr(updater_module.wx, "MessageBox",
                             lambda *a, **kw: boxes.append(a))

        stub._on_whats_new()

        assert seen["parent"] is stub
        assert seen["changelog"] == "V1.0.0.0\nfake entry"
        assert seen.get("shown") is True
        assert seen.get("destroyed") is True
        assert boxes == [], "no changelog dialog must not show when a changelog exists"

    def test_empty_changelog_shows_the_no_news_dialog(self, monkeypatch):
        stub = _Stub()
        monkeypatch.setattr(updater_module, "load_changelog_text", lambda lang: "")

        dialog_calls = []
        monkeypatch.setattr(updater_module, "WhatsNewDialog",
                             lambda *a, **kw: dialog_calls.append(a))
        boxes = []
        monkeypatch.setattr(updater_module.wx, "MessageBox",
                             lambda *a, **kw: boxes.append(a))

        stub._on_whats_new()

        assert dialog_calls == [], "WhatsNewDialog must not open with nothing to show"
        assert len(boxes) == 1
        message, title = boxes[0][0], boxes[0][1]
        assert message == "whats_new_none_message"
        assert title == "whats_new_none_title"

    def test_whitespace_only_changelog_is_treated_as_empty(self, monkeypatch):
        """A changelog file that exists but has no real content (e.g. just
        blank lines) must not open a blank WhatsNewDialog window."""
        stub = _Stub()
        monkeypatch.setattr(updater_module, "load_changelog_text", lambda lang: "   \n  \n")

        dialog_calls = []
        monkeypatch.setattr(updater_module, "WhatsNewDialog",
                             lambda *a, **kw: dialog_calls.append(a))
        boxes = []
        monkeypatch.setattr(updater_module.wx, "MessageBox",
                             lambda *a, **kw: boxes.append(a))

        stub._on_whats_new()

        assert dialog_calls == []
        assert len(boxes) == 1

    def test_uses_the_current_ui_language(self, monkeypatch):
        stub = _Stub(language="es-ES")
        seen_lang = []
        monkeypatch.setattr(updater_module, "load_changelog_text",
                             lambda lang: seen_lang.append(lang) or "")
        monkeypatch.setattr(updater_module.wx, "MessageBox", lambda *a, **kw: None)

        stub._on_whats_new()

        assert seen_lang == ["es-ES"]
