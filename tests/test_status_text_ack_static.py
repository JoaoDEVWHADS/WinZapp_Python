from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_text_status_has_bounded_ack_wait():
    source = (
        ROOT / "client" / "api_patches" / "src" / "controller"
        / "statusController.ts"
    ).read_text(encoding="utf-8")
    assert "waitForAck: true" in source
    assert "const sendPromise = req.client.sendTextStatus(" in source
    assert "const timeoutPromise = new Promise(" in source
    assert "statusTimeoutHandled: true" in source
    assert "10000" in source
    assert "Promise.race([sendPromise, timeoutPromise])" in source


def test_status_http_timeout_allows_ack_fallback_to_finish():
    source = (ROOT / "client" / "status_panel.py").read_text(encoding="utf-8")
    assert source.count(
        "api_post(url, json=payload, headers=headers, timeout=60)"
    ) >= 3
