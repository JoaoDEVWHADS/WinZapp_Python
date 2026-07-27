"""Tests for outgoing-message delivery status.

These cover the "WinZapp says sent, the message never arrived" family of bugs:

* ``on_wpp_ack`` translated WhatsApp's ACK with ``mapping.get(ack, 2)``, so every
  ack it did not recognise — including ``ACK.FAILED`` (-1), i.e. WhatsApp Web
  telling us the message will never leave the outbox — was reported as "sent".
* ``_build_message_values`` hardcoded the indexed ``status`` column to 0 on every
  insert, so the delivery state existed only in memory.
* ``_map_status`` had no branch for a failed status at all, and scanned the whole
  status history for any positive value, so a message acked as sent and *then*
  reported failed still read as "sent".
"""

import pytest

from core.database import _delivery_status
from core.websocket_client import STATUS_FAILED, STATUS_PENDING, ack_to_status


class TestAckToStatus:
    @pytest.mark.parametrize("ack, expected", [
        (1, 2),   # SENT
        (2, 3),   # RECEIVED  -> delivered
        (3, 4),   # READ
        (4, 5),   # PLAYED
        (5, 2),   # PEER (another of our own devices) -> sent
    ])
    def test_positive_acks_map_to_the_app_scale(self, ack, expected):
        assert ack_to_status(ack) == expected

    def test_clock_is_pending_not_sent(self):
        # ACK.CLOCK means "created locally, server has not acknowledged it".
        assert ack_to_status(0) == STATUS_PENDING
        assert ack_to_status(0) != 2

    @pytest.mark.parametrize("ack", [-1, -2, -3, -4, -5, -6, -7])
    def test_every_negative_ack_is_a_failure(self, ack):
        # FAILED / EXPIRED / CONTENT_GONE / CONTENT_TOO_BIG / ...
        assert ack_to_status(ack) == STATUS_FAILED

    def test_failed_ack_is_not_reported_as_sent(self):
        # The regression itself: -1 used to fall through the mapping's default.
        assert ack_to_status(-1) != 2

    @pytest.mark.parametrize("ack", [None, "2", 2.5, object()])
    def test_unrecognised_ack_yields_none(self, ack):
        # None tells the caller to leave the stored status alone, which is the
        # only honest answer — never "sent".
        assert ack_to_status(ack) is None

    def test_booleans_are_not_treated_as_ints(self):
        # bool is a subclass of int; True must not silently mean ACK.SENT.
        assert ack_to_status(True) is None
        assert ack_to_status(False) is None


class TestDeliveryStatusColumn:
    def _msg(self, **extra):
        base = {"key": {"id": "3EB0AA", "fromMe": True}}
        base.update(extra)
        return base

    def test_uses_latest_message_update(self):
        msg = self._msg(MessageUpdate=[{"status": "2"}, {"status": "3"}])
        assert _delivery_status(msg) == 3

    def test_latest_failure_wins_over_earlier_success(self):
        msg = self._msg(MessageUpdate=[{"status": "2"}, {"status": "-1"}])
        assert _delivery_status(msg) == STATUS_FAILED

    def test_falls_back_to_root_status(self):
        assert _delivery_status(self._msg(status=4)) == 4

    def test_ignores_ack_because_it_is_on_whatsapps_scale(self):
        # msg["ack"]=1 is ACK.SENT, which is 2 on the app's scale. Reading it
        # unmapped would record every sent message as delivered.
        assert _delivery_status(self._msg(ack=1)) == 0

    def test_no_status_information_is_zero(self):
        assert _delivery_status(self._msg()) == 0

    def test_malformed_entries_are_skipped(self):
        msg = self._msg(MessageUpdate=[{"status": "3"}, {"status": "nonsense"}, "junk"])
        assert _delivery_status(msg) == 3

    def test_survives_a_message_with_no_updates_key(self):
        assert _delivery_status({"key": {"id": "x"}}) == 0
