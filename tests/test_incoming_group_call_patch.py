from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_incoming_group_call_uses_native_participants_when_group_flag_is_missing():
    source = (ROOT / "client/api_patches/src/util/createSessionUtil.ts").read_text(
        encoding="utf-8"
    )

    # A selected-participant call has no group chat JID, and the active model
    # can be published before its group flag is hydrated.
    assert "const groupParticipantCountOf = (call: any): number =>" in source
    assert "!!groupJidOf(call) || groupParticipantCountOf(call) > 1" in source
    assert "const isGroup = isGroupCall(richCall) || isGroupCall(call)" in source


def test_incoming_group_evidence_survives_stale_store_model():
    source = (ROOT / "client/api_patches/src/util/createSessionUtil.ts").read_text(
        encoding="utf-8"
    )

    assert "isGroupCall(richCall) || isGroupCall(call)" in source
    assert "emitCall('offer', richCall, 'INCOMING_RING', call)" in source
    assert "isGroupCall(call) || isGroupCall(evidence)" in source
    assert "groupJidOf(call) || groupJidOf(evidence)" in source
    assert "call?.get?.('isGroup')" in source
