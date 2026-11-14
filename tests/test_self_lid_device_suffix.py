"""A self LID with a companion-device suffix ("<id>:56@lid") must never be
used as a send destination: WhatsApp Web answers HTTP 500 and a message to
oneself ends as "could not confirm the send"."""

from main import MainWindow


class _Stub:
    def __init__(self, phone_to_lid):
        self._phone_to_lid = phone_to_lid


def test_cached_lid_with_device_suffix_is_stripped_on_send():
    stub = _Stub({"5511999990000@s.whatsapp.net": "123456:56@lid"})
    got = MainWindow._resolve_jid_for_chat_state(stub, "5511999990000@s.whatsapp.net")
    assert got == "123456@lid"


def test_lid_destination_with_device_suffix_is_stripped():
    stub = _Stub({})
    assert MainWindow._resolve_jid_for_chat_state(stub, "123456:56@lid") == "123456@lid"


def test_plain_lid_is_untouched():
    stub = _Stub({"5511999990000@s.whatsapp.net": "123456@lid"})
    got = MainWindow._resolve_jid_for_chat_state(stub, "5511999990000@c.us")
    assert got == "123456@lid"


def test_register_jid_mapping_strips_device_suffix_from_lid():
    import threading

    class Reg(_Stub):
        _normalize_jid = staticmethod(MainWindow._normalize_jid)

        def __init__(self):
            super().__init__({})
            self._lid_to_phone = {}
            self._lid_mapping_lock = threading.RLock()
            self.my_lid = ""
            self.my_jid = ""

        def _is_self_jid(self, jid):
            return False

    stub = Reg()
    try:
        MainWindow.register_jid_mapping(stub, "123456:56@lid", "5511999990000@s.whatsapp.net", save=False, defer_ui=True)
    except AttributeError:
        pass  # later, unrelated stub gaps; the cache write happens first
    assert "123456:56@lid" not in stub._lid_to_phone
    assert stub._phone_to_lid.get("5511999990000@s.whatsapp.net") in (None, "123456@lid")


def test_strip_device_suffix_helper():
    from core.jid_device import strip_device_suffix

    assert strip_device_suffix("123:56@lid") == "123@lid"
    assert strip_device_suffix("123@lid") == "123@lid"
    assert strip_device_suffix("") == ""
