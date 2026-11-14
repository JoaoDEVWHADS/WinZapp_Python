"""The transcription settings that act on the process are applied at startup,
not only on Apply (core/transcription/runtime_settings.py)."""

from core.transcription import residency, reused_runtimes, runtime_settings
from tests.god_modules import main_window_method_source


def test_startup_applies_both(monkeypatch):
    seen = []
    monkeypatch.setattr(residency.residency, "configure", lambda keep: seen.append(("keep", keep)))
    monkeypatch.setattr(reused_runtimes, "configure_from", lambda app: seen.append(("reuse", app)))
    app = object()
    runtime_settings.apply({"transcription": {"keep_model_loaded": True}}, app)
    assert seen == [("keep", True), ("reuse", app)]


def test_a_failing_residency_does_not_stop_the_folders(monkeypatch):
    seen = []

    def boom(keep):
        raise RuntimeError("x")

    monkeypatch.setattr(residency.residency, "configure", boom)
    monkeypatch.setattr(reused_runtimes, "configure_from", lambda app: seen.append(app))
    runtime_settings.apply({}, "app")
    assert seen == ["app"]


def test_load_settings_calls_it():
    source = main_window_method_source("load_settings")
    assert "runtime_settings.apply(self.settings" in source
