"""Regression tests for adaptive message-page overfetching."""

from main import MainWindow


def _message(message_type="conversation"):
    return {"messageType": message_type}


def test_full_visible_page_does_not_request_a_refill():
    messages = [_message() for _ in range(200)]

    assert MainWindow._needs_display_page_refill(200, messages, 200) is False


def test_hidden_rows_in_a_saturated_page_request_a_refill():
    messages = [_message() for _ in range(199)] + [_message("reactionMessage")]

    assert MainWindow._needs_display_page_refill(200, messages, 200) is True


def test_genuinely_short_conversation_does_not_request_a_refill():
    messages = [_message() for _ in range(132)]

    assert MainWindow._needs_display_page_refill(132, messages, 200) is False
