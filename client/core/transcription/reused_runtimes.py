"""CUDA libraries and whisper.cpp programs the user already has in another folder.

The counterpart of external_models for the two downloads that are not models:
a user who has WinZapp's ``cuda_runtime`` or ``whisper_cpp_runtime`` folder
from another copy of WinZapp (or the CUDA libraries from a toolkit) points
WinZapp at it instead of fetching ~0.6-0.8 GB again.

* **Never copied, never changed, never deleted.** The folder is only read: the
  CUDA directory is added to the loader's search path next to WinZapp's own
  (device.register_cuda_library_directory), and the whisper.cpp root is
  consulted by whisper_cpp_runtime.usable_root() *after* WinZapp's own. Install,
  repair and remove keep acting on WinZapp's own folders only.
* **Checked before it is chosen.** A CUDA folder must hold every library WinZapp
  installs and they must load (the same measured probe the GPU decision uses,
  asked about that folder alone). A whisper.cpp root must hold at least one
  build WinZapp itself can vouch for: the manifest, every file at its size, and
  — before every launch — the pinned digests (whisper_cpp_runtime.
  verify_executable), exactly as for the builds it downloads. A folder of
  whisper.cpp files WinZapp did not write cannot be vouched for and is refused.
* **Install-wide**, like the models folder: two keys of app_settings.

No user-facing text lives here: the check answers with a code.
"""

import os
from dataclasses import dataclass

from core.transcription import cuda_runtime, device, whisper_cpp_builds, whisper_cpp_runtime

#: The install-wide keys, in app_settings.py's own `_DEFAULTS`; a test pins the
#: spellings together.
CUDA_SETTING = "transcription_cuda_extra_dir"
WHISPER_CPP_SETTING = "transcription_whisper_cpp_extra_dir"

OK = "ok"
NOT_A_FOLDER = "not_a_folder"
MISSING = "missing"
NOT_LOADABLE = "not_loadable"
NO_BUILD = "no_build"


@dataclass(frozen=True)
class CudaFolderCheck:
    code: str
    path: str = ""
    #: The files the folder lacks, when `code` is MISSING.
    missing: tuple = ()


@dataclass(frozen=True)
class WhisperCppFolderCheck:
    code: str
    #: The root to keep (the parent when the user picked a build's own folder).
    path: str = ""
    #: The ids of the complete builds found there.
    builds: tuple = ()


def normalize(path) -> str:
    """The absolute, normalised spelling stored for a folder; "" for none."""
    text = str(path).strip() if path else ""
    return os.path.normpath(os.path.abspath(text)) if text else ""


def check_cuda_folder(path, probe=None) -> CudaFolderCheck:
    """Whether `path` holds CUDA libraries WinZapp can use.

    `probe` is device.probe_cuda_libraries' signature, the tests' way in. A
    probe that cannot answer (None: off Windows) is not a refusal — the same
    rule as the GPU decision: an obstacle that was not observed is not invented.
    """
    folder = normalize(path)
    if not folder or not os.path.isdir(folder):
        return CudaFolderCheck(NOT_A_FOLDER, folder)
    names = tuple(name for name, _member in cuda_runtime._LIBRARY_MEMBERS)
    missing = tuple(name for name in names if not os.path.isfile(os.path.join(folder, name)))
    if missing:
        return CudaFolderCheck(MISSING, folder, missing)
    ok, _missing, _error = (probe or device.probe_cuda_libraries)([folder])
    if ok is False:
        return CudaFolderCheck(NOT_LOADABLE, folder)
    return CudaFolderCheck(OK, folder)


def check_whisper_cpp_folder(path) -> WhisperCppFolderCheck:
    """Whether `path` is a root of whisper.cpp builds WinZapp can vouch for.

    The folder of a single build (the one holding winzapp_manifest.json) is
    accepted too and read as its parent: it is the folder the user is most
    likely to pick.
    """
    folder = normalize(path)
    if not folder or not os.path.isdir(folder):
        return WhisperCppFolderCheck(NOT_A_FOLDER, folder)
    roots = [folder]
    if os.path.isfile(os.path.join(folder, whisper_cpp_runtime.MANIFEST_FILENAME)):
        roots.insert(0, os.path.dirname(folder))
    for root in roots:
        found = tuple(
            build.id for build in whisper_cpp_builds.BUILDS
            if _installed(build, root)
        )
        if found:
            return WhisperCppFolderCheck(OK, root, found)
    return WhisperCppFolderCheck(NO_BUILD, folder)


def _installed(build, root) -> bool:
    try:
        return (whisper_cpp_runtime.installation_state(build, root).state
                == whisper_cpp_runtime.STATE_INSTALLED)
    except Exception:
        return False


def cuda_check_message(check):
    """(i18n key, format arguments) saying what `check_cuda_folder` found."""
    if check.code == OK:
        return "transcription_reuse_cuda_ok", {}
    if check.code == MISSING:
        return "transcription_reuse_cuda_missing", {"files": ", ".join(check.missing)}
    if check.code == NOT_LOADABLE:
        return "transcription_reuse_cuda_not_loadable", {}
    return "transcription_reuse_not_a_folder", {}


def whisper_cpp_check_message(check, build_name=None):
    """The same for `check_whisper_cpp_folder`. `build_name(build_id)` names a
    build out loud (management_text.build_name); without one, the id."""
    if check.code == OK:
        name = build_name or (lambda build_id: build_id)
        return "transcription_reuse_whisper_cpp_ok", {
            "builds": ", ".join(name(build_id) for build_id in check.builds)}
    if check.code == NO_BUILD:
        return "transcription_reuse_whisper_cpp_none", {}
    return "transcription_reuse_not_a_folder", {}


#: The CUDA folder this module registered, so that choosing another (or none)
#: takes the previous one off the loader's search path.
_registered_cuda = ""


def registered_cuda_dir() -> str:
    """The reused CUDA folder in effect, "" for none."""
    return _registered_cuda


def configure(cuda_dir, whisper_cpp_dir) -> None:
    """Put the stored folders into effect. Safe to repeat; never raises.

    A CUDA folder that has since lost its files is still registered, and the
    measured probe (not this call) decides whether the GPU is used — the same
    stance as register_installed_runtime().
    """
    global _registered_cuda
    whisper_cpp_runtime.set_extra_root(normalize(whisper_cpp_dir) or None)
    folder = normalize(cuda_dir)
    if os.path.normcase(folder) == os.path.normcase(
            normalize(cuda_runtime.default_cuda_runtime_dir())):
        # WinZapp's own folder: registered (and kept) by cuda_runtime already.
        folder = ""
    if _registered_cuda and _registered_cuda != folder:
        device.unregister_cuda_library_directory(_registered_cuda)
        _registered_cuda = ""
    if folder and device.register_cuda_library_directory(folder):
        _registered_cuda = folder


def configure_from(app_settings) -> None:
    """`configure()` with what the install-wide settings hold. Never raises:
    it runs at startup, and an unreadable app.json is not a reason not to start
    (the folders then simply are not reused until it can be read)."""
    if app_settings is None:
        return
    try:
        configure(app_settings.get(CUDA_SETTING), app_settings.get(WHISPER_CPP_SETTING))
    except Exception:
        pass
