"""Label routes: the pure functions that build what the bridge stores and answers."""
import labels


def test_first_label_of_the_bridge_does_not_collide_with_the_phones():
    assert labels.next_id({}) == "1000"


def test_next_id_follows_the_highest_one_already_used():
    assert labels.next_id({"1000": {}, "1004": {}, "3": {}}) == "1005"


def test_requested_valid_color_is_respected_and_the_rest_rotates():
    assert labels.color_index({"labelColor": 7}, {}) == 7
    assert labels.color_index({"color": 0}, {"a": {}}) == 0
    assert labels.color_index(None, {"a": {}, "b": {}}) == 2
    assert labels.color_index({"labelColor": 4278190335}, {}) == 0
    assert labels.color_index({"labelColor": True}, {}) == 0
    assert labels.color_index(None, {str(i): {} for i in range(21)}) == 1


def test_create_registers_and_returns_the_wpp_entry():
    registry = {}
    fresh = labels.create(registry, "Customers", {"labelColor": 5})
    assert fresh == {"id": "1000", "name": "Customers", "colorIndex": 5, "count": 0}
    assert registry["1000"]["chats"] == []
    assert labels.create(registry, "Suppliers", None)["id"] == "1001"


def test_list_comes_out_in_numeric_order_with_the_chat_count():
    registry = {"1010": {"name": "B", "colorIndex": 1, "chats": ["a@g.us", "b@g.us"]},
                "1002": {"name": "A", "colorIndex": 0, "chats": []}}
    assert labels.list_to_wpp(registry) == [
        {"id": "1002", "name": "A", "colorIndex": 0, "count": 0},
        {"id": "1010", "name": "B", "colorIndex": 1, "count": 2}]


def test_apply_marks_unmarks_and_ignores_an_unknown_label():
    registry = {"1000": {"name": "X", "colorIndex": 0, "chats": []}}
    labels.apply(registry, "1000", "5511@s.whatsapp.net", True)
    labels.apply(registry, "1000", "5511@s.whatsapp.net", True)
    assert registry["1000"]["chats"] == ["5511@s.whatsapp.net"]
    labels.apply(registry, "1000", "5511@s.whatsapp.net", False)
    assert registry["1000"]["chats"] == []
    labels.apply(registry, "7", "5511@s.whatsapp.net", True)
    assert "7" not in registry


def test_label_requests_reads_the_wpp_format_and_ignores_the_rest():
    options = [{"labelId": 76, "type": "add"}, {"labelId": "3", "type": "REMOVE"},
               {"labelId": "4"}, {"type": "add"}, {"labelId": "5", "type": "x"}, "junk"]
    assert labels.label_requests(options) == [
        ("76", True), ("3", False), ("4", True)]
    assert labels.label_requests(None) == []


def test_edit_mutation_has_whatsmeows_index():
    m = labels.edit_mutation(1000, "Customers", 3, False, 99)
    assert m["index"] == ["label_edit", "1000"]
    assert m["value"] == {"timestamp": 99, "labelEditAction": {
        "name": "Customers", "color": 3, "deleted": False}}


def test_chat_mutation_carries_the_jid_in_the_index():
    m = labels.chat_mutation("1000", "5511@s.whatsapp.net", False, 7)
    assert m["index"] == ["label_jid", "1000", "5511@s.whatsapp.net"]
    assert m["value"]["labelAssociationAction"] == {"labeled": False}


def test_save_and_load_round_trip(tmp_path):
    assert labels.load(tmp_path) == {}
    registry = {"1000": {"name": "Customer ç", "colorIndex": 2, "chats": ["a@g.us"]}}
    labels.save(tmp_path, registry)
    assert labels.load(tmp_path) == registry


def test_corrupted_file_becomes_an_empty_registry(tmp_path):
    (tmp_path / labels.FILE).write_text("{not json", encoding="utf-8")
    assert labels.load(tmp_path) == {}
