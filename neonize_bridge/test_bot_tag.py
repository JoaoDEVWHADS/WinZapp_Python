"""The bridge keeps neonize from marking every private message as sent by a bot."""
import sys

import server


def test_turn_off_bot_tag_overrides_any_value(monkeypatch):
    monkeypatch.setenv("NEONIZE_BOT_TAG", "on")
    server.turn_off_bot_tag()
    assert server.os.environ["NEONIZE_BOT_TAG"] == "off"


def test_main_turns_the_bot_tag_off_before_serving(monkeypatch, tmp_path):
    monkeypatch.delenv("NEONIZE_BOT_TAG", raising=False)
    seen = {}
    monkeypatch.setattr(server, "create_app", lambda *a, **k: object())
    monkeypatch.setattr(server.web, "run_app",
                        lambda *a, **k: seen.update(tag=server.os.environ.get("NEONIZE_BOT_TAG")))
    monkeypatch.setattr(sys, "argv", ["server.py", "--folder", str(tmp_path)])
    server.main()
    assert seen["tag"] == "off"
