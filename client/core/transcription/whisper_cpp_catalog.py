"""The GGML files whisper.cpp can transcribe with, as data.

model_catalog's counterpart for the second backend, and the same contract with
a remote repository: every file below was listed from the Hugging Face API of
`ggerganov/whisper.cpp` at revision 5359861c739e955e79d9a303bcbc70fb988958b1
(and the voice-activity model from `ggml-org/whisper-vad` at
9ffd54a1e1ee413ddf265af9913beaf518d1639b) on 2026-10-05, twice, with identical
results. The sizes and digests are what model_store downloads and verifies
against, through the same code as the faster-whisper models.

What differs from the faster-whisper catalogue, and why:

* **A model is one file, and a quantization is a different file.** There is no
  folder of tokenizer and config files: `ggml-small-q5_1.bin` is the whole
  model. So choosing a quantization (part 11) is choosing which entry, and an
  entry knows its `base_model` and its `quantization` for exactly that purpose
  — `variant()` and `variants_of()` are the lookups. Only the variants the
  repository actually publishes are here; they are not uniform (tiny..small
  have q5_1, medium and the large ones q5_0, large-v1 nothing but f16, large-v3
  no q8_0), and a variant that is not published is not a variant.

* **Every file carries its own sha256.** Hugging Face states one for every LFS
  file, and each of these is one, so unlike model_catalog — where only
  model.bin has one — nothing here is checked by size alone.

* **The single-language models are offered, and say so.** The English-only
  ones (`*.en`, the distilled ones) can be the better model of their size for
  a note in English, and the third-party fine-tunes (KBLab's Swedish,
  ivrit.ai's Hebrew and Yiddish, Kotoba's Japanese) for theirs; the
  maintainers asked for all of them (2026-10-05). None can detect a language
  or hear another one — handed Portuguese, an `.en` model answers with
  confident English a listener cannot tell from a transcription — so
  `language` is what the rest of the app keys on: the picker names it, a run
  forces it and says so, and the automatic choice never picks one unless it
  is the user's language (preferences.resolve()). Each `base_model` is the
  faster-whisper id of the same model ("small.en", "kb-whisper-small").

* **The other repositories name their files their own way**
  (`ggml-model.bin`, `ggml-kotoba-whisper-v2.0-q5_0.bin`, the distil-whisper
  team's `ggml-medium-32-2.en.bin`), and each has its own repository and
  revision: those entries carry all of it explicitly (`_published()`), read
  from the Hugging Face API at the pinned revision on 2026-10-05 with
  `?blobs=true` and then file by file. Only the files listed are fetched — the
  same repositories hold the PyTorch weights too (`pytorch_model*.bin`,
  `original-model*.bin`).

* **The distil-whisper team publishes full precision too.** Beside each f16
  file of distil-large-v3, distil-large-v2, distil-medium.en and
  distil-small.en sits an fp32 one, the only 32-bit files here: twice the
  download for the same model, offered because they are official
  (distil-large-v3.5 has none). Only a user's own choice ever runs one: the
  automatic choice never picks a 32-bit file (device.auto_select_model()).

* **The CoreML `*-encoder.mlmodelc.zip` files are macOS-only** and not listed.

The ids are the file names without `.bin` ("ggml-small-q5_1"): they double as
the folder name under the models root (model_store.model_dir()), and the
`ggml-` prefix keeps them from ever colliding with a faster-whisper id should
both catalogues one day share a root.

No user-facing text lives here: the size classes reuse model_catalog's, whose
i18n keys already exist, and naming a quantization is the UI layer's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.transcription import model_catalog
from core.transcription.model_catalog import (
    ENGLISH,
    ORIGIN_OFFICIAL,
    ORIGIN_THIRD_PARTY,
    SIZE_CLASSES,
    SIZE_LARGE,
    SIZE_MEDIUM,
    SIZE_SMALL,
    language_rank,
)

MODELS_REPO = "ggerganov/whisper.cpp"
MODELS_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"

VAD_REPO = "ggml-org/whisper-vad"
VAD_REVISION = "9ffd54a1e1ee413ddf265af9913beaf518d1639b"

# Quantizations, most faithful first. f16 is what the repository calls plain
# `ggml-<model>.bin`: the converter writes half precision unless asked to
# quantize. f32, full precision, only the distil-whisper team publishes.
QUANT_F32 = "f32"
QUANT_F16 = "f16"
QUANT_Q8_0 = "q8_0"
QUANT_Q5_1 = "q5_1"
QUANT_Q5_0 = "q5_0"

QUANTIZATIONS = (QUANT_F32, QUANT_F16, QUANT_Q8_0, QUANT_Q5_1, QUANT_Q5_0)

# Bits per weight, which is what the picker names a quantization by.
QUANTIZATION_BITS = {QUANT_F32: 32, QUANT_F16: 16, QUANT_Q8_0: 8, QUANT_Q5_1: 5,
                     QUANT_Q5_0: 5}

# The Whisper models in the order the picker presents them, each with the
# size class model_catalog gives the same model — the shared ids are the same
# model, and "fast / balanced / accurate" must not change with the backend.
# large-v1 and large-v2 are large models in every sense, and kotoba-whisper-v1.0
# exists only here.
_BASE_MODELS = (
    ("tiny", SIZE_SMALL),
    ("base", SIZE_SMALL),
    ("small", SIZE_MEDIUM),
    ("medium", SIZE_MEDIUM),
    ("large-v3-turbo", SIZE_LARGE),
    ("large-v1", SIZE_LARGE),
    ("large-v2", SIZE_LARGE),
    ("large-v3", SIZE_LARGE),
    # After every multilingual model, so that within a size class they are
    # listed after them, and among themselves in the order of
    # model_catalog.list_models().
    ("tiny.en", SIZE_SMALL),
    ("base.en", SIZE_SMALL),
    ("distil-small.en", SIZE_SMALL),
    ("small.en", SIZE_MEDIUM),
    ("distil-medium.en", SIZE_MEDIUM),
    ("medium.en", SIZE_MEDIUM),
    ("distil-large-v2", SIZE_LARGE),
    ("distil-large-v3", SIZE_LARGE),
    ("distil-large-v3.5", SIZE_LARGE),
    # The third-party ones, with the size class of the official model each
    # was trained from.
    ("kb-whisper-tiny", SIZE_SMALL),
    ("kb-whisper-base", SIZE_SMALL),
    ("kb-whisper-small", SIZE_MEDIUM),
    ("kb-whisper-medium", SIZE_MEDIUM),
    ("kb-whisper-large", SIZE_LARGE),
    ("ivrit-large-v3-turbo", SIZE_LARGE),
    ("ivrit-large-v3", SIZE_LARGE),
    ("ivrit-yi-large-v3-turbo", SIZE_LARGE),
    ("ivrit-yi-large-v3", SIZE_LARGE),
    ("kotoba-whisper-v2.0", SIZE_LARGE),
    ("kotoba-whisper-v1.0", SIZE_LARGE),
)

BASE_MODELS = tuple(name for name, _size_class in _BASE_MODELS)

_ENGLISH_ONLY_SUFFIX = ".en"
_FILE_PREFIX = "ggml-"
_FILE_SUFFIX = ".bin"
_QUANT_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<quant>q\d_\d)$")


@dataclass(frozen=True)
class GgmlFile:
    """One downloadable GGML file, shaped so model_store can handle it.

    model_store reads `id`, `repo`, `revision`, `files`, `download_bytes` and
    `sha256_of()`; a WhisperModel answers the same names, which is the whole of
    what lets both catalogues share one downloader, one verifier and one
    remover instead of two copies drifting apart.
    """

    id: str
    repo: str
    # Fetched by this sha, never by branch: see model_store.file_url().
    revision: str
    filename: str
    size_bytes: int
    sha256: str
    # The model_catalog id of the same model where there is one ("small",
    # "large-v3-turbo"); "" for the voice-activity model.
    base_model: str = ""
    # One of QUANTIZATIONS, or "" for the voice-activity model.
    quantization: str = ""
    size_class: str = ""
    # The one language the model was trained on, or None for a multilingual
    # one — as model_catalog.WhisperModel.language, and for the same reasons.
    language: str | None = None
    origin: str = ORIGIN_OFFICIAL
    publisher: str = ""

    @property
    def english_only(self) -> bool:
        """Whether this file holds an English-only model (see the docstring)."""
        return self.language == ENGLISH

    @property
    def third_party(self) -> bool:
        return self.origin == ORIGIN_THIRD_PARTY

    @property
    def full_precision(self) -> bool:
        """Whether this is a 32-bit file, which only a user's choice runs."""
        return self.quantization == QUANT_F32

    @property
    def bits(self) -> int | None:
        """How many bits each weight takes in this file, or None for the VAD.

        What the picker says instead of the quantization's own name: "5 bits"
        is something a listener can weigh, "q5_1" is three characters a screen
        reader spells out. The two 5-bit layouts are never both published for
        one model, so the figure alone tells every variant of a model apart.
        """
        return QUANTIZATION_BITS.get(self.quantization)

    @property
    def min_ram_mb(self) -> int:
        """Memory to plan for on the processor — see `_memory_twin()`."""
        return _memory_twin(self).min_ram_mb + _full_precision_extra_mb(self)

    @property
    def min_vram_mb(self) -> int:
        """Memory to plan for on the graphics card — see `_memory_twin()`."""
        return _memory_twin(self).min_vram_mb + _full_precision_extra_mb(self)

    @property
    def files(self) -> tuple[tuple[str, int], ...]:
        return ((self.filename, self.size_bytes),)

    @property
    def download_bytes(self) -> int:
        return self.size_bytes

    @property
    def disk_bytes(self) -> int:
        # Written straight into its folder, nothing extracted, nothing cached.
        return self.size_bytes

    def sha256_of(self, name):
        """The digest `name` is checked against: this file's, or None."""
        return self.sha256 if name == self.filename else None


def _ggml(filename, size_bytes, sha256) -> GgmlFile:
    """One model entry, with its base model and quantization read off the name.

    Derived rather than restated beside the name: thirty-odd entries times two
    restatements is sixty chances for a row to say "q5_1" next to a q5_0 file.
    The name is asserted to be a bare basename for the reason model_catalog
    gives — the store joins it onto a user-chosen directory and deletes it.
    """
    assert filename.startswith(_FILE_PREFIX) and filename.endswith(_FILE_SUFFIX), filename
    assert not set(filename) & {"/", "\\"}, filename
    stem = filename[len(_FILE_PREFIX):-len(_FILE_SUFFIX)]
    match = _QUANT_SUFFIX.match(stem)
    base, quant = (match["base"], match["quant"]) if match else (stem, QUANT_F16)
    size_class = dict(_BASE_MODELS)[base]
    assert quant in QUANTIZATIONS, filename
    return GgmlFile(
        id=filename[:-len(_FILE_SUFFIX)],
        repo=MODELS_REPO,
        revision=MODELS_REVISION,
        filename=filename,
        size_bytes=size_bytes,
        sha256=sha256,
        base_model=base,
        quantization=quant,
        size_class=size_class,
        language=ENGLISH if base.endswith(_ENGLISH_ONLY_SUFFIX) else None,
    )


def _published(model_id, repo, revision, filename, size_bytes, sha256, base_model,
               quantization, language, publisher="") -> GgmlFile:
    """An entry of a repository other than ggerganov's, carried explicitly.

    Nothing can be read off these names (`ggml-model.bin` is the file of every
    KBLab size), so the id — which is also the folder the file goes into — is
    given, and must keep the `ggml-` prefix and be unique like every other.
    """
    assert model_id.startswith(_FILE_PREFIX) and not set(model_id) & {"/", "\\"}, model_id
    assert filename.endswith(_FILE_SUFFIX) and not set(filename) & {"/", "\\"}, filename
    assert quantization in QUANTIZATIONS, model_id
    return GgmlFile(
        id=model_id,
        repo=repo,
        revision=revision,
        filename=filename,
        size_bytes=size_bytes,
        sha256=sha256,
        base_model=base_model,
        quantization=quantization,
        size_class=dict(_BASE_MODELS)[base_model],
        language=language,
        origin=ORIGIN_THIRD_PARTY if publisher else ORIGIN_OFFICIAL,
        publisher=publisher,
    )


# Single source of truth, in the order the repository lists them.
MODELS = (
    _ggml("ggml-tiny.bin", 77_691_713,
          "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21"),
    _ggml("ggml-tiny-q5_1.bin", 32_152_673,
          "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"),
    _ggml("ggml-tiny-q8_0.bin", 43_537_433,
          "c2085835d3f50733e2ff6e4b41ae8a2b8d8110461e18821b09a15c40c42d1cca"),
    _ggml("ggml-base.bin", 147_951_465,
          "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"),
    _ggml("ggml-base-q5_1.bin", 59_707_625,
          "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898"),
    _ggml("ggml-base-q8_0.bin", 81_768_585,
          "c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9"),
    _ggml("ggml-small.bin", 487_601_967,
          "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
    _ggml("ggml-small-q5_1.bin", 190_085_487,
          "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb"),
    _ggml("ggml-small-q8_0.bin", 264_464_607,
          "49c8fb02b65e6049d5fa6c04f81f53b867b5ec9540406812c643f177317f779f"),
    _ggml("ggml-medium.bin", 1_533_763_059,
          "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"),
    _ggml("ggml-medium-q5_0.bin", 539_212_467,
          "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f"),
    _ggml("ggml-medium-q8_0.bin", 823_369_779,
          "42a1ffcbe4167d224232443396968db4d02d4e8e87e213d3ee2e03095dea6502"),
    _ggml("ggml-large-v1.bin", 3_094_623_691,
          "7d99f41a10525d0206bddadd86760181fa920438b6b33237e3118ff6c83bb53d"),
    _ggml("ggml-large-v2.bin", 3_094_623_691,
          "9a423fe4d40c82774b6af34115b8b935f34152246eb19e80e376071d3f999487"),
    _ggml("ggml-large-v2-q5_0.bin", 1_080_732_091,
          "3a214837221e4530dbc1fe8d734f302af393eb30bd0ed046042ebf4baf70f6f2"),
    _ggml("ggml-large-v2-q8_0.bin", 1_656_129_691,
          "fef54e6d898246a65c8285bfa83bd1807e27fadf54d5d4e81754c47634737e8c"),
    _ggml("ggml-large-v3.bin", 3_095_033_483,
          "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"),
    _ggml("ggml-large-v3-q5_0.bin", 1_081_140_203,
          "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1"),
    _ggml("ggml-large-v3-turbo.bin", 1_624_555_275,
          "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"),
    _ggml("ggml-large-v3-turbo-q5_0.bin", 574_041_195,
          "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"),
    _ggml("ggml-large-v3-turbo-q8_0.bin", 874_188_075,
          "317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1"),
    _ggml("ggml-tiny.en.bin", 77_704_715,
          "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"),
    _ggml("ggml-tiny.en-q5_1.bin", 32_166_155,
          "c77c5766f1cef09b6b7d47f21b546cbddd4157886b3b5d6d4f709e91e66c7c2b"),
    _ggml("ggml-tiny.en-q8_0.bin", 43_550_795,
          "5bc2b3860aa151a4c6e7bb095e1fcce7cf12c7b020ca08dcec0c6d018bb7dd94"),
    _ggml("ggml-base.en.bin", 147_964_211,
          "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002"),
    _ggml("ggml-base.en-q5_1.bin", 59_721_011,
          "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f"),
    _ggml("ggml-base.en-q8_0.bin", 81_781_811,
          "a4d4a0768075e13cfd7e19df3ae2dbc4a68d37d36a7dad45e8410c9a34f8c87e"),
    _ggml("ggml-small.en.bin", 487_614_201,
          "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"),
    _ggml("ggml-small.en-q5_1.bin", 190_098_681,
          "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30"),
    _ggml("ggml-small.en-q8_0.bin", 264_477_561,
          "67a179f608ea6114bd3fdb9060e762b588a3fb3bd00c4387971be4d177958067"),
    _ggml("ggml-medium.en.bin", 1_533_774_781,
          "cc37e93478338ec7700281a7ac30a10128929eb8f427dda2e865faa8f6da4356"),
    _ggml("ggml-medium.en-q5_0.bin", 539_225_533,
          "76733e26ad8fe1c7a5bf7531a9d41917b2adc0f20f2e4f5531688a8c6cd88eb0"),
    _ggml("ggml-medium.en-q8_0.bin", 823_382_461,
          "43fa2cd084de5a04399a896a9a7a786064e221365c01700cea4666005218f11c"),
    # The distilled models, official (Hugging Face's distil-whisper team) and
    # English-only, and then the third-party fine-tunes: see the docstring.
    _published("ggml-distil-large-v3.5", "distil-whisper/distil-large-v3.5-ggml",
               "960ecb5c2ecfba3ebb9ebe485c1032ec266cf436",
               "ggml-model.bin", 1_519_521_155,
               "ec2498919b498c5f6b00041adb45650124b3cd9f26f545fffa8f5d11c28dcf26",
               "distil-large-v3.5", QUANT_F16, ENGLISH),
    _published("ggml-distil-large-v3", "distil-whisper/distil-large-v3-ggml",
               "0d78dd96ed9fc152325f63b53788fec3b43de031",
               "ggml-distil-large-v3.bin", 1_519_521_155,
               "2883a11b90fb10ed592d826edeaee7d2929bf1ab985109fe9e1e7b4d2b69a298",
               "distil-large-v3", QUANT_F16, ENGLISH),
    _published("ggml-distil-large-v3-f32", "distil-whisper/distil-large-v3-ggml",
               "0d78dd96ed9fc152325f63b53788fec3b43de031",
               "ggml-distil-large-v3.fp32.bin", 3_026_260_355,
               "1a3d507e5e2d82ce0add00cb4e4df4fe3defb82c525c836e5a706188a1a798e0",
               "distil-large-v3", QUANT_F32, ENGLISH),
    _published("ggml-distil-large-v2", "distil-whisper/distil-large-v2",
               "97d2c8f9cae1b0f6c8fc2e173495ee4cedc05843",
               "ggml-large-32-2.en.bin", 1_519_111_363,
               "2ed2bbe6c4138b3757f292b0622981bdb3d02bcac57f77095670dac85fab3cd6",
               "distil-large-v2", QUANT_F16, ENGLISH),
    _published("ggml-distil-large-v2-f32", "distil-whisper/distil-large-v2",
               "97d2c8f9cae1b0f6c8fc2e173495ee4cedc05843",
               "ggml-large-32-2.fp32.en.bin", 3_025_479_363,
               "05f8644ed040e75575ec58a18c7a692e4763f5e677a164865268f9a8e40172c2",
               "distil-large-v2", QUANT_F32, ENGLISH),
    _published("ggml-distil-medium.en", "distil-whisper/distil-medium.en",
               "6e61418885eaf4d5cc9f64e508e80ac5b4c052b7",
               "ggml-medium-32-2.en.bin", 794_018_180,
               "ad53ccb618188b210550e98cc32bf5a13188d86635e395bb11115ed275d6e7aa",
               "distil-medium.en", QUANT_F16, ENGLISH),
    _published("ggml-distil-medium.en-f32", "distil-whisper/distil-medium.en",
               "6e61418885eaf4d5cc9f64e508e80ac5b4c052b7",
               "ggml-medium-32-2.en.fp32.bin", 1_578_107_268,
               "598761592c57db1f8ad90a38b59a2e20d067fb8225bb605299e1bc68250bff21",
               "distil-medium.en", QUANT_F32, ENGLISH),
    _published("ggml-distil-small.en", "distil-whisper/distil-small.en",
               "9e4a67ca4569c30be43a3fe7fba1621e504f0093",
               "ggml-distil-small.en.bin", 336_191_657,
               "7691eb11167ab7aaf6b3e05d8266f2fd9ad89c550e433f86ac266ebdee6c970a",
               "distil-small.en", QUANT_F16, ENGLISH),
    _published("ggml-distil-small.en-f32", "distil-whisper/distil-small.en",
               "9e4a67ca4569c30be43a3fe7fba1621e504f0093",
               "ggml-distil-small.en.fp32.bin", 665_129_129,
               "5fe36f7a61b2d350672401b178a56d47f5c4983968d3926ddca059dfc8dc9e67",
               "distil-small.en", QUANT_F32, ENGLISH),
    _published("ggml-kb-whisper-tiny", "KBLab/kb-whisper-tiny",
               "76d796af43a50fa34321efa562c9b9887a187463",
               "ggml-model.bin", 77_691_730,
               "054187c95948ee0455d428db0c0d6c84d6c6157dab72e86857ced13233118b03",
               "kb-whisper-tiny", QUANT_F16, "sv", "KBLab"),
    _published("ggml-kb-whisper-tiny-q5_0", "KBLab/kb-whisper-tiny",
               "76d796af43a50fa34321efa562c9b9887a187463",
               "ggml-model-q5_0.bin", 29_875_738,
               "98d46b7d23e5528d006e8a42e29eb0cb39b44bed94e1329f10f57d1fd15c658b",
               "kb-whisper-tiny", QUANT_Q5_0, "sv", "KBLab"),
    _published("ggml-kb-whisper-base", "KBLab/kb-whisper-base",
               "1499d2d2f0c7ed545bd6f2eec85287cf8d8c8b38",
               "ggml-model.bin", 147_951_482,
               "f5e3cdb33e537eedfa2a749b5cae28c4c511873a1b13362f87dffbe07891d3fe",
               "kb-whisper-base", QUANT_F16, "sv", "KBLab"),
    _published("ggml-kb-whisper-base-q5_0", "KBLab/kb-whisper-base",
               "1499d2d2f0c7ed545bd6f2eec85287cf8d8c8b38",
               "ggml-model-q5_0.bin", 55_295_450,
               "aead29b356bca8840e72a8dc2286e2d69e6702639751a1e60cb3c8eacefec546",
               "kb-whisper-base", QUANT_Q5_0, "sv", "KBLab"),
    _published("ggml-kb-whisper-small", "KBLab/kb-whisper-small",
               "3564d61a42fc210ceaa55a22a96dd64478959c78",
               "ggml-model.bin", 487_601_984,
               "de6911330cbdc131362f7a955682b65c8a5a2394caba73e7ea821a9822efb8c6",
               "kb-whisper-small", QUANT_F16, "sv", "KBLab"),
    _published("ggml-kb-whisper-small-q5_0", "KBLab/kb-whisper-small",
               "3564d61a42fc210ceaa55a22a96dd64478959c78",
               "ggml-model-q5_0.bin", 175_209_680,
               "6768836a51abc902e420c613153e6d418c90ea2774e913274d02ab23170225b7",
               "kb-whisper-small", QUANT_Q5_0, "sv", "KBLab"),
    _published("ggml-kb-whisper-medium", "KBLab/kb-whisper-medium",
               "0abe10b9d7f75d0902656e5c06c5c4d549604dc5",
               "ggml-model.bin", 1_533_763_076,
               "1b7842bc1c3f79fb3bf043a0a3590961d625a49ef3ccbdceb00e738c5dd8b015",
               "kb-whisper-medium", QUANT_F16, "sv", "KBLab"),
    _published("ggml-kb-whisper-medium-q5_0", "KBLab/kb-whisper-medium",
               "0abe10b9d7f75d0902656e5c06c5c4d549604dc5",
               "ggml-model-q5_0.bin", 539_212_484,
               "7f8762e0ade9e0073674c0d5acae942a0b1ea98add9baa008ee89c94eaba43d0",
               "kb-whisper-medium", QUANT_Q5_0, "sv", "KBLab"),
    _published("ggml-kb-whisper-large", "KBLab/kb-whisper-large",
               "d5d5984b4d8f7c4847a8ea203f1976285fb28300",
               "ggml-model.bin", 3_095_033_483,
               "b66f2dda369a88f6c03fe37326d7cc37aa216f6f34e6fc1be686e497ba9c2f39",
               "kb-whisper-large", QUANT_F16, "sv", "KBLab"),
    _published("ggml-kb-whisper-large-q5_0", "KBLab/kb-whisper-large",
               "d5d5984b4d8f7c4847a8ea203f1976285fb28300",
               "ggml-model-q5_0.bin", 1_081_140_203,
               "6d2863812d7410322bb7d8647a5c7260761300fa946714c9ed66d22bb30bcb19",
               "kb-whisper-large", QUANT_Q5_0, "sv", "KBLab"),
    _published("ggml-ivrit-large-v3", "ivrit-ai/whisper-large-v3-ggml",
               "9ead614052ce13dfe5f8d0f6cd3e36787a9cf60c",
               "ggml-model.bin", 3_095_033_483,
               "09e66ec67b2e00c6933afab6684cbf78fe023e8ad153c1848f62000e4335a07f",
               "ivrit-large-v3", QUANT_F16, "he", "ivrit.ai"),
    _published("ggml-ivrit-large-v3-turbo", "ivrit-ai/whisper-large-v3-turbo-ggml",
               "2130c78e4a9cb4914cc4df91a1c3031407789705",
               "ggml-model.bin", 1_624_555_275,
               "c8090411113357097bfafc2b8e228ec1639fa7f5fe4ecb5d054ac0ccef8641b1",
               "ivrit-large-v3-turbo", QUANT_F16, "he", "ivrit.ai"),
    _published("ggml-ivrit-yi-large-v3", "ivrit-ai/yi-whisper-large-v3-ggml",
               "296eb0be71d79ec35da5b0f69051ae5cd071dc0e",
               "ggml-model.bin", 3_095_033_483,
               "4081c7105d96dfe989f65c0c176dbafa26fc557eef80acf2d1bf7cc26d1f7350",
               "ivrit-yi-large-v3", QUANT_F16, "yi", "ivrit.ai"),
    _published("ggml-ivrit-yi-large-v3-turbo", "ivrit-ai/yi-whisper-large-v3-turbo-ggml",
               "fc7dfcd52abe9f2b1fe86a2ab89269b0e5c8a908",
               "ggml-model.bin", 1_624_555_275,
               "a2094962a33f48ce1fc59ab6f34ca9bb4408443bf8a86361b6b1775aaa4bc1f3",
               "ivrit-yi-large-v3-turbo", QUANT_F16, "yi", "ivrit.ai"),
    _published("ggml-kotoba-whisper-v2.0", "kotoba-tech/kotoba-whisper-v2.0-ggml",
               "e3a0cf6a62b95911703cfb97d819292e058f12c3",
               "ggml-kotoba-whisper-v2.0.bin", 1_519_521_155,
               "eff70a8a236e731abba774ba71e1f6d0fce53302137208c32207e694e0bf4546",
               "kotoba-whisper-v2.0", QUANT_F16, "ja", "Kotoba Technologies"),
    _published("ggml-kotoba-whisper-v2.0-q5_0", "kotoba-tech/kotoba-whisper-v2.0-ggml",
               "e3a0cf6a62b95911703cfb97d819292e058f12c3",
               "ggml-kotoba-whisper-v2.0-q5_0.bin", 537_819_875,
               "4a3b92192b5d3578ff854a5876213e2e27af0c2d357492c2d14271e82c303658",
               "kotoba-whisper-v2.0", QUANT_Q5_0, "ja", "Kotoba Technologies"),
    _published("ggml-kotoba-whisper-v1.0", "kotoba-tech/kotoba-whisper-v1.0-ggml",
               "bc0fb8704ab1108e06e3eaedeca1bf458ddbcd11",
               "ggml-kotoba-whisper-v1.0.bin", 1_519_521_155,
               "78225aa1c745e03d033937a52d488b72b754cb1acc8531193a9f2a3a43f5fb7f",
               "kotoba-whisper-v1.0", QUANT_F16, "ja", "Kotoba Technologies"),
    _published("ggml-kotoba-whisper-v1.0-q5_0", "kotoba-tech/kotoba-whisper-v1.0-ggml",
               "bc0fb8704ab1108e06e3eaedeca1bf458ddbcd11",
               "ggml-kotoba-whisper-v1.0-q5_0.bin", 537_819_875,
               "8561df79ce6e2492cd532650463ac4045ad01e5134f9b88014a8ffee85ab9f24",
               "kotoba-whisper-v1.0", QUANT_Q5_0, "ja", "Kotoba Technologies"),
)

# The voice-activity model whisper-cli's `--vad` loads. Two are published at
# the pinned revision, 885,098 bytes each: silero v5.1.2 and v6.2.0. v6.2.0 is
# Silero's newer release, and nothing measured here prefers v5.1.2: at the
# same size they cost the same, so the newer one wins by default. That it
# loads in release b4938 is unverified (see whisper_cpp_backend: a VAD that
# fails to load costs the filter, never the transcription, and the result
# says so) — and if a real run disagrees, swapping is this one row.
VAD_MODEL = GgmlFile(
    id="ggml-silero-v6.2.0",
    repo=VAD_REPO,
    revision=VAD_REVISION,
    filename="ggml-silero-v6.2.0.bin",
    size_bytes=885_098,
    sha256="2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987",
)


def _memory_twin(model):
    """The faster-whisper entry whose memory minimums this file plans with.

    The same model's: `base_model` is its model_catalog id, and every base
    model here has one. Not a measurement of whisper.cpp — none was made — but
    an upper bound in the safe direction: those minimums cover the model at
    the precision it is loaded in plus its working memory, and every GGML file
    of a model but an f32 one is at most as large as its f16 one, so a
    quantized file is planned with room to spare, never too little (an f32
    file adds `_full_precision_extra_mb()`). large-v3's figures stand in
    should a base model ever lack its twin.
    """
    return (model_catalog.get_model(model.base_model)
            or model_catalog.get_model(_MEMORY_STAND_INS.get(model.base_model))
            or model_catalog.get_model("large-v3"))


#: Base models with no faster-whisper twin, and the one whose memory they
#: share: kotoba-whisper-v1.0 is v2.0's architecture (distil-large-v3's).
_MEMORY_STAND_INS = {"kotoba-whisper-v1.0": "kotoba-whisper-v2.0"}

_MIB = 1024 * 1024


def _full_precision_extra_mb(model) -> int:
    """What an f32 file needs beyond its twin's figures, in MB; 0 otherwise.

    The twin's figures cover the f16 file (`_memory_twin()`), and every byte
    the f32 file adds over that f16 sibling is weight held twice as wide, in
    memory as on disk; read off the two files' own sizes and rounded up. On
    the graphics card that is device._requirement_mb()'s own rescale from
    float16 to float32. On the processor, where the twin's figure is for int8,
    it is an approximation in the same spirit as `_memory_twin()`'s, not a
    measurement. Every f32 file here has its f16 sibling.
    """
    if not model.full_precision:
        return 0
    extra_bytes = model.size_bytes - variant(model.base_model, QUANT_F16).size_bytes
    return -(-extra_bytes // _MIB)


def _order(model: GgmlFile) -> tuple[int, int, int, int]:
    return (
        SIZE_CLASSES.index(model.size_class),
        language_rank(model),
        BASE_MODELS.index(model.base_model),
        QUANTIZATIONS.index(model.quantization),
    )


def list_models() -> tuple[GgmlFile, ...]:
    """Every model file, by size class, then language (multilingual first,
    third-party last, as model_catalog.list_models()), then base model, then
    fidelity."""
    return tuple(sorted(MODELS, key=_order))


def get_model(model_id) -> GgmlFile | None:
    """The entry with this id, the voice-activity model included, or None.

    None rather than raising, as model_catalog.get_model() answers: the id
    comes from settings, where a file a later version dropped is a normal
    state.
    """
    for model in MODELS + (VAD_MODEL,):
        if model.id == model_id:
            return model
    return None


def variants_of(base_model) -> tuple[GgmlFile, ...]:
    """Every published quantization of `base_model`, most faithful first."""
    return tuple(model for model in list_models() if model.base_model == base_model)


def variant(base_model, quantization) -> GgmlFile | None:
    """The file holding `base_model` at `quantization`, or None if unpublished.

    The question part 11's quantization choice asks: "small at q5_1" is a file,
    and a combination the repository does not publish (large-v3 at q8_0) has
    to read as "not offered" rather than fall back to some other file.
    """
    for model in MODELS:
        if model.base_model == base_model and model.quantization == quantization:
            return model
    return None
