from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_wppconnect_patch_exposes_voice_call_control_routes():
    routes = _source("client/api_patches/src/routes/index.ts")
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert '/api/:session/call/accept' in routes
    assert '/api/:session/call/reject' in routes
    assert '/api/:session/call/end' in routes
    assert '/api/:session/call/offer' in routes
    assert "getVoipStackInterface" in controller
    assert "enableCallInterface" in controller
    assert "requireVoipJsBackend" in controller
    assert "initWAWebVoip" in controller
    assert "acceptCall(true" in controller
    assert "rejectCall()" in controller
    assert "endCall(2, true)" in controller
    assert "WPP.call.accept" in controller
    assert "WPP.call.rejectCall" in controller
    assert "WPP.call.end" in controller
    assert "WPP.call.offer" in controller
    assert "prepareAudioBridge(req)" in controller


def test_call_media_bridge_replaces_browser_microphone_with_python_pcm():
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    assert "navigator.mediaDevices" in bridge
    assert "getUserMedia" in bridge
    assert "MediaStreamAudioDestinationNode" in bridge or "createMediaStreamDestination" in bridge
    assert "pushMicrophone" in bridge
    assert "decodePcm16" in bridge
    assert "call:audio:mic" in bridge
    assert "call:audio:remote" in bridge
    assert "RTCPeerConnection" in bridge
    assert "__winzappOnCallRemoteAudio" in bridge
    assert "if (!constraints?.audio) return nativeGetUserMedia(constraints)" in bridge
    assert "if (!state.enabled || !constraints?.audio)" not in bridge


def test_chromium_does_not_disable_voice_input_for_python_call_bridge():
    config = _source("client/api_patches/src/config.ts")
    session_util = _source("client/api_patches/src/util/sessionUtil.ts")

    assert "--disable-voice-input" not in config
    assert "--disable-voice-input" not in session_util
    assert "--mute-audio" in config


def test_setup_api_copies_call_patch_files_into_runtime_api():
    setup_api = _source("setup_api.py")

    assert "src/util/callMediaBridge.ts" in setup_api
    assert "src/controller/callController.ts" in setup_api
