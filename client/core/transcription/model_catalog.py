"""The Whisper models WinZapp offers, as data.

Models are not shipped inside the installer — a single one of them is bigger
than the whole app — so they are downloaded from Hugging Face on demand. That
makes the catalogue a contract with a remote repository: the revisions, file
names, file sizes and the model.bin digest below were read from the Hugging
Face API on 2026-09-03 and are what the download and the "this model is
complete" check are measured against.

Three details of that contract are easy to get wrong and expensive afterwards:

* **The file list is not uniform.** The Systran tiny..medium conversions ship
  ``vocabulary.txt`` and no ``preprocessor_config.json``, while large-v3 and the
  turbo conversion ship ``vocabulary.json`` *and* ``preprocessor_config.json``.
  Assuming one shape leaves a "complete" model that CTranslate2 refuses to load,
  which is indistinguishable to the user from a corrupted download.
* **Every model is pinned to a revision.** Downloads go to
  ``.../resolve/<revision>/...`` rather than ``/main/``, so a new revision
  published upstream cannot invalidate the byte counts here or swap the weights
  under an install that already verified them. Because the revision is pinned,
  every size below is a constant, not an estimate — which is what lets
  MODEL_CORRUPTED mean "missing or the wrong size" for *every* file rather than
  only for model.bin.
* **The totals are sums, never guesses.** They used to add an approximated
  couple of megabytes for the auxiliary files, and on the turbo conversion that
  guess was 181 KB *under* the real figure — an error in the wrong direction for
  a number that feeds a "does this fit?" gate.

Not every model is OpenAI's Whisper as published. Some are trained on one
language only — the `.en` and distilled conversions on English, and the
third-party fine-tunes (KBLab's Swedish, ivrit.ai's Hebrew and Yiddish,
Kotoba's Japanese) on theirs — and those carry that `language`: such a model
cannot detect a language or transcribe another one, so a run forces its
language and says so (preferences.resolve()). The third-party ones also carry
their `origin` and `publisher`, which the picker says beside the name: their
quality and licence are the publisher's, not Whisper's. Their repositories
hold more than the conversion (model.safetensors, an onnx/ folder): only the
files listed here are ever fetched.

No user-facing text lives here, only ids and i18n keys: the size classes are
what the model picker labels "fast / balanced / accurate", and translating them
is the UI layer's job. A publisher's name is a proper name and is shown as it
is.
"""

from __future__ import annotations

from dataclasses import dataclass

# Size classes, in the order the picker presents them. These drive the
# "rápido / equilibrado / preciso" labelling, so they describe what the user
# gets, not the byte count — large-v3-turbo is smaller than large-v3 and still
# belongs with it, because its output is a large model's output.
SIZE_SMALL = "small"
SIZE_MEDIUM = "medium"
SIZE_LARGE = "large"

SIZE_CLASSES = (SIZE_SMALL, SIZE_MEDIUM, SIZE_LARGE)

SIZE_CLASS_I18N_KEYS = {
    SIZE_SMALL: "transcription_size_fast",
    SIZE_MEDIUM: "transcription_size_balanced",
    SIZE_LARGE: "transcription_size_accurate",
}

# Who published the weights. OpenAI's Whisper and its conversions (Systran's,
# deepdml's turbo, Hugging Face's distil-whisper team) are "official"; a
# fine-tune by somebody else is "third-party", named by its `publisher`.
ORIGIN_OFFICIAL = "official"
ORIGIN_THIRD_PARTY = "third_party"

ENGLISH = "en"


@dataclass(frozen=True)
class WhisperModel:
    """One downloadable CTranslate2 conversion of a Whisper model."""

    id: str
    repo: str
    # The commit the files were measured at. Everything is fetched by this sha,
    # never by branch — see the module docstring.
    revision: str
    # model.bin's digest at that revision, so an integrity check can go past
    # "the right number of bytes" for the one file where a silent corruption
    # costs a multi-gigabyte re-download to discover.
    model_bin_sha256: str
    # (name, exact bytes) for every file the model needs, in the order the
    # repository lists them. A tuple of pairs rather than a dict because the
    # catalogue is shared module state a caller must not be able to edit in
    # place; `dict(model.files)` is the lookup form.
    files: tuple[tuple[str, int], ...]
    # Pulled out of `files` for the callers that only care about the weights.
    model_bin_bytes: int
    # What the download costs, and what it leaves behind — both the exact sum of
    # `files`. They are equal today because the files are written straight into
    # the model folder (nothing is extracted, no separate blob cache is kept),
    # but the picker quotes both to the user, and a future cache layout that
    # duplicates blobs would move only one of them.
    download_bytes: int
    disk_bytes: int
    size_class: str
    # Recommended minimums, not hard requirements: roughly twice the weights,
    # which covers activations, the KV cache at beam size 5 and the CUDA
    # context. Undershooting them does not fail cleanly — CTranslate2 aborts
    # mid-transcription with an allocation error — so auto_select_model() keeps
    # its distance from them (see device.py).
    min_vram_mb: int  # float16 on the GPU
    min_ram_mb: int  # int8 on the CPU
    # The one language the model was trained on (the `.en` conversions, the
    # distilled ones, every third-party fine-tune), or None for a multilingual
    # model. Such a model cannot detect a language or transcribe another one:
    # handed Portuguese, an English one answers with confident English, which
    # a listener cannot tell from a real transcription. So a run forces this
    # language and says so, and the automatic choice never lands on one unless
    # it is the user's language (preferences.resolve()).
    language: str | None = None
    origin: str = ORIGIN_OFFICIAL
    # The third-party publisher's name, said beside the model's; "" otherwise.
    publisher: str = ""

    @property
    def english_only(self) -> bool:
        return self.language == ENGLISH

    @property
    def third_party(self) -> bool:
        return self.origin == ORIGIN_THIRD_PARTY

    def sha256_of(self, name):
        """The digest file `name` is checked against, or None when it has none.

        Only model.bin has one: it is the sole LFS file in these repositories,
        and the one where a silent corruption costs a multi-gigabyte re-download
        to discover. Asked through the entry rather than decided by model_store
        so that the whisper.cpp catalogue, whose one file is not called
        model.bin, can go through the same download and the same checks.
        """
        return self.model_bin_sha256 if name == "model.bin" else None


def _model(model_id, repo, revision, model_bin_sha256, files, size_class,
           min_vram_mb, min_ram_mb, language=None, publisher="") -> WhisperModel:
    """One catalogue entry, with everything derivable derived from `files`.

    The totals and the model.bin size are read off the file table instead of
    being restated beside it: six models times three restatements is eighteen
    chances for two numbers describing the same download to disagree.

    Every file name has to be a bare basename, and that is asserted rather than
    assumed: the model store joins these names onto a directory the user may
    point anywhere and deletes exactly them, so a nested layout
    ("snapshots/<sha>/model.bin", which is the shape these repositories use
    internally) or a ".." would have a delete reach outside the models root.
    """
    for name, _size in files:
        # Both separators, not just this platform's: the catalogue is written
        # once and read on Windows, where a name carrying either one escapes
        # the model's own directory.
        assert name and name not in (".", "..") and not set(name) & {"/", "\\"}, (
            f"{model_id}: file names must be bare basenames, got {name!r}"
        )
    total = sum(size for _name, size in files)
    return WhisperModel(
        id=model_id,
        repo=repo,
        revision=revision,
        model_bin_sha256=model_bin_sha256,
        files=files,
        model_bin_bytes=dict(files)["model.bin"],
        download_bytes=total,
        disk_bytes=total,
        size_class=size_class,
        min_vram_mb=min_vram_mb,
        min_ram_mb=min_ram_mb,
        language=language,
        origin=ORIGIN_THIRD_PARTY if publisher else ORIGIN_OFFICIAL,
        publisher=publisher,
    )


# Single source of truth. Declared in the order the repositories were verified;
# list_models() is what defines presentation order.
MODELS = (
    _model(
        "tiny",
        "Systran/faster-whisper-tiny",
        "d90ca5fe260221311c53c58e660288d3deb8d356",
        "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
        (
            ("config.json", 2_249),
            ("model.bin", 75_538_270),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
    ),
    _model(
        "base",
        "Systran/faster-whisper-base",
        "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
        "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
        (
            ("config.json", 2_309),
            ("model.bin", 145_217_532),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
    ),
    _model(
        "small",
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        (
            ("config.json", 2_370),
            ("model.bin", 483_546_902),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_MEDIUM,
        min_vram_mb=2048,
        min_ram_mb=3072,
    ),
    _model(
        "medium",
        "Systran/faster-whisper-medium",
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
        (
            ("config.json", 2_257),
            ("model.bin", 1_527_906_378),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_MEDIUM,
        min_vram_mb=4096,
        min_ram_mb=6144,
    ),
    _model(
        "large-v3",
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
        (
            ("config.json", 2_394),
            ("model.bin", 3_087_284_237),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_480_617),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
    ),
    _model(
        "large-v3-turbo",
        "deepdml/faster-whisper-large-v3-turbo-ct2",
        "4df90f75321148c3a29a9e2351b7ddf8f5b115a8",
        "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
        (
            ("config.json", 2_263),
            ("model.bin", 1_617_884_929),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_710_337),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
    ),
    # The English-only conversions, read from the Hugging Face API on
    # 2026-10-05 (pinned revision and main, twice, identical). Same tensors as
    # the multilingual model of the same size, so the same size class and the
    # same memory minimums; a different tokenizer, which is why every file
    # size differs from its multilingual sibling's.
    _model(
        "tiny.en",
        "Systran/faster-whisper-tiny.en",
        "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
        "1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a",
        (
            ("config.json", 2_317),
            ("model.bin", 75_537_502),
            ("tokenizer.json", 2_128_466),
            ("vocabulary.txt", 422_309),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
        language=ENGLISH,
    ),
    _model(
        "base.en",
        "Systran/faster-whisper-base.en",
        "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
        "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef",
        (
            ("config.json", 2_227),
            ("model.bin", 145_216_508),
            ("tokenizer.json", 2_128_466),
            ("vocabulary.txt", 422_309),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
        language=ENGLISH,
    ),
    _model(
        "small.en",
        "Systran/faster-whisper-small.en",
        "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
        "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
        (
            ("config.json", 2_657),
            ("model.bin", 483_545_366),
            ("tokenizer.json", 2_128_466),
            ("vocabulary.txt", 422_309),
        ),
        SIZE_MEDIUM,
        min_vram_mb=2048,
        min_ram_mb=3072,
        language=ENGLISH,
    ),
    _model(
        "medium.en",
        "Systran/faster-whisper-medium.en",
        "a29b04bd15381511a9af671baec01072039215e3",
        "11b220779aea4c6f3ce9d2549c8a95ea869ed84066864b999531ef53e594fe5b",
        (
            ("config.json", 2_643),
            ("model.bin", 1_527_904_330),
            ("tokenizer.json", 2_128_466),
            ("vocabulary.txt", 422_309),
        ),
        SIZE_MEDIUM,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language=ENGLISH,
    ),
    # The other official Systran conversions, read from the Hugging Face API
    # on 2026-10-05 (pinned revision and main, twice, identical), offered so
    # that every official model is: large-v1 and large-v2 (multilingual, the
    # same architecture and memory as large-v3, and the same layout as the
    # small ones), and the three distilled models — English-only all three,
    # distil-large-v3 included although its name does not say so (its model
    # card lists "en" alone). The distilled ones ship vocabulary.json and
    # preprocessor_config.json, like large-v3; their memory minimums follow
    # the "about twice the weights" rule of the entries above, rounded up.
    _model(
        "large-v1",
        "Systran/faster-whisper-large-v1",
        "b07c8d4be0be90092aa01a29c975077acb8d15c9",
        "a3cce8081a5414206ab09a80aa410ebf9965feef52adafeead13f4a83398b1d1",
        (
            ("config.json", 2_352),
            ("model.bin", 3_086_912_962),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
    ),
    _model(
        "large-v2",
        "Systran/faster-whisper-large-v2",
        "f0fe81560cb8b68660e564f55dd99207059c092e",
        "bf2a9746382e1aa7ffff6b3a0d137ed9edbd9670c3b87e5d35f5e85e70d0333a",
        (
            ("config.json", 2_796),
            ("model.bin", 3_086_912_962),
            ("tokenizer.json", 2_203_239),
            ("vocabulary.txt", 459_861),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
    ),
    _model(
        "distil-small.en",
        "Systran/faster-distil-whisper-small.en",
        "ef77d90526ccd62cde3808ee70626a01e5cf83e4",
        "1187de3982cdcf962a2fb8f797e429fb4651b875b18fe9ce50b58b52fc9072b7",
        (
            ("config.json", 2_812),
            ("model.bin", 332_308_257),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 2_405_466),
            ("vocabulary.json", 825_480),
        ),
        SIZE_SMALL,
        min_vram_mb=2048,
        min_ram_mb=3072,
        language=ENGLISH,
    ),
    _model(
        "distil-medium.en",
        "Systran/faster-distil-whisper-medium.en",
        "80ddfce281f77766d8943d63109199fc8145dfa5",
        "d4cb75d823dcd2647191064da76f026774c06c036908f38456165368d0e2d66a",
        (
            ("config.json", 2_574),
            ("model.bin", 788_826_555),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 2_405_678),
            ("vocabulary.json", 825_480),
        ),
        SIZE_MEDIUM,
        min_vram_mb=3072,
        min_ram_mb=4096,
        language=ENGLISH,
    ),
    _model(
        "distil-large-v3",
        "Systran/faster-distil-whisper-large-v3",
        "c3058b475261292e64a0412df1d2681c06260fab",
        "b79368e19b6623813609431a6e5ee309a71506701ebc49fd7820e692dec7c5f5",
        (
            ("config.json", 2_690),
            ("model.bin", 1_512_927_867),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_480_617),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language=ENGLISH,
    ),
    # distil-large-v3.5 is official (Hugging Face's distil-whisper team, who
    # published distil-large-v3 too) and English-only, like its predecessor.
    _model(
        "distil-large-v3.5",
        "distil-whisper/distil-large-v3.5-ct2",
        "9793ccc07920e0f830e1dba0343efcdf0ef8c903",
        "c58b88b8585ffcd2135fddaaf421ce72cb223b32edea70d156aed1dea319a119",
        (
            ("config.json", 2_690),
            ("model.bin", 1_512_927_867),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_480_645),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language=ENGLISH,
    ),
    # distil-large-v2, the last official conversion missing, read from the
    # Hugging Face API on 2026-10-05 (`?blobs=true` and blob by blob, twice,
    # identical). English-only and distil-large-v3's layout and size, so the
    # same size class and memory minimums.
    _model(
        "distil-large-v2",
        "Systran/faster-distil-whisper-large-v2",
        "fe9b404fc56de3f7c38606ef9ba6fd83526d05e4",
        "b415593cd109c0418d42ecb106c40ae45c8229cb4090e67db12243901e071ab3",
        (
            ("config.json", 2_657),
            ("model.bin", 1_512_556_667),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 2_481_187),
            ("vocabulary.json", 1_068_103),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language=ENGLISH,
    ),
    # Third-party fine-tunes of Whisper for one language each, read from the
    # Hugging Face API at the pinned revision with `?blobs=true` and then file
    # by file (2026-10-05; the `tree` listing swapped rows for KBLab, so these
    # are the blob figures). Offered because the maintainers asked for them,
    # and said to be third-party with their language wherever they are named.
    # Only the CTranslate2 files below are fetched: the KBLab repositories
    # also hold model.safetensors and an onnx/ folder, never wanted here.
    # Memory as for the official model each one was trained from.
    # kotoba-whisper-bilingual-v1.0-faster is deliberately absent: its
    # repository has no tokenizer.json, and faster-whisper would fall back to
    # openai/whisper-tiny's pre-v3 vocabulary for a v3 model.
    _model(
        "kb-whisper-tiny",
        "KBLab/kb-whisper-tiny",
        "76d796af43a50fa34321efa562c9b9887a187463",
        "6edbc6036ceb79f12c30c5c5c2290383eac7a0bfec0be3163c480e79b26b16b9",
        (
            ("config.json", 3_562),
            ("model.bin", 75_538_384),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 3_931_232),
            ("vocabulary.json", 1_068_103),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
        language="sv",
        publisher="KBLab",
    ),
    _model(
        "kb-whisper-base",
        "KBLab/kb-whisper-base",
        "1499d2d2f0c7ed545bd6f2eec85287cf8d8c8b38",
        "fa942ec92ad7747aec2e9ea8c57ad8971a3695f3c9ff440018a3667bb818a5c4",
        (
            ("config.json", 3_622),
            ("model.bin", 145_217_646),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 3_931_232),
            ("vocabulary.json", 1_068_103),
        ),
        SIZE_SMALL,
        min_vram_mb=1024,
        min_ram_mb=2048,
        language="sv",
        publisher="KBLab",
    ),
    _model(
        "kb-whisper-small",
        "KBLab/kb-whisper-small",
        "3564d61a42fc210ceaa55a22a96dd64478959c78",
        "58bf16e6878108f898c4db7983d0f4ec01c4891500f7a2b3a2c9ce98b3c0029d",
        (
            ("config.json", 3_690),
            ("model.bin", 483_547_016),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 3_931_232),
            ("vocabulary.json", 1_068_103),
        ),
        SIZE_MEDIUM,
        min_vram_mb=2048,
        min_ram_mb=3072,
        language="sv",
        publisher="KBLab",
    ),
    _model(
        "kb-whisper-medium",
        "KBLab/kb-whisper-medium",
        "0abe10b9d7f75d0902656e5c06c5c4d549604dc5",
        "4a4a32952026bcfa0bcfaa76b0b006f232ffba6a8f5bccbcb12e4a1153a40494",
        (
            ("config.json", 3_592),
            ("model.bin", 1_527_906_492),
            ("preprocessor_config.json", 339),
            ("tokenizer.json", 3_931_232),
            ("vocabulary.json", 1_068_103),
        ),
        SIZE_MEDIUM,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language="sv",
        publisher="KBLab",
    ),
    _model(
        "kb-whisper-large",
        "KBLab/kb-whisper-large",
        "d5d5984b4d8f7c4847a8ea203f1976285fb28300",
        "69ed56887f68417f651d50fd5f225c60dfc0f9515bef85bb0f1404825c6f01de",
        (
            ("config.json", 3_717),
            ("model.bin", 3_087_284_276),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 3_931_383),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
        language="sv",
        publisher="KBLab",
    ),
    _model(
        "ivrit-large-v3",
        "ivrit-ai/whisper-large-v3-ct2",
        "e9ed4a4a98d761b0f617d668303de2c514236c66",
        "765965efd777190f76e8b337520056f00d68e48bb99b2f95d28670b2364a02ce",
        (
            ("config.json", 1_536),
            ("model.bin", 3_087_284_276),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_480_617),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
        language="he",
        publisher="ivrit.ai",
    ),
    _model(
        "ivrit-large-v3-turbo",
        "ivrit-ai/whisper-large-v3-turbo-ct2",
        "72ad623a37947395efcc3933132353790e5a12f5",
        "db2a2265aa012c16c7db9edda3d699c99f984efdd3f2e22a72a8ce7e9720f3a2",
        (
            ("config.json", 1_405),
            ("model.bin", 1_617_884_968),
            ("preprocessor_config.json", 357),
            ("tokenizer.json", 2_710_337),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language="he",
        publisher="ivrit.ai",
    ),
    _model(
        "ivrit-yi-large-v3",
        "ivrit-ai/yi-whisper-large-v3-ct2",
        "58ad8942662665e762008c268ade5022e8dcd198",
        "1d3afba86e7977617945f39be197b6eb15f24960d621be5a1743ad639f7f476d",
        (
            ("config.json", 1_536),
            ("model.bin", 3_087_284_237),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_480_617),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=6144,
        min_ram_mb=8192,
        language="yi",
        publisher="ivrit.ai",
    ),
    _model(
        "ivrit-yi-large-v3-turbo",
        "ivrit-ai/yi-whisper-large-v3-turbo-ct2",
        "cddb73c5ea83e4354a3926682a59c3b063f5a98e",
        "cf157e277a11895a44bdf6479c324408441613ae9b87871d69cb0a9bc01df835",
        (
            ("config.json", 1_405),
            ("model.bin", 1_617_884_929),
            ("preprocessor_config.json", 357),
            ("tokenizer.json", 2_710_337),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language="yi",
        publisher="ivrit.ai",
    ),
    _model(
        "kotoba-whisper-v2.0",
        "kotoba-tech/kotoba-whisper-v2.0-faster",
        "f44edd35eaeb2274e85ac7b31fb2c6f59ff1c4bc",
        "60d2bc2e33de9d43f2745be09caefe1161acab670f6796d4a750d8d848382b36",
        (
            ("config.json", 2_394),
            ("model.bin", 1_512_927_867),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2_481_381),
            ("vocabulary.json", 1_068_114),
        ),
        SIZE_LARGE,
        min_vram_mb=4096,
        min_ram_mb=6144,
        language="ja",
        publisher="Kotoba Technologies",
    ),
)


def language_rank(model) -> int:
    """Where a model goes within its size class: multilingual first, then the
    official single-language ones, then the third-party fine-tunes."""
    if model.third_party:
        return 2
    return 1 if model.language else 0


def _order(model: WhisperModel) -> tuple[int, int, int]:
    return (SIZE_CLASSES.index(model.size_class), language_rank(model), model.download_bytes)


def list_models() -> tuple[WhisperModel, ...]:
    """Every model, cheapest first.

    Ordered by size class and then by download size, so the two large models
    are listed turbo-first: it is the one to reach for when large-v3 is too
    much, and putting it after would bury it under the 3 GB entry. Within a
    size class the single-language models come after the multilingual ones,
    and the third-party ones last: a tiny.en is a few hundred kilobytes
    smaller than tiny, and by size alone it would be the first entry a user
    arrowing through the list hears.
    """
    return tuple(sorted(MODELS, key=_order))


def get_model(model_id) -> WhisperModel | None:
    """The model with this id, or None.

    Deliberately not raising: the id comes from settings, where a model that
    was renamed or removed between versions is a normal state, not a fault.
    """
    for model in MODELS:
        if model.id == model_id:
            return model
    return None


def total_bytes(model_id) -> int | None:
    """Bytes a fresh install of `model_id` costs, or None for an unknown id.

    None rather than 0, even though 0 would spare the caller a check. The
    caller that matters here is the free-space gate, and an unknown id is
    exactly what a settings file naming a model some later version dropped
    looks like: answering 0 tells that gate "it fits" and starts a download of
    something that does not exist.
    """
    model = get_model(model_id)
    return model.download_bytes if model else None


def size_class_i18n_key(size_class) -> str | None:
    """The i18n key labelling a size class, or None for an unknown one."""
    return SIZE_CLASS_I18N_KEYS.get(size_class)
