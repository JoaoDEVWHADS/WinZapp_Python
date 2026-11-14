"""faster-whisper's precision (part 11 of issue 112): offered, chosen, replaced, said.

A user who runs faster-whisper from a script loads the very same download with
`compute_type="int8"`; WinZapp now lets them choose it too. Four failures this
pins, each of them silent:

* **A precision the device cannot run is a refused load, not a slower one.**
  Asked explicitly, CTranslate2 raises "Requested float16 compute type, but
  the target device or backend do not support efficient float16 computation"
  — on the processor, for the most ordinary choice there is. So a choice the
  device cannot run is replaced *before* the load, along CTranslate2's own
  fallback tables, and int8 is never handed to an sm_120 card whatever its
  supported list says.
* **The replacement is said.** The run carries what was chosen and what runs
  (`PrecisionChoice`), the loading line says both, and the tab says it as the
  choice is made. A switch nobody hears about is the bug.
* **"Automatic" is exactly what it was.** Same compute type, same memory
  estimate, nothing announced — a user who never opens the picker must not
  notice it exists.
* **The memory estimate follows the precision.** float32 weights take twice
  float16's and 8-bit ones half, which makes room for a larger model; picking
  a model against the wrong figure is an allocation error half way through a
  transcription.

Nothing here touches the machine: the probe arrives as an argument, the
CTranslate2 query is faked where the probe itself is under test.
"""

import sys
import types

from tests.locales import load_strings, registered_locale_codes
import pytest

from core.transcription import (
    backend as backend_module,
    device,
    errors,
    faster_whisper_backend,
    management,
    model_catalog,
    narration,
    precision,
    preferences,
    whisper_cpp_catalog,
)


LOCALES = registered_locale_codes()

# What CTranslate2 4.8.2 answered on an Intel x86-64 processor (measured), and
# what it would answer on an AMD one, which has no int16 kernels.
_INTEL_CPU = ("float32", "int16", "int8", "int8_float32")
_AMD_CPU = ("float32", "int8", "int8_float32")
# An Ampere card (8.x): everything but int16.
_AMPERE = ("bfloat16", "float16", "float32", "int8", "int8_bfloat16",
           "int8_float16", "int8_float32")
# A Pascal card (6.1): int8 with float32 around it, and float32.
_PASCAL = ("float32", "int8", "int8_float32")


def _cpu(types_=_INTEL_CPU, ram=16_384, available=12_288):
    return device.HardwareProbe(total_ram_mb=ram, available_ram_mb=available,
                                cpu_compute_types=types_)


def _gpu(capability=(8, 6), cuda_types=_AMPERE, vram=8192):
    return device.HardwareProbe(
        cuda_available=True, cuda_device_count=1, compute_capability=capability,
        total_vram_mb=vram, free_vram_mb=vram, total_ram_mb=16_384,
        available_ram_mb=12_288, cpu_compute_types=_INTEL_CPU,
        cuda_compute_types=cuda_types,
    )


class _I18n:
    def __init__(self, locale="en-US"):
        self.language = locale
        self._table = load_strings(locale)

    def t(self, key):
        return self._table.get(key, key)


class TestWhatIsOffered:
    def test_the_processor_offers_what_ctranslate2_said_in_the_pickers_order(self):
        assert precision.offered_compute_types(device.DEVICE_CPU, _cpu()) == (
            "int8", "int8_float32", "int16", "float32")

    def test_an_amd_processor_is_not_offered_int16(self):
        assert device.COMPUTE_INT16 not in precision.offered_compute_types(
            device.DEVICE_CPU, _cpu(_AMD_CPU))

    def test_the_card_offers_its_own_list(self):
        assert precision.offered_compute_types(device.DEVICE_CUDA, _gpu()) == (
            "int8", "int8_float32", "int8_float16", "int8_bfloat16",
            "float16", "bfloat16", "float32")

    def test_sm_120_is_offered_no_int8_whatever_its_list_says(self):
        """The CTranslate2 builds that support Blackwell are compiled without
        its int8 kernels; the list is capability-based and does not know."""
        offered = precision.offered_compute_types(device.DEVICE_CUDA, _gpu((12, 0)))
        assert offered == ("float16", "bfloat16", "float32")

    def test_a_card_nvml_could_not_describe_is_offered_no_int8_either(self):
        # device.gpu_supports_int8(None) is False: the existing conservative
        # rule, kept rather than relaxed for the picker.
        offered = precision.offered_compute_types(device.DEVICE_CUDA, _gpu(None))
        assert not any(c.startswith("int8") for c in offered)

    def test_nothing_measured_offers_everything(self):
        assert precision.offered_compute_types(None, None) == precision.COMPUTE_TYPES
        unasked = device.HardwareProbe(total_ram_mb=16_384, available_ram_mb=12_288)
        assert precision.offered_compute_types(device.DEVICE_CPU, unasked) == (
            precision.COMPUTE_TYPES)


class TestThePickersList:
    def test_automatic_first_then_what_the_device_runs(self):
        assert precision.picker_choices(device.DEVICE_CPU, _cpu()) == (
            precision.AUTO, "int8", "int8_float32", "int16", "float32")

    def test_a_stored_choice_the_device_cannot_run_keeps_its_entry(self):
        """Without it the list falls back to "automatic" and OK writes that
        over the user's choice, silently."""
        choices = precision.picker_choices(device.DEVICE_CPU, _cpu(), "float16")
        assert choices == (precision.AUTO, "int8", "int8_float32", "int16",
                           "float16", "float32")

    def test_before_the_probe_everything_is_listed(self):
        assert precision.picker_choices(None, None) == (
            (precision.AUTO,) + precision.COMPUTE_TYPES)


class TestResolving:
    @pytest.mark.parametrize("probe,device_id,expected", [
        (_cpu(), device.DEVICE_CPU, device.COMPUTE_INT8),
        (_gpu(), device.DEVICE_CUDA, device.COMPUTE_FLOAT16),
        (_gpu((6, 1), _PASCAL), device.DEVICE_CUDA, device.COMPUTE_FLOAT32),
        (_gpu((12, 0)), device.DEVICE_CUDA, device.COMPUTE_FLOAT16),
    ])
    def test_automatic_is_select_compute_type_and_says_nothing(
            self, probe, device_id, expected):
        choice = precision.resolve_compute_type(precision.AUTO, device_id, probe)
        assert choice == precision.PrecisionChoice(expected)
        assert choice.compute_type == device.select_compute_type(device_id, probe)
        assert choice.requested is None and not choice.replaced

    def test_an_unknown_value_is_automatic(self):
        choice = precision.resolve_compute_type("int4", device.DEVICE_CPU, _cpu())
        assert choice == precision.PrecisionChoice(device.COMPUTE_INT8)

    @pytest.mark.parametrize("chosen", ["int8", "int8_float32", "int16", "float32"])
    def test_a_choice_the_processor_runs_is_used_as_it_is(self, chosen):
        choice = precision.resolve_compute_type(chosen, device.DEVICE_CPU, _cpu())
        assert choice == precision.PrecisionChoice(chosen, chosen)
        assert not choice.replaced

    @pytest.mark.parametrize("probe,device_id,chosen,used", [
        # The processor has no float16 or bfloat16 kernels: float32.
        (_cpu(), device.DEVICE_CPU, "float16", "float32"),
        (_cpu(), device.DEVICE_CPU, "bfloat16", "float32"),
        (_cpu(), device.DEVICE_CPU, "int8_float16", "int8_float32"),
        (_cpu(), device.DEVICE_CPU, "int8_bfloat16", "int8_float32"),
        # An AMD processor has no int16.
        (_cpu(_AMD_CPU), device.DEVICE_CPU, "int16", "int8_float32"),
        # No card has int16 kernels.
        (_gpu(), device.DEVICE_CUDA, "int16", "float16"),
        (_gpu((6, 1), _PASCAL), device.DEVICE_CUDA, "int16", "float32"),
        (_gpu((6, 1), _PASCAL), device.DEVICE_CUDA, "int8_float16", "int8_float32"),
        (_gpu((6, 1), _PASCAL), device.DEVICE_CUDA, "float16", "float32"),
        # 7.x: no bfloat16.
        (_gpu((7, 5), tuple(c for c in _AMPERE if "bfloat16" not in c)),
         device.DEVICE_CUDA, "bfloat16", "float32"),
        # sm_120: every int8 is vetoed, so the automatic float16 runs.
        (_gpu((12, 0)), device.DEVICE_CUDA, "int8", "float16"),
        (_gpu((12, 0)), device.DEVICE_CUDA, "int8_float16", "float16"),
        # A Pascal card NVML could not describe: int8 vetoed, and the
        # automatic float16 is not on its list either, so float32.
        (_gpu(None, _PASCAL), device.DEVICE_CUDA, "int8", "float32"),
        (_gpu(None, _PASCAL), device.DEVICE_CUDA, "int8_float16", "float32"),
    ])
    def test_a_choice_the_device_cannot_run_is_replaced_and_says_so(
            self, probe, device_id, chosen, used):
        choice = precision.resolve_compute_type(chosen, device_id, probe)
        assert choice == precision.PrecisionChoice(used, chosen)
        assert choice.replaced

    @pytest.mark.parametrize("chosen", precision.COMPUTE_TYPES)
    @pytest.mark.parametrize("probe,device_id", [
        (_cpu(), device.DEVICE_CPU), (_cpu(_AMD_CPU), device.DEVICE_CPU),
        (_gpu(), device.DEVICE_CUDA), (_gpu((6, 1), _PASCAL), device.DEVICE_CUDA),
        (_gpu((12, 0)), device.DEVICE_CUDA), (_gpu(None), device.DEVICE_CUDA),
        (_gpu(None, _PASCAL), device.DEVICE_CUDA),
    ])
    def test_whatever_is_chosen_what_runs_is_runnable(self, chosen, probe, device_id):
        """The point of resolving before the load: CTranslate2 refuses a type
        the device cannot run instead of falling back."""
        choice = precision.resolve_compute_type(chosen, device_id, probe)
        assert choice.compute_type in precision.offered_compute_types(device_id, probe)

    def test_a_choice_nothing_could_check_is_left_as_it_is(self):
        """Unknown is not "unsupported": no obstacle is invented."""
        unasked = device.HardwareProbe(total_ram_mb=16_384, available_ram_mb=12_288)
        choice = precision.resolve_compute_type("float16", device.DEVICE_CPU, unasked)
        assert choice == precision.PrecisionChoice("float16", "float16")


class TestTheMemoryFollowsThePrecision:
    _LARGE = model_catalog.get_model("large-v3")

    def test_no_precision_or_the_catalogues_own_is_the_catalogue_figure(self):
        for compute in (None, "float16"):
            assert device._requirement_mb(self._LARGE, device.DEVICE_CUDA, compute) == (
                self._LARGE.min_vram_mb)
        for compute in (None, "int8"):
            assert device._requirement_mb(self._LARGE, device.DEVICE_CPU, compute) == (
                self._LARGE.min_ram_mb)

    def test_on_the_card_float32_needs_more_and_8_bits_less(self):
        """Only the weights move: large-v3's float16 model.bin is about half
        the catalogue's figure."""
        float16 = self._LARGE.min_vram_mb
        float32 = device._requirement_mb(self._LARGE, device.DEVICE_CUDA, "float32")
        int8_float16 = device._requirement_mb(self._LARGE, device.DEVICE_CUDA, "int8_float16")
        assert 1.4 * float16 <= float32 <= 2 * float16
        assert 0.5 * float16 <= int8_float16 < 0.85 * float16
        # 8-bit weights are 8-bit weights, whatever the rest is computed in.
        assert device._requirement_mb(self._LARGE, device.DEVICE_CUDA, "int8") == int8_float16
        assert device._requirement_mb(self._LARGE, device.DEVICE_CUDA, "bfloat16") == float16

    def test_on_the_processor_float32_needs_more_than_int8(self):
        int8 = self._LARGE.min_ram_mb
        float32 = device._requirement_mb(self._LARGE, device.DEVICE_CPU, "float32")
        int16 = device._requirement_mb(self._LARGE, device.DEVICE_CPU, "int16")
        assert int8 < int16 < float32 < 2 * int8

    def test_a_whisper_cpp_file_keeps_its_own_figure(self):
        """Its precision is the file, already in its figures."""
        ggml = whisper_cpp_catalog.list_models()[0]
        assert device._requirement_mb(ggml, device.DEVICE_CUDA, "float32") == (
            ggml.min_vram_mb)

    def test_model_fits_measures_in_the_precision_given(self):
        budget = int(self._LARGE.min_vram_mb * 1.3)
        assert device.model_fits(self._LARGE, budget, device.DEVICE_CUDA) is True
        assert device.model_fits(self._LARGE, budget, device.DEVICE_CUDA, "float32") is False

    def test_the_automatic_model_follows_the_precision(self):
        """6000 MB free: in float16 a 4 GB-class model fits and large-v3 does
        not; 8-bit weights make room for large-v3, float32 for neither."""
        probe = _gpu(vram=6000)
        chosen = {
            compute: device.auto_select_model(probe, device.DEVICE_CUDA, (),
                                              compute_type=compute)
            for compute in (None, "int8_float16", "float32")
        }
        size = {k: model_catalog.get_model(v).min_vram_mb for k, v in chosen.items()}
        assert size["int8_float16"] > size[None] > size["float32"]

    @pytest.mark.parametrize("compute", [c for c in precision.COMPUTE_TYPES
                                         if device._COMPUTE_TYPE_WEIGHT_BYTES[c] <= 2])
    def test_less_memory_never_picks_a_smaller_model_than_float16(self, compute):
        """The precision decides what fits, never the order: models share the
        catalogue's figures and differ in weights, and ranking on the rescaled
        figure once put medium above large-v3-turbo under int8 (5800 MB free
        on an 8.6 card, where float16 picks large-v3-turbo)."""
        probe = _gpu(vram=5800)

        def _size(model_id):
            model = model_catalog.get_model(model_id)
            return (model.min_vram_mb, model.download_bytes)

        float16 = device.auto_select_model(probe, device.DEVICE_CUDA, (),
                                           compute_type="float16")
        assert float16 == device.auto_select_model(probe, device.DEVICE_CUDA, ())
        chosen = device.auto_select_model(probe, device.DEVICE_CUDA, (),
                                          compute_type=compute)
        assert _size(chosen) >= _size(float16), (compute, chosen, float16)

    @pytest.mark.parametrize("compute", [None] + list(precision.COMPUTE_TYPES))
    def test_an_unknown_budget_still_picks_the_smallest_installed(self, compute):
        probe = _gpu(vram=None)
        assert device.auto_select_model(probe, device.DEVICE_CUDA, ("tiny", "base"),
                                        compute_type=compute) == "tiny"

    def test_memory_compute_type_is_none_under_automatic(self):
        assert precision.memory_compute_type(precision.AUTO, device.DEVICE_CPU, _cpu()) is None
        # Otherwise the type that will really load, replacement included.
        assert precision.memory_compute_type("float16", device.DEVICE_CPU, _cpu()) == "float32"

    def test_the_download_question_measures_in_the_chosen_precision(self, tmp_path):
        model = self._LARGE
        probe = _gpu(vram=int(model.min_vram_mb * 1.3))
        fits = {
            compute: management.model_download_summary(
                model.id, str(tmp_path), probe, 10 ** 12,
                compute_type_preference=compute).fits_memory
            for compute in (precision.AUTO, "float32")
        }
        assert fits == {precision.AUTO: True, "float32": False}


class TestTheSettings:
    def test_the_default_is_a_stored_automatic(self):
        assert preferences.DEFAULTS[preferences.SETTING_COMPUTE_TYPE] == preferences.AUTO
        assert preferences.resolve({}, _cpu()).compute_type_preference == preferences.AUTO

    @pytest.mark.parametrize("chosen", precision.COMPUTE_TYPES)
    def test_a_stored_choice_reaches_the_run_as_stored(self, chosen):
        resolved = preferences.resolve({"transcription": {"compute_type": chosen}}, _cpu())
        assert resolved.compute_type_preference == chosen
        assert resolved.substitutions == ()

    @pytest.mark.parametrize("stored", ["int4", "", ["int8"], None])
    def test_an_unknown_value_is_automatic_and_says_so(self, stored):
        resolved = preferences.resolve({"transcription": {"compute_type": stored}}, _cpu())
        assert resolved.compute_type_preference == preferences.AUTO
        [substitution] = resolved.substitutions
        assert substitution.setting == preferences.SETTING_COMPUTE_TYPE
        assert substitution.i18n_key == "transcription_substituted_compute_type"

    def test_sanitize_rewrites_an_unknown_value_and_keeps_a_known_one(self):
        settings = {"transcription": {"compute_type": "int4"}}
        assert preferences.sanitize_section(settings) is True
        assert settings["transcription"]["compute_type"] == preferences.AUTO
        settings = {"transcription": {"compute_type": "int8_float16"}}
        assert preferences.sanitize_section(settings) is False

    def test_the_automatic_model_is_chosen_in_the_chosen_precision(self):
        """float32 on a 12 GB processor budget: the automatic model is a
        smaller one than "automatic" picks."""
        probe = _cpu(available=10_500)
        automatic = preferences.resolve({}, probe).model_id
        in_float32 = preferences.resolve(
            {"transcription": {"compute_type": "float32"}}, probe).model_id
        assert (model_catalog.get_model(in_float32).min_ram_mb
                < model_catalog.get_model(automatic).min_ram_mb)

    def test_whisper_cpp_ignores_it_when_choosing_a_model(self):
        probe = _cpu(available=10_500)
        base = {"backend": backend_module.BACKEND_WHISPER_CPP}
        assert preferences.resolve({"transcription": dict(base)}, probe).model_id == (
            preferences.resolve({"transcription": dict(base, compute_type="float32")},
                                probe).model_id)


class TestWhatIsSaid:
    def test_automatic_says_nothing(self):
        assert precision.spoken_names(_I18n(), None) == (None, None)
        chosen, used = precision.spoken_names(_I18n(), precision.PrecisionChoice("int8"))
        assert (chosen, used) == (None, None)
        notes = narration.device_announcement(
            device.DEVICE_CPU, device.REASON_CPU_REQUESTED, "small",
            precision_chosen=chosen, precision_used=used,
        )
        assert [n.i18n_key for n in notes] == ["transcription_running_on_cpu"]

    def test_a_chosen_precision_is_named(self):
        i18n = _I18n()
        chosen, used = precision.spoken_names(i18n, precision.PrecisionChoice("int8", "int8"))
        notes = narration.device_announcement(
            device.DEVICE_CPU, device.REASON_CPU_REQUESTED, "small",
            precision_chosen=chosen, precision_used=used)
        assert notes[-1] == narration.Note(
            narration.PRECISION_USED_I18N_KEY, {"precision": i18n.t("transcription_precision_int8")})

    def test_a_replaced_precision_names_both_after_the_devices_reason(self):
        i18n = _I18n()
        chosen, used = precision.spoken_names(
            i18n, precision.PrecisionChoice("float32", "float16"))
        notes = narration.device_announcement(
            device.DEVICE_CPU, device.REASON_CUDA_UNAVAILABLE, "small",
            precision_chosen=chosen, precision_used=used)
        assert [n.i18n_key for n in notes] == [
            "transcription_running_on_cpu",
            device.device_reason_i18n_key(device.REASON_CUDA_UNAVAILABLE),
            narration.PRECISION_REPLACED_I18N_KEY,
        ]
        sentence = i18n.t(notes[-1].i18n_key).format(**notes[-1].values)
        assert "float16" in sentence and "float32" in sentence

    def test_an_unknown_type_is_said_as_itself(self):
        assert precision.display_name(_I18n(), "int4_float8") == "int4_float8"

    @pytest.mark.parametrize("locale", LOCALES)
    def test_every_label_exists_names_its_type_and_is_unique(self, locale):
        """The CTranslate2 name is what a guide or a script calls it; two equal
        labels would be two entries a screen reader cannot tell apart."""
        table = load_strings(locale)
        labels = {}
        for compute, key in precision.COMPUTE_TYPE_I18N_KEYS.items():
            label = table[key]
            assert f"({compute})" in label, (locale, key, label)
            assert "{" not in label and "&" not in label, (locale, key)
            labels[label] = compute
        assert len(labels) == len(precision.COMPUTE_TYPES)

    @pytest.mark.parametrize("locale", LOCALES)
    def test_every_sentence_formats_with_what_it_is_given(self, locale):
        table = load_strings(locale)
        table["transcription_note_precision_used"].format(precision="x")
        table["transcription_note_precision_replaced"].format(chosen="x", used="y")
        table["transcription_notice_precision_replaced"].format(chosen="x", used="y")
        for key in ("transcription_error_precision_unsupported",
                    "transcription_retry_on_cpu_precision",
                    "transcription_substituted_compute_type"):
            assert table[key] and "{" not in table[key], (locale, key)


class TestTheDeviceRefusingIt:
    _MESSAGE = ("Requested float16 compute type, but the target device or backend "
                "do not support efficient float16 computation.")

    def test_ctranslate2s_refusal_is_its_own_code(self):
        error = faster_whisper_backend.classify_backend_error(
            ValueError(self._MESSAGE), device.DEVICE_CPU)
        assert error.code == errors.PRECISION_UNSUPPORTED

    def test_ctranslate2s_conversion_warning_is_not_a_refusal(self):
        """The warning CTranslate2 logs when it did fall back shares the words
        "do not support efficient"; it is not this failure."""
        warning = ("The compute type inferred from the saved model is float16, but "
                   "the target device or backend do not support efficient float16 "
                   "computation. The model weights have been automatically "
                   "converted to use the float32 compute type instead.")
        error = faster_whisper_backend.classify_backend_error(
            RuntimeError(warning), device.DEVICE_CPU)
        assert error.code != errors.PRECISION_UNSUPPORTED

    def test_on_the_card_the_processor_is_offered(self):
        error = errors.TranscriptionError(errors.PRECISION_UNSUPPORTED, self._MESSAGE)
        assert device.cpu_retry_i18n_key(error, device.DEVICE_CUDA) == (
            "transcription_retry_on_cpu_precision")
        assert device.cpu_retry_i18n_key(error, device.DEVICE_CPU) is None


class TestTheProbeAsksCTranslate2:
    @pytest.fixture
    def no_driver(self, monkeypatch):
        monkeypatch.setattr(device, "_probe_nvml", lambda: ((8, 6), 8192, 8192, None))
        monkeypatch.setattr(device, "probe_cuda_libraries", lambda: (True, (), None))

    def _fake(self, monkeypatch, count, answer):
        asked = []

        def _supported(device_id):
            asked.append(device_id)
            return answer(device_id)

        monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(
            get_cuda_device_count=lambda: count,
            get_supported_compute_types=_supported,
        ))
        return asked

    def test_the_processor_only_when_no_card_was_counted(self, monkeypatch, no_driver):
        asked = self._fake(monkeypatch, 0, lambda d: {"int8", "float32"})
        probe = device.probe_hardware()
        assert asked == [device.DEVICE_CPU]
        assert probe.cpu_compute_types == ("float32", "int8")
        assert probe.cuda_compute_types is None

    def test_both_when_a_card_was_counted(self, monkeypatch, no_driver):
        self._fake(monkeypatch, 1, lambda d: {"float16", "float32"} if d == "cuda"
                   else {"int8"})
        probe = device.probe_hardware()
        assert probe.cpu_compute_types == ("int8",)
        assert probe.cuda_compute_types == ("float16", "float32")

    def test_a_question_that_raises_is_unknown_and_logged(self, monkeypatch, no_driver):
        def _boom(device_id):
            raise RuntimeError("cuda said no")

        self._fake(monkeypatch, 1, _boom)
        probe = device.probe_hardware()
        assert probe.cpu_compute_types is None and probe.cuda_compute_types is None
        assert "cuda said no" in probe.driver_error
        # Never the driver-fault field: the card was described fine.
        assert probe.cuda_probe_error is None


class TestTheBackendsAnswer:
    def test_faster_whisper_honours_the_choice(self):
        backend = faster_whisper_backend.FasterWhisperBackend()
        assert backend.resolve_compute_type("float16", device.DEVICE_CPU, _cpu()) == (
            precision.PrecisionChoice("float32", "float16"))

    def test_whisper_cpp_ignores_it_since_its_precision_is_the_file(self):
        from core.transcription.whisper_cpp_backend import WhisperCppBackend

        choice = WhisperCppBackend().resolve_compute_type("float32", device.DEVICE_CPU, _cpu())
        assert choice == precision.PrecisionChoice(device.COMPUTE_INT8)
        assert choice.requested is None
