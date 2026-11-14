"""Which calls the connection engine takes (core/call_logic.engine_refuses_call):
WPPConnect all of them; the Neonize bridge what its /send-capabilities says it
carries: calls, video calls, group calls."""

import pytest

from core.call_logic import engine_refuses_call


@pytest.mark.parametrize("placing, is_video, is_group", [
    (True, False, False), (True, True, False), (True, False, True), (False, True, True),
])
def test_wppconnect_takes_every_call(placing, is_video, is_group):
    assert not engine_refuses_call(False, False, placing=placing,
                                   is_video=is_video, is_group=is_group)


def test_a_bridge_without_the_call_layer_takes_none():
    assert engine_refuses_call(True, False, placing=True)
    assert engine_refuses_call(True, False, placing=False)


def test_a_bridge_with_voice_calls_only_places_one_to_one_voice_calls():
    assert not engine_refuses_call(True, True, placing=True)
    assert engine_refuses_call(True, True, placing=True, is_video=True)
    assert engine_refuses_call(True, True, placing=True, is_group=True)


def test_a_bridge_with_video_and_group_calls_places_them():
    def refuses(is_video, is_group, video, group):
        return engine_refuses_call(True, True, placing=True, is_video=is_video,
                                   is_group=is_group, bridge_has_video=video,
                                   bridge_has_group_calls=group)
    assert not refuses(True, False, True, False)
    assert not refuses(False, True, False, True)
    assert not refuses(True, True, True, True)
    assert refuses(True, True, False, True)          # a group video call needs both
    assert refuses(True, True, True, False)
    # without the call layer, nothing, whatever else it says
    assert engine_refuses_call(True, False, placing=True, bridge_has_video=True,
                               bridge_has_group_calls=True)


def test_it_answers_any_incoming_call_with_voice():
    assert not engine_refuses_call(True, True, placing=False, is_video=True, is_group=True)
