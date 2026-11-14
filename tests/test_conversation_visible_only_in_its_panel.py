"""An open conversation is on screen only while the panel it was opened from
(main, archived or locked) is the one shown.

The pure rules are tested here (a plain switch hides it everywhere; an
explicit reveal shows it in its own panel); the real entry points (Alt+1,
Alt+4, the navigation list, the locked panel, Alt+2/3/M) are in
test_panel_switch_wiring.py.
"""

from core.conversation_view import (
    ARCHIVED, LOCKED, MAIN, conversation_visible_in, mnemonic_letter,
    resolve_origin,
)

A = "a@s.whatsapp.net"


def test_a_conversation_is_visible_only_in_its_own_panel():
    assert conversation_visible_in(ARCHIVED, ARCHIVED)
    assert not conversation_visible_in(ARCHIVED, MAIN)
    assert not conversation_visible_in(MAIN, ARCHIVED)
    assert not conversation_visible_in(LOCKED, MAIN)
    assert not conversation_visible_in(None, MAIN)


def test_origin_defaults_to_main_even_for_an_archived_chat_from_the_search_box():
    assert resolve_origin(None, None, True, False) == MAIN
    assert resolve_origin(None, MAIN, True, True) == MAIN


def test_origin_is_kept_for_a_chat_opened_from_inside_a_detail_only_conversation():
    assert resolve_origin(None, ARCHIVED, False, True) == ARCHIVED
    assert resolve_origin(None, LOCKED, False, True) == LOCKED
    # the archived chat is parked behind the main list: that is not inside it
    assert resolve_origin(None, ARCHIVED, True, False) == MAIN


def test_an_explicit_origin_wins():
    assert resolve_origin(ARCHIVED, MAIN, True, True) == ARCHIVED


def test_mnemonic_letter():
    assert mnemonic_letter("&Mensagens", "X") == "M"
    assert mnemonic_letter("Ty&pe a message to", "X") == "P"
    assert mnemonic_letter("Messages", "M") == "M"
    assert mnemonic_letter("Messages &", "M") == "M"
    assert mnemonic_letter("& x", "M") == "M"


def _esc(monkeypatch, origin, jid=A, unlocked=True):
    import wx
    from ui.conversation_panel.conversation_navigation import ConversationNavigationMixin

    queued = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a: queued.append(fn.__name__))

    class _Stub:
        _conversation_origin = origin
        main_window = type("MW", (), {
            "_chat_lock_unlocked": unlocked,
            "archived_conversations_panel": object(),
            "locked_conversations_panel": object(),
        })()

        def _close_conversation_core(self):
            return True, jid

        def _restore_to_archived_list(self, jid): pass
        def _restore_to_locked_list(self, jid): pass
        def _restore_conversation_selection(self): pass

    ConversationNavigationMixin.close_conversation(_Stub())
    return queued


def test_esc_returns_to_the_list_the_conversation_was_opened_from(monkeypatch):
    assert _esc(monkeypatch, ARCHIVED) == ["_restore_to_archived_list"]
    assert _esc(monkeypatch, LOCKED) == ["_restore_to_locked_list"]
    assert _esc(monkeypatch, MAIN) == ["_restore_conversation_selection"]


def test_esc_on_a_locked_origin_with_a_closed_vault_goes_to_the_main_list(monkeypatch):
    assert _esc(monkeypatch, LOCKED, unlocked=False) == ["_restore_conversation_selection"]
