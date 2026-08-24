"""Test for GitHub issue #12: editing the most recent message in a chat
didn't update its preview in the conversations list.

Root cause: ConversationsPanel's edit-mode branch (_apply_message_edit(),
split out of on_send_message()) mutates the message dict in place and
persists it via
main_window._schedule_save(), but never told the conversations LIST widget
to redraw — _last_msg_preview() (main.py) reads straight from the mutated
record so the data was correct, nothing just repainted the row. Only
closing the conversation (which rebuilds the list for an unrelated reason)
picked up the change. The companion path for a REMOTE edit
(_apply_possible_edit(), main.py) already called
main_window._schedule_set_chats() and never had this bug — this fixes the
local-edit path to match.

The edit path sits deep in wx widget interactions (message_field, mention
pills, etc.) that aren't practical to drive end to end without a running
wx.App, so this pins the fix structurally via source inspection — same
approach as tests/test_archived_context_menu.py. The behaviour it can be
driven for lives in tests/test_edit_message_off_ui_thread.py.
"""

import inspect
import re

from ui.conversations import ConversationsPanel


def test_edit_mode_branch_refreshes_the_conversations_list():
    edit_branch = inspect.getsource(ConversationsPanel._apply_message_edit)

    assert "self.main_window._schedule_save(dirty_jid=remote_jid)" in edit_branch
    assert "self.main_window._schedule_set_chats()" in edit_branch, (
        "the edit-mode branch persists the edit but never refreshes the "
        "conversations list preview — issue #12"
    )

    # The refresh call must come after the save, and before edit mode is
    # exited (_on_cancel_edit()), matching the flow described in the fix.
    save_pos    = edit_branch.index("self.main_window._schedule_save(dirty_jid=remote_jid)")
    refresh_pos = edit_branch.index("self.main_window._schedule_set_chats()")
    cancel_pos  = edit_branch.index("self._on_cancel_edit()")
    assert save_pos < refresh_pos < cancel_pos
