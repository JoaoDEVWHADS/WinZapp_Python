"""Regression tests for binary-blob detection used by message rendering."""

from core.utils import looks_like_binary_blob


def test_long_alphabetic_chat_text_is_not_a_binary_blob():
    # Reported live: an ordinary text message made only of letters and longer
    # than 64 chars was mistaken for base64 and rendered as
    # "Mensagem incompatível".
    text = (
        "fflsdjlfjsdklfjklsdfljsdlfsdjflsdfjklsdjfljsdlkfjsdljfsdjfklj"
        "sdlfkjsdfjsdfs"
    )

    assert len(text) > 64
    assert text.isalpha()
    assert not looks_like_binary_blob(text)


def test_known_jpeg_base64_signature_is_still_detected():
    assert looks_like_binary_blob("/9j/" + ("A" * 100))


def test_generic_long_base64ish_blob_with_nonletters_is_still_detected():
    assert looks_like_binary_blob(("AbCdEf0123456789+/" * 5))
