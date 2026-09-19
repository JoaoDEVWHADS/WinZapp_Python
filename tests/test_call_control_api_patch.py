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
    assert "if (!constraints?.audio) return nativeGetUserMedia(constraints)" in bridge
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

    assert "audioCapture" in create_session
    assert "videoCapture" in create_session


def test_setup_api_copies_call_patch_files_into_runtime_api():
    setup_api = _source("setup_api.py")

    assert "src/util/callMediaBridge.ts" in setup_api
    assert "src/controller/callController.ts" in setup_api


def test_outgoing_call_allows_native_voip_more_than_generic_http_timeout():
    main_py = _source("client/main.py")

    assert '"offer",\n                        {"to": peer_jid, "isVideo": False},\n                        timeout=75,' in main_py


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


def test_wa_js_voip_initialization_can_retry_after_lazy_backend_failure():
    source = _source("rm download/wa-js/src/call/functions/enableCallInterface.ts")

    assert "initializationPromise" in source
    assert "isEnabled = false" in source
    assert "throw err" in source


def test_voip_runtime_warmup_is_deduplicated_per_session():
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    assert "__winzappVoipWarmupPromise" in bridge
    assert "if (pending) return pending" in bridge
    assert "delete (client as any).__winzappVoipWarmupPromise" in bridge
    assert "winzapp_session_warmup" in bridge
    assert "getDidVoipInitError" in bridge


def test_group_voice_call_offer_matches_whatsapp_native_group_routing():
    routes = _source("client/api_patches/src/routes/index.ts")
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert '/api/:session/call/group/offer' in routes
    assert 'CallController.offerGroupCall' in routes
    assert "action === 'offer-group'" in controller
    assert "WAWebVoipStartCall" in controller
    assert "startWAWebVoipGroupCallFromChat" in controller
    assert "startWAWebVoipGroupCallFromWids" in controller
    assert "GROUP_CHAT_PICKER ?? 24" in controller
    assert "NOT_OPENED ?? 5" in controller
    assert "payload.useGroupChat === true" in controller
    assert "payload.groupJid" in controller
    assert "native-group-wids" in controller
    assert "WAWebWidFactory" in controller
    assert "At least two participants are required" in controller
    assert "Video group calls are not supported" in controller
    assert "prepareAudioBridge(req)" in controller


def test_group_voice_call_resolves_registered_participants_and_rejects_stale_active_call():
    controller = _source("client/api_patches/src/controller/callController.ts")

    # Partial group selection follows WhatsApp's own participant selector:
    # resolve a callable contact WID, then let FromWids perform its native
    # LID/PN conversion, device sync and TC-token fan-out.
    assert "WAWebQueryExistsJob" in controller
    assert "queryWidExists" in controller
    assert "if (!result?.wid && !result?.lid)" in controller
    assert "serializeId(result.wid).endsWith('@lid')" in controller
    assert ": result.wid || requestedWid;" in controller
    assert "participant is not registered or reachable" in controller

    # A stale outgoing model must not be mistaken for the WA-JS seed call.
    assert "const previousActiveId = callIdOf(callStore?.activeCall)" in controller
    assert "const preexistingIds = new Set(" in controller
    assert "activeId !== previousActiveId" in controller
    assert "!preexistingIds.has(activeId)" in controller


def test_group_voice_call_always_uses_selected_participant_native_path():
    controller = _source("client/api_patches/src/controller/callController.ts")
    conversations = _source("client/ui/conversations.py")

    assert "const rawValue =" in controller
    assert "call?.getState?.() ?? call?.state" in controller
    assert "state !== 'NONE'" in controller

    # Device testing showed FromChat creates a local CALLING model that dies
    # before ringing. WinZapp must keep group calls on the working FromWids
    # participant-picker path even when every member is selected.
    assert "await callStart.startWAWebVoipGroupCallFromChat(" not in controller
    assert "await callStart.startWAWebVoipGroupCallFromWids(" in controller
    assert "GROUP_CHAT_PICKER ?? 24" in controller
    assert "GROUP_CHAT_DIRECT ?? 25" not in controller
    assert "force-selected-participants" in controller
    assert "False," in conversations
    assert "full_group_selected =" not in conversations

    assert "WAWebVoipGatingUtils" in controller
    assert "isGroupCallingEnabled" in controller
    assert "groupParticipantCountOf(current) >= 2" in controller
    assert "did not create a live outgoing group call" in controller


def test_group_voice_call_rejects_ghost_calling_model_without_participants():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "groupParticipantCount: groupParticipantCountOf(call)" in controller
    assert "await callStart.startWAWebVoipGroupCallFromChat(" not in controller
    assert "await callStart.startWAWebVoipGroupCallFromWids(" in controller
    assert "current?.isGroup &&" in controller
    assert "groupParticipantCountOf(current) >= 2" in controller
    assert "activeId !== previousActiveId" in controller
    assert "!preexistingIds.has(activeId)" in controller


def test_group_call_api_emits_high_detail_diagnostics():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "WinZapp group-call request" in controller
    assert "WinZapp group-call result" in controller
    assert "const functionDiagnostic =" in controller
    assert "const callStoreSnapshot =" in controller
    assert "enable_web_voip_proxy_and_sctp_workers" in controller
    assert "enable_web_voip_webtransport_group_calls" in controller
    assert "stackStartGroupCall" in controller
    assert "startWAWebVoipGroupCallFromChat" in controller
    assert "startWAWebVoipGroupCallFromWids" in controller
    assert "for (const waitMs of [250, 500, 1000, 2000])" in controller
    assert "diagnostics.timeline" in controller
    assert "groupParticipantStates: groupParticipantStatesOf(call)" in controller
    assert "finalSeedCall: summarizeCall(startedCall)" in controller
    assert "diagnostics.voip.stackInvocation" in controller
    assert "original.apply(this, args)" in controller
    assert "restoreStartGroupCall?.()" in controller
    assert "diagnostics," in controller


def test_group_call_forces_main_thread_voip_stack():
    controller = _source("client/api_patches/src/controller/callController.ts")
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    for source in (controller, bridge):
        assert "enable_web_voip_proxy_and_sctp_workers" in source
        assert "__winzappDirectVoipStack" in source
        assert "return false" in source

    assert "winzappDirectVoipStack" in controller
    assert "WhatsApp aborted the outgoing group call before remote signaling remained active" in controller
    assert "const finalActiveCall = getCallStore()?.activeCall" in controller
    assert "groupParticipantCountOf(finalActiveCall) < 2" in controller


def test_group_call_failure_preserves_browser_diagnostics_in_node_logs():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "__winzappGroupCallFailure: true" in controller
    assert "Do not throw inside page.evaluate here" in controller
    assert "WinZapp group-call result" in controller
    assert "WinZapp group-call diagnostics" in controller
    assert "error.winzappGroupCallDiagnostics = result?.diagnostics || null" in controller


def test_group_call_probes_wasm_start_status():
    controller = _source("client/api_patches/src/controller/callController.ts")

    assert "WAWebBackendApi" in controller
    assert "initializeVoipWasm" in controller
    assert "__winzappStartVoipGroupCallProbe" in controller
    assert "__winzappLastStartVoipGroupCallStatus" in controller
    assert "originalStartVoipGroupCall(...args)" in controller
    assert "wasmProbe.lastStatus" in controller
    assert "pnCount" in controller
    assert "deviceCsvCount" in controller


def test_group_call_installs_wasm_probe_before_voip_warmup():
    controller = _source("client/api_patches/src/controller/callController.ts")
    bridge = _source("client/api_patches/src/util/callMediaBridge.ts")

    for source in (controller, bridge):
        assert "const installEarlyWasmProbe = () =>" in source
        assert "__winzappWasmProbeInstalled" in source
        assert "__winzappEarlyWasmProbeInstalled" in source
        assert "args[0] === 'initializeVoipWasm'" in source
        assert "__winzappLastStartVoipGroupCallStatus" in source

    assert "earlyHookInstalled" in controller
    assert "earlyWasmProbe=" in bridge
