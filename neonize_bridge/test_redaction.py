"""redact: the log never shows the whole JID, phone or session name."""
from redaction import redact


def test_person_jid_keeps_only_the_last_two_digits_and_the_server():
    assert redact("5511999998888@s.whatsapp.net") == "...88@s.whatsapp.net"


def test_group_jid_and_lid_keep_the_type():
    assert redact("120363025246125486@g.us") == "...86@g.us"
    assert redact("98765432109876@lid") == "...76@lid"


def test_session_name_without_at_sign():
    assert redact("my-account") == "...nt"


def test_short_or_empty_value_does_not_break():
    assert redact("a") == "...a"
    assert redact("") == "?"
    assert redact(None) == "?"


def test_the_result_never_contains_the_original_value():
    for original in ("5511999998888@s.whatsapp.net", "120363025246125486@g.us",
                     "johns-account"):
        assert original not in redact(original)
        assert original.partition("@")[0][:-2] not in redact(original)


# ---------------------------------------------------------- log filter
import io
import logging

from redaction import RedactionFilter, mask_text


def test_mask_text_hides_jid_and_long_number():
    assert mask_text("failed with 5511999998888@s.whatsapp.net in 120363025246125486@g.us") \
        == "failed with ...88@s.whatsapp.net in ...86@g.us"
    assert mask_text("number 5511999998888 invalid") == "number ...88 invalid"
    assert mask_text("error 404 in 3 attempts") == "error 404 in 3 attempts"


def _log_with_filter():
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(RedactionFilter())
    record = logging.getLogger("test_redaction")
    record.handlers = [handler]
    record.propagate = False
    record.setLevel(logging.INFO)
    return record, out


def test_the_filter_masks_the_formatted_message_and_the_traceback():
    record, out = _log_with_filter()
    try:
        raise ValueError("rejected: 5511999998888@s.whatsapp.net")
    except ValueError:
        record.exception("sending to %s", "5511999998888@s.whatsapp.net")
    text = out.getvalue()
    assert "5511999998888" not in text
    assert "...88@s.whatsapp.net" in text
