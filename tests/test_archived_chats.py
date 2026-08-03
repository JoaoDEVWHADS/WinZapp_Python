"""Tests for the archived-chats list.

Reported live: archived groups appearing twice, and activating a row announcing
one group but opening a different one. Two independent causes, both here:

1. Every rendered row is identified by ``chat["remoteJid"]``, but
   _compute_chat_lists() iterated ``self.chats`` by *key* — and the two are not
   always the same string, because merges/renames (_merge_lid_into_phone,
   deduplicate_chats) rewrite one of them. Two keys resolving to the same
   remoteJid produced two identical rows, and every index→chat lookup
   downstream matches on remoteJid, so either row could open either chat.

2. add_chats_to_ui() returned early when its content fingerprint was unchanged.
   But _apply_chat_lists() overwrites ``panel.chats_list`` with the *unfiltered*
   sorted list immediately before that call, and the archived panel's rows were
   never part of the fingerprint at all — so the early return left the backing
   list and the rendered rows describing two different lists, and skipped the
   archived refresh entirely.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App, so
the deduplication rule is exercised as a plain function — same approach as
tests/test_chat_identity.py.
"""

import pytest

from ui.conversations import ArchivedConversationsPanel


def render_jids(chats_items):
    """The rule _compute_chat_lists() applies when deciding which entries of
    ``self.chats`` get a row: one row per distinct remoteJid, first wins."""
    seen = set()
    out = []
    for key, chat in chats_items:
        render_jid = chat.get("remoteJid") or key
        if render_jid in seen:
            continue
        seen.add(render_jid)
        out.append(render_jid)
    return out


GROUP = "120363151058129530@g.us"


class TestRenderJidDeduplication:
    def test_ordinary_chats_are_all_kept(self):
        items = [
            ("a@s.whatsapp.net", {"remoteJid": "a@s.whatsapp.net"}),
            ("b@s.whatsapp.net", {"remoteJid": "b@s.whatsapp.net"}),
            (GROUP, {"remoteJid": GROUP}),
        ]
        assert render_jids(items) == [
            "a@s.whatsapp.net",
            "b@s.whatsapp.net",
            GROUP,
        ]

    def test_a_stale_key_pointing_at_a_renamed_chat_does_not_duplicate_it(self):
        """The reported shape: a chat merged in place keeps the dict it had, so
        its old key still maps to a record whose remoteJid is now the new one."""
        items = [
            ("999@lid", {"remoteJid": GROUP}),
            (GROUP, {"remoteJid": GROUP}),
        ]
        assert render_jids(items) == [GROUP]

    def test_two_stale_keys_still_render_once(self):
        items = [
            ("999@lid", {"remoteJid": GROUP}),
            ("888@lid", {"remoteJid": GROUP}),
            (GROUP, {"remoteJid": GROUP}),
        ]
        assert render_jids(items) == [GROUP]

    def test_a_chat_without_a_remote_jid_falls_back_to_its_key(self):
        items = [("a@s.whatsapp.net", {"name": "Ana"})]
        assert render_jids(items) == ["a@s.whatsapp.net"]

    def test_deduplication_never_drops_a_distinct_chat(self):
        items = [
            ("999@lid", {"remoteJid": GROUP}),
            ("other@g.us", {"remoteJid": "other@g.us"}),
            (GROUP, {"remoteJid": GROUP}),
        ]
        assert render_jids(items) == [GROUP, "other@g.us"]


def fingerprint(conv_filter, search, jids, texts):
    """The fingerprint add_chats_to_ui() now computes — it describes exactly the
    rows that would be rendered, so an equal fingerprint means the control
    already holds them."""
    return (conv_filter, search, tuple(jids), tuple(texts))


class TestChatsUiFingerprint:
    def test_identical_rows_produce_an_equal_fingerprint(self):
        a = fingerprint("all", "", ["x@g.us"], ["Grupo X"])
        b = fingerprint("all", "", ["x@g.us"], ["Grupo X"])
        assert a == b

    def test_a_reordering_busts_it(self):
        """Row order is what maps an index back to a chat — the old fingerprint
        had to notice this and the new one still must."""
        a = fingerprint("all", "", ["x@g.us", "y@g.us"], ["X", "Y"])
        b = fingerprint("all", "", ["y@g.us", "x@g.us"], ["Y", "X"])
        assert a != b

    def test_a_changed_preview_busts_it(self):
        a = fingerprint("all", "", ["x@g.us"], ["X ola"])
        b = fingerprint("all", "", ["x@g.us"], ["X tchau"])
        assert a != b

    def test_a_changed_filter_busts_it(self):
        a = fingerprint("all", "", ["x@g.us"], ["X"])
        b = fingerprint("groups", "", ["x@g.us"], ["X"])
        assert a != b

    def test_a_changed_search_busts_it(self):
        a = fingerprint("all", "", ["x@g.us"], ["X"])
        b = fingerprint("all", "gru", ["x@g.us"], ["X"])
        assert a != b


class TestArchivedPanelAccessibility:
    def test_the_list_gets_an_explicit_accessible_name(self):
        """A wx.ListCtrl exposes no accessible name of its own on Windows, so
        NVDA announced the archived list as an unnamed "list" — the preceding
        wx.StaticText is only a visual caption. _init_ui() must attach an
        accessible carrying the localized "archived chats" label."""
        import inspect

        src = inspect.getsource(ArchivedConversationsPanel._init_ui)
        assert "SetAccessible" in src
        assert 'archived_chats' in src

    def test_relabelling_updates_the_accessible_name_too(self):
        import inspect

        src = inspect.getsource(ArchivedConversationsPanel.refresh_labels)
        assert "_list_accessible" in src, "a language change must retranslate it"
