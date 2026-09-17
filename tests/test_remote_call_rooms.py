from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_remote_call_audio_is_emitted_only_to_authenticated_session_room():
    source = (ROOT / "client/api_patches/src/util/callMediaBridge.ts").read_text(encoding="utf-8")
    assert "io.to(`session:${client.session}`).emit('call:audio:remote'" in source
    assert "io.emit('call:audio:remote'" not in source


def test_remote_call_signaling_is_emitted_only_to_session_room():
    source = (ROOT / "client/api_patches/src/util/createSessionUtil.ts").read_text(encoding="utf-8")
    assert source.count("req.io.to(`session:${client.session}`).emit('incomingcall'") == 2
    assert "req.io.to(`session:${client.session}`).emit('callstate'" in source


def test_unrelated_socket_events_keep_existing_behavior():
    source = (ROOT / "client/api_patches/src/util/createSessionUtil.ts").read_text(encoding="utf-8")
    # This change is deliberately call-only: normal message ACK traffic remains untouched.
    assert "req.io.emit('onack', { ...ack, session: client.session });" in source
