from core.call_logic import (
    active_call_label_key,
    incoming_call_can_answer,
    normalize_group_call_participants,
)


def test_group_voice_call_is_answerable_but_group_video_is_not():
    assert incoming_call_can_answer({"is_group": True, "is_video": False}) is True
    assert incoming_call_can_answer({"is_group": True, "is_video": True}) is False


def test_direct_voice_call_remains_answerable():
    assert incoming_call_can_answer({"is_group": False, "is_video": False}) is True


def test_group_voice_call_uses_group_specific_label_key():
    assert active_call_label_key({"is_group": True}) == "voice_group_call_active_label"
    assert active_call_label_key({"is_group": False}) == "voice_call_active_label"


def test_group_call_participants_normalize_phone_jids_and_resolve_lids():
    result = normalize_group_call_participants(
        [
            "551100000001@s.whatsapp.net",
            "551100000002@c.us",
            "12345@lid",
            "12345@lid",
            "99999@g.us",
        ],
        {"12345@lid": "551100000003@s.whatsapp.net"},
    )

    assert result == [
        "551100000001@c.us",
        "551100000002@c.us",
        "551100000003@c.us",
    ]


def test_group_call_participants_skip_unresolved_lids():
    assert normalize_group_call_participants(["12345@lid", "5511@s.whatsapp.net"]) == [
        "5511@c.us"
    ]


def test_main_window_posts_group_voice_call_to_group_offer_endpoint():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "client/main.py").read_text(encoding="utf-8")
    assert "def start_group_voice_call(" in source
    assert '"group/offer",' in source
    assert '{"participants": participants, "isVideo": False}' in source
    assert '"is_group": True' in source
