"""The pairing code error in the format the client reads."""
import pytest

import pairing


def test_common_error_carries_name_and_message_and_is_not_quota():
    info = pairing.code_error(RuntimeError("connection reset"))
    assert info == {"name": "LinkCodeError", "message": "RuntimeError: connection reset",
                    "rateLimited": False}


@pytest.mark.parametrize("text", [
    "iq error: rate-overlimit", "IQErrorRateOverlimit", "server said 429", "RATE-OVERLIMIT"])
def test_refusal_by_quota_is_recognized(text):
    assert pairing.code_error(Exception(text))["rateLimited"] is True


def test_number_that_only_contains_429_is_not_quota():
    assert pairing.code_error(Exception("id 14290001"))["rateLimited"] is False


def test_phone_never_goes_in_the_message():
    info = pairing.code_error(Exception("invalid number 5511999998888 for user"))
    assert "5511999998888" not in info["message"] and "<n>" in info["message"]


def test_empty_message_keeps_only_the_name_and_the_size_has_a_limit():
    assert pairing.code_error(ValueError())["message"] == "ValueError"
    assert len(pairing.code_error(Exception("x" * 5000))["message"]) <= pairing.MESSAGE_LIMIT


# ── The Brazilian 9th digit ─────────────────────────────────────────────────
# Reported: on Neonize a number only paired once the user left the 9 out.

def test_a_mobile_outside_the_nine_first_areas_tries_without_the_nine_first():
    assert pairing.phone_candidates("+55 (31) 99876-5432") == ["553198765432", "5531998765432"]
    assert pairing.phone_candidates("553198765432") == ["553198765432", "5531998765432"]


def test_a_mobile_in_the_nine_first_areas_tries_with_the_nine_first():
    assert pairing.phone_candidates("5511987654321") == ["5511987654321", "551187654321"]
    assert pairing.phone_candidates("551187654321") == ["5511987654321", "551187654321"]


def test_landlines_and_other_countries_go_as_typed():
    assert pairing.phone_candidates("551132654321") == ["551132654321"]
    assert pairing.phone_candidates("14155550123") == ["14155550123"]
    assert pairing.phone_candidates("5511876543") == ["5511876543"]


def test_the_server_tries_the_other_form_after_a_refusal():
    import pathlib
    source = (pathlib.Path(__file__).parent / "server.py").read_text(encoding="utf-8")
    assert "candidates = pairing.phone_candidates(phone_number)" in source
    assert "number = candidates[attempt % len(candidates)]" in source
    assert "cli.PairPhone(number," in source
