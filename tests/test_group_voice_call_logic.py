from core.call_logic import active_call_label_key, incoming_call_can_answer


def test_group_voice_call_is_answerable_but_group_video_is_not():
    assert incoming_call_can_answer({"is_group": True, "is_video": False}) is True
    assert incoming_call_can_answer({"is_group": True, "is_video": True}) is False


def test_direct_voice_call_remains_answerable():
    assert incoming_call_can_answer({"is_group": False, "is_video": False}) is True


def test_group_voice_call_uses_group_specific_label_key():
    assert active_call_label_key({"is_group": True}) == "voice_group_call_active_label"
    assert active_call_label_key({"is_group": False}) == "voice_call_active_label"
