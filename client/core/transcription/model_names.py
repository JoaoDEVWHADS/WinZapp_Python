"""How a model is named to the user, in the model picker and in every sentence.

A model id is not always a name. "small" is; "ggml-small-q5_1" is three things
a screen reader spells out — a prefix, a file name and a quantization code —
and "external:3f2a…" is nothing at all. Since part 9b two catalogues name
their models (faster-whisper's and whisper.cpp's), and some of them only
understand English, which the user has to hear *before* choosing one. So every
place that says a model — the picker line, the download question, the
"loading" sentence, the stored transcription's headline — asks here, and they
all say the same thing:

* a faster-whisper model is its id ("large-v3");
* a GGML file of whisper.cpp's is its model and its bits per weight ("small, 5
  bits") — for whisper.cpp the quantization *is* the file, and two files of
  one model are told apart by nothing else. A 32-bit file has a sentence of
  its own ("distil-small.en, English only, 32 bits, full precision"): "32"
  takes another plural than 5, 8 and 16 in Polish and Romanian;
* an English-only model says so ("small.en, English only");
* a third-party model says its language and who published it
  ("kb-whisper-small (svenska only, third-party: KBLab)") — the language by
  its endonym, as every other sentence that names a language does, and the
  publisher because the quality and the licence are theirs, not Whisper's;
* a custom model is its folder's or file's name, and unknown is None.

Pure: the i18n object comes in as an argument, like external_view's.
"""

from __future__ import annotations

from core.transcription import external_models, preferences, whisper_cpp_catalog

ENGLISH_ONLY_I18N_KEY = "transcription_model_name_english_only"
THIRD_PARTY_I18N_KEY = "transcription_model_name_third_party"
QUANTIZED_I18N_KEY = "transcription_model_name_quantized"
FULL_PRECISION_I18N_KEY = "transcription_model_name_full_precision"

#: Every key this module asks for; the i18n tests read it.
MODEL_NAME_I18N_KEYS = (ENGLISH_ONLY_I18N_KEY, THIRD_PARTY_I18N_KEY, QUANTIZED_I18N_KEY,
                        FULL_PRECISION_I18N_KEY)


def display_name(i18n, model_id, references=()):
    """The name to show and say for the model setting `model_id`, or None.

    None only for a custom choice whose reference was forgotten — the raw
    `external:<id>` is never worth reading out (external_models.model_name()).
    An id neither catalogue knows is said as it is: it is what the log says,
    and a retired model is still better named than not.
    """
    if not model_id:
        return None
    if preferences.custom_model_reference_id(model_id) is not None:
        return external_models.model_name(model_id, references)
    entry = preferences.catalogue_entry(model_id)
    if entry is None:
        return str(model_id)
    if entry in whisper_cpp_catalog.MODELS:
        model = _qualified(i18n, entry.base_model, entry)
        if entry.full_precision:
            return i18n.t(FULL_PRECISION_I18N_KEY).format(model=model)
        return i18n.t(QUANTIZED_I18N_KEY).format(model=model, bits=entry.bits)
    return _qualified(i18n, entry.id, entry)


#: What joins a list of display names. Not a comma: a name may hold one
#: ("small, 5 bits"), and "tiny, small, 5 bits" would be three models to the
#: ear. A semicolon is a list separator in all seven languages.
LIST_SEPARATOR = "; "


def display_list(i18n, model_ids):
    """Model ids as one spoken list of names, without the voice-activity
    model's — a file that comes with the GGML models and is nobody's choice."""
    return LIST_SEPARATOR.join(
        display_name(i18n, model_id) or str(model_id)
        for model_id in model_ids
        if model_id and model_id != whisper_cpp_catalog.VAD_MODEL.id
    )


def backend_name(i18n, backend_id):
    """The backend's label ("faster-whisper", "whisper.cpp"), or None."""
    key = preferences.BACKEND_I18N_KEYS.get(backend_id)
    if key is None or backend_id == preferences.AUTO:
        return None
    return i18n.t(key)


def _qualified(i18n, name, entry):
    """`name` with what the entry's language and origin oblige it to say."""
    if entry.third_party:
        return i18n.t(THIRD_PARTY_I18N_KEY).format(
            model=name,
            language=preferences.language_name(entry.language) or entry.language,
            publisher=entry.publisher,
        )
    if entry.english_only:
        return i18n.t(ENGLISH_ONLY_I18N_KEY).format(model=name)
    return name
