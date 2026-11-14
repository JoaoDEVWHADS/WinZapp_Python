"""Live delivered / read / played times of a sent message (WPP.chat.getMessageACK).

No window is opened (CLAUDE.md). The rules are plain functions; the server call
runs against a fake ``api_post``; the window's text is built on a stand-in
ConversationsPanel that carries only the attributes the methods touch, the same
approach as tests/test_message_status_history.py.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import pytest

from core import message_ack
from main_window.message_ack import MessageAckMixin
from ui.conversation_panel.message_data import MessageDataMixin
import main_window.message_ack as ack_module
from tests.god_modules import patch_conversations_global
from tests.locales import load_strings, registered_locale_codes
from ui.conversations import ConversationsPanel

ROOT = Path(__file__).resolve().parent.parent / "client"

# A fixed, clearly-not-today moment so the formatted text never depends on when the suite runs.
T0 = datetime(2024, 1, 1, 14, 29, 0).timestamp()
T1 = T0 + 60
T2 = T0 + 180

GROUP = "120363000000000001@g.us"
DIRECT = "5511999990000@s.whatsapp.net"
ANA = "5511911110000@c.us"
BIA = "5511922220000@c.us"
CAIO = "5511933330000@c.us"
LID = "99887766554433@lid"


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _p(jid, delivered=None, read=None, played=None):
    record = {"id": jid}
    if delivered:
        record["deliveredAt"] = delivered
    if read:
        record["readAt"] = read
    if played:
        record["playedAt"] = played
    return record


# ── the plain rules ──────────────────────────────────────────────────────────


class TestParticipants:
    def test_the_id_in_either_shape(self):
        assert message_ack.participant_id({"id": ANA}) == ANA
        assert message_ack.participant_id({"wid": {"_serialized": BIA}}) == BIA

    @pytest.mark.parametrize("junk", [None, "x", 5, {}, {"id": None}, {"wid": "x"}, {"wid": {}}])
    def test_anything_else_is_empty(self, junk):
        assert message_ack.participant_id(junk) == ""

    def test_only_dict_participants_are_kept(self):
        assert message_ack.participants_of({"participants": [_p(ANA), None, "x", 3]}) == [_p(ANA)]

    @pytest.mark.parametrize("junk", [None, [], "x", {}, {"participants": None}, {"participants": "ana"}])
    def test_a_bad_answer_has_no_participants(self, junk):
        assert message_ack.participants_of(junk) == []


class TestFurthestStage:
    def test_played_beats_read_beats_delivered(self):
        assert message_ack.furthest_stage(_p(ANA, T0, T1, T2)) == "played"
        assert message_ack.furthest_stage(_p(ANA, T0, T1)) == "read"
        assert message_ack.furthest_stage(_p(ANA, T0)) == "delivered"

    def test_no_stage_at_all(self):
        assert message_ack.furthest_stage(_p(ANA)) is None

    def test_a_missing_earlier_stage_does_not_hide_a_later_one(self):
        # WhatsApp sometimes reports a read with no separate delivery time.
        assert message_ack.furthest_stage(_p(ANA, None, T1)) == "read"


class TestDirectTimeline:
    def test_the_stages_in_the_order_they_happen(self):
        ack = {"participants": [_p(DIRECT, T0, T1, T2)]}
        assert message_ack.direct_timeline(ack) == [("delivered", T0), ("read", T1), ("played", T2)]

    def test_stages_not_reached_are_left_out(self):
        assert message_ack.direct_timeline({"participants": [_p(DIRECT, T0)]}) == [("delivered", T0)]

    def test_only_the_first_participant_counts(self):
        ack = {"participants": [_p(DIRECT, T0), _p(ANA, T0, T1)]}
        assert message_ack.direct_timeline(ack) == [("delivered", T0)]

    def test_nothing_reported(self):
        assert message_ack.direct_timeline({"participants": []}) == []
        assert message_ack.direct_timeline(None) == []


class TestGroupByStage:
    ACK = {"participants": [_p(ANA, T0, T1, T2), _p(BIA, T0, T1), _p(CAIO, T0), _p("x@c.us")]}

    def test_each_person_appears_once_at_their_furthest_stage(self):
        groups = message_ack.group_by_stage(self.ACK, lambda jid: jid.split("@")[0])
        assert groups["played"] == ["5511911110000"]
        assert groups["read"] == ["5511922220000"]
        assert groups["delivered"] == ["5511933330000"]

    def test_a_participant_with_no_stage_is_in_no_list(self):
        groups = message_ack.group_by_stage(self.ACK, lambda jid: jid)
        assert "x@c.us" not in sum(groups.values(), [])


class TestGroupLines:
    NAMES = {ANA: "Ana", BIA: "Bia", CAIO: "Caio"}

    def _lines(self, ack, max_names=40):
        return message_ack.group_lines(
            ack, lambda jid: self.NAMES.get(jid, jid),
            lambda stage: stage.capitalize(), lambda n: f"and {n} more", max_names,
        )

    def test_one_line_per_stage_furthest_first_with_a_count_of_the_total(self):
        ack = {"participants": [_p(ANA, T0, T1), _p(BIA, T0, T1), _p(CAIO, T0)]}
        assert self._lines(ack) == ["Read (2/3): Ana, Bia", "Delivered (1/3): Caio"]

    def test_the_total_includes_people_nothing_reached_yet(self):
        ack = {"participants": [_p(ANA, T0), _p(BIA)]}
        assert self._lines(ack) == ["Delivered (1/2): Ana"]

    def test_a_long_list_is_cut_and_summarised(self):
        ack = {"participants": [_p(f"{n}@c.us", T0) for n in range(5)]}
        assert self._lines(ack, max_names=2) == ["Delivered (5/5): 0@c.us, 1@c.us and 3 more"]

    def test_nobody_reached_is_no_lines(self):
        assert self._lines({"participants": [_p(ANA)]}) == []
        assert self._lines(None) == []


class TestDisplayName:
    @staticmethod
    def _fmt(jid):
        return f"+{jid.split('@')[0]}"

    def test_a_saved_name_wins(self):
        assert message_ack.display_name(ANA, "Ana", lambda lid: "", self._fmt) == "Ana"

    def test_a_lid_is_shown_as_the_phone_it_maps_to(self):
        shown = message_ack.display_name(LID, "", lambda lid: ANA, self._fmt)
        assert shown == "+5511911110000"

    def test_an_unmapped_lid_still_shows_something(self):
        assert message_ack.display_name(LID, "", lambda lid: "", self._fmt) == "+99887766554433"

    def test_a_formatter_with_nothing_to_say_falls_back_to_the_number_part(self):
        assert message_ack.display_name(ANA, "", lambda lid: "", lambda jid: "") == "5511911110000"


# ── the server call ──────────────────────────────────────────────────────────


class _Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _Window(MessageAckMixin):
    wpp_server = "http://127.0.0.1"
    wpp_port = 21465
    token = "TOKEN"
    _serialize_msg_id = staticmethod(lambda jid, key: f"true_{jid}_{key.get('id', '')}" if key.get("id") else "")


@pytest.fixture
def post(monkeypatch):
    calls = []

    class Recorder(list):
        answer = _Response(200, {"response": {"participants": [_p(ANA, T0)]}})

    recorder = Recorder()

    def fake(url, **kwargs):
        recorder.append((url, kwargs))
        if isinstance(recorder.answer, Exception):
            raise recorder.answer
        return recorder.answer

    monkeypatch.setattr(ack_module, "api_post", fake)
    return recorder


KEY = {"id": "3EB0SECRETMESSAGEID", "fromMe": True}


class TestFetchMessageAck:
    def test_it_asks_the_message_ack_route_with_the_serialized_id(self, post):
        _Window().fetch_message_ack(GROUP, KEY)
        url, kwargs = post[0]
        assert url == "http://127.0.0.1:21465/api/TOKEN/message-ack"
        assert kwargs["json"] == {"messageId": f"true_{GROUP}_3EB0SECRETMESSAGEID"}
        assert kwargs["headers"]["Authorization"] == "Bearer TOKEN"
        assert kwargs["timeout"] == MessageAckMixin._MESSAGE_ACK_TIMEOUT

    def test_the_answer_is_returned(self, post):
        assert _Window().fetch_message_ack(GROUP, KEY) == {"participants": [_p(ANA, T0)]}

    @pytest.mark.parametrize("status", [400, 404, 500])
    def test_a_failed_call_is_none(self, post, status):
        post.answer = _Response(status, {"message": "x"})
        assert _Window().fetch_message_ack(GROUP, KEY) is None

    def test_a_dead_server_is_none_not_an_exception(self, post):
        post.answer = ConnectionError("refused")
        assert _Window().fetch_message_ack(GROUP, KEY) is None

    @pytest.mark.parametrize("body", [None, [], "x", {"response": None}, {"response": "ok"}])
    def test_an_answer_of_the_wrong_shape_is_none(self, post, body):
        post.answer = _Response(200, body)
        assert _Window().fetch_message_ack(GROUP, KEY) is None

    def test_a_message_with_no_id_asks_nobody(self, post):
        assert _Window().fetch_message_ack(GROUP, {}) is None
        assert post == []

    def test_nothing_that_identifies_a_conversation_reaches_the_log(self, post, caplog):
        caplog.set_level(logging.DEBUG)
        post.answer = ConnectionError(f"{GROUP} 3EB0SECRETMESSAGEID")
        _Window().fetch_message_ack(GROUP, KEY)
        post.answer = _Response(500, {})
        _Window().fetch_message_ack(GROUP, KEY)
        assert "3EB0SECRETMESSAGEID" not in caplog.text
        assert GROUP not in caplog.text


# ── the text of the window ───────────────────────────────────────────────────


class _I18n:
    STRINGS = {
        "status_sent": "Enviada", "status_delivered": "Entregue", "status_read": "Lida",
        "status_played": "Reproduzida", "status_failed": "Falha", "status_pending": "Pendente",
        "message_data_status_label": "Status", "and_n_more_suffix": "e mais {n}",
        "message_data_loading": "Buscando...", "datetime_fmt": "%d/%m/%Y %H:%M",
        "time_fmt": "%H:%M", "message_data": "Dados da mensagem", "close": "Fechar",
    }

    def t(self, key):
        return self.STRINGS[key]


class _MainWindow:
    def __init__(self):
        self.i18n = _I18n()
        self._lid_to_phone = {LID: ANA}
        self.said = []
        self.ack = None
        self.fetched = []

    def _is_self_jid(self, jid):
        return False

    def output(self, text, interrupt=False):
        self.said.append(text)

    def fetch_message_ack(self, chat_jid, key):
        self.fetched.append((chat_jid, key))
        return self.ack


@pytest.fixture(autouse=True)
def _pinned_format(monkeypatch):
    patch_conversations_global(monkeypatch, "get_time_format", lambda fallback: fallback)
    patch_conversations_global(monkeypatch, "get_datetime_format", lambda fallback: fallback)


def _fmt(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def _panel(chat_jid=DIRECT, names=None):
    panel = ConversationsPanel.__new__(ConversationsPanel)
    panel.main_window = _MainWindow()
    panel.conversation = {"remoteJid": chat_jid}
    names = {ANA: "Ana", BIA: "Bia", CAIO: "Caio"} if names is None else names
    panel._saved_contact_name = lambda jid: names.get(jid, "")
    panel._sender_label = lambda msg: "Eu"
    panel._get_message_content = lambda msg: "oi"
    return panel


def _msg(from_me=True, ts=T0):
    return {"key": {"id": "3EB0SECRETMESSAGEID", "fromMe": from_me, "remoteJid": DIRECT}, "messageTimestamp": ts}


class TestWhichMessagesAskWhatsApp:
    def test_our_own_message_in_a_direct_chat(self):
        assert _panel()._wants_live_receipts(_msg(), DIRECT) is True

    def test_our_own_message_in_a_group(self):
        assert _panel(GROUP)._wants_live_receipts(_msg(), GROUP) is True

    def test_a_message_we_received_never_asks(self):
        assert _panel()._wants_live_receipts(_msg(from_me=False), DIRECT) is False

    @pytest.mark.parametrize("jid", ["", "status@broadcast", "12345@broadcast"])
    def test_a_chat_with_no_receipts_never_asks(self, jid):
        assert _panel()._wants_live_receipts(_msg(), jid) is False

    def test_the_self_chat_never_asks(self):
        panel = _panel()
        panel._receipts_are_meaningless = lambda chat_jid=None: True
        assert panel._wants_live_receipts(_msg(), DIRECT) is False


class TestTheLines:
    def test_a_direct_message_lists_each_stage_with_its_full_date_and_time(self):
        ack = {"participants": [_p(DIRECT, T0, T1, T2)]}
        lines = _panel()._message_data_lines(_msg(), DIRECT, ack)
        assert lines == [
            "Eu: oi",
            f"Enviada: {_fmt(T0)}",
            f"Entregue: {_fmt(T0)}",
            f"Lida: {_fmt(T1)}",
            f"Reproduzida: {_fmt(T2)}",
        ]

    def test_a_group_message_lists_who_received_and_who_read(self):
        ack = {"participants": [_p(ANA, T0, T1), _p(BIA, T0, T1), _p(CAIO, T0)]}
        lines = _panel(GROUP)._message_data_lines(_msg(), GROUP, ack)
        assert lines[2:] == ["Lida (2/3): Ana, Bia", "Entregue (1/3): Caio"]

    def test_a_participant_with_no_saved_name_is_shown_by_phone_number(self):
        ack = {"participants": [_p(CAIO, T0, T1)]}
        lines = _panel(GROUP, names={})._message_data_lines(_msg(), GROUP, ack)
        assert lines[2] == "Lida (1/1): +55 11 93333-0000"

    def test_a_participant_known_only_by_lid_is_shown_as_the_phone_it_maps_to(self):
        ack = {"participants": [_p(LID, T0, T1)]}
        lines = _panel(GROUP, names={})._message_data_lines(_msg(), GROUP, ack)
        assert lines[2] == "Lida (1/1): +55 11 91111-0000"

    def test_a_saved_name_is_what_a_lid_participant_is_shown_as(self):
        ack = {"participants": [_p(LID, T0, T1)]}
        lines = _panel(GROUP, names={LID: "Ana"})._message_data_lines(_msg(), GROUP, ack)
        assert lines[2] == "Lida (1/1): Ana"

    def test_a_long_group_is_cut(self):
        ack = {"participants": [_p(f"55119{n:08d}@c.us", T0) for n in range(45)]}
        lines = _panel(GROUP)._message_data_lines(_msg(), GROUP, ack)
        assert lines[2].startswith("Entregue (45/45): ")
        assert lines[2].endswith("e mais 5")

    def test_without_an_answer_the_local_history_is_used(self):
        msg = _msg()
        msg["MessageUpdate"] = [{"status": "DELIVERY_ACK", "ts": T0}, {"status": "READ", "ts": T1}]
        lines = _panel()._message_data_lines(msg, DIRECT, None)
        assert lines == ["Eu: oi", f"Enviada: {_fmt(T0)}", f"Entregue: {_fmt(T0)}", f"Lida: {_fmt(T1)}"]

    def test_with_neither_the_old_single_status_line_remains(self):
        msg = _msg()
        msg["status"] = "READ"
        lines = _panel()._message_data_lines(msg, DIRECT, None)
        assert lines[:2] == ["Eu: oi", f"Enviada: {_fmt(T0)}"]
        assert lines[2].startswith("Status: ")

    def test_an_empty_answer_falls_back_too(self):
        msg = _msg()
        msg["MessageUpdate"] = [{"status": "READ", "ts": T1}]
        lines = _panel()._message_data_lines(msg, DIRECT, {"participants": []})
        assert f"Lida: {_fmt(T1)}" in lines

    def test_a_message_we_received_is_never_given_live_receipts(self):
        ack = {"participants": [_p(DIRECT, T0, T1)]}
        lines = _panel()._message_data_lines(_msg(from_me=False), DIRECT, ack)
        assert lines == ["Eu: oi", f"Enviada: {_fmt(T0)}"]


class _Immediately:
    """A threading.Thread that runs its target on start()."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        self._target()


class TestTheWaitingFlow:
    @pytest.fixture
    def flow(self, monkeypatch):
        import ui.conversation_panel.message_data as module

        shown = []
        monkeypatch.setattr(module.threading, "Thread", _Immediately)
        monkeypatch.setattr(module.wx, "CallAfter", lambda fn, *a: fn(*a))
        panel = _panel()
        panel._show_message_data = lambda msg, chat_jid, ack: shown.append((msg, chat_jid, ack))
        return panel, shown

    def test_our_message_says_it_is_waiting_then_shows_what_whatsapp_answered(self, flow):
        panel, shown = flow
        panel.main_window.ack = {"participants": [_p(DIRECT, T0)]}
        panel._on_menu_message_data(_msg())
        assert panel.main_window.said == ["Buscando..."]
        assert panel.main_window.fetched == [(DIRECT, {"id": "3EB0SECRETMESSAGEID", "fromMe": True, "remoteJid": DIRECT})]
        assert shown[0][2] == {"participants": [_p(DIRECT, T0)]}

    def test_a_failed_call_still_opens_the_window(self, flow):
        panel, shown = flow
        panel.main_window.ack = None
        panel._on_menu_message_data(_msg())
        assert len(shown) == 1 and shown[0][2] is None

    def test_a_message_we_received_opens_at_once_and_never_asks(self, flow):
        panel, shown = flow
        panel._on_menu_message_data(_msg(from_me=False))
        assert panel.main_window.fetched == []
        assert panel.main_window.said == []
        assert len(shown) == 1 and shown[0][2] is None

    def test_a_second_press_while_the_first_is_asking_does_nothing(self, flow, monkeypatch):
        import ui.conversation_panel.message_data as module

        panel, shown = flow
        started = []

        class _Held:
            def __init__(self, target=None, daemon=None, **kw):
                started.append(target)

            def start(self):
                pass

        monkeypatch.setattr(module.threading, "Thread", _Held)
        panel._on_menu_message_data(_msg())
        panel._on_menu_message_data(_msg())
        assert len(started) == 1
        assert panel.main_window.said == ["Buscando..."]


# ── the formatter, the wiring and the strings ────────────────────────────────


class TestFullDatetime:
    def test_it_is_always_the_full_date_and_time(self):
        panel = _panel()
        assert panel._format_full_datetime(T0) == _fmt(T0)

    def test_milliseconds_are_understood(self):
        assert _panel()._format_full_datetime(int(T0 * 1000)) == _fmt(T0)

    @pytest.mark.parametrize("ts", [None, 0, "", "abc"])
    def test_nothing_usable_is_empty(self, ts):
        assert _panel()._format_full_datetime(ts) == ""


class TestWiring:
    MAIN = _read("main.py")
    PANEL = _read("ui", "conversations.py")
    MENU = _read("ui", "conversation_panel", "message_menu.py")
    ROUTES = _read("api_patches", "src", "routes", "index.ts")
    CONTROLLER = _read("api_patches", "src", "controller", "deviceController.ts")

    def test_both_mixins_are_part_of_their_class(self):
        assert re.search(r"class MainWindow\([^)]*\bMessageAckMixin\b", self.MAIN)
        assert issubclass(ConversationsPanel, MessageDataMixin)
        assert callable(MessageAckMixin.fetch_message_ack)

    def test_the_handler_lives_in_one_place_only(self):
        assert "_on_menu_message_data" in vars(MessageDataMixin)
        assert "_on_menu_message_data" not in vars(ConversationsPanel)
        assert callable(ConversationsPanel._on_menu_message_data)

    def test_the_menu_item_still_calls_it(self):
        assert "self._on_menu_message_data(m)" in self.MENU

    def test_the_route_and_the_controller_exist(self):
        assert "'/api/:session/message-ack'" in self.ROUTES
        assert "DeviceController.getMessageAck" in self.ROUTES
        assert "export async function getMessageAck" in self.CONTROLLER
        assert "WPP.chat.getMessageACK" in self.CONTROLLER

    def test_the_call_never_runs_on_the_ui_thread(self):
        source = _read("ui", "conversation_panel", "message_data.py")
        assert "threading.Thread(target=work, daemon=True).start()" in source
        assert source.index("mw.fetch_message_ack(") > source.index("def work()")


class TestStringsInEveryLocale:
    NEEDED = ("and_n_more_suffix", "message_data_loading", "message_data", "status_sent",
              "status_delivered", "status_read", "status_played")

    @pytest.mark.parametrize("locale", registered_locale_codes())
    def test_every_string_exists_and_is_not_empty(self, locale):
        strings = load_strings(locale)
        assert [k for k in self.NEEDED if not str(strings.get(k, "")).strip()] == []

    @pytest.mark.parametrize("locale", registered_locale_codes())
    def test_the_count_placeholder_survives_translation(self, locale):
        text = load_strings(locale)["and_n_more_suffix"]
        assert "{n}" in text
        text.format(n=3)  # no stray braces
