"""Regression coverage for private-chat visible history pagination."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "client" / "main.py").read_text(encoding="utf-8")
CONVERSATIONS = (ROOT / "client" / "ui" / "conversations.py").read_text(
    encoding="utf-8"
)


def test_private_sync_requests_raw_margin_but_groups_do_not():
    assert 'fetch_limit = limit if remote_jid.endswith("@g.us") else limit + 50' in MAIN
    assert "get-messages/{phone}?count={fetch_limit}" in MAIN


def test_private_db_load_reads_raw_margin_before_visible_pagination():
    margin = '''if not _conv_jid.endswith("@g.us"):
                    limit += 50'''
    assert margin in CONVERSATIONS

    filter_pos = CONVERSATIONS.index(
        "displayable = [\n                m for m in messages_sorted"
    )
    paginate_pos = CONVERSATIONS.index(
        "self._messages_offset, self._unread_sep_idx = paginated_window("
    )
    assert filter_pos < paginate_pos
