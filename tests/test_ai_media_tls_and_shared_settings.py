"""Two main-branch defects in the online AI feature, pinned.

* **Online AI ignored the system certificate store.** `requests.Session` verifies
  against the CA list baked into certifi, so behind an antivirus that scans
  HTTPS every answer, probe and model list failed as "network" while the
  updater (which goes through `core.tls_trust`) worked on the same machine. The
  default session factory of every online-AI HTTP path is now
  `tls_trust.create_session`; the `session_factory` seam stays for tests.

* **`getattr(mw, "app_settings", ...)` — MainWindow only has `_app_settings`.**
  The bare spelling is never set, so the AI actions and the AI settings tab
  silently built a fresh AppSettings of their own instead of the shared
  install-wide one the rest of the app edits.
"""
import ast
import inspect
import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_settings import AppSettings
from core import tls_trust
from core.ai_media import model_catalog, service
from ui.conversation_panel import ai_actions
from ui.conversation_panel.ai_actions import AIActionsMixin

CLIENT = Path(__file__).resolve().parent.parent / "client"

ONLINE_AI_ENTRY_POINTS = [
    service.request_answer,
    service.probe_connection,
    service.run_chain,
    model_catalog.fetch_models,
]


class TestOnlineAIVerifiesThroughTheSystemTrustStore:
    @pytest.mark.parametrize("function", ONLINE_AI_ENTRY_POINTS,
                             ids=lambda f: f.__name__)
    def test_the_default_session_is_the_trust_aware_one(self, function):
        default = inspect.signature(function).parameters["session_factory"].default
        assert default is tls_trust.create_session

    def test_that_default_mounts_the_system_trust_adapter_for_https(self, monkeypatch):
        monkeypatch.setattr(tls_trust, "system_ssl_context", ssl.create_default_context)
        default = inspect.signature(service.request_answer).parameters["session_factory"].default
        with default() as session:
            assert isinstance(session.get_adapter("https://api.openai.com/v1"),
                              tls_trust._SystemTrustAdapter)

    def test_no_online_ai_module_builds_a_bare_requests_session(self):
        """media_input only receives the local server's `post`; nothing in the
        package may open its own plain Session."""
        for path in (CLIENT / "core" / "ai_media").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and node.attr == "Session"
                        and isinstance(node.value, ast.Name) and node.value.id == "requests"):
                    raise AssertionError(f"{path.name} uses requests.Session directly")

    def test_an_injected_factory_is_still_honoured(self):
        used = []

        class _Http:
            def __enter__(self):
                used.append(True)
                raise RuntimeError("stop here")

            def __exit__(self, *exc):
                return False

        with pytest.raises(RuntimeError):
            model_catalog.fetch_models("openai", "key", service.RequestToken(),
                                       session_factory=_Http)
        assert used == [True]


class TestTheSharedInstallWideSettingsAreUsed:
    @pytest.fixture
    def panel(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_actions, "global_dir", lambda: str(tmp_path))
        shared = AppSettings(str(tmp_path))
        mw = SimpleNamespace(_app_settings=shared)
        return SimpleNamespace(main_window=mw), shared

    def test_ai_settings_returns_the_instance_main_window_holds(self, panel):
        stub, shared = panel
        app, _config = AIActionsMixin._ai_settings(stub)
        assert app is shared

    def test_the_bare_spelling_is_not_consulted(self, panel):
        stub, shared = panel
        stub.main_window = SimpleNamespace(app_settings=object())
        app, _config = AIActionsMixin._ai_settings(stub)
        assert app is not stub.main_window.app_settings

    def test_without_a_main_window_attribute_a_fresh_instance_is_the_fallback(self, panel):
        stub, shared = panel
        stub.main_window = SimpleNamespace()
        app, _config = AIActionsMixin._ai_settings(stub)
        assert isinstance(app, AppSettings) and app is not shared

    def test_no_client_module_reads_the_attribute_without_the_underscore(self):
        """Covers the AI settings tab, the result dialog's callers and anything
        added later: MainWindow never assigns `app_settings`."""
        offenders = []
        for path in CLIENT.rglob("*.py"):
            if "api" in path.relative_to(CLIENT).parts[:1]:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if ((isinstance(node, ast.Constant) and node.value == "app_settings")
                        or (isinstance(node, ast.Attribute) and node.attr == "app_settings")):
                    offenders.append(f"{path.relative_to(CLIENT)}:{node.lineno}")
        assert offenders == []
