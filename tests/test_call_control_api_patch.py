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
    assert '/api/:session/call/diagnostics' in routes
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
    assert "isOutgoingOrLiveCall" in controller
    assert "without successful voipInit" in controller
    assert "installAudioBridge(req)" in controller
    assert "callDiagnostics" in controller


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
    assert "if (!constraints?.audio && !constraints?.video) {" in bridge
    assert "new MediaStream([cameraTrack()])" in bridge
    assert "call:video:camera" in bridge
    assert "call:video:remote" in bridge
    assert "video-request-refused" not in bridge
    assert "microphone" in bridge
    assert "camera" in bridge
    assert "webkitGetUserMedia" in bridge
    assert "if (!state.enabled || !constraints?.audio)" not in bridge

def test_chromium_does_not_disable_voice_input_for_python_call_bridge():
    start_js = _source("client/api_patches/start.js")
    config = _source("client/api_patches/src/config.ts")
    session_util = _source("client/api_patches/src/util/sessionUtil.ts")

    assert "'--disable-voice-input'," not in start_js
    assert "--disable-voice-input" not in config
    assert "--disable-voice-input" not in session_util
    assert "--mute-audio" not in config
    assert "\n  '--mute-audio'," not in start_js
    assert "--mute-audio" not in session_util
    assert "ignoreDefaultArgs: ['--mute-audio']" in start_js


def test_headless_chromium_auto_grants_webrtc_media_permission():
    start_js = _source("client/api_patches/start.js")
    config = _source("client/api_patches/src/config.ts")
    session_util = _source("client/api_patches/src/util/sessionUtil.ts")

    # Current WhatsApp Web initializes the native VoIP backend only after the
    # browser-level media permission gate passes.  The Python bridge replaces
    # getUserMedia with a synthetic track, while fake-ui removes Chromium's
    # permission UI (which cannot be answered in headless mode). Never launch
    # a fake capture device: WhatsApp's native VoIP backend can bypass the JS
    # wrapper and would then transmit Chromium's silent test microphone.
    for source in (start_js, config, session_util):
        assert "--use-fake-ui-for-media-stream" in source
        assert "--use-fake-device-for-media-stream" not in source


def test_runtime_user_agent_matches_the_launched_chromium_for_voip():
    start_js = _source("client/api_patches/start.js")

    assert "WAuserAgente" in start_js
    assert "uaModule.useragentOverride" in start_js
    assert "Chromium user-agent aligned" in start_js


def test_pinned_document_preserves_cross_origin_isolation_for_voip_wasm():
    start_js = _source("client/api_patches/start.js")

    assert "Cross-Origin-Opener-Policy" in start_js
    assert "Cross-Origin-Embedder-Policy" in start_js
    assert "require-corp" in start_js
    assert "Origin-Agent-Cluster" in start_js
    assert "--disable-web-security" not in start_js


def test_chromium_keeps_rendering_backend_available_for_voip_runtime():
    session_util = "\n".join(
        line
        for line in _source("client/api_patches/src/util/sessionUtil.ts").splitlines()
        if not line.lstrip().startswith("//")
    )

    assert "--disable-software-rasterizer" not in session_util
    assert "--disable-3d-apis" not in session_util
    assert "--disable-webgl" not in session_util


def test_cdp_permission_grant_includes_voip_capture_permissions():
    create_session = _source("client/api_patches/src/util/createSessionUtil.ts")
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    granted = [
        line for line in create_session.splitlines()
        if "permissions: [" in line and not line.lstrip().startswith("//")
    ]
    assert len(granted) == 1, granted
    assert "'audioCapture'" in granted[0]
    assert "'videoCapture'" in granted[0]
    assert "name === 'microphone' || name === 'camera'" in bridge
    assert "new MediaStream([cameraTrack()])" in bridge
    assert "video-request-refused" not in bridge

def test_setup_api_copies_call_patch_files_into_runtime_api():
    setup_api = _source("setup_api.py")

    assert "src/util/callMediaBridge.ts" in setup_api
    assert "src/controller/callController.ts" in setup_api


def test_outgoing_call_allows_native_voip_more_than_generic_http_timeout():
    main_py = _source("client/main.py")

    offer = main_py[main_py.index("def _start_individual_call"):]
    offer = offer[: offer.index("threading.Thread(target=_worker")]
    assert '"offer",' in offer
    assert "timeout=75," in offer
    assert "dial_jid = self._resolve_jid_for_send(peer_jid) or peer_jid" in offer
    assert '{"to": dial_jid, "isVideo": is_video}' in offer

def test_outgoing_call_prefers_new_active_call_over_stale_collection_model():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "const preexistingIds = new Set(" in controller
    assert "const previousActiveId = callIdOf(storeBeforeOffer?.activeCall)" in controller
    assert "const active = store?.activeCall" in controller
    assert "activeId !== previousActiveId" in controller
    assert "!preexistingIds.has(offeredId)" in controller
    assert "!preexistingIds.has(modelId)" in controller




def test_active_call_poll_tolerates_transient_active_call_gaps():
    source = _source("client/api_patches/src/util/createSessionUtil.ts")

    assert "const ACTIVE_CALL_MISSING_GRACE_MS = 5000" in source
    assert "let activeCallMissingSince = 0" in source
    assert "if (previousId) activeCall = findCall(previousId)" in source
    assert "now - activeCallMissingSince < ACTIVE_CALL_MISSING_GRACE_MS" in source
    assert "emitCallState('ended', lastActiveCall, 'ENDED')" in source
    # The regression was a one-poll null immediately becoming ENDED.
    assert "if (!activeCall) {\n                if (lastActiveCall) {" not in source

def test_handled_incoming_call_cannot_fire_stale_120_second_timeout():
    create_session = _source("client/api_patches/src/util/createSessionUtil.ts")
    controller = _source("client/api_patches/src/controller/callController.ts")

    # Valmir's log showed offer -> accept -> NOT_ANSWERED exactly 120 seconds
    # after the original offer. Newer WA keeps accepted calls in activeCall,
    # so the incoming tracker must see that slot instead of its stale ring model.
    assert "const active = store?.activeCall || store?.get?.('activeCall')" in create_session
    assert "if (active && callIdOf(active) === id) return active" in create_session

    # Successful WinZapp actions also retire the incoming watchdog explicitly,
    # covering builds where activeCall changes identity during the transition.
    assert "__winzappForgetIncomingCall" in create_session
    assert "trackedCalls.delete(id)" in create_session
    assert "forgetIncomingCall(callId || callIdOf(call))" in controller
    assert "forgetIncomingCall(callId)" in controller
    assert "forgetIncomingCall(handledCallId)" in controller

def test_session_prewarms_lazy_whatsapp_voip_runtime():
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")
    create_session = _source("client/api_patches/src/util/createSessionUtil.ts")

    assert "export async function warmCallVoipRuntime" in bridge
    assert "requireVoipJsBackend" in bridge
    assert "initWAWebVoip" in bridge
    assert "getVoipStackInterface" in bridge
    assert "void warmCallVoipRuntime(client, req.logger)" in create_session
def test_native_call_actions_wait_for_lazy_voip_rpc_initialization():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "const maxAttempts = 8" in controller
    assert "isVoipInitError(error)" in controller
    assert "Math.min(1500, 300 * (attempt + 1))" in controller
    assert "winzapp_call_action" in controller
    assert "getIsVoipInited" in controller
    assert "retryWAWebVoipInitAfterFailure" in controller


def test_voip_initialization_can_retry_after_lazy_backend_failure():
    """A failed lazy VoIP initialization must be retried by WinZapp's bridge."""
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    assert "WPP?.call?.enableCallInterface" in bridge
    assert "getDidVoipInitError" in bridge
    assert "retryWAWebVoipInitAfterFailure" in bridge
    assert "attempt < 10" in bridge

def test_voip_runtime_warmup_is_deduplicated_per_session():
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    assert "__winzappVoipWarmupPromise" in bridge
    assert "if (pending) return pending" in bridge
    assert "delete (client as any).__winzappVoipWarmupPromise" in bridge
    assert "winzapp_session_warmup" in bridge
    assert "getDidVoipInitError" in bridge


def test_page_native_audio_is_always_muted_without_touching_real_call_audio():
    """WhatsApp Web's own sounds (ringtone, message chimes) must never be
    audible through this Chromium process. The prior diagnostic
    instrumentation confirmed live that the ringtone plays as a plain,
    looping <audio> element's native .play() (isRtcStream=false) — a
    categorically different path from the call's own remote audio track,
    which never touches an <audio>/Audio() element at all: it is tapped
    directly off the RTCPeerConnection's MediaStreamTrack via the Web Audio
    API and was already silenced before this fix (attachRemoteTrack's
    `sink` GainNode, gain=0). So muting every native <audio>/<video> element
    and every `new Audio()` instance, unconditionally, is safe — there is no
    call-state window where it would also mute real call audio, so nothing
    needs to be tracked or toggled back on.

    This also fixes the sibling report from the same investigation: a
    missed/unanswered call left the page's own ringtone looping forever,
    because the terminal callstate/incomingcall handling in main.py only
    ever stops WinZapp's own sound — it has no way to reach into the page.
    Muting page audio unconditionally removes that dependency entirely.
    """
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    assert "el.muted = true;" in bridge
    assert "el.volume = 0;" in bridge
    assert "win.HTMLMediaElement.prototype.play = function" in bridge
    assert "return nativeMediaPlay.apply(this, args);" in bridge
    assert "win.Audio = new Proxy(NativeAudio" in bridge
    # The autoplay-attribute backstop is scanMediaElements() itself — it must
    # silence every element it finds, not only the RTC-stream ones.
    scan = bridge[bridge.index("const scanMediaElements = ()"):]
    scan = scan[: scan.index("\n  };")]
    assert "silenceElement(element);" in scan
    # Bounded, so a call with a looping/reactivating ringtone cannot flood
    # wppconnect.log for the rest of the session.
    assert "if (mutedLogCount > 40) return;" in bridge
