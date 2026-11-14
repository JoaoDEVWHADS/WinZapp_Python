import server


def test_id_parts_private_and_group():
    s = server.Session
    assert s.id_parts("true_5551@c.us_ABC") == (True, "5551@s.whatsapp.net", "ABC", "")
    assert s.id_parts("false_123@g.us_XYZ_9@lid") == (False, "123@g.us", "XYZ", "9@lid")
    assert s.id_parts("loose") == (False, "", "loose", "")
