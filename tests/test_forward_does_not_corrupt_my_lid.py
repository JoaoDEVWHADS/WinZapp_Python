"""Regression test for MainWindow.on_new_message()'s "learn my_lid from a
fromMe message's own participant field" heuristic.

Reported live: forwarding a contact's message from a group into "Mensagens
para mim" (the self-chat) made that SAME CONTACT'S messages, in a completely
different chat, start rendering as if they were the user's own — the chat
list's last-message preview showed "Eu" for a message the contact actually
sent, and replies to the contact showed "respondendo a Eu" instead of the
contact's name.

Root cause: on_new_message() has a documented, deliberate heuristic — "a
fromMe message's own 'participant' field always identifies us" — used to
learn self.my_lid the first time the user sends any group message this
session, without waiting on the async resolve_self_lid() API round-trip.
That assumption is true for an ordinary fromMe group send, but not for a
*forwarded* copy: the copy's own contextInfo/participant fields can carry
residual provenance about whoever originally authored the message being
forwarded, not about the forward action's actual sender (always the current
user, on a fromMe message). Forwarding to "Mensagens para mim" hit this
directly — self.my_lid got set to the ORIGINAL AUTHOR's own @lid, which then
made _is_self_jid() (and therefore every "is this fromMe/me" check
throughout the app) treat that person as the user themselves, everywhere,
for the rest of the session.

The fix excludes any message is_message_forwarded() flags true from ever
being used as the my_lid-learning signal. Since on_new_message() is a huge
method with many other dependencies not relevant here, this is a source
inspection test (same pattern already used elsewhere in this codebase for
methods embedded too deep in the "god object" to cheaply stub — see
test_system_event_actions_blocked.py's TestDeleteKeepsLocalButDropsForEveryone)
rather than a full behavioral drive of on_new_message() itself.
"""

import inspect

from main import MainWindow


class TestMyLidLearningExcludesForwardedMessages:
    def test_the_heuristic_checks_is_message_forwarded(self):
        src = inspect.getsource(MainWindow.on_new_message)
        assert "not is_message_forwarded(msg)" in src

    def test_the_forwarded_check_is_part_of_the_same_guard_that_sets_my_lid(self):
        """Not just present somewhere in the method — actually gating the
        specific `self.my_lid = my_lid = participant_raw` assignment, not a
        loosely related check elsewhere in this very long method."""
        src = inspect.getsource(MainWindow.on_new_message)
        guard_at = src.index("not is_message_forwarded(msg)")
        assignment_at = src.index("self.my_lid = my_lid = participant_raw")
        # The guard's own `if` statement must be the one immediately
        # preceding the assignment (no unrelated code in between deciding
        # whether the assignment runs).
        between = src[guard_at:assignment_at]
        assert between.count("\n") <= 3, (
            "is_message_forwarded(msg) is not right next to the "
            "self.my_lid assignment it's supposed to guard"
        )
