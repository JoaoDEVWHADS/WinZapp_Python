"""Which precision (CTranslate2 compute type) a faster-whisper run loads with.

Part 11. Until then `device.select_compute_type()` decided alone; now the user
may choose, and "automatic" is still the default and still exactly that rule.
The choice is faster-whisper's only: whisper.cpp's quantization is the file
itself (whisper_cpp_catalog, one entry per published variant), so its backend
ignores this preference (`WhisperCppBackend.resolve_compute_type()`).

CTranslate2 quantizes **at load time**, from the same float16 weights the
catalogue downloads — the "8-bit model" a script loads with
`WhisperModel(path, compute_type="int8")` is the very download WinZapp already
has. So a precision is a load argument, never another file, and no
pre-quantized repository is offered (the research for this part found none
that is trustworthy, and none would be smaller than load-time int8 anyway).

Three rules, each a silent failure if it is missed:

* **Only what this device can run is offered.** The list comes from
  `ctranslate2.get_supported_compute_types()` for the device that will actually
  run, measured by `device.probe_hardware()` — never from a table, because the
  answer depends on the processor's instruction set and the card's compute
  capability — minus WinZapp's own measured veto: no int8 kernel exists for
  sm_120 (`device.gpu_supports_int8()`), whatever the list says.
* **A choice the device cannot run is replaced, and the replacement is said.**
  The device can change under a stored choice (the card is gone, the radio was
  moved to the processor). Asked explicitly for a type it cannot run,
  CTranslate2 refuses the load ("Requested float16 compute type, but the target
  device or backend do not support efficient float16 computation"), so the
  replacement happens here, before the load, following CTranslate2's own
  fallback tables, and `PrecisionChoice` carries both halves so the run can
  say "you chose X, Y is used" (narration). Never silently.
* **Unknown is not "unsupported".** A probe that could not ask CTranslate2 (it
  failed to import, which fails the run anyway) leaves the choice as it is
  rather than inventing an obstacle nobody observed — the same asymmetry
  device.py keeps for the CUDA libraries.

Pure, like device.py's decision functions: the probe arrives as an argument.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.transcription import device

#: The stored "let WinZapp decide" — preferences.AUTO's value, on purpose.
AUTO = device.PREFERENCE_AUTO

#: Every compute type CTranslate2 4.8.2 accepts for a model, in the order the
#: picker lists them: smallest first, as the size classes are. "default" and
#: "auto" are CTranslate2's own automatics and are not offered — WinZapp's
#: automatic is `device.select_compute_type()`, which knows the sm_120 veto.
COMPUTE_TYPES = (
    device.COMPUTE_INT8,
    device.COMPUTE_INT8_FLOAT32,
    device.COMPUTE_INT8_FLOAT16,
    device.COMPUTE_INT8_BFLOAT16,
    device.COMPUTE_INT16,
    device.COMPUTE_FLOAT16,
    device.COMPUTE_BFLOAT16,
    device.COMPUTE_FLOAT32,
)

#: How each one is said, in the picker and in the loading line. The bit count
#: first, which is what a user comparing them is choosing on, and the
#: CTranslate2 name in brackets, which is what a script or a guide calls it.
COMPUTE_TYPE_I18N_KEYS = {
    device.COMPUTE_INT8: "transcription_precision_int8",
    device.COMPUTE_INT8_FLOAT32: "transcription_precision_int8_float32",
    device.COMPUTE_INT8_FLOAT16: "transcription_precision_int8_float16",
    device.COMPUTE_INT8_BFLOAT16: "transcription_precision_int8_bfloat16",
    device.COMPUTE_INT16: "transcription_precision_int16",
    device.COMPUTE_FLOAT16: "transcription_precision_float16",
    device.COMPUTE_BFLOAT16: "transcription_precision_bfloat16",
    device.COMPUTE_FLOAT32: "transcription_precision_float32",
}

# What replaces a type the device cannot run, in order of preference: the
# first one it can run wins, and when none can, the automatic choice does.
# Read off CTranslate2's quantization tables (4.8.2) — on the processor
# (Intel and AMD) and on cards from compute capability 6.1 up — so the
# replacement is the one CTranslate2 itself would make when it is allowed to
# fall back. Two lists because they differ where the hardware does: the
# processor has int16 kernels and no float16 ones, the card the other way
# round. The veto (sm_120, or a card NVML could not describe) has no row of
# its own: every int8 type is vetoed there, so an int8 choice runs out of
# candidates and lands on the automatic choice — float16, which is what a
# Blackwell card loads — or on float32 when the card does not offer float16
# either (resolve_compute_type()).
_CPU_FALLBACKS = {
    device.COMPUTE_INT8: (device.COMPUTE_INT8_FLOAT32,),
    device.COMPUTE_INT8_FLOAT32: (device.COMPUTE_INT8,),
    device.COMPUTE_INT8_FLOAT16: (device.COMPUTE_INT8_FLOAT32, device.COMPUTE_INT8),
    device.COMPUTE_INT8_BFLOAT16: (device.COMPUTE_INT8_FLOAT32, device.COMPUTE_INT8),
    # An AMD processor has no int16 kernels.
    device.COMPUTE_INT16: (device.COMPUTE_INT8_FLOAT32, device.COMPUTE_INT8),
    device.COMPUTE_FLOAT16: (device.COMPUTE_FLOAT32,),
    device.COMPUTE_BFLOAT16: (device.COMPUTE_FLOAT32,),
    device.COMPUTE_FLOAT32: (),
}
_CUDA_FALLBACKS = {
    device.COMPUTE_INT8: (device.COMPUTE_INT8_FLOAT32,),
    device.COMPUTE_INT8_FLOAT32: (device.COMPUTE_INT8,),
    # 6.1: no fast float16, so the 8-bit weights keep float32 for the rest.
    device.COMPUTE_INT8_FLOAT16: (device.COMPUTE_INT8_FLOAT32, device.COMPUTE_INT8),
    # 7.x: no bfloat16.
    device.COMPUTE_INT8_BFLOAT16: (device.COMPUTE_INT8_FLOAT32, device.COMPUTE_INT8),
    # No card has int16 kernels: float16 from 7.0, float32 below.
    device.COMPUTE_INT16: (device.COMPUTE_FLOAT16, device.COMPUTE_FLOAT32),
    device.COMPUTE_FLOAT16: (device.COMPUTE_FLOAT32,),
    device.COMPUTE_BFLOAT16: (device.COMPUTE_FLOAT32,),
    device.COMPUTE_FLOAT32: (),
}


@dataclass(frozen=True)
class PrecisionChoice:
    """The compute type a run loads with, and what the user had asked for.

    `requested` is None under "automatic" — there is then nothing to say about
    the precision, which is what the run did before part 11. Otherwise it is
    the stored choice, and `replaced` says whether the device could not run it.
    """

    compute_type: str
    requested: str | None = None

    @property
    def replaced(self) -> bool:
        return self.requested is not None and self.requested != self.compute_type


def is_choice(value) -> bool:
    """Whether a stored value is a precision this version can load with."""
    return isinstance(value, str) and value in COMPUTE_TYPES


def offered_compute_types(device_id, probe) -> tuple:
    """The compute types `device_id` can run, as the picker lists them.

    Every type when nothing was measured (no probe yet, or CTranslate2 could
    not be asked): a list cut down to what is known would hide the user's own
    stored choice before anybody had looked. The sm_120 veto applies even
    then, since it needs only the capability.
    """
    if device_id == device.DEVICE_CUDA:
        supported = getattr(probe, "cuda_compute_types", None)
    else:
        supported = getattr(probe, "cpu_compute_types", None)
    offered = tuple(
        compute for compute in COMPUTE_TYPES
        if supported is None or compute in supported
    )
    if device_id == device.DEVICE_CUDA and probe is not None and not device.gpu_supports_int8(
            probe.compute_capability):
        offered = tuple(compute for compute in offered if not compute.startswith("int8"))
    return offered


def picker_choices(device_id, probe, selected=None) -> tuple:
    """The values of the settings tab's precision list, in order.

    AUTO first, then what `device_id` can run — and `selected`, in its place,
    when it is a precision the device cannot run: the stored choice must keep
    an entry, or the list would fall back to "automatic" and OK would write
    that over the user's choice without a word. The tab says what replaces
    it instead (precision.resolve_compute_type()). `device_id` is None while
    nothing was measured, and then everything is listed.
    """
    offered = offered_compute_types(device_id, probe)
    return (AUTO,) + tuple(
        compute for compute in COMPUTE_TYPES if compute in offered or compute == selected
    )


def resolve_compute_type(preference, device_id, probe) -> PrecisionChoice:
    """What a run on `device_id` loads with, for the stored `preference`.

    "Automatic" — and any value this version does not know, which
    preferences.resolve() reports as a substitution — is
    `device.select_compute_type()`, unchanged. A choice the device can run is
    used as it is; one it cannot is replaced by the first of its fallbacks
    the device can run, or by the automatic choice when none can — or by
    float32 when the device cannot run that either: a replacement is never a
    type the device did not offer, since CTranslate2 would refuse the load.
    """
    automatic = device.select_compute_type(device_id, probe)
    if not is_choice(preference):
        return PrecisionChoice(automatic)
    offered = offered_compute_types(device_id, probe)
    fallbacks = (_CUDA_FALLBACKS if device_id == device.DEVICE_CUDA
                 else _CPU_FALLBACKS)[preference]
    for candidate in (preference,) + fallbacks:
        if candidate in offered:
            return PrecisionChoice(candidate, preference)
    # The automatic float16 is not always offered: a Pascal card whose
    # capability NVML could not read has its int8 vetoed and no float16.
    if automatic not in offered and device.COMPUTE_FLOAT32 in offered:
        return PrecisionChoice(device.COMPUTE_FLOAT32, preference)
    return PrecisionChoice(automatic, preference)


def memory_compute_type(preference, device_id, probe):
    """The compute type a memory estimate should assume, or None for the
    catalogue's own figures (`device.model_fits()`'s default).

    None under "automatic", which keeps the automatic model choice exactly
    what it was before part 11; the type that will really load otherwise —
    the replacement, when the choice cannot run here.
    """
    if not is_choice(preference):
        return None
    return resolve_compute_type(preference, device_id, probe).compute_type


def display_name(i18n, compute_type) -> str:
    """A compute type as it is said ("8 bits (int8), smaller and faster").

    An unknown one is said as it is — it can only come from a newer
    CTranslate2, and its own name is better than none.
    """
    key = COMPUTE_TYPE_I18N_KEYS.get(compute_type)
    return i18n.t(key) if key else str(compute_type or "")


def spoken_names(i18n, choice):
    """(chosen, used) — what narration.device_announcement() says about a
    run's precision, as names; (None, None) under "automatic"."""
    if choice is None or choice.requested is None:
        return None, None
    return (display_name(i18n, choice.requested),
            display_name(i18n, choice.compute_type))
