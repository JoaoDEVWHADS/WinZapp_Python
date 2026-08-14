"""Searching inside a conversation must match content, not row decorations.

Reported live: searching "reproduz" returned every played voice message. The
search compared the query against _render_message_line() — the fully rendered
row — and that string carries the delivery status ("Reproduzida"), the
timestamp, "Editada"/"Encaminhada" and the reaction summary alongside the
actual message. Every one of those was matchable; the status was simply the
one a user noticed first.

_message_search_text() now supplies what searching looks at: sender, body,
and (for replies) the quoted sender and quote text. A reply can quote a
message that scrolled out of the loaded history, so the quote is sometimes the
only copy of those words on screen — it stays searchable on purpose.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test run against a stub — same approach as
tests/test_message_bookmarks.py. The stub deliberately implements
_render_message_line() *with* the decorations: if the search is ever pointed
back at the rendered row, these tests fail instead of silently regressing.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeSearchField:
    def __init__(self, value=""):
        self._value = value

    def GetValue(self):
        return self._value


class _FakeMainWindow:
    """Accent folding off — the default. Covered on its own in
    tests/test_search_normalization.py; here it must not interfere."""

    @staticmethod
    def _search_folds_accents():
        return False


class _Stub:
    _is_separator = ConversationsPanel._is_separator
    _message_search_text = ConversationsPanel._message_search_text
    _on_search_text_changed = ConversationsPanel._on_search_text_changed

    def __init__(self, messages, query=""):
        self._sorted_messages = messages
        self._search_field = _FakeSearchField(query)
        self._search_results = []
        self._search_result_idx = -1
        self.main_window = _FakeMainWindow()

    # ── stand-ins for the real content helpers ──────────────────────────
    def _is_system_event(self, msg):
        return bool(msg.get("_system"))

    def _sender_label(self, msg):
        return msg.get("_sender", "")

    def _get_message_content(self, msg):
        return msg.get("_body", "")

    def _get_context_info(self, msg):
        return msg.get("_ctx")

    def _get_quoted_sender(self, ctx, msg):
        return ctx.get("_quoted_sender", "")

    def _get_quoted_preview(self, quoted):
        return quoted.get("_preview", "")

    def _render_message_line(self, msg):
        """What the row actually looks like — content AND decorations.

        Only here so the tests can prove the search does not use it.
        """
        line = f"{msg.get('_sender', '')}: {msg.get('_body', '')}"
        for decoration in ("_status", "_time", "_flags"):
            if msg.get(decoration):
                line += f", {msg[decoration]}"
        return line

    def search(self, query):
        self._search_field = _FakeSearchField(query)
        self._on_search_text_changed(None)
        return self._search_results


def _audio(msg_id, sender="Fulano", status="Reproduzida"):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "messageType": "audioMessage",
        "_sender": sender,
        "_body": "Áudio, duração 12 segundos",
        "_status": status,
        "_time": "14:32",
    }


def _text(msg_id, body, sender="Fulano", **extra):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "messageType": "conversation",
        "_sender": sender,
        "_body": body,
        **extra,
    }


class TestTheReportedBug:
    def test_played_audio_is_not_matched_by_its_status(self):
        panel = _Stub([_audio("A1"), _audio("A2"), _audio("A3")])

        assert panel.search("reproduz") == []

    def test_the_status_really_is_in_the_rendered_row(self):
        """Guards the guard: if the row stopped carrying the status, the test
        above would pass for the wrong reason."""
        panel = _Stub([_audio("A1")])

        assert "Reproduzida" in panel._render_message_line(panel._sorted_messages[0])

    def test_audio_is_still_findable_by_what_it_is(self):
        panel = _Stub([_audio("A1"), _text("T1", "bom dia")])

        assert panel.search("áudio") == ["A1"]


class TestOtherDecorationsAreAlsoExcluded:
    @pytest.mark.parametrize("decoration,query", [
        ("_status", "entregue"),
        ("_flags", "encaminhada"),
        ("_flags", "editada"),
        ("_time", "14:32"),
    ])
    def test_decoration_does_not_match(self, decoration, query):
        msg = _text("T1", "bom dia")
        msg[decoration] = {"_status": "Entregue", "_flags": "Encaminhada, Editada",
                           "_time": "14:32"}[decoration]
        panel = _Stub([msg])

        assert panel.search(query) == []


class TestContentStillMatches:
    def test_body(self):
        panel = _Stub([_text("T1", "reunião amanhã"), _text("T2", "bom dia")])

        assert panel.search("reunião") == ["T1"]

    def test_sender_name(self):
        panel = _Stub([_text("T1", "oi", sender="Beltrano"),
                       _text("T2", "oi", sender="Fulano")])

        assert panel.search("beltrano") == ["T1"]

    def test_search_is_case_insensitive(self):
        panel = _Stub([_text("T1", "Reunião Amanhã")])

        assert panel.search("REUNIÃO") == ["T1"]

    def test_quoted_text_and_quoted_sender(self):
        """A reply can quote a message no longer in the loaded list — the
        quote is then the only copy of those words on screen."""
        reply = _text("R1", "concordo", _ctx={
            "_quoted_sender": "Ciclano",
            "quotedMessage": {"_preview": "vamos fechar o orçamento"},
        })
        panel = _Stub([reply])

        assert panel.search("orçamento") == ["R1"]
        assert panel.search("ciclano") == ["R1"]

    def test_system_events_match_on_their_own_text(self):
        """System events render without a sender prefix (the sentence already
        names who acted), and search follows the same shape."""
        ev = _text("S1", "Fulano saiu do grupo", sender="Fulano", _system=True)
        panel = _Stub([ev])

        assert panel.search("saiu do grupo") == ["S1"]


class TestResultBookkeeping:
    def test_separators_and_id_less_rows_are_skipped(self):
        panel = _Stub([
            {"_type": "unread_separator", "count": 2},
            {"key": {}, "messageType": "conversation", "_body": "bom dia"},
            _text("T1", "bom dia"),
        ])

        assert panel.search("bom dia") == ["T1"]

    def test_an_empty_query_clears_the_results(self):
        panel = _Stub([_text("T1", "bom dia")])
        panel.search("bom")

        assert panel.search("   ") == []
        assert panel._search_result_idx == -1
