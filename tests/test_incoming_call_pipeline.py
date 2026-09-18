"""Regression coverage for the native incoming-call pipeline.

(This file used to also carry test_wa_js_dependency_is_pinned_to_an_exact_
revision, a guard that could not fail — see
tests/test_wpp_homologated_runtime_pin.py, which replaced it.)
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_api_patch_forwards_native_call_events_to_socket_io():
    source = _source("client/api_patches/src/util/createSessionUtil.ts")
    assert "WPP.on('call.incoming_call'" in source
    assert ".emit('incomingcall', {" in source
    assert "req.io.to(`session:${client.session}`)" in source
    assert "call?.id?.toString?.()" in source
    assert "ignored historical offer" in source


def test_websocket_normalizes_calls_before_dispatching_to_ui():
    source = _source("client/core/websocket_client.py")
    assert 'self.sio.on("incomingcall", self.on_wpp_incoming_call)' in source
    assert "self.main_window.on_incoming_call_event" in source
    assert "normalized" in source


def test_ui_has_native_alert_lifecycle_and_user_stop_controls():
    main = _source("client/main.py")
    dialog = _source("client/ui/dialogs/incoming_call.py")
    assert "_arm_incoming_call_watchdog" in main
    assert "stop_all_incoming_call_alerts" in main
    assert "_show_incoming_call_dialog" in main
    assert "IncomingCallDialog" in dialog


def test_active_call_poll_promotes_ringing_calls_to_incoming_alert_pipeline():
    source = _source("client/api_patches/src/util/createSessionUtil.ts")

    assert "let lastActiveIncomingOfferId = ''" in source
    assert "const isIncomingRingingCall =" in source
    assert "!isHistoricalIncomingCall(activeCall, 'activeCall')" in source
    assert "emitCall('offer', activeCall, 'INCOMING_RING')" in source
    assert "rememberCall(activeCall)" in source

def test_native_active_call_change_event_promotes_incoming_calls_immediately():
    source = _source("client/api_patches/src/util/createSessionUtil.ts")

    # Current WhatsApp Web can skip the old incoming-call event entirely.
    # Observe the native activeCall attribute exactly where the runtime mutates it.
    assert "WAWebCallCollection" in source
    assert "nativeCallCollection" in source
    assert "nativeCallCollection.on('change:activeCall'" in source
    assert "args.find(" in source
    assert "isIncomingRingingCall(call)" in source
    assert "emitIncomingOffer(call, 0, 'activeCallChange')" in source


def test_native_call_collection_is_preferred_for_active_call_polling():
    source = _source("client/api_patches/src/util/createSessionUtil.ts")

    assert "const stores = [\n            nativeCallCollection," in source
