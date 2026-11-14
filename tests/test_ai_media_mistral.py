"""Mistral routes each media kind to its own model; no network in this suite."""
import json
import pytest
from core.ai_media import config, model_catalog, providers, service
from core.ai_media.errors import DescriptionError
from core.ai_media.mistral_ocr import readable_text
from core.ai_media.payload import Media
from tests.test_ai_media_core import FakeHTTP, FakeResponse

AUDIO = Media("audio", b"synthetic-recording", "audio/ogg", "audio.ogg")
IMAGE = Media("image", b"synthetic-picture", "image/jpeg", "image.jpg")
PDF = Media("pdf", b"synthetic-pdf", "application/pdf", "document.pdf")


def request(media, model="mistral-small-latest", history=()):
    return providers.build_request("mistral", model, "synthetic-key", media,
                                   history, "Describe this", "Accessible description", "balanced")


@pytest.mark.parametrize("model", ["mistral-small-latest", "ministral-3b-latest", "voxtral-mini-2602"])
def test_audio_never_goes_to_the_vision_model(model):
    """The provider window's model is for pictures: a vision id reaching the
    audio path (or a voice id off the reviewed list) falls back to the default
    voice-message model."""
    result = request(AUDIO, model)
    assert result.url == "https://api.mistral.ai/v1/audio/transcriptions"
    assert result.headers == {"Authorization": "Bearer synthetic-key"}
    assert result.data == {"model": "voxtral-mini-transcribe-3"}
    assert result.files == {"file": ("audio.ogg", AUDIO.data, "audio/ogg")}
    assert result.json is None


@pytest.mark.parametrize("model", ["voxtral-mini-transcribe-3", "voxtral-small-transcribe-3"])
def test_audio_uses_the_chosen_voice_message_model(model):
    assert request(AUDIO, model).data == {"model": model}


def test_an_unsafe_model_id_never_reaches_the_audio_path():
    with pytest.raises(DescriptionError, match="ai_error_request"):
        request(AUDIO, "../voxtral")


def test_the_voice_models_are_the_file_transcription_ones_with_the_live_tested_default():
    """Mistral's file-transcription guide accepts exactly these two; both are
    Public Preview, which the list says. Mini was the one tested live."""
    spec = config.PROVIDERS["mistral"]
    assert [c.id for c in spec.transcribe_choices] == ["voxtral-mini-transcribe-3",
                                                       "voxtral-small-transcribe-3"]
    assert spec.transcribe_model == "voxtral-mini-transcribe-3"
    assert all(c.preview for c in spec.transcribe_choices)
    assert all(config.valid_model(c.id) and c.name for c in spec.transcribe_choices)
    # Only Mistral offers a choice; the others keep their one fixed model.
    assert [p for p, s in config.PROVIDERS.items() if s.transcribe_choices] == ["mistral"]


@pytest.mark.parametrize("saved, expected", [
    (None, "voxtral-mini-transcribe-3"),
    ({"mistral": "voxtral-small-transcribe-3"}, "voxtral-small-transcribe-3"),
    ({"mistral": "voxtral-mini-transcribe-realtime-3"}, "voxtral-mini-transcribe-3"),  # a stream
    ({"mistral": "voxtral-mini-2602"}, "voxtral-mini-transcribe-3"),  # "Invalid model" for files
    ({"mistral": "ministral-3b-latest"}, "voxtral-mini-transcribe-3"),
    ({"mistral": 3}, "voxtral-mini-transcribe-3"),
    ("not a dict", "voxtral-mini-transcribe-3"),
])
def test_a_saved_voice_model_is_kept_only_when_it_is_on_the_reviewed_list(saved, expected):
    prefs = config.preferences({"ai_media": {"transcribe_models": saved}})
    assert prefs["transcribe_models"] == {"mistral": expected}


def test_only_audio_is_sent_to_the_voice_model():
    prefs = config.preferences({"ai_media": {
        "models": {"mistral": "mistral-small-latest"},
        "transcribe_models": {"mistral": "voxtral-small-transcribe-3"}}})
    audio = config.models_for(prefs, "audio")
    assert audio["mistral"] == "voxtral-small-transcribe-3"
    assert audio["openai"] == prefs["models"]["openai"]  # resolved to its fixed model later
    for kind in ("image", "sticker", "video", "pdf"):
        assert config.models_for(prefs, kind)["mistral"] == "mistral-small-latest"
    # A configuration without the field (an older caller) still routes audio.
    assert config.models_for({"models": {"mistral": "x"}}, "audio") == {"mistral": "x"}


def test_other_providers_keep_their_fixed_transcription_model():
    for provider, model in (("openai", "gpt-4o-mini-transcribe"), ("groq", "whisper-large-v3-turbo")):
        result = providers.build_request(provider, "voxtral-mini-transcribe-3", "k", AUDIO, (),
                                         "", "", "balanced")
        assert result.data["model"] == model


def test_images_and_stickers_use_selected_vision_model_and_history():
    for kind in ("image", "sticker"):
        result = request(Media(kind, IMAGE.data, IMAGE.mime, IMAGE.filename),
                         "ministral-3b-latest", (("assistant", "a green rectangle"),))
        assert result.url == "https://api.mistral.ai/v1/chat/completions"
        assert result.json["model"] == "ministral-3b-latest"
        assert result.json["messages"][0] == {"role": "system", "content": "Accessible description"}
        assert result.json["messages"][1]["content"] == "a green rectangle"
        part = result.json["messages"][-1]["content"][-1]
        assert part["image_url"].startswith("data:image/jpeg;base64,")
        assert result.files is None


def test_pdf_always_uses_ocr_in_a_single_inline_request():
    result = request(PDF, "ministral-3b-latest")
    assert result.url == "https://api.mistral.ai/v1/ocr"
    assert result.json["model"] == "mistral-ocr-4"
    assert result.json["document"]["document_url"].startswith("data:application/pdf;base64,")
    assert result.json["include_image_base64"] is False
    assert "pages" not in result.json
    assert result.files is None


def test_every_kind_can_go_to_mistral():
    prefs = config.preferences({"ai_media": {}})
    for kind in config.KINDS:
        assert config.supports("mistral", kind)
        assert config.chain(prefs, kind, lambda p: p == "mistral") == ["mistral"]


def test_the_provider_window_note_comes_from_the_table_and_only_mistral_has_one():
    # The window shows Provider.model_note before the model field; Mistral's
    # explains that both audio and PDFs bypass the model chosen there.
    noted = {name for name, spec in config.PROVIDERS.items() if spec.model_note}
    assert noted == {"mistral"}
    spec = config.PROVIDERS["mistral"]
    assert spec.model_note == "ai_mistral_model_note"
    assert spec.ocr_model and spec.transcribe_model


def test_get_models_lists_only_vision_and_uses_mistral():
    body = {"data": [{"id": name} for name in (
        "mistral-small-latest", "ministral-3b-latest", "mistral-ocr-latest", "mistral-ocr-4",
        "voxtral-mini-transcribe-3", "voxtral-mini-latest", "../unsafe")]}
    http = FakeHTTP(FakeResponse(data=json.dumps(body).encode()))
    options = model_catalog.fetch_models("mistral", "key", service.RequestToken(),
                                         session_factory=lambda: http)
    assert [option.id for option in options] == ["mistral-small-latest", "ministral-3b-latest"]
    assert http.calls[0][0] == "https://api.mistral.ai/v1/models"
    assert http.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("body", [{}, {"text": None}, {"text": []}, {"text": " "},
                                   {"text": "partial", "finish_reason": "length"}])
def test_malformed_or_partial_transcripts_are_not_success(body):
    with pytest.raises(DescriptionError, match="ai_error_response"):
        providers.parse_answer("mistral", body, "audio")


def test_complete_ocr_pages_are_returned_in_reading_order():
    body = {"pages": [{"index": 1, "markdown": "Page two"},
                       {"index": 0, "markdown": "Page one"}],
            "usage_info": {"pages_processed": 2, "doc_size_bytes": 3002783}}
    assert providers.parse_answer("mistral", body, "pdf") == "Page one\n\nPage two"


@pytest.mark.parametrize("body", [
    {}, {"pages": []}, {"pages": [{"index": 0, "markdown": None}]},
    {"pages": [{"index": 1, "markdown": "missing page zero"}]},
    {"pages": [{"index": 0, "markdown": "a"}, {"index": 0, "markdown": "duplicate"}]},
    {"pages": [{"index": 0, "markdown": "a"}], "usage_info": {"pages_processed": 2}},
    {"pages": [{"index": 0, "markdown": "a"}], "usage_info": {"pages_processed": "1"}},
    # Only an image on every page: nothing is left to read.
    {"pages": [{"index": 0, "markdown": "![img-0.jpeg](img-0.jpeg)"}],
     "usage_info": {"pages_processed": 1}},
])
def test_incomplete_ocr_is_not_announced_as_complete(body):
    with pytest.raises(DescriptionError, match="ai_error_response"):
        providers.parse_answer("mistral", body, "pdf")


def test_long_transcripts_are_never_cut_silently():
    with pytest.raises(DescriptionError, match="ai_error_output_limit"):
        providers.parse_answer("mistral", {"text": "x"*(config.MAX_OUTPUT_CHARS["audio"]+1)}, "audio")


def test_mistral_service_reads_the_response_and_probe_is_metadata_only():
    http = FakeHTTP(FakeResponse(data=b'{"text":"synthetic transcript"}'))
    text = service.request_answer("mistral", "mistral-small-latest", "key", AUDIO,
                                  (), "", "", "balanced", service.RequestToken(),
                                  session_factory=lambda: http)
    assert text == "synthetic transcript"
    assert http.calls[0][1]["data"] == {"model": "voxtral-mini-transcribe-3"}
    assert service.probe_request("mistral", "mistral-small-latest", "key")[0] == (
        "https://api.mistral.ai/v1/models/mistral-small-latest")


class TestOcrMarkdownIsReadAsText:
    """The OCR answer is renderer Markdown (shapes from Mistral's OCR guide);
    a screen reader would read its image links, entities and tags aloud."""

    def test_image_links_entities_and_breaks_become_plain_text(self):
        markdown = (
            "# Leveraging Unlabeled Data\n\nSee Sec. 5 for details on our testbed.\n\n"
            "![img-1.jpeg](img-1.jpeg)\n\n"
            "Recently, methods were proposed (Deng &amp; Zheng, 2021) as in ![img-2.jpeg](img-2.jpeg) here."
            "\n\nFirst line<br>Second line<BR/>Third line")
        assert readable_text(markdown) == (
            "# Leveraging Unlabeled Data\n\nSee Sec. 5 for details on our testbed.\n\n"
            "Recently, methods were proposed (Deng & Zheng, 2021) as in here.\n\n"
            "First line\nSecond line\nThird line")

    def test_a_table_row_keeps_its_cells_on_one_line(self):
        markdown = "| Model | Titles |\n| --- | --- |\n| A | 1. Crown <br></br> 2. Magic |"
        assert readable_text(markdown) == "| Model | Titles |\n| --- | --- |\n| A | 1. Crown 2. Magic |"

    def test_the_text_itself_is_kept(self):
        # An entity is decoded once, and a bare "&" (an author list in the
        # guide's sample, "&Sivaraman") or a legacy name without ";" stays.
        markdown = "&Sivaraman Balakrishnan\nR&D &notice\nWrite &lt;br&gt; literally, caf&#233;"
        assert readable_text(markdown) == (
            "&Sivaraman Balakrishnan\nR&D &notice\nWrite <br> literally, café")

    def test_blank_lines_left_by_removed_images_collapse(self):
        body = {"pages": [{"index": 0, "markdown": "Page one\n\n  ![img-0.jpeg](img-0.jpeg)  \n\n"},
                          {"index": 1, "markdown": "![img-1.jpeg](img-1.jpeg)"},
                          {"index": 2, "markdown": "\n\n\n\nPage three"}],
                "usage_info": {"pages_processed": 3}}
        assert providers.parse_answer("mistral", body, "pdf") == "Page one\n\nPage three"
