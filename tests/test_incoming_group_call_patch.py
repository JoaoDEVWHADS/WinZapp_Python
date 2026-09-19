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
    assert "const isGroup = isGroupCall(richCall)" in source
    assert "isGroupCall(call)," in source
