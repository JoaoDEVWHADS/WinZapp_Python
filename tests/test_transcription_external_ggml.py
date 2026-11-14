"""whisper.cpp models the user already has: one GGML file, anywhere on disk.

external_models' rules, held for a file instead of a folder:

* **Only the digest makes a file "model X".** The size picks the candidates
  and nothing more: three third-party large-v3 fine-tunes ship a
  `ggml-model.bin` of exactly the same size, so a file of that size is hashed
  against every one of them, and the one whose digest matches is the answer.
* **Anything else is custom only because the user said so,** and only once
  whisper-cli loaded it.
* **The user's file is never copied, moved or deleted.** It is remembered
  where it is, and forgetting it removes the record.

A synthetic catalogue of a few kilobytes stands in for the real one: no test
here downloads or hashes gigabytes.
"""

import hashlib
import os

import pytest

import app_settings
from core.transcription import (
    backend as backend_module,
    errors,
    external_ggml,
    external_models,
    model_catalog,
    whisper_cpp_catalog,
)

_ALPHA = b"A" * 4096
_BETA = b"B" * 4096
_SMALL_CLASS = model_catalog.get_model("small").size_class


def _entry(model_id, repo, contents, base_model="small", language=None):
    return whisper_cpp_catalog.GgmlFile(
        id=model_id,
        repo=repo,
        revision=model_id.encode().hex().ljust(40, "0")[:40],
        filename="ggml-model.bin",
        size_bytes=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        base_model=base_model,
        quantization=whisper_cpp_catalog.QUANT_F16,
        size_class=_SMALL_CLASS,
        language=language,
    )


@pytest.fixture
def catalogue(monkeypatch):
    """Two files of one name and one size, in two repositories — the shape of
    the real collision between the large-v3 fine-tunes."""
    alpha = _entry("ggml-alpha", "Example-Org/whisper-alpha-ggml", _ALPHA)
    beta = _entry("ggml-beta", "Example-Org/whisper-beta-ggml", _BETA, base_model="medium")
    monkeypatch.setattr(whisper_cpp_catalog, "MODELS", (alpha, beta))
    return {"alpha": alpha, "beta": beta}


@pytest.fixture
def settings(tmp_path):
    return app_settings.AppSettings(str(tmp_path / "global"))


@pytest.fixture
def models_root(tmp_path):
    return str(tmp_path / "winzapp_models")


def _file(path, contents):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(contents)
    return path


class _TrialBackend:
    """Stands in for WhisperCppBackend: records the trial load, or refuses it."""

    def __init__(self, refuse=None):
        self.refuse = refuse
        self.calls = []

    def trial_load(self, path, device, compute_type, should_cancel=None):
        self.calls.append((path, device))
        if self.refuse is not None:
            raise self.refuse


class TestInspectingAFile:
    def test_a_file_with_bytes_in_it_passes(self, tmp_path):
        assert external_ggml.inspect_file(_file(tmp_path / "m.bin", b"x")) is None

    def test_an_empty_file_is_not_a_model(self, tmp_path):
        path = _file(tmp_path / "m.bin", b"")
        assert external_ggml.inspect_file(path) == external_ggml.REFUSED_NOT_GGML

    def test_a_folder_is_not_a_file(self, tmp_path):
        assert (external_ggml.inspect_file(str(tmp_path))
                == external_models.REFUSED_NOT_A_FOLDER)

    def test_a_missing_path_is_said_as_missing(self, tmp_path):
        assert (external_ggml.inspect_file(str(tmp_path / "gone.bin"))
                == external_models.REFUSED_FOLDER_MISSING)


class TestIdentifyingAFile:
    def test_a_size_no_entry_has_is_not_even_hashed(self, tmp_path, catalogue, monkeypatch):
        monkeypatch.setattr(external_ggml, "_hash", lambda *a: pytest.fail("hashed"))
        path = _file(tmp_path / "m.bin", b"C" * 10)
        assert external_ggml.identify_file(path) == (external_models.MATCH_NONE, None)

    @pytest.mark.parametrize("which, contents", [("alpha", _ALPHA), ("beta", _BETA)])
    def test_two_entries_of_one_size_are_told_apart_by_the_digest(
        self, tmp_path, catalogue, which, contents
    ):
        path = _file(tmp_path / "ggml-model.bin", contents)
        assert external_ggml.identify_file(path) == (
            external_models.MATCH_VERIFIED, catalogue[which].id
        )

    @pytest.mark.parametrize("model_id", [
        "ggml-distil-large-v3.5", "ggml-distil-large-v3",
        "ggml-kotoba-whisper-v2.0", "ggml-kotoba-whisper-v1.0",
    ])
    def test_four_real_entries_of_one_size_cost_one_hash(self, tmp_path, monkeypatch, model_id):
        # The real catalogue: distil-large-v3's f16 file weighs exactly what
        # distil-large-v3.5's and both kotoba ones do.
        entry = whisper_cpp_catalog.get_model(model_id)
        assert len([e for e in whisper_cpp_catalog.MODELS
                    if e.size_bytes == entry.size_bytes]) == 4
        hashed = []
        monkeypatch.setattr(external_models, "file_mark",
                            lambda path: (entry.size_bytes, 1))
        monkeypatch.setattr(external_ggml, "_hash",
                            lambda *args: hashed.append(args) or entry.sha256)
        path = _file(tmp_path / "ggml-model.bin", b"x")
        assert external_ggml.identify_file(path) == (external_models.MATCH_VERIFIED, model_id)
        assert len(hashed) == 1

    def test_the_right_size_and_other_bytes_is_a_mismatch(self, tmp_path, catalogue):
        path = _file(tmp_path / "ggml-model.bin", b"Z" * len(_ALPHA))
        match, model_id = external_ggml.identify_file(path)
        assert match == external_models.MATCH_DIGEST_MISMATCH
        assert model_id in (catalogue["alpha"].id, catalogue["beta"].id)


class TestAcceptingACatalogueFile:
    def test_a_verified_file_is_remembered_where_it_is(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", _BETA)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.ACCEPT_ADDED
        (reference,) = external_models.load_references(settings)
        assert reference.path == path
        assert reference.model_id == catalogue["beta"].id
        assert reference.is_file and reference.verified
        assert reference.backend == backend_module.BACKEND_WHISPER_CPP
        # Neither copied into the models folder nor moved out of its own.
        assert not os.path.exists(models_root)
        assert os.listdir(os.path.dirname(path)) == ["ggml-model.bin"]
        assert external_models.reference_state(reference) == external_models.REF_READY

    def test_a_rechecked_file_that_changed_keeps_the_model_it_was_stored_as(
        self, tmp_path, monkeypatch, settings, models_root
    ):
        # The real catalogue's same-size group: distil-large-v3's f16 file
        # weighs what distil-large-v3.5's and both kotoba ones do, and
        # distil-large-v3.5 comes first. A verified distil-large-v3 replaced by
        # other bytes of that size is an unverified distil-large-v3, not a
        # damaged distil-large-v3.5.
        entry = whisper_cpp_catalog.get_model("ggml-distil-large-v3")
        first = next(e for e in whisper_cpp_catalog.MODELS if e.size_bytes == entry.size_bytes)
        assert first.id != entry.id
        path = _file(tmp_path / "downloads" / "ggml-distil-large-v3.bin", b"x")
        digest = [entry.sha256]
        monkeypatch.setattr(external_models, "file_mark",
                            lambda p: (entry.size_bytes, 1) if str(p) == path else None)
        monkeypatch.setattr(external_ggml, "_hash", lambda *args: digest[0])

        assert external_ggml.accept_ggml_file(settings, path, models_root).code == (
            external_models.ACCEPT_ADDED)
        digest[0] = "0" * 64
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)

        assert outcome.code == external_models.ACCEPT_DIGEST_MISMATCH
        assert outcome.identification.model_id == entry.id
        (reference,) = external_models.load_references(settings)
        assert (reference.model_id, reference.verified) == (entry.id, False)

    def test_a_stored_file_now_of_another_entrys_size_is_named_by_that_size(
        self, tmp_path, monkeypatch, settings, models_root
    ):
        # The dialog says "has the size of the {model} model", so it names
        # the first entry of the new size; the record keeps the user's model,
        # unverified.
        entry = whisper_cpp_catalog.get_model("ggml-distil-large-v3")
        other = whisper_cpp_catalog.get_model("ggml-large-v3")
        first = next(e for e in whisper_cpp_catalog.MODELS if e.size_bytes == other.size_bytes)
        path = _file(tmp_path / "downloads" / "ggml-distil-large-v3.bin", b"x")
        state = {"size": entry.size_bytes, "digest": entry.sha256}
        monkeypatch.setattr(external_models, "file_mark",
                            lambda p: (state["size"], 1) if str(p) == path else None)
        monkeypatch.setattr(external_ggml, "_hash", lambda *args: state["digest"])

        assert external_ggml.accept_ggml_file(settings, path, models_root).code == (
            external_models.ACCEPT_ADDED)
        state.update(size=other.size_bytes, digest="0" * 64)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)

        assert outcome.code == external_models.ACCEPT_DIGEST_MISMATCH
        assert outcome.identification.model_id == first.id
        (reference,) = external_models.load_references(settings)
        assert (reference.model_id, reference.verified) == (entry.id, False)

    def test_a_first_time_mismatch_names_the_first_of_its_size_and_stores_nothing(
        self, tmp_path, monkeypatch, settings, models_root
    ):
        entry = whisper_cpp_catalog.get_model("ggml-distil-large-v3")
        first = next(e for e in whisper_cpp_catalog.MODELS if e.size_bytes == entry.size_bytes)
        path = _file(tmp_path / "downloads" / "ggml-model.bin", b"x")
        monkeypatch.setattr(external_models, "file_mark", lambda p: (entry.size_bytes, 1))
        monkeypatch.setattr(external_ggml, "_hash", lambda *args: "0" * 64)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.ACCEPT_DIGEST_MISMATCH
        assert outcome.identification.model_id == first.id
        assert external_models.load_references(settings) == ()

    def test_a_mismatch_stores_nothing_new(self, tmp_path, catalogue, settings, models_root):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", b"Z" * len(_ALPHA))
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.ACCEPT_DIGEST_MISMATCH
        assert external_models.load_references(settings) == ()

    def test_an_unknown_file_waits_for_the_users_word(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "mine.bin", b"C" * 10)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.ACCEPT_NOT_IDENTIFIED
        assert external_models.load_references(settings) == ()

    def test_a_file_inside_winzapps_own_folder_is_refused(
        self, catalogue, settings, models_root
    ):
        path = _file(os.path.join(models_root, "ggml-alpha", "ggml-model.bin"), _ALPHA)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.REFUSED_INSIDE_MODELS_ROOT

    def test_a_file_rewritten_while_it_is_hashed_stores_nothing(
        self, tmp_path, catalogue, settings, models_root, monkeypatch
    ):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", _ALPHA)
        real = external_ggml.identify_file

        def rewrite_meanwhile(*args, **kwargs):
            answer = real(*args, **kwargs)
            info = os.stat(path)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
            return answer

        monkeypatch.setattr(external_ggml, "identify_file", rewrite_meanwhile)
        outcome = external_ggml.accept_ggml_file(settings, path, models_root)
        assert outcome.code == external_models.ACCEPT_CHANGED_WHILE_CHECKED
        assert external_models.load_references(settings) == ()


class TestAcceptingACustomFile:
    def test_it_is_remembered_only_after_whisper_cli_loaded_it(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "fine-tune.bin", b"C" * 10)
        backend = _TrialBackend()
        outcome = external_ggml.accept_custom_ggml_file(settings, path, models_root, backend)
        # On the processor build whatever the preference: whether the file
        # loads does not depend on the device.
        assert backend.calls == [(path, "cpu")]
        assert outcome.code == external_models.ACCEPT_ADDED
        (reference,) = external_models.load_references(settings)
        assert reference.is_custom and reference.is_file and reference.verified
        assert external_models.custom_reference_backends((reference,)) == {
            reference.id: backend_module.BACKEND_WHISPER_CPP
        }

    def test_a_file_that_would_not_load_stores_nothing(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "fine-tune.bin", b"C" * 10)
        refusal = errors.TranscriptionError(errors.MODEL_CORRUPTED, "would not load")
        with pytest.raises(errors.TranscriptionError):
            external_ggml.accept_custom_ggml_file(
                settings, path, models_root, _TrialBackend(refuse=refusal)
            )
        assert external_models.load_references(settings) == ()
        assert os.path.exists(path)


def _accepted(settings, path, models_root):
    external_ggml.accept_ggml_file(settings, path, models_root)
    (reference,) = external_models.load_references(settings)
    return reference


class TestWhereTheRunLoadsTheFileFrom:
    def test_winzapps_own_complete_copy_wins(self, catalogue, models_root):
        own = _file(os.path.join(models_root, "ggml-alpha", "ggml-model.bin"), _ALPHA)
        assert external_ggml.model_file(models_root, "ggml-alpha") == own

    def test_a_ready_reference_is_loaded_where_it_is(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", _ALPHA)
        reference = _accepted(settings, path, models_root)
        assert external_ggml.model_file(models_root, "ggml-alpha", (reference,)) == path
        assert external_ggml.usable_ggml_ids(models_root, (reference,)) == ("ggml-alpha",)

    def test_a_reference_whose_disk_is_gone_says_so(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", _ALPHA)
        reference = _accepted(settings, path, models_root)
        os.remove(path)
        with pytest.raises(errors.TranscriptionError) as caught:
            external_ggml.model_file(models_root, "ggml-alpha", (reference,))
        assert caught.value.code == errors.EXTERNAL_MODEL_MISSING
        assert external_ggml.usable_ggml_ids(models_root, (reference,)) == ()

    def test_a_reference_rewritten_since_is_changed(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "ggml-model.bin", _ALPHA)
        reference = _accepted(settings, path, models_root)
        info = os.stat(path)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        assert external_models.reference_state(reference) == external_models.REF_CHANGED
        with pytest.raises(errors.TranscriptionError) as caught:
            external_ggml.model_file(models_root, "ggml-alpha", (reference,))
        assert caught.value.code == errors.EXTERNAL_MODEL_CHANGED

    def test_nothing_anywhere_is_not_installed(self, catalogue, models_root):
        with pytest.raises(errors.TranscriptionError) as caught:
            external_ggml.model_file(models_root, "ggml-alpha")
        assert caught.value.code == errors.MODEL_NOT_INSTALLED

    def test_a_custom_choice_loads_its_own_file(
        self, tmp_path, catalogue, settings, models_root
    ):
        path = _file(tmp_path / "downloads" / "fine-tune.bin", b"C" * 10)
        external_ggml.accept_custom_ggml_file(settings, path, models_root, _TrialBackend())
        (reference,) = external_models.load_references(settings)
        choice = external_models.custom_choice(reference)
        assert external_ggml.model_file(models_root, choice, (reference,)) == path
        # A custom file is never a candidate of the automatic choice.
        assert external_ggml.usable_ggml_ids(models_root, (reference,)) == ()

    def test_a_custom_folder_of_faster_whispers_is_not_a_file_to_load(self, models_root):
        folder_reference = external_models.ExternalReference(
            id="abc", path="C:\\models\\mine", model_id=None, verified=True,
        )
        with pytest.raises(errors.TranscriptionError) as caught:
            external_ggml.model_file(models_root, "external:abc", (folder_reference,))
        assert caught.value.code == errors.MODEL_NOT_INSTALLED


def _cache_file(cache, repo, name, contents, revision="0" * 40):
    folder = os.path.join(str(cache), "models--" + repo.replace("/", "--"),
                          "snapshots", revision)
    return _file(os.path.join(folder, name), contents)


class TestDiscoveringTheCache:
    def test_a_file_is_recognised_by_its_repository_name_and_size(
        self, tmp_path, catalogue
    ):
        # The same name and size in both repositories: only the repository
        # tells which model the file looks like.
        alpha = _cache_file(tmp_path, catalogue["alpha"].repo, "ggml-model.bin", _ALPHA)
        beta = _cache_file(tmp_path, catalogue["beta"].repo, "ggml-model.bin", _BETA)
        found = {item.path: item.model_id
                 for item in external_ggml.discover_hf_cache(str(tmp_path))}
        assert found == {alpha: "ggml-alpha", beta: "ggml-beta"}

    def test_a_file_of_a_repository_the_catalogue_does_not_name_is_unrecognised(
        self, tmp_path, catalogue
    ):
        path = _cache_file(tmp_path, "Someone/whisper-fork", "ggml-model.bin", _ALPHA)
        (item,) = external_ggml.discover_hf_cache(str(tmp_path))
        assert (item.path, item.model_id) == (path, None)

    def test_the_voice_activity_model_and_other_repositories_are_left_out(
        self, tmp_path, catalogue
    ):
        vad = whisper_cpp_catalog.VAD_MODEL
        _cache_file(tmp_path, vad.repo, vad.filename, b"v" * 10)
        _cache_file(tmp_path, "Example-Org/llama-ggml", "ggml-model.bin", b"x" * 10)
        _cache_file(tmp_path, catalogue["alpha"].repo, "model.safetensors", b"x" * 10)
        _cache_file(tmp_path, catalogue["alpha"].repo, "ggml-empty.bin", b"")
        assert external_ggml.discover_hf_cache(str(tmp_path)) == ()
