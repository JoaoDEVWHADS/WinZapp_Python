from pathlib import Path


SOURCE = Path("client/ui/conversations.py").read_text(encoding="utf-8")


def test_local_history_prefers_mapped_lid():
    assert "def _history_storage_jid" in SOURCE
    assert 'phone_to_lid.get(remote_jid, "")' in SOURCE
    assert "db.get_messages(storage_jid" in SOURCE


def test_duplicate_server_page_advances_anchor_instead_of_finishing():
    assert "self._server_history_anchor.get(phone_jid)" in SOURCE
    assert "self._server_history_anchor[phone_jid_val] = next_anchor" in SOURCE
    assert "Duplicate page advanced anchor" in SOURCE
    assert "not treating overlap as server start" in SOURCE


def test_only_empty_server_response_marks_start():
    fetch_block = SOURCE[SOURCE.index("def _fetch():"):SOURCE.index("def _set_reached_start")]
    assert "if fetched:" in fetch_block
    assert "self._set_reached_start" in fetch_block
    duplicate_block = SOURCE[SOURCE.index("if n_new == 0:"):SOURCE.index("self._recompute_unread_sep_idx()")]
    assert "_reached_server_start[" not in duplicate_block
