from core.phone_variants import (
    brazilian_variant_chat_jid,
    other_brazilian_mobile_jid,
)


def test_nine_digit_mobile_maps_to_the_eight_digit_form_and_back():
    nine = "5511987654321@s.whatsapp.net"
    eight = "551187654321@s.whatsapp.net"
    assert other_brazilian_mobile_jid(nine) == eight
    assert other_brazilian_mobile_jid(eight) == nine


def test_non_brazilian_and_non_phone_jids_have_no_variant():
    assert other_brazilian_mobile_jid("14155550123@s.whatsapp.net") == ""
    assert other_brazilian_mobile_jid("5511987654321@lid") == ""
    assert other_brazilian_mobile_jid("120363@g.us") == ""
    assert other_brazilian_mobile_jid("") == ""


def test_variant_chat_is_found_only_when_it_exists():
    chats = {"5511987654321@s.whatsapp.net": {}}
    assert (
        brazilian_variant_chat_jid(chats, "551187654321@s.whatsapp.net")
        == "5511987654321@s.whatsapp.net"
    )
    assert brazilian_variant_chat_jid({}, "551187654321@s.whatsapp.net") == ""


def test_a_landline_has_no_nine_digit_variant():
    assert other_brazilian_mobile_jid("551133334444@s.whatsapp.net") == ""
