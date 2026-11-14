"""Checking a folder of the user's on a worker thread, and saying how it went.

The progress dialog the Transcription tab runs this behind has no idea what a
job is doing, and the screen reader has nothing else to go on, so what these
pin is what the user hears and whether the dialog can ever be left hanging:

* **Exactly one report, whatever happens.** A job that raised, was cancelled
  before its thread ran, or whose callback raised still finishes once — the
  dialog has no close box and waits for that report.
* **A failure to read or load somebody else's folder is not "download the model
  again".** MODEL_CORRUPTED's stock sentence is 3 GB of wrong advice for a
  folder WinZapp never wrote; each kind of check has a sentence of its own, and
  every other code keeps the stock one that is true wherever the model lives.
* **A held app.json is a wait, not a fault.** The `LockTimeout` of
  `AppSettings.update()` becomes MODELS_BUSY instead of "the operation could
  not be completed".
* **A trial load runs where the model will run.** The device and compute type
  are decided on the worker from a fresh probe, as TranscriptionJob does.
"""

import json
import os

from tests.locales import load_strings, registered_locale_codes
import pytest

from coord_locks import LockTimeout
from core.transcription import (
    backend as backend_module,
    device,
    errors,
    external_job,
    external_models,
    management,
)
from tests.test_transcription_external_models import (  # noqa: F401  (fixtures)
    _backend,
    _Factory,
    _same_length_other_bytes,
    _write,
    catalogue,
    models_root,
    settings,
)

LOCALES = registered_locale_codes()


class _Watcher:
    def __init__(self, fail_progress=False):
        self.ticks = []
        self.finished = []
        self._fail_progress = fail_progress

    def progress(self, tick):
        self.ticks.append(tick)
        if self._fail_progress:
            raise RuntimeError("a callback that raises")

    def done(self, result, error):
        self.finished.append((result, error))


def _run(job):
    job.start()
    job.join(10)
    return job


def _job(kind, settings_, folder, models_root_, watcher, **kwargs):
    return external_job.ExternalModelJob(
        kind, settings_, folder, models_root_,
        on_progress=watcher.progress, on_finished=watcher.done, **kwargs,
    )


@pytest.fixture
def cpu_machine(monkeypatch):
    monkeypatch.setattr(
        external_job.device, "probe_hardware",
        lambda: device.HardwareProbe(total_ram_mb=16_384, available_ram_mb=12_288),
    )


class TestVerifyingACatalogueFolder:
    def test_a_verified_folder_is_stored_and_reported_once(
        self, catalogue, tmp_path, settings, models_root
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)
        watcher = _Watcher()

        job = _run(_job(external_job.KIND_VERIFY, settings, folder, models_root, watcher))

        [(result, error)] = watcher.finished
        assert error is None
        assert result.code == external_models.ACCEPT_ADDED
        assert [r.model_id for r in external_models.load_references(settings)] == ["alpha"]
        assert watcher.ticks, "the hash reports progress"
        assert watcher.ticks[-1].percent == 100
        assert job.announcement(result, error).i18n_key == external_job.ADDED_I18N_KEY

    def test_a_folder_nobody_claims_comes_back_as_an_outcome_and_stores_nothing(
        self, catalogue, tmp_path, settings, models_root
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", dict(contents, **{"model.bin": b"C" * 5000}))
        watcher = _Watcher()

        _run(_job(external_job.KIND_VERIFY, settings, folder, models_root, watcher))

        [(result, error)] = watcher.finished
        assert error is None
        assert result.code == external_models.ACCEPT_NOT_IDENTIFIED
        assert external_models.load_references(settings) == ()

    def test_a_cancel_before_the_thread_ran_touches_nothing(
        self, catalogue, tmp_path, settings, models_root
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)
        watcher = _Watcher()
        job = _job(external_job.KIND_VERIFY, settings, folder, models_root, watcher)

        job.cancel()
        _run(job)

        [(result, error)] = watcher.finished
        assert result is None and error.code == errors.CANCELLED
        assert external_models.load_references(settings) == ()
        assert job.cancelled


class TestTrialLoadingACustomFolder:
    def test_it_loads_on_the_device_decided_from_a_fresh_probe(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", dict(contents, **{"model.bin": b"C" * 5000}))
        factory = _Factory()
        monkeypatch.setattr(
            external_job.backend_module, "get_backend",
            lambda backend_id: _backend(factory),
        )
        watcher = _Watcher()

        _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, watcher,
                  device_preference=device.PREFERENCE_CPU))

        [(result, error)] = watcher.finished
        assert error is None and result.code == external_models.ACCEPT_ADDED
        [load] = factory.loads
        assert (load["device"], load["compute_type"]) == (
            device.DEVICE_CPU, device.COMPUTE_INT8)
        [reference] = external_models.load_references(settings)
        assert reference.is_custom

    def test_it_loads_in_the_precision_the_run_will_use(
        self, catalogue, tmp_path, settings, models_root, monkeypatch
    ):
        """Part 11: a precision chosen in the tab is honoured by the trial too,
        replaced as the run would replace it — float16 on the processor is a
        load CTranslate2 refuses."""
        monkeypatch.setattr(
            external_job.device, "probe_hardware",
            lambda: device.HardwareProbe(
                total_ram_mb=16_384, available_ram_mb=12_288,
                cpu_compute_types=("float32", "int16", "int8", "int8_float32")),
        )
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", dict(contents, **{"model.bin": b"C" * 5000}))
        factory = _Factory()
        monkeypatch.setattr(
            external_job.backend_module, "get_backend",
            lambda backend_id: _backend(factory),
        )

        _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, _Watcher(),
                  device_preference=device.PREFERENCE_CPU,
                  compute_type_preference=device.COMPUTE_FLOAT16))

        [load] = factory.loads
        assert (load["device"], load["compute_type"]) == (
            device.DEVICE_CPU, device.COMPUTE_FLOAT32)

    def test_a_model_the_backend_cannot_load_is_not_stored(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", dict(contents, **{"model.bin": b"C" * 5000}))
        factory = _Factory(error=RuntimeError("not a model"))
        monkeypatch.setattr(
            external_job.backend_module, "get_backend",
            lambda backend_id: _backend(factory),
        )
        watcher = _Watcher()

        job = _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, watcher))

        [(result, error)] = watcher.finished
        assert result is None and error is not None
        assert external_models.load_references(settings) == ()
        # Whatever code the backend classified it as, the user is not told to
        # download a model that was never ours.
        assert job.announcement(result, error).i18n_key in (
            external_job.LOAD_FAILED_I18N_KEY, errors.error_i18n_key(error.code))
        assert job.announcement(result, error).outcome == management.OUTCOME_FAILED

    def test_no_backend_is_its_stock_sentence(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)

        monkeypatch.setattr(external_job.backend_module, "get_backend",
                            lambda backend_id: None)
        watcher = _Watcher()
        job = _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, watcher))
        [(result, error)] = watcher.finished
        assert job.announcement(result, error).i18n_key == errors.error_i18n_key(
            errors.BACKEND_MISSING)


    @pytest.mark.parametrize("selected", [None, backend_module.BACKEND_FASTER_WHISPER])
    def test_a_folder_is_always_tried_by_faster_whisper(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch, selected
    ):
        """Never whisper.cpp, whatever the tab had selected: a folder is not
        a file whisper-cli can open, and its refusal would blame the folder."""
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", dict(contents, **{"model.bin": b"C" * 5000}))
        factory = _Factory()
        asked = []
        monkeypatch.setattr(external_job.backend_module, "get_backend",
                            lambda backend_id: asked.append(backend_id) or _backend(factory))
        monkeypatch.setattr(
            external_job.backend_module, "resolve_backend",
            lambda preferred=None: pytest.fail("the automatic backend was asked"))
        _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, _Watcher(),
                  backend_id=selected))
        assert asked == [backend_module.BACKEND_FASTER_WHISPER]
        assert len(factory.loads) == 1

    def test_faster_whisper_missing_is_its_stock_sentence(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)

        class _Unavailable:
            def is_available(self):
                return False

        monkeypatch.setattr(external_job.backend_module, "get_backend",
                            lambda backend_id: _Unavailable())
        watcher = _Watcher()
        _run(_job(external_job.KIND_CUSTOM, settings, folder, models_root, watcher))
        [(_result, error)] = watcher.finished
        assert error.code == errors.BACKEND_MISSING


class TestARootChosenButNotApplied:
    def test_a_folder_under_it_is_refused_by_either_kind_of_check(
        self, catalogue, tmp_path, settings, models_root, cpu_machine, monkeypatch
    ):
        """The settings dialog's Browse has not been applied yet; OK would
        move WinZapp's models on top of what is being added."""
        _model, contents = catalogue["alpha"]
        pending = str(tmp_path / "chosen")
        folder = _write(os.path.join(pending, "small"), contents)
        factory = _Factory()
        monkeypatch.setattr(
            external_job.backend_module, "get_backend",
            lambda backend_id: _backend(factory),
        )
        for kind in external_job.KINDS:
            watcher = _Watcher()
            _run(_job(kind, settings, folder, models_root, watcher,
                      other_roots=(pending,)))
            [(result, error)] = watcher.finished
            assert error is None, kind
            assert result.code == external_models.REFUSED_INSIDE_MODELS_ROOT, kind
        assert factory.loads == []
        assert external_models.load_references(settings) == ()


class TestEveryWayOutIsOneReport:
    def test_a_held_settings_file_is_a_wait_not_a_fault(
        self, catalogue, tmp_path, settings, models_root, monkeypatch
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)

        def _held(*args, **kwargs):
            raise LockTimeout("app.json held")

        monkeypatch.setattr(external_job.external_models, "accept_catalogue_folder", _held)
        watcher = _Watcher()
        job = _run(_job(external_job.KIND_VERIFY, settings, folder, models_root, watcher))
        [(result, error)] = watcher.finished
        assert result is None and error.code == errors.MODELS_BUSY
        assert job.announcement(result, error).i18n_key == errors.error_i18n_key(
            errors.MODELS_BUSY)

    def test_an_unexpected_exception_is_a_failure_with_a_sentence(
        self, catalogue, tmp_path, settings, models_root, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise ValueError("a bug")

        monkeypatch.setattr(external_job.external_models, "accept_catalogue_folder", _boom)
        watcher = _Watcher()
        job = _run(_job(external_job.KIND_VERIFY, settings, tmp_path, models_root, watcher))
        [(result, error)] = watcher.finished
        assert result is None and error.code == errors.BACKEND_ERROR
        assert job.announcement(result, error).i18n_key == external_job.READ_FAILED_I18N_KEY

    def test_a_callback_that_raises_costs_the_run_nothing(
        self, catalogue, tmp_path, settings, models_root
    ):
        _model, contents = catalogue["alpha"]
        folder = _write(tmp_path / "mine", contents)
        watcher = _Watcher(fail_progress=True)
        _run(_job(external_job.KIND_VERIFY, settings, folder, models_root, watcher))
        assert len(watcher.finished) == 1
        assert watcher.finished[0][1] is None

    def test_an_unknown_kind_is_the_callers_bug_and_raises_at_once(self, settings):
        with pytest.raises(ValueError):
            external_job.ExternalModelJob("bless", settings, "x", "y")


class TestAWhisperCppFile:
    """whisper.cpp means a GGML file: the same job, external_ggml's checks and
    the sentences that say "file"."""

    @pytest.fixture
    def recorded(self, monkeypatch):
        calls = []
        outcome = external_models.AcceptOutcome(external_models.ACCEPT_ADDED)

        def verify(*args, **kwargs):
            calls.append(("verify", args, kwargs))
            return outcome

        def custom(*args, **kwargs):
            calls.append(("custom", args, kwargs))
            return outcome

        monkeypatch.setattr(external_job.external_ggml, "accept_ggml_file", verify)
        monkeypatch.setattr(external_job.external_ggml, "accept_custom_ggml_file", custom)
        return calls

    @pytest.mark.parametrize("kind, called", [
        (external_job.KIND_VERIFY, "verify"), (external_job.KIND_CUSTOM, "custom"),
    ])
    def test_the_check_is_external_ggmls(
        self, settings, models_root, tmp_path, recorded, kind, called
    ):
        watcher = _Watcher()
        path = str(tmp_path / "ggml-model.bin")
        _run(_job(kind, settings, path, models_root, watcher,
                  backend_id=backend_module.BACKEND_WHISPER_CPP))
        ((name, args, kwargs),) = recorded
        assert name == called and args[1] == path
        if kind == external_job.KIND_CUSTOM:
            # whisper.cpp's own backend, never the automatic one, which would
            # hand a GGML file to faster-whisper.
            assert args[3].id == backend_module.BACKEND_WHISPER_CPP
        ((_result, error),) = watcher.finished
        assert error is None

    def test_the_announcement_says_file(self, settings, models_root, tmp_path):
        job = _job(external_job.KIND_VERIFY, settings, str(tmp_path / "m.bin"),
                   models_root, _Watcher(), backend_id=backend_module.BACKEND_WHISPER_CPP)
        outcome = external_models.AcceptOutcome(
            external_models.ACCEPT_ADDED,
            external_models.ExternalReference("id", "/x", "ggml-small", True),
        )
        said = job.announcement(outcome, None)
        assert said.i18n_key == external_job.ADDED_I18N_KEY + "_file"
        folder = _job(external_job.KIND_VERIFY, settings, str(tmp_path / "m"),
                      models_root, _Watcher())
        assert folder.announcement(outcome, None).i18n_key == external_job.ADDED_I18N_KEY

    def test_a_file_that_vanished_is_called_a_file(self):
        error = errors.TranscriptionError(errors.EXTERNAL_MODEL_MISSING, "gone")
        said = external_job.announcement(external_job.KIND_VERIFY, "/p/m.bin", None, error,
                                         is_file=True)
        assert said.i18n_key == errors.error_i18n_key(errors.EXTERNAL_MODEL_MISSING) + "_file"

    def test_an_empty_file_has_its_own_sentence(self):
        said = external_job.announcement(
            external_job.KIND_VERIFY, "/p/m.bin",
            external_models.AcceptOutcome(external_job.external_ggml.REFUSED_NOT_GGML),
            None, is_file=True,
        )
        assert said.i18n_key == external_job.REFUSED_NOT_GGML_I18N_KEY
        assert said.outcome == management.OUTCOME_WARNING


class TestWhatTheUserHears:
    """announcement() is a table: every outcome of a check has a sentence, and
    the ones that are not a failure are not played the error sound."""

    @staticmethod
    def _said(kind, code, shape=None, model_id=""):
        reference = (external_models.ExternalReference("id", "/x", model_id or None, True)
                     if model_id or code in (external_models.ACCEPT_ADDED,
                                             external_models.ACCEPT_UPDATED) else None)
        outcome = external_models.AcceptOutcome(code, reference, None, shape)
        return external_job.announcement(kind, "/some/place/mine", outcome, None)

    @pytest.mark.parametrize("kind, code, key", [
        (external_job.KIND_VERIFY, external_models.ACCEPT_ADDED, "ADDED_I18N_KEY"),
        (external_job.KIND_VERIFY, external_models.ACCEPT_UPDATED, "CHECKED_I18N_KEY"),
        (external_job.KIND_CUSTOM, external_models.ACCEPT_ADDED, "CUSTOM_ADDED_I18N_KEY"),
        (external_job.KIND_CUSTOM, external_models.ACCEPT_UPDATED, "CUSTOM_CHECKED_I18N_KEY"),
    ])
    def test_a_folder_that_worked(self, kind, code, key):
        said = self._said(kind, code, model_id="alpha")
        assert said.i18n_key == getattr(external_job, key)
        assert said.outcome == management.OUTCOME_DONE
        assert said.values["name"] == "mine"

    @pytest.mark.parametrize("code, key", [
        (external_models.ACCEPT_NOT_IDENTIFIED, external_job.NOT_ADDED_I18N_KEY),
        (external_models.ACCEPT_DIGEST_MISMATCH, external_job.NOT_ADDED_I18N_KEY),
        (external_models.ACCEPT_CHANGED_WHILE_CHECKED,
         external_job.CHANGED_WHILE_CHECKED_I18N_KEY),
        (external_models.REFUSED_FOLDER_MISSING, external_job.REFUSED_UNREACHABLE_I18N_KEY),
        (external_models.REFUSED_NOT_A_FOLDER, external_job.REFUSED_UNREACHABLE_I18N_KEY),
        (external_models.REFUSED_UNREADABLE, external_job.REFUSED_UNREACHABLE_I18N_KEY),
        (external_models.REFUSED_FILES_MISSING, external_job.REFUSED_NOT_A_MODEL_I18N_KEY),
        (external_models.REFUSED_BAD_CONFIG, external_job.REFUSED_BAD_CONFIG_I18N_KEY),
        (external_models.REFUSED_INSIDE_MODELS_ROOT, external_job.REFUSED_INSIDE_ROOT_I18N_KEY),
    ])
    def test_a_folder_that_was_not_added_says_why(self, code, key):
        said = self._said(external_job.KIND_VERIFY, code)
        assert said.i18n_key == key
        assert said.outcome == management.OUTCOME_WARNING

    def test_what_is_missing_is_listed(self):
        shape = external_models.FolderShape(
            "/x", external_models.REFUSED_FILES_MISSING, ("model.bin", "vocabulary.*"))
        said = self._said(
            external_job.KIND_VERIFY, external_models.REFUSED_FILES_MISSING, shape)
        assert said.values["files"] == "model.bin, vocabulary.*"

    def test_a_config_that_is_there_and_wrong_is_not_called_missing(self):
        """"Missing: config.json" about a file the user can see in the folder
        sends them looking for something that is not lost."""
        shape = external_models.FolderShape("/x", external_models.REFUSED_BAD_CONFIG, ())
        said = self._said(
            external_job.KIND_VERIFY, external_models.REFUSED_BAD_CONFIG, shape)
        assert said.i18n_key != external_job.REFUSED_NOT_A_MODEL_I18N_KEY

    def test_every_code_the_check_can_refuse_with_has_a_sentence(self):
        assert set(external_models.REFUSAL_CODES) <= set(external_job._REFUSAL_I18N_KEYS)

    @pytest.mark.parametrize("kind, key", [
        (external_job.KIND_VERIFY, external_job.READ_FAILED_I18N_KEY),
        (external_job.KIND_CUSTOM, external_job.LOAD_FAILED_I18N_KEY),
    ])
    @pytest.mark.parametrize("code", [errors.MODEL_CORRUPTED, errors.BACKEND_ERROR, "nope"])
    def test_a_folder_that_could_not_be_read_or_loaded_is_not_download_it_again(
        self, kind, key, code
    ):
        error = errors.TranscriptionError(code, "detail")
        said = external_job.announcement(kind, "/p/mine", None, error)
        assert said.i18n_key == key
        assert said.i18n_key != errors.error_i18n_key(errors.MODEL_CORRUPTED)
        assert said.outcome == management.OUTCOME_FAILED

    def test_a_folder_that_vanished_keeps_the_stock_sentence(self):
        error = errors.TranscriptionError(errors.EXTERNAL_MODEL_MISSING, "gone")
        said = external_job.announcement(external_job.KIND_VERIFY, "/p/mine", None, error)
        assert said.i18n_key == errors.error_i18n_key(errors.EXTERNAL_MODEL_MISSING)

    def test_a_cancel_is_a_cancel_not_a_failure(self):
        error = errors.TranscriptionError(errors.CANCELLED, "by the user")
        said = external_job.announcement(external_job.KIND_VERIFY, "/p/mine", None, error)
        assert said.i18n_key == management.CANCELLED_I18N_KEY
        assert said.outcome == management.OUTCOME_CANCELLED


@pytest.mark.parametrize("locale", LOCALES)
def test_every_sentence_exists_in_every_locale_and_formats(locale):
    """A missing key is read out as its own name, and a placeholder a locale
    dropped or invented is a KeyError in the middle of announcing."""
    table = load_strings(locale)
    keys = (set(external_job.ANNOUNCEMENT_I18N_KEYS)
            | set(external_job.STATUS_I18N_KEYS.values()))
    values = {"name": "mine", "model": "alpha", "files": "model.bin"}
    for key in sorted(keys):
        assert table.get(key, "").strip(), f"{locale}: {key} is missing or blank"
        text = table[key].format(**values)
        assert "{" not in text, f"{locale}: {key}"
    # The sentences about a folder name it; a dropped {name} loses the one
    # thing that says which of several references this is about.
    for key in (external_job.ADDED_I18N_KEY, external_job.CHECKED_I18N_KEY,
                external_job.CUSTOM_ADDED_I18N_KEY, external_job.READ_FAILED_I18N_KEY,
                external_job.LOAD_FAILED_I18N_KEY, *external_job.STATUS_I18N_KEYS.values()):
        assert "{name}" in table[key], f"{locale}: {key} lost {{name}}"
    assert "{files}" in table[external_job.REFUSED_NOT_A_MODEL_I18N_KEY]
