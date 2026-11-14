"""Extra group routes: the pure functions that build what the bridge returns."""
import base64
import io
from types import SimpleNamespace as N

import pytest
from PIL import Image

import groups_extra as g


def jid(user="", server="s.whatsapp.net"):
    return N(User=user, Server=server)


def person(phone="", lid="", jid_="", admin=False, owner=False, name=""):
    return N(JID=jid(jid_), LID=jid(lid, "lid"), PhoneNumber=jid(phone),
             IsAdmin=admin, IsSuperAdmin=owner, DisplayName=name)


def group(participants, name="Class", announcement=False, locked=False):
    return N(JID=jid("111-222", "g.us"), OwnerPN=jid("5511"), OwnerJID=jid(),
             GroupName=N(Name=name), GroupTopic=N(Topic="desc"),
             GroupAnnounce=N(IsAnnounce=announcement), GroupLocked=N(isLocked=locked),
             GroupCreated=1700000000, Participants=participants)


def test_group_jid_only_completes_what_is_missing():
    assert g.group_jid("111-222") == "111-222@g.us"
    assert g.group_jid("111-222@g.us") == "111-222@g.us"
    assert g.group_jid(" 333@lid ") == "333@lid"


def test_groups_from_body_accepts_groupid_phone_and_list():
    assert g.groups_from_body({"groupId": "1@g.us"}) == ["1@g.us"]
    assert g.groups_from_body({"phone": "1"}) == ["1@g.us"]
    assert g.groups_from_body({"phone": ["1@g.us", "2@g.us"]}) == ["1@g.us", "2@g.us"]
    assert g.groups_from_body({"groupId": "", "phone": "3@g.us"}) == ["3@g.us"]
    assert g.groups_from_body({}) == []


def test_as_boolean():
    assert g.as_boolean(None) is True
    assert g.as_boolean(None, False) is False
    assert g.as_boolean("false") is False
    assert g.as_boolean("True") is True
    assert g.as_boolean(False) is False
    assert g.as_boolean(0) is False
    assert g.as_boolean("") is True


def test_wid_uses_the_whatsapp_web_format():
    assert g.wid_of("5511:12@s.whatsapp.net") == {
        "server": "c.us", "user": "5511", "_serialized": "5511@c.us"}
    assert g.wid_of("333@lid")["_serialized"] == "333@lid"


def test_participant_prefers_the_number_and_carries_the_lid():
    row = g.participant_to_wpp(person(phone="5511", lid="333", admin=True, name="Ana"))
    assert row == {"id": {"server": "c.us", "user": "5511", "_serialized": "5511@c.us"},
                   "isAdmin": True, "isSuperAdmin": False,
                   "lid": {"server": "lid", "user": "333", "_serialized": "333@lid"},
                   "name": "Ana"}


def test_participant_with_only_a_lid_uses_the_lid_and_the_owner_counts_as_admin():
    row = g.participant_to_wpp(person(lid="333", owner=True))
    assert row["id"]["_serialized"] == "333@lid"
    assert row["isAdmin"] and row["isSuperAdmin"]
    assert "name" not in row


def test_a_hidden_number_is_not_the_member_name():
    row = g.participant_to_wpp(person(phone="5511", lid="333", name="+55∙∙∙∙∙∙∙∙76"))
    assert "name" not in row
    assert g.is_masked_number("+1 ∙∙∙ ∙∙∙-∙∙33")
    for name in ("Ana", "Ana • Silva", "+55 11 99999-0000", "", None):
        assert not g.is_masked_number(name)


def test_members_ids_and_administrators():
    info = group([person(phone="1", admin=True), person(phone="2"), person(phone="3", owner=True)])
    assert [m["id"]["user"] for m in g.members_to_wpp(info)] == ["1", "2", "3"]
    assert [i["_serialized"] for i in g.member_ids(info)] == ["1@c.us", "2@c.us", "3@c.us"]
    assert [i["_serialized"] for i in g.administrator_ids(info)] == ["1@c.us", "3@c.us"]


def test_group_becomes_the_chat_of_all_groups():
    chat = g.group_to_chat(group([person(phone="1")], announcement=True, locked=True))
    assert chat["id"]["_serialized"] == "111-222@g.us" and chat["isGroup"] is True
    meta = chat["groupMetadata"]
    assert meta["subject"] == "Class" and meta["desc"] == "desc"
    assert meta["announce"] is True and meta["restrict"] is True
    assert meta["owner"]["_serialized"] == "5511@c.us"
    assert meta["creation"] == 1700000000
    assert len(meta["participants"]) == 1


def test_group_without_a_known_owner_does_not_break():
    info = group([])
    info.OwnerPN = jid()
    assert g.group_to_chat(info)["groupMetadata"]["owner"] is None


def test_properties_neonize_knows_how_to_change():
    assert g.property_action("announce") == "announce"
    assert g.property_action("Restrict") == "locked"
    assert g.property_action("ephemeral") is None
    assert g.property_action(None) is None


def png(side=10):
    output = io.BytesIO()
    Image.new("RGBA", (side, side), (255, 0, 0, 128)).save(output, format="PNG")
    return output.getvalue()


def test_image_from_body_reads_base64_and_data_uri():
    data = png()
    plain = base64.b64encode(data).decode()
    assert g.image_from_body({"base64": plain}) == data
    assert g.image_from_body({"path": "data:image/png;base64," + plain}) == data
    assert g.image_from_body({}) == b""


def test_image_from_body_refuses_what_is_not_base64_and_does_not_read_files():
    with pytest.raises(ValueError):
        g.image_from_body({"path": "C:/Users/x/photo.png"})
    with pytest.raises(ValueError):
        g.image_from_body({"base64": "this is not base64!"})


def test_photo_becomes_jpeg_and_shrinks():
    jpeg = g.photo_to_jpeg(png(1000))
    image = Image.open(io.BytesIO(jpeg))
    assert image.format == "JPEG" and max(image.size) == g.MAX_PHOTO_SIDE


def test_small_jpeg_passes_without_recompression():
    output = io.BytesIO()
    Image.new("RGB", (50, 50)).save(output, format="JPEG")
    assert g.photo_to_jpeg(output.getvalue()) == output.getvalue()


def test_invalid_photo_raises_an_error():
    with pytest.raises(Exception):
        g.photo_to_jpeg(b"not an image")
