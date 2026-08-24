"""Tests for per-message caption handling when forwarding.

Forwarding normally goes through WPP.chat.forwardMessagesV2, which reproduces
the message as WhatsApp does. Preserving a caption needs a different call —
resend_media_message_with_caption — which is a *media* resend.

That distinction did not matter while forwarding was one message at a time.
Mass forward broke it: keep_caption was read once from a checkbox built out of
whichever message the selection happened to hand over first, then applied to
every message in the batch. Two failures came out of that, and both are pinned
here:

  * first message has no caption -> the checkbox is never built -> every other
    message's caption is dropped without asking;
  * first message has one -> keep_caption is True for the whole batch -> plain
    text messages selected alongside it are pushed through the media call.

message_caption() is the per-message answer both now go through. It is a
module-level function precisely so it can be tested without a wx.App —
ConversationsPanel is a wx.Panel and cannot be instantiated without one (same
approach as tests/test_message_bookmarks.py and tests/test_sender_names.py).
"""

import json

import pytest

from ui.conversations import message_caption


def _media(kind, caption=None):
    inner = {kind: {"url": "https://example.invalid/x.enc"}}
    if caption is not None:
        inner[kind]["caption"] = caption
    return {"key": {"id": "X", "remoteJid": "1@s.whatsapp.net"}, "message": inner}


def _text(body="olá"):
    return {"key": {"id": "T", "remoteJid": "1@s.whatsapp.net"},
            "message": {"conversation": body}}


class TestMessageCaption:
    @pytest.mark.parametrize("kind", ["imageMessage", "videoMessage", "documentMessage"])
    def test_a_captioned_media_message_reports_its_caption(self, kind):
        assert message_caption(_media(kind, "no alto da serra")) == "no alto da serra"

    @pytest.mark.parametrize("kind", ["imageMessage", "videoMessage", "documentMessage"])
    def test_the_same_media_without_a_caption_reports_nothing(self, kind):
        assert message_caption(_media(kind)) == ""

    def test_a_whitespace_only_caption_does_not_count(self):
        """It would send an empty caption down the media path for nothing."""
        assert message_caption(_media("imageMessage", "   \n ")) == ""

    def test_a_null_caption_does_not_raise(self):
        """WPPConnect sends caption: null rather than omitting the field; the
        previous inline copy called .strip() straight on it."""
        assert message_caption(_media("imageMessage", None)) == ""
        raw = {"key": {"id": "X"}, "message": {"imageMessage": {"caption": None}}}
        assert message_caption(raw) == ""

    def test_a_text_message_has_no_caption(self):
        assert message_caption(_text()) == ""

    @pytest.mark.parametrize("kind", ["audioMessage", "stickerMessage", "contactMessage"])
    def test_media_types_that_cannot_carry_a_caption(self, kind):
        assert message_caption({"message": {kind: {"url": "x"}}}) == ""

    def test_a_json_encoded_payload_is_parsed(self):
        """message arrives as a JSON string on some paths."""
        msg = {"key": {"id": "X"},
               "message": json.dumps({"imageMessage": {"caption": "praia"}})}
        assert message_caption(msg) == "praia"

    @pytest.mark.parametrize("junk", [None, "", "not json", 42, [], {"message": None}])
    def test_junk_never_raises(self, junk):
        assert message_caption(junk) == ""


def _resolve_batch(messages, checkbox_value):
    """What _on_menu_forward now computes: whether the checkbox is offered at
    all, and the keep_caption actually handed to each message."""
    offered = any(message_caption(m) for m in messages)
    keep_captions = checkbox_value if offered else False
    return offered, [keep_captions and bool(message_caption(m)) for m in messages]


class TestTheBatchDecision:
    def test_a_text_message_is_never_sent_down_the_media_path(self):
        """The regression: a captioned image selected together with plain
        text. Batch-wide keep_caption made every one of these True."""
        batch = [_media("imageMessage", "praia"), _text(), _text("tchau")]
        offered, keep = _resolve_batch(batch, checkbox_value=True)
        assert offered is True
        assert keep == [True, False, False]

    def test_the_checkbox_is_offered_when_only_a_later_message_has_a_caption(self):
        """The other half: the picker used to key the offer on the first
        message, so this batch silently lost the image's caption."""
        batch = [_text(), _media("imageMessage", "praia")]
        offered, keep = _resolve_batch(batch, checkbox_value=True)
        assert offered is True
        assert keep == [False, True]

    def test_declining_the_checkbox_keeps_every_message_on_the_plain_path(self):
        batch = [_media("imageMessage", "praia"), _media("videoMessage", "serra")]
        offered, keep = _resolve_batch(batch, checkbox_value=False)
        assert offered is True
        assert keep == [False, False]

    def test_a_batch_with_no_captions_never_offers_the_checkbox(self):
        batch = [_text(), _media("imageMessage"), _media("audioMessage")]
        offered, keep = _resolve_batch(batch, checkbox_value=True)
        assert offered is False
        assert keep == [False, False, False]

    def test_a_single_captioned_message_still_behaves_as_before(self):
        """The one-message path this dialog was originally written for."""
        offered, keep = _resolve_batch([_media("imageMessage", "praia")], True)
        assert offered is True
        assert keep == [True]

    def test_every_captioned_message_in_a_large_mixed_batch_is_preserved(self):
        batch = [_text(), _media("imageMessage", "a"), _text(),
                 _media("documentMessage", "b"), _media("videoMessage"), _text()]
        offered, keep = _resolve_batch(batch, checkbox_value=True)
        assert offered is True
        assert keep == [False, True, False, True, False, False]
