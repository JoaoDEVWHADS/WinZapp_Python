"""Pairing refused by WhatsApp: the QR shown, the repair and its limits."""
import base64
import logging
import os
import struct
import threading
from types import SimpleNamespace as N

import segno

import pairing_repair
import server
import session_lifecycle


def test_failure_kind_reads_the_two_whatsmeow_lines():
    assert pairing_repair.failure_kind(
        "Failed to pair device: invalid device identity HMAC") == pairing_repair.QR
    assert pairing_repair.failure_kind(
        "Failed to handle code pair notification: x") == pairing_repair.CODE
    assert pairing_repair.failure_kind("Connected to WhatsApp") is None


def test_budget_gives_three_restarts_and_is_given_back():
    b = pairing_repair.Budget()
    assert [b.take() for _ in range(4)] == [True, True, True, False]
    b.reset()
    assert b.take()


def test_handler_reports_only_error_lines():
    seen = []
    handler = pairing_repair.FailureHandler(seen.append)
    log = logging.getLogger("test.pairing.repair")
    log.propagate = False
    log.addHandler(handler)
    log.error("Failed to pair device: invalid device identity HMAC")
    log.warning("Failed to pair device: warning level is not an error")
    log.error("something else")
    log.removeHandler(handler)
    assert seen == [pairing_repair.QR]


def test_wipe_deletes_the_database_last(tmp_path, monkeypatch):
    for name in ("session.db", "session.db-wal", "session.db-shm", "session.db-journal"):
        (tmp_path / name).write_bytes(b"x")
    order = []
    real = os.remove
    monkeypatch.setattr(pairing_repair.os, "remove", lambda path: (order.append(os.path.basename(path)), real(path)))
    assert pairing_repair.wipe_session_keys(str(tmp_path))
    assert order[-1] == "session.db" and order.index("session.db-wal") < order.index("session.db")


def test_a_failed_wipe_never_leaves_a_wal_without_its_database(tmp_path, monkeypatch):
    for name in ("session.db", "session.db-wal"):
        (tmp_path / name).write_bytes(b"x")
    real = os.remove

    def locked(path):
        if os.path.basename(path) == "session.db":
            raise PermissionError(path)
        real(path)
    monkeypatch.setattr(pairing_repair.os, "remove", locked)
    assert not pairing_repair.wipe_session_keys(str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == ["session.db"]


def test_wipe_removes_the_keys_and_keeps_the_messages(tmp_path):
    for name in ("session.db", "session.db-wal", "bridge.db"):
        (tmp_path / name).write_bytes(b"x")
    assert pairing_repair.wipe_session_keys(str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == ["bridge.db"]
    assert pairing_repair.wipe_session_keys(str(tmp_path))     # nothing left is fine


def test_qr_image_has_the_wide_margin_and_whole_pixel_modules():
    text = "2@" + "abc/+=" * 30
    url = server.qr_data_url(text)
    assert url.startswith("data:image/png;base64,")
    png = base64.b64decode(url.split(",", 1)[1])
    width, height = struct.unpack(">II", png[16:24])
    modules = segno.make_qr(text, error="l").symbol_size(border=server.QR_BORDER, scale=1)[0]
    assert width == height == modules * server.QR_SCALE
    assert png[25] == 0 and png[24] == 1        # 1 bit per pixel, greyscale: pure black and white


def stub(tmp_path, *, status="QRCODE", used=0, alive=False, thread=None):
    """A Session with a real lifecycle and the real stop(); begin() and emit() only record."""
    calls = []
    s = N(folder=str(tmp_path), name="s", client=None, thread=thread,
          lifecycle=session_lifecycle.Lifecycle(), pairing_repairs=pairing_repair.Budget(),
          _lifecycle_lock=threading.RLock(), _thread_alive=lambda: alive,
          emit=lambda event, data: calls.append(("emit", event, data["name"])),
          begin=lambda *a, **k: calls.append(("begin", k)), _repair_pairing=lambda *a: None,
          _has_identity=lambda: False)
    s.lifecycle.status = s.status = status
    s.pairing_repairs.used = used
    s.stop = lambda status=None: server.Session.stop(s, status)
    s._give_up = lambda message: server.Session._give_up(s, message)
    return s, calls


def repair(s, kind, phone=None):
    server.Session._repair_pairing(s, s.lifecycle.generation, kind, phone)


def test_qr_refusal_wipes_the_keys_and_starts_again(tmp_path):
    (tmp_path / "session.db").write_bytes(b"keys")
    (tmp_path / "bridge.db").write_bytes(b"messages")
    s, calls = stub(tmp_path)
    repair(s, pairing_repair.QR)
    assert calls == [("begin", {"repairing": True})]
    assert sorted(os.listdir(tmp_path)) == ["bridge.db"]
    assert s.lifecycle.status == session_lifecycle.CLOSED


def test_code_refusal_wipes_but_does_not_mint_another_code(tmp_path):
    (tmp_path / "session.db").write_bytes(b"keys")
    s, calls = stub(tmp_path)
    repair(s, pairing_repair.CODE)
    assert calls == [("emit", "phoneCodeError", "LinkCodeRefreshFailed")]
    assert not (tmp_path / "session.db").exists()


def test_a_qr_refusal_of_a_session_started_with_a_phone_never_becomes_a_qr(tmp_path):
    s, calls = stub(tmp_path)
    repair(s, pairing_repair.QR, phone="5511999990000")
    assert [c[0] for c in calls] == ["emit"]


def test_after_three_repairs_it_gives_up_aloud_and_stays_offline(tmp_path):
    s, calls = stub(tmp_path, used=3)
    repair(s, pairing_repair.QR)
    assert calls == [("emit", "phoneCodeError", "LinkCodeRefreshFailed")]
    assert s.lifecycle.status == session_lifecycle.TERMINAL


def test_a_thread_that_will_not_finish_is_announced_too(tmp_path):
    s, calls = stub(tmp_path, alive=True)
    repair(s, pairing_repair.QR)
    assert calls == [("emit", "phoneCodeError", "LinkCodeRefreshFailed")]
    assert s.lifecycle.status == session_lifecycle.TERMINAL


def test_a_session_that_got_paired_while_the_repair_waited_keeps_its_keys(tmp_path):
    (tmp_path / "session.db").write_bytes(b"new keys")
    s, calls = stub(tmp_path)
    s.lifecycle.status = s.status = "CONNECTED"        # the scan went through meanwhile
    repair(s, pairing_repair.QR)
    repair(s, pairing_repair.CODE)
    assert calls == [] and (tmp_path / "session.db").read_bytes() == b"new keys"
    assert s.lifecycle.status == "CONNECTED"


def test_a_session_that_already_holds_an_identity_keeps_its_keys(tmp_path):
    """Between whatsmeow saving the paired device and the connected event the status
    is still QRCODE; a late refusal line must not wipe what was just saved."""
    (tmp_path / "session.db").write_bytes(b"new keys")
    s, calls = stub(tmp_path)
    s._has_identity = lambda: True
    repair(s, pairing_repair.CODE)
    repair(s, pairing_repair.QR)
    assert calls == [] and (tmp_path / "session.db").read_bytes() == b"new keys"
    assert s.lifecycle.status == session_lifecycle.QRCODE


def test_the_identity_check_reads_the_clients_own_id():
    ready = N(client=N(get_me=lambda: N(JID=N(User="5511")))) 
    empty = N(client=N(get_me=lambda: N(JID=N(User=""))))
    broken = N(client=None)
    assert server.Session._has_identity(ready) is True
    assert server.Session._has_identity(empty) is False
    assert server.Session._has_identity(broken) is False


def test_an_old_generation_is_not_repaired(tmp_path):
    s, calls = stub(tmp_path)
    server.Session._repair_pairing(s, s.lifecycle.generation - 1, pairing_repair.QR, None)
    assert calls == []


def test_a_user_start_gives_the_repairs_back_but_a_repair_start_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(server.threading, "Thread", lambda **kw: N(start=lambda: None))
    s = N(name="s", status="CLOSED", thread=None, pairing_repairs=pairing_repair.Budget(),
          lifecycle=session_lifecycle.Lifecycle(), _lifecycle_lock=threading.RLock(),
          _thread_alive=lambda: False, _run=None)
    s.pairing_repairs.used = 3
    assert server.Session.begin(s, repairing=True)
    assert s.pairing_repairs.used == 3
    assert server.Session.begin(s)
    assert s.pairing_repairs.used == 0


def test_a_refusal_starts_the_repair_thread_only_for_a_waiting_current_session(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(server.threading, "Thread", lambda **kw: N(start=lambda: started.append(1)))
    old, _ = stub(tmp_path)
    paired, _ = stub(tmp_path, status="CONNECTED")
    server.Session._on_pairing_failure(old, old.lifecycle.generation - 1, pairing_repair.QR, None)
    server.Session._on_pairing_failure(paired, paired.lifecycle.generation, pairing_repair.QR, None)
    assert started == []
    waiting, _ = stub(tmp_path)
    server.Session._on_pairing_failure(waiting, waiting.lifecycle.generation, pairing_repair.QR, None)
    assert started == [1]


def watch_stub(status="QRCODE"):
    seen = []
    s = N(status=status, lifecycle=session_lifecycle.Lifecycle(),
          _on_pairing_failure=lambda g, kind, phone: seen.append((g, kind, phone)))
    return s, seen


def test_watch_attaches_one_handler_and_leaves_no_trace():
    watch = pairing_repair.Watch()
    logger = logging.getLogger(watch.LOGGER)
    before = list(logger.handlers)
    a, _ = watch_stub()
    b, _ = watch_stub()
    watch.add(a, 0, None)
    watch.add(b, 0, None)
    assert len(logger.handlers) == len(before) + 1
    watch.remove(a, 0)
    watch.remove(b, 0)
    assert logger.handlers == before


def test_watch_removal_belongs_to_the_generation_that_added(tmp_path):
    watch = pairing_repair.Watch()
    a, _ = watch_stub()
    watch.add(a, 2, None)
    watch.remove(a, 1)              # an old thread finishing late
    assert id(a) in watch._entries
    watch.remove(a, 2)
    assert not watch._entries


def test_watch_sends_a_refusal_to_the_only_session_waiting_for_a_scan():
    watch = pairing_repair.Watch()
    waiting, seen = watch_stub()
    paired, other = watch_stub(status="CONNECTED")
    watch.add(waiting, 0, "5511")
    watch.add(paired, 0, None)
    try:
        watch._dispatch(pairing_repair.QR)
    finally:
        watch.remove(waiting, 0)
        watch.remove(paired, 0)
    assert seen == [(0, pairing_repair.QR, "5511")] and other == []


def test_watch_repairs_nobody_when_two_sessions_wait_for_a_scan():
    watch = pairing_repair.Watch()
    a, seen_a = watch_stub()
    b, seen_b = watch_stub()
    watch.add(a, 0, None)
    watch.add(b, 0, None)
    try:
        watch._dispatch(pairing_repair.QR)
    finally:
        watch.remove(a, 0)
        watch.remove(b, 0)
    assert seen_a == seen_b == []
