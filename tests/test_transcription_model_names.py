"""How a model is named in the picker and in every sentence that says one.

An id is not a name: "ggml-small-q5_1" is a prefix, a file name and a code a
screen reader spells out, and a model that only understands one language has
to say so *before* it is chosen, not after a Portuguese voice note comes back
in English. Every place that names a model asks model_names, so these pin
what it answers.
"""

import re

from tests.locales import load_strings, registered_locale_codes
import pytest

from core.transcription import (
    backend as backend_module,
    external_models,
    model_names,
    preferences,
)


class _I18n:
    """The key and what it was formatted with, so assertions need no locale."""

    def t(self, key):
        return _Template(key)


class _Template(str):
    def format(self, **values):
        return f"{self}(" + ",".join(f"{k}={v}" for k, v in sorted(values.items())) + ")"


def _locales():
    return list(registered_locale_codes())


def _table(locale):
    return load_strings(locale)


class TestTheNames:
    def test_a_multilingual_faster_whisper_model_is_its_id(self):
        assert model_names.display_name(_I18n(), "large-v3") == "large-v3"

    def test_an_english_only_model_says_so(self):
        assert model_names.display_name(_I18n(), "small.en") == (
            f"{model_names.ENGLISH_ONLY_I18N_KEY}(model=small.en)"
        )

    @pytest.mark.parametrize("model_id", ["distil-large-v3.5", "distil-large-v3",
                                          "distil-large-v2", "distil-medium.en",
                                          "distil-small.en"])
    def test_every_distilled_model_says_english_only_and_none_says_third_party(
        self, model_id
    ):
        # distil-large-v3.5 comes from the Hugging Face distil-whisper team,
        # whose models Systran converts: official, like the others.
        assert model_names.display_name(_I18n(), model_id) == (
            f"{model_names.ENGLISH_ONLY_I18N_KEY}(model={model_id})"
        )
        assert not preferences.catalogue_entry(model_id).third_party

    def test_a_third_party_model_says_its_language_and_publisher(self):
        assert model_names.display_name(_I18n(), "kb-whisper-small") == (
            f"{model_names.THIRD_PARTY_I18N_KEY}(language={preferences.language_name('sv')},"
            "model=kb-whisper-small,publisher=KBLab)"
        )

    def test_a_ggml_file_is_its_model_and_its_bits_never_its_file_name(self):
        assert model_names.display_name(_I18n(), "ggml-small-q5_1") == (
            f"{model_names.QUANTIZED_I18N_KEY}(bits=5,model=small)"
        )
        assert model_names.display_name(_I18n(), "ggml-small") == (
            f"{model_names.QUANTIZED_I18N_KEY}(bits=16,model=small)"
        )

    def test_an_english_only_ggml_file_says_both(self):
        name = model_names.display_name(_I18n(), "ggml-tiny.en-q8_0")
        assert name == (f"{model_names.QUANTIZED_I18N_KEY}(bits=8,model="
                        f"{model_names.ENGLISH_ONLY_I18N_KEY}(model=tiny.en))")

    @pytest.mark.parametrize("model_id, base_model", [
        ("ggml-distil-large-v3-f32", "distil-large-v3"),
        ("ggml-distil-large-v2-f32", "distil-large-v2"),
        ("ggml-distil-medium.en-f32", "distil-medium.en"),
        ("ggml-distil-small.en-f32", "distil-small.en"),
    ])
    def test_a_32_bit_file_says_full_precision_and_its_f16_sibling_16_bits(
        self, model_id, base_model
    ):
        english = f"{model_names.ENGLISH_ONLY_I18N_KEY}(model={base_model})"
        assert model_names.display_name(_I18n(), model_id) == (
            f"{model_names.FULL_PRECISION_I18N_KEY}(model={english})"
        )
        assert model_names.display_name(_I18n(), model_id[:-len("-f32")]) == (
            f"{model_names.QUANTIZED_I18N_KEY}(bits=16,model={english})"
        )

    def test_a_third_party_ggml_file_says_who_and_which_language(self):
        name = model_names.display_name(_I18n(), "ggml-ivrit-large-v3")
        assert name.startswith(f"{model_names.QUANTIZED_I18N_KEY}(bits=16,model=")
        assert f"language={preferences.language_name('he')}" in name
        assert "publisher=ivrit.ai" in name

    def test_a_custom_model_is_its_files_name(self):
        reference = external_models.ExternalReference(
            "abc", "/disk/models/fine-tune.bin", None, True,
            backend=backend_module.BACKEND_WHISPER_CPP,
        )
        assert model_names.display_name(_I18n(), "external:abc", (reference,)) == (
            "fine-tune.bin"
        )
        # Forgotten: nothing worth reading out, and the caller says so.
        assert model_names.display_name(_I18n(), "external:abc", ()) is None

    @pytest.mark.parametrize("model_id", [None, ""])
    def test_no_model_is_no_name(self, model_id):
        assert model_names.display_name(_I18n(), model_id) is None

    def test_an_id_no_catalogue_knows_is_said_as_it_is(self):
        assert model_names.display_name(_I18n(), "retired-model") == "retired-model"


class TestAListOfModels:
    def test_each_id_is_said_by_its_name_and_the_filter_not_at_all(self):
        from core.transcription import whisper_cpp_catalog

        said = model_names.display_list(
            _I18n(), ["small", whisper_cpp_catalog.VAD_MODEL.id, "ggml-tiny-q5_1"])
        assert said == model_names.LIST_SEPARATOR.join((
            "small", f"{model_names.QUANTIZED_I18N_KEY}(bits=5,model=tiny)"))
        assert "silero" not in said and "ggml-" not in said

    def test_the_separator_cannot_appear_in_an_id(self):
        from core.transcription import management, model_catalog, whisper_cpp_catalog

        for entry in model_catalog.MODELS + whisper_cpp_catalog.MODELS:
            assert management.LIST_SEPARATOR not in entry.id


class TestTheBackendName:
    @pytest.mark.parametrize("backend_id", backend_module.BACKEND_IDS)
    def test_every_backend_has_its_label(self, backend_id):
        assert model_names.backend_name(_I18n(), backend_id) == (
            preferences.BACKEND_I18N_KEYS[backend_id]
        )

    @pytest.mark.parametrize("backend_id", [None, preferences.AUTO, "nonsense"])
    def test_automatic_or_unknown_is_not_a_backend(self, backend_id):
        assert model_names.backend_name(_I18n(), backend_id) is None


@pytest.mark.parametrize("locale", _locales())
def test_every_name_is_translated_with_the_values_it_is_given(locale):
    table = _table(locale)
    expected = {
        model_names.ENGLISH_ONLY_I18N_KEY: {"model"},
        model_names.THIRD_PARTY_I18N_KEY: {"model", "language", "publisher"},
        model_names.QUANTIZED_I18N_KEY: {"model", "bits"},
        # "32" is written into each sentence: its plural is not 5's in pl or ro.
        model_names.FULL_PRECISION_I18N_KEY: {"model"},
    }
    assert set(expected) == set(model_names.MODEL_NAME_I18N_KEYS)
    for key, placeholders in expected.items():
        assert table.get(key, "").strip(), f"{locale}: {key} is missing or blank"
        assert set(re.findall(r"\{(\w+)\}", table[key])) == placeholders, f"{locale}: {key}"
