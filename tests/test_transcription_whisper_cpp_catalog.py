"""The whisper.cpp GGML catalogue, and its files going through model_store.

Two things are pinned here. The catalogue is a contract with a remote
repository, read off its API by hand: a mistyped digest, a duplicated file
name or a quantization label that disagrees with its file is invisible until a
user's download fails its check — or, worse, until two entries share a folder
and removing one deletes the other. So its invariants are asserted on the data
itself.

And the store is model_store's code, not a copy: a GgmlFile has to survive the
same download, verify, repair and remove a faster-whisper model does, while
those keep behaving exactly as before for faster-whisper (its own file pins
that). A synthetic GGML entry of a few bytes stands in for the real ones here.

The tests that reach Hugging Face — every GGML URL and the VAD model's
serving exactly the catalogued size, and the two smallest files hashing to
their digests — are marked `network` and skipped unless
WINZAPP_RUN_NETWORK_TESTS is set, like the faster-whisper catalogue's.
"""

import hashlib
import os
import re

import pytest

from core import tls_trust
from core.transcription import (
    device,
    errors,
    model_catalog,
    model_store,
    preferences,
    whisper_cpp_catalog,
    whisper_cpp_store,
)

_NETWORK_OPT_IN_ENV = "WINZAPP_RUN_NETWORK_TESTS"
_ALL_FILES = whisper_cpp_catalog.MODELS + (whisper_cpp_catalog.VAD_MODEL,)
#: The entries of ggerganov's repository, named `ggml-<model>[-<quant>].bin`.
_GGERGANOV = tuple(
    entry for entry in whisper_cpp_catalog.MODELS
    if entry.repo == whisper_cpp_catalog.MODELS_REPO
)
#: The rest: other publishers' repositories, each file name carried as is.
_PUBLISHED_ELSEWHERE = tuple(
    entry for entry in whisper_cpp_catalog.MODELS if entry not in _GGERGANOV
)


# ── The catalogue ────────────────────────────────────────────────────────────


class TestTheCatalogueIsWhatTheRepositoryPublishes:
    def test_every_digest_is_64_lowercase_hex(self):
        for entry in _ALL_FILES:
            assert re.fullmatch(r"[0-9a-f]{64}", entry.sha256), entry.id

    def test_every_revision_is_a_full_commit_sha(self):
        for entry in _ALL_FILES:
            assert re.fullmatch(r"[0-9a-f]{40}", entry.revision), entry.id

    def test_file_names_ids_and_digests_are_unique(self):
        for field in ("id", "sha256"):
            values = [getattr(entry, field) for entry in _ALL_FILES]
            assert len(values) == len(set(values)), field
        # A file name is unique within its repository only: every KBLab size
        # publishes a `ggml-model.bin`. The id, which names the folder, is
        # what keeps them apart on disk.
        locations = [(entry.repo, entry.filename) for entry in _ALL_FILES]
        assert len(locations) == len(set(locations))

    def test_ids_never_collide_with_a_faster_whisper_id(self):
        # Both catalogues name folders under a models root; a shared name
        # would let removing one model delete the other's folder.
        theirs = {model.id for model in model_catalog.MODELS}
        assert not theirs & {entry.id for entry in _ALL_FILES}

    def test_sizes_are_positive_and_one_file_per_entry(self):
        for entry in _ALL_FILES:
            assert entry.size_bytes > 0
            assert entry.files == ((entry.filename, entry.size_bytes),)
            assert entry.download_bytes == entry.disk_bytes == entry.size_bytes

    def test_the_label_agrees_with_the_file_name(self):
        for entry in _GGERGANOV:
            if entry.quantization == whisper_cpp_catalog.QUANT_F16:
                expected = f"ggml-{entry.base_model}.bin"
            else:
                expected = f"ggml-{entry.base_model}-{entry.quantization}.bin"
            assert entry.filename == expected
            assert entry.id == expected[:-len(".bin")]

    def test_only_the_published_variants_are_offered(self):
        published = {
            base: tuple(entry.quantization for entry in whisper_cpp_catalog.variants_of(base))
            for base in whisper_cpp_catalog.BASE_MODELS
        }
        assert published == {
            "tiny": ("f16", "q8_0", "q5_1"),
            "base": ("f16", "q8_0", "q5_1"),
            "small": ("f16", "q8_0", "q5_1"),
            "medium": ("f16", "q8_0", "q5_0"),
            "large-v3-turbo": ("f16", "q8_0", "q5_0"),
            "large-v1": ("f16",),
            "large-v2": ("f16", "q8_0", "q5_0"),
            "large-v3": ("f16", "q5_0"),
            "tiny.en": ("f16", "q8_0", "q5_1"),
            "base.en": ("f16", "q8_0", "q5_1"),
            "small.en": ("f16", "q8_0", "q5_1"),
            "medium.en": ("f16", "q8_0", "q5_0"),
            "distil-small.en": ("f32", "f16"),
            "distil-medium.en": ("f32", "f16"),
            "distil-large-v2": ("f32", "f16"),
            "distil-large-v3": ("f32", "f16"),
            "distil-large-v3.5": ("f16",),
            "kb-whisper-tiny": ("f16", "q5_0"),
            "kb-whisper-base": ("f16", "q5_0"),
            "kb-whisper-small": ("f16", "q5_0"),
            "kb-whisper-medium": ("f16", "q5_0"),
            "kb-whisper-large": ("f16", "q5_0"),
            "ivrit-large-v3-turbo": ("f16",),
            "ivrit-large-v3": ("f16",),
            "ivrit-yi-large-v3-turbo": ("f16",),
            "ivrit-yi-large-v3": ("f16",),
            "kotoba-whisper-v2.0": ("f16", "q5_0"),
            "kotoba-whisper-v1.0": ("f16", "q5_0"),
        }

    def test_the_english_only_models_are_offered_and_say_so(self):
        # Offered since 2026-10-05, and marked: a run forces "en" for them
        # instead of letting a Portuguese note come back as confident English.
        english = [entry for entry in _GGERGANOV if ".en" in entry.filename]
        assert len(english) == 12
        for entry in english:
            assert entry.english_only and entry.language == "en", entry.id
            assert not entry.third_party
        multilingual = [entry for entry in _GGERGANOV if ".en" not in entry.filename]
        assert all(entry.language is None for entry in multilingual)

    def test_every_third_party_entry_says_its_language_and_its_publisher(self):
        third_party = [entry for entry in whisper_cpp_catalog.MODELS if entry.third_party]
        assert {entry.publisher for entry in third_party} == {
            "KBLab", "ivrit.ai", "Kotoba Technologies",
        }
        for entry in third_party:
            assert entry.origin == model_catalog.ORIGIN_THIRD_PARTY
            assert entry.language in preferences.LANGUAGE_NAMES, entry.id
        assert {entry.language for entry in third_party} == {"sv", "he", "yi", "ja"}
        # Every official single-language model is an English one.
        for entry in whisper_cpp_catalog.MODELS:
            if not entry.third_party:
                assert entry.publisher == ""
                assert entry.language in (None, "en"), entry.id

    def test_the_other_repositories_are_pinned_file_by_file(self):
        pinned = {
            (entry.repo, entry.revision) for entry in _PUBLISHED_ELSEWHERE
        }
        assert pinned == {
            ("distil-whisper/distil-large-v3.5-ggml",
             "960ecb5c2ecfba3ebb9ebe485c1032ec266cf436"),
            ("distil-whisper/distil-large-v3-ggml",
             "0d78dd96ed9fc152325f63b53788fec3b43de031"),
            ("distil-whisper/distil-large-v2", "97d2c8f9cae1b0f6c8fc2e173495ee4cedc05843"),
            ("distil-whisper/distil-medium.en", "6e61418885eaf4d5cc9f64e508e80ac5b4c052b7"),
            ("distil-whisper/distil-small.en", "9e4a67ca4569c30be43a3fe7fba1621e504f0093"),
            ("KBLab/kb-whisper-tiny", "76d796af43a50fa34321efa562c9b9887a187463"),
            ("KBLab/kb-whisper-base", "1499d2d2f0c7ed545bd6f2eec85287cf8d8c8b38"),
            ("KBLab/kb-whisper-small", "3564d61a42fc210ceaa55a22a96dd64478959c78"),
            ("KBLab/kb-whisper-medium", "0abe10b9d7f75d0902656e5c06c5c4d549604dc5"),
            ("KBLab/kb-whisper-large", "d5d5984b4d8f7c4847a8ea203f1976285fb28300"),
            ("ivrit-ai/whisper-large-v3-ggml", "9ead614052ce13dfe5f8d0f6cd3e36787a9cf60c"),
            ("ivrit-ai/whisper-large-v3-turbo-ggml",
             "2130c78e4a9cb4914cc4df91a1c3031407789705"),
            ("ivrit-ai/yi-whisper-large-v3-ggml", "296eb0be71d79ec35da5b0f69051ae5cd071dc0e"),
            ("ivrit-ai/yi-whisper-large-v3-turbo-ggml",
             "fc7dfcd52abe9f2b1fe86a2ab89269b0e5c8a908"),
            ("kotoba-tech/kotoba-whisper-v2.0-ggml", "e3a0cf6a62b95911703cfb97d819292e058f12c3"),
            ("kotoba-tech/kotoba-whisper-v1.0-ggml", "bc0fb8704ab1108e06e3eaedeca1bf458ddbcd11"),
        }
        # Their own names, carried explicitly — and only the GGML files: the
        # same repositories hold the PyTorch weights too.
        for entry in _PUBLISHED_ELSEWHERE:
            assert entry.filename.startswith("ggml-") and entry.filename.endswith(".bin")
            assert entry.id.startswith("ggml-"), entry.id
        kb = whisper_cpp_catalog.variant("kb-whisper-small", "q5_0")
        assert (kb.filename, kb.size_bytes) == ("ggml-model-q5_0.bin", 175_209_680)
        assert kb.sha256 == "6768836a51abc902e420c613153e6d418c90ea2774e913274d02ab23170225b7"
        medium = whisper_cpp_catalog.variant("distil-medium.en", "f32")
        assert (medium.id, medium.filename, medium.size_bytes) == (
            "ggml-distil-medium.en-f32", "ggml-medium-32-2.en.fp32.bin", 1_578_107_268)
        assert medium.sha256 == (
            "598761592c57db1f8ad90a38b59a2e20d067fb8225bb605299e1bc68250bff21")

    def test_the_distil_whisper_repositories_give_only_their_ggml_files(self):
        # They hold pytorch_model*.bin and original-model*.bin beside the GGML
        # ones: a download of those would be gigabytes whisper.cpp cannot load.
        distil = [entry for entry in _PUBLISHED_ELSEWHERE
                  if entry.repo.startswith("distil-whisper/")]
        assert len(distil) == 9
        for entry in distil:
            assert entry.filename.startswith("ggml-"), entry.id
            assert not entry.filename.startswith(("pytorch_model", "original-model"))

    def test_full_precision_is_the_distil_whisper_teams_beside_each_f16_file(self):
        full = [entry for entry in whisper_cpp_catalog.MODELS
                if entry.quantization == whisper_cpp_catalog.QUANT_F32]
        assert {entry.base_model for entry in full} == {
            "distil-small.en", "distil-medium.en", "distil-large-v2", "distil-large-v3",
        }
        for entry in full:
            half = whisper_cpp_catalog.variant(entry.base_model, "f16")
            assert (half.repo, half.revision) == (entry.repo, entry.revision), entry.id
            assert entry.id == f"{half.id}-f32"
            assert ".fp32." in entry.filename and ".fp32." not in half.filename
            assert entry.bits == 32 and half.bits == 16
            # Twice the bytes per weight, and nothing else of any size.
            assert 1.9 < entry.size_bytes / half.size_bytes < 2.1, entry.id
            assert (entry.language, entry.origin, entry.publisher) == ("en", "official", "")

    def test_pinned_to_the_revisions_that_were_measured(self):
        for entry in _GGERGANOV:
            assert entry.repo == "ggerganov/whisper.cpp"
            assert entry.revision == "5359861c739e955e79d9a303bcbc70fb988958b1"
        vad = whisper_cpp_catalog.VAD_MODEL
        assert (vad.repo, vad.revision) == (
            "ggml-org/whisper-vad", "9ffd54a1e1ee413ddf265af9913beaf518d1639b"
        )
        assert vad.filename == "ggml-silero-v6.2.0.bin"

    def test_shared_models_keep_the_faster_whisper_size_class(self):
        # "Fast / balanced / accurate" must not change with the backend.
        for model in model_catalog.MODELS:
            for entry in whisper_cpp_catalog.variants_of(model.id):
                assert entry.size_class == model.size_class, entry.id

    def test_every_faster_whisper_model_has_a_ggml_counterpart(self):
        # The distilled ones too: not in ggerganov's repository, but in the
        # distil-whisper team's own.
        for model in model_catalog.MODELS:
            assert whisper_cpp_catalog.variant(model.id, "f16") is not None, model.id

    def test_the_picker_lists_the_english_only_models_as_faster_whisper_does(self):
        def english(models, name):
            seen = []
            for model in models:
                if model.language == "en" and name(model) not in seen:
                    seen.append(name(model))
            return seen

        assert english(whisper_cpp_catalog.list_models(), lambda e: e.base_model) == english(
            model_catalog.list_models(), lambda m: m.id)

    def test_a_file_plans_its_twins_memory_and_an_f32_one_its_wider_weights_too(self):
        for entry in whisper_cpp_catalog.MODELS:
            twin = model_catalog.get_model(entry.base_model) or model_catalog.get_model(
                "kotoba-whisper-v2.0")
            figures = (entry.min_vram_mb, entry.min_ram_mb)
            if entry.quantization != whisper_cpp_catalog.QUANT_F32:
                assert figures == (twin.min_vram_mb, twin.min_ram_mb), entry.id
                continue
            half = whisper_cpp_catalog.variant(entry.base_model, "f16")
            extra = -(-(entry.size_bytes - half.size_bytes) // (1024 * 1024))
            assert figures == (half.min_vram_mb + extra, half.min_ram_mb + extra), entry.id
        large = whisper_cpp_catalog.get_model("ggml-distil-large-v3-f32")
        assert (large.min_vram_mb, large.min_ram_mb) == (5533, 7581)

    def test_a_ggml_file_has_the_language_and_origin_of_its_faster_whisper_twin(self):
        for entry in whisper_cpp_catalog.MODELS:
            twin = model_catalog.get_model(entry.base_model)
            if twin is None:
                continue
            assert (entry.language, entry.origin, entry.publisher) == (
                twin.language, twin.origin, twin.publisher
            ), entry.id

    def test_each_file_digests_itself_and_nothing_else(self):
        entry = whisper_cpp_catalog.get_model("ggml-small-q5_1")
        assert entry.sha256_of("ggml-small-q5_1.bin") == entry.sha256
        assert entry.sha256_of("model.bin") is None


class TestLookups:
    def test_a_quantization_choice_is_a_file(self):
        entry = whisper_cpp_catalog.variant("large-v3-turbo", "q5_0")
        assert entry.filename == "ggml-large-v3-turbo-q5_0.bin"
        assert entry.size_bytes == 574_041_195

    def test_an_unpublished_combination_is_none_not_another_file(self):
        assert whisper_cpp_catalog.variant("large-v3", "q8_0") is None
        assert whisper_cpp_catalog.variant("large-v1", "q5_0") is None
        assert whisper_cpp_catalog.variant("nope", "f16") is None

    def test_variants_come_most_faithful_first(self):
        order = whisper_cpp_catalog.QUANTIZATIONS
        for base in whisper_cpp_catalog.BASE_MODELS:
            quants = [entry.quantization for entry in whisper_cpp_catalog.variants_of(base)]
            assert quants == sorted(quants, key=order.index)

    def test_the_list_runs_from_fast_to_accurate(self):
        classes = [entry.size_class for entry in whisper_cpp_catalog.list_models()]
        assert classes == sorted(classes, key=model_catalog.SIZE_CLASSES.index)
        assert len(whisper_cpp_catalog.list_models()) == len(whisper_cpp_catalog.MODELS)

    @pytest.mark.parametrize("budget_mb", [3_000, 6_000, 9_500, 1_000_000])
    def test_language_detection_never_picks_an_english_only_file(self, budget_mb):
        probe = device.HardwareProbe(total_ram_mb=budget_mb, available_ram_mb=budget_mb)
        chosen = device.auto_select_model(
            probe, device.DEVICE_CPU, (), catalog=whisper_cpp_catalog.list_models())
        assert whisper_cpp_catalog.get_model(chosen).language is None, chosen

    @pytest.mark.parametrize("device_id", [device.DEVICE_CPU, device.DEVICE_CUDA])
    @pytest.mark.parametrize(
        "budget_mb", [3_000, 3_500, 4_300, 5_000, 6_100, 7_000, 9_500, 1_000_000])
    def test_the_automatic_choice_never_picks_a_32_bit_file(self, device_id, budget_mb):
        if device_id == device.DEVICE_CPU:
            probe = device.HardwareProbe(total_ram_mb=budget_mb, available_ram_mb=budget_mb)
        else:
            probe = device.HardwareProbe(
                cuda_available=True, cuda_device_count=1, compute_capability=(8, 6),
                total_vram_mb=budget_mb, free_vram_mb=budget_mb)
        chosen = device.auto_select_model(
            probe, device_id, (), catalog=whisper_cpp_catalog.list_models(), language="en")
        assert not whisper_cpp_catalog.get_model(chosen).full_precision, chosen
        pinned = {(device.DEVICE_CPU, 9_500): "ggml-large-v3-turbo",
                  (device.DEVICE_CPU, 4_300): "ggml-small.en",
                  (device.DEVICE_CPU, 1_000_000): "ggml-large-v3",
                  (device.DEVICE_CUDA, 1_000_000): "ggml-large-v3"}
        if (device_id, budget_mb) in pinned:
            assert chosen == pinned[(device_id, budget_mb)]

    def test_get_model_finds_the_vad_model_and_answers_none_for_the_unknown(self):
        assert whisper_cpp_catalog.get_model("ggml-silero-v6.2.0") is whisper_cpp_catalog.VAD_MODEL
        assert whisper_cpp_catalog.get_model("small") is None
        assert whisper_cpp_catalog.get_model(None) is None


# ── The store: model_store's code, with a GGML entry ─────────────────────────


def _synthetic(monkeypatch, data=b"G" * 5000, vad=b"V" * 300):
    """A one-entry GGML catalogue and VAD model of a few bytes."""
    entry = whisper_cpp_catalog.GgmlFile(
        id="ggml-alpha-q5_1",
        repo="example-org/whisper.cpp",
        revision="a" * 40,
        filename="ggml-alpha-q5_1.bin",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        base_model="alpha",
        quantization="q5_1",
        size_class=model_catalog.SIZE_SMALL,
    )
    vad_entry = whisper_cpp_catalog.GgmlFile(
        id="ggml-vad",
        repo="example-org/whisper-vad",
        revision="b" * 40,
        filename="ggml-vad.bin",
        size_bytes=len(vad),
        sha256=hashlib.sha256(vad).hexdigest(),
    )
    monkeypatch.setattr(whisper_cpp_catalog, "MODELS", (entry,))
    monkeypatch.setattr(whisper_cpp_catalog, "_BASE_MODELS", (("alpha", model_catalog.SIZE_SMALL),))
    monkeypatch.setattr(whisper_cpp_catalog, "BASE_MODELS", ("alpha",))
    monkeypatch.setattr(whisper_cpp_catalog, "VAD_MODEL", vad_entry)
    return entry, data, vad_entry, vad


class _Response:
    def __init__(self, body):
        self._body = body
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=None):
        half = max(1, len(self._body) // 2)
        yield self._body[:half]
        yield self._body[half:]

    def close(self):
        pass


class _Session:
    def __init__(self, bodies):
        self.bodies = bodies
        self.requested = []

    def get(self, url, stream=False, timeout=None, headers=None):
        self.requested.append(url)
        return _Response(self.bodies[url])

    def close(self):
        pass


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    """Keep the lock files of these tests out of the real global folder."""
    directory = tmp_path / "global"
    directory.mkdir()
    monkeypatch.setattr(model_store, "global_dir", lambda *parts: str(directory))
    return directory


class TestGgmlFilesGoThroughTheModelStore:
    def test_a_download_lands_verified_where_whisper_cli_will_look(
        self, tmp_path, monkeypatch, lock_dir
    ):
        entry, data, _vad, _vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        session = _Session({model_store.file_url(entry, entry.filename): data})

        model_store.download_model(entry, root, session=session)

        path = whisper_cpp_store.ensure_ready(root, entry.id)
        assert path == os.path.join(root, entry.id, entry.filename)
        with open(path, "rb") as handle:
            assert handle.read() == data
        assert session.requested == [
            f"https://huggingface.co/example-org/whisper.cpp/resolve/{'a' * 40}/"
            "ggml-alpha-q5_1.bin"
        ]
        assert whisper_cpp_store.list_installed(root) == (entry.id,)

    def test_the_digest_of_the_whole_file_is_checked_on_download(
        self, tmp_path, monkeypatch, lock_dir
    ):
        # Unlike a faster-whisper model, where only model.bin has a digest,
        # the one GGML file has one: same length, wrong bytes, refused.
        entry, data, _vad, _vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        session = _Session({model_store.file_url(entry, entry.filename): b"X" * len(data)})

        with pytest.raises(errors.TranscriptionError) as caught:
            model_store.download_model(entry, root, session=session)

        assert caught.value.code == errors.MODEL_CORRUPTED
        assert not os.path.exists(whisper_cpp_store.model_path(root, entry))

    def test_verify_hashes_the_file_and_repair_replaces_it(
        self, tmp_path, monkeypatch, lock_dir
    ):
        entry, data, _vad, _vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        url = model_store.file_url(entry, entry.filename)
        model_store.download_model(entry, root, session=_Session({url: data}))
        with open(whisper_cpp_store.model_path(root, entry), "wb") as handle:
            handle.write(b"Z" * len(data))  # right size, wrong bytes

        seen = []
        with pytest.raises(errors.TranscriptionError) as caught:
            model_store.verify_model(root, entry, progress=lambda d, t: seen.append((d, t)))
        assert caught.value.code == errors.MODEL_CORRUPTED
        assert seen[-1] == (len(data), len(data))

        model_store.repair_model(entry, root, session=_Session({url: data}))
        model_store.verify_model(root, entry)

    def test_remove_deletes_the_file_and_nothing_else(self, tmp_path, monkeypatch, lock_dir):
        entry, data, _vad, _vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        url = model_store.file_url(entry, entry.filename)
        model_store.download_model(entry, root, session=_Session({url: data}))
        stranger = os.path.join(root, entry.id, "mine.txt")
        with open(stranger, "w") as handle:
            handle.write("the user's own file")

        assert whisper_cpp_store.remove_model(root, entry.id) is True

        assert os.path.exists(stranger)
        assert not os.path.exists(whisper_cpp_store.model_path(root, entry))
        assert whisper_cpp_store.remove_model(root, "ggml-unknown") is False

    def test_a_missing_model_is_not_installed_and_a_short_one_is_corrupted(
        self, tmp_path, monkeypatch
    ):
        entry, data, _vad, _vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        for model_id in (entry.id, "ggml-dropped-by-a-later-version"):
            with pytest.raises(errors.TranscriptionError) as caught:
                whisper_cpp_store.ensure_ready(root, model_id)
            assert caught.value.code == errors.MODEL_NOT_INSTALLED

        os.makedirs(os.path.join(root, entry.id))
        with open(whisper_cpp_store.model_path(root, entry), "wb") as handle:
            handle.write(data[:-1])
        with pytest.raises(errors.TranscriptionError) as caught:
            whisper_cpp_store.ensure_ready(root, entry.id)
        assert caught.value.code == errors.MODEL_CORRUPTED

    def test_the_vad_model_is_never_a_transcription_model(
        self, tmp_path, monkeypatch, lock_dir
    ):
        # Installed and complete, and still refused for `-m`: whisper-cli would
        # fail on it and the user would hear "the model is corrupted".
        _entry, _data, vad, vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        model_store.download_model(
            vad, root, session=_Session({model_store.file_url(vad, vad.filename): vad_data})
        )
        with pytest.raises(errors.TranscriptionError) as caught:
            whisper_cpp_store.ensure_ready(root, vad.id)
        assert caught.value.code == errors.MODEL_NOT_INSTALLED
        real_vad_id = "ggml-silero-v6.2.0"
        with pytest.raises(errors.TranscriptionError):
            whisper_cpp_store.ensure_ready(root, real_vad_id)

    def test_the_vad_model_is_found_only_when_complete(self, tmp_path, monkeypatch, lock_dir):
        _entry, _data, vad, vad_data = _synthetic(monkeypatch)
        root = str(tmp_path / "models")
        assert whisper_cpp_store.vad_model_path(root) is None
        model_store.download_model(
            vad, root, session=_Session({model_store.file_url(vad, vad.filename): vad_data})
        )
        assert whisper_cpp_store.vad_model_path(root) == os.path.join(root, vad.id, vad.filename)
        # Not a transcription model: never offered in the installed list.
        assert whisper_cpp_store.list_installed(root) == ()

    def test_a_ggml_file_lives_in_the_models_folder_beside_the_faster_whisper_ones(
            self, tmp_path):
        # One folder for both backends (whisper_cpp_store's docstring): no
        # second root of its own, so moving the models folder moves these too.
        assert not hasattr(whisper_cpp_store, "default_models_dir")
        entry = whisper_cpp_catalog.get_model("ggml-kb-whisper-small-q5_0")
        assert whisper_cpp_store.model_path(str(tmp_path), entry) == os.path.join(
            model_store.model_dir(str(tmp_path), entry.id), "ggml-model-q5_0.bin"
        )


# ── The tests that reach Hugging Face ────────────────────────────────────────


class TestTheGgmlUrlsAreLive:
    """Every GGML URL, the VAD model's included, serves exactly its size.

    The same safety net as TestTheCatalogueUrlsAreLive in
    test_transcription_model_store.py, for the same reason: a wrong revision or
    a renamed file looks fine to a fake session. Skipped unless asked for.
    """

    pytestmark = [
        pytest.mark.network,
        pytest.mark.skipif(
            os.environ.get(_NETWORK_OPT_IN_ENV, "").strip() in ("", "0", "false", "False"),
            reason=f"reaches huggingface.co - set {_NETWORK_OPT_IN_ENV}=1 to run it",
        ),
    ]

    @pytest.mark.parametrize("entry", _ALL_FILES, ids=[entry.id for entry in _ALL_FILES])
    def test_the_url_serves_exactly_the_catalogued_size(self, entry):
        url = model_store.file_url(entry, entry.filename)
        # Through tls_trust and with identity encoding, for the reasons
        # spelled out in the faster-whisper catalogue's live test.
        with tls_trust.create_session() as session:
            response = session.head(
                url, allow_redirects=True, timeout=30,
                headers={"Accept-Encoding": "identity"},
            )
        assert response.status_code == 200, f"{url} answered {response.status_code}"
        reported = response.headers.get("Content-Length") or response.headers.get(
            "x-linked-size"
        )
        assert reported is not None, f"{url} reported no size at all"
        assert int(reported) == entry.size_bytes

    @pytest.mark.parametrize(
        "entry",
        [whisper_cpp_catalog.VAD_MODEL, whisper_cpp_catalog.get_model("ggml-tiny-q5_1"),
         whisper_cpp_catalog.get_model("ggml-kb-whisper-tiny-q5_0")],
        ids=["vad", "tiny-q5_1", "kb-whisper-tiny-q5_0"],
    )
    def test_the_bytes_hash_to_the_catalogued_digest(self, entry):
        # The smallest files (0.9 MB, 32 MB, and 30 MB for the third-party
        # repositories), downloaded whole: the digests were read off the API,
        # and this is where they are proved.
        digest = hashlib.sha256()
        with tls_trust.create_session() as session:
            response = session.get(
                model_store.file_url(entry, entry.filename), stream=True, timeout=60
            )
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                digest.update(chunk)
        assert digest.hexdigest() == entry.sha256
