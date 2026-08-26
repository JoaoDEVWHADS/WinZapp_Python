"""Regression tests: history sync had no defense against fake self-chat
sync artifacts.

WPPConnect/Baileys occasionally reports one of our own sends tagged with an
identity that isn't our real phone JID — either a "participant" whose digits
match "remoteJid" (impossible for a real group, whose JID is independently
allocated), or a "@g.us" remoteJid that is simply our own phone number. Left
alone, either shape spawns an unnamed phantom "group"/duplicate of "Eu" that
can't be cleanly identified or deleted. on_new_message() (the live path) has
always redirected this; on_historical_message() (history sync) never did, so
a fake self-chat arriving in a history-sync batch sat in the chat list
unfiltered until the next full deduplicate_chats() pass happened to run.

The fix extracts the shared detection/redirect logic into
MainWindow._redirect_self_chat_artifact() and calls it from both places.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so both the extracted helper and on_historical_message() are
exercised bound to plain stubs — same approach as
tests/test_phantom_group_participant_chats.py and
tests/test_lid_merge_keeps_messages.py.
"""

from main import MainWindow

MY_PHONE = "5511999999999@s.whatsapp.net"
MY_LID = "11111111111111@lid"


class _GuardStub:
    """Just enough for _redirect_self_chat_artifact() itself."""

    _redirect_self_chat_artifact = MainWindow._redirect_self_chat_artifact
    _phone_digits_equivalent = staticmethod(MainWindow._phone_digits_equivalent)
    _is_self_jid = MainWindow._is_self_jid

    def __init__(self, my_jid="", my_lid=""):
        self.my_jid = my_jid
        self.my_lid = my_lid
        self._lid_to_phone = {}

    def _normalize_jid(self, jid):
        return MainWindow._normalize_jid(jid)


class TestRedirectSelfChatArtifact:
    def test_case_a_group_shaped_participant_digits_match_remote(self):
        """A "group" whose own JID equals the participant's JID never
        happens for a real group — remoteJid is independently allocated."""
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"participant": "5511999999999@lid", "fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "5511999999999@g.us", key, False
        )

        assert remote_jid == MY_PHONE
        assert from_me is True

    def test_case_a_bare_jid_requires_from_me_true(self):
        """A bare, not-yet-resolved remoteJid with matching participant
        digits is only unambiguous when fromMe is already True — for a real
        1:1 chat, an incoming message's participant legitimately mirrors
        remoteJid, and that combination must NOT be redirected."""
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"participant": MY_PHONE, "fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            MY_PHONE, key, False
        )

        assert remote_jid == MY_PHONE  # unchanged — this IS the real 1:1 case
        assert from_me is False

    def test_case_a_bare_jid_with_from_me_true_is_redirected(self):
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"participant": MY_PHONE, "fromMe": True}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            MY_PHONE, key, True
        )

        assert remote_jid == MY_PHONE
        assert from_me is True

    def test_case_b_g_us_remote_is_actually_our_own_number(self):
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"fromMe": False}  # no participant artifact at all

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "5511999999999@g.us", key, False
        )

        assert remote_jid == MY_PHONE
        assert from_me is True

    def test_case_b_tolerates_the_brazilian_9th_digit_variant(self):
        stub = _GuardStub(my_jid="5511999999999@s.whatsapp.net")
        key = {"fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "551199999999@g.us", key, False  # 8-digit variant, no leading 9
        )

        assert remote_jid == "5511999999999@s.whatsapp.net"
        assert from_me is True

    def test_plain_self_chat_digit_variant_is_canonicalised(self):
        """Same self-chat, just the other digit-count variant of our own
        number — redirected to the canonical form, but this shape never
        implies fromMe on its own."""
        stub = _GuardStub(my_jid="5511999999999@s.whatsapp.net")
        key = {"fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "551199999999@s.whatsapp.net", key, False
        )

        assert remote_jid == "5511999999999@s.whatsapp.net"
        assert from_me is False

    def test_a_real_group_is_never_redirected(self):
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"participant": "5521888888888@s.whatsapp.net", "fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "120363409931936700@g.us", key, False
        )

        assert remote_jid == "120363409931936700@g.us"
        assert from_me is False

    def test_a_real_incoming_1on1_chat_is_never_redirected(self):
        stub = _GuardStub(my_jid=MY_PHONE)
        key = {"participant": "5521888888888@s.whatsapp.net", "fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "5521888888888@s.whatsapp.net", key, False
        )

        assert remote_jid == "5521888888888@s.whatsapp.net"
        assert from_me is False

    def test_falls_back_to_my_lid_when_my_jid_is_unknown(self):
        stub = _GuardStub(my_jid="", my_lid=MY_LID)
        key = {"participant": "5511999999999@lid", "fromMe": False}

        remote_jid, from_me = stub._redirect_self_chat_artifact(
            "5511999999999@g.us", key, False
        )

        assert remote_jid == MY_LID
        assert from_me is True


# ── on_historical_message() actually applying the guard ─────────────────────


class _Executor:
    def submit(self, fn):
        return None


class _HistoricalStub:
    on_historical_message = MainWindow.on_historical_message
    _redirect_self_chat_artifact = MainWindow._redirect_self_chat_artifact
    _phone_digits_equivalent = staticmethod(MainWindow._phone_digits_equivalent)
    _is_self_jid = MainWindow._is_self_jid

    def __init__(self, my_jid=""):
        self.my_jid = my_jid
        self.my_lid = ""
        self._lid_to_phone = {}
        self.chats = {}
        self._msg_bg_executor = _Executor()

    def _normalize_jid(self, jid):
        return MainWindow._normalize_jid(jid)

    def _live_events_ready(self):
        return True

    def _extract_lid_mapping(self, msg):
        pass

    def _learn_sender_name(self, msg):
        return False

    def _apply_group_subject_change(self, remote_jid, chat, msg):
        pass

    def _fill_group_name(self, remote_jid):
        return ""

    def _is_cleared_message(self, remote_jid, msg):
        return False

    def _schedule_save(self, dirty_jid=None):
        pass

    def _schedule_set_chats(self):
        pass


def _historical_msg(remote_jid, participant="", from_me=False, msg_id="H1"):
    key = {"remoteJid": remote_jid, "id": msg_id, "fromMe": from_me}
    if participant:
        key["participant"] = participant
    return {
        "key": key,
        "messageType": "conversation",
        "message": {"conversation": "oi"},
        "messageTimestamp": 1,
        "pushName": "",
    }


class TestOnHistoricalMessageAppliesTheGuard:
    def test_no_phantom_chat_is_created_under_the_fake_jid(self):
        stub = _HistoricalStub(my_jid=MY_PHONE)
        msg = _historical_msg("5511999999999@g.us", participant="5511999999999@lid")

        stub.on_historical_message(msg)

        assert "5511999999999@g.us" not in stub.chats

    def test_the_message_is_filed_under_the_real_self_chat(self):
        stub = _HistoricalStub(my_jid=MY_PHONE)
        msg = _historical_msg("5511999999999@g.us", participant="5511999999999@lid")

        stub.on_historical_message(msg)

        assert MY_PHONE in stub.chats
        records = stub.chats[MY_PHONE]["messages"]["messages"]["records"]
        assert [r["key"]["id"] for r in records] == ["H1"]

    def test_a_real_group_message_is_unaffected(self):
        stub = _HistoricalStub(my_jid=MY_PHONE)
        msg = _historical_msg(
            "120363409931936700@g.us", participant="5521888888888@s.whatsapp.net"
        )

        stub.on_historical_message(msg)

        assert "120363409931936700@g.us" in stub.chats
        assert MY_PHONE not in stub.chats

    def test_a_real_incoming_1on1_message_is_unaffected(self):
        stub = _HistoricalStub(my_jid=MY_PHONE)
        msg = _historical_msg(
            "5521888888888@s.whatsapp.net", participant="5521888888888@s.whatsapp.net"
        )

        stub.on_historical_message(msg)

        assert "5521888888888@s.whatsapp.net" in stub.chats
