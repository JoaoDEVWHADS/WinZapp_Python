"""whisper.cpp as a backend: the command line, what it prints, and the process.

The failures this file pins all look the same to a listener — a wrong or
missing transcription — and each has a precise cause:

* **whisper-cli's `-l` defaults to English.** Without "-l auto" a Portuguese
  voice note comes back as fluent invented English, not as an error. The
  command is built by a pure function and its every flag is asserted.

* **Progress is parsed from stderr, which arrives in arbitrary chunks.** A
  chunk can end in "progress = 4" with "2%" still to come; a percentage read
  early makes the bar jump back, and a screen reader reads every number.

* **The voice-activity filter is a preference.** A filter that cannot load
  costs the filter, never the transcription, and the result says so; a real
  failure that merely happened while the filter was on is not retried.

* **The failure codes are what the user acts on.** A full graphics card, a
  machine with no CUDA, a damaged model and a damaged program are four
  different sentences; anything unrecognised is the generic one.

* **The text never reaches the log, and the process never outlives a cancel.**

A generated script behind a launcher stands in for whisper-cli.exe, because
the code under test spawns a real process on purpose: the cancellation has to
kill one, and stderr has to arrive through a real file while it runs. No
window is ever created — the launcher is a console script and the backend
asks for no console on Windows.
"""

import json
import logging
import os
import sys
import tempfile
import time

import pytest

from core.transcription import (
    _fileops,
    backend as backend_module,
    errors,
    whisper_cpp_backend,
    whisper_cpp_cli as cli,
    whisper_cpp_runtime,
    whisper_cpp_store,
)

_PAYLOAD = {
    "result": {"language": "pt"},
    "transcription": [
        {"timestamps": {"from": "00:00:00,000", "to": "00:00:01,500"},
         "offsets": {"from": 0, "to": 1500}, "text": " Bom dia"},
        {"timestamps": {"from": "00:00:01,500", "to": "00:00:03,200"},
         "offsets": {"from": 1500, "to": 3200}, "text": " tudo certo?"},
    ],
}

_PROGRESS_LINES = (
    "whisper_full_with_state: auto-detected language: pt (p = 0.971234)\n",
    "whisper_print_progress_callback: progress =  10%\n",
    "whisper_print_progress_callback: progress =  50%\n",
    "whisper_print_progress_callback: progress =  40%\n",
    "whisper_print_progress_callback: progress = 100%\n",
)


# ── The command line ─────────────────────────────────────────────────────────


class TestTheCommandLine:
    def _command(self, **overrides):
        fields = dict(executable="cli.exe", model_path="m.bin", audio_path="a.wav",
                      output_base="out", language=None, threads=3, use_gpu=False)
        fields.update(overrides)
        return cli.build_command(**fields)

    def test_detection_is_asked_for_because_the_default_is_english(self):
        command = self._command()
        assert command[command.index("-l") + 1] == "auto"

    @pytest.mark.parametrize("language, passed", [
        ("pt", "pt"), ("PT", "pt"), (" es ", "es"), ("haw", "haw"),
        ("", "auto"), ("-ng", "auto"), ("portuguese", "auto"), ("p1", "auto"),
    ])
    def test_a_language_is_passed_only_when_it_is_a_language_code(self, language, passed):
        command = self._command(language=language)
        assert command[command.index("-l") + 1] == passed

    def test_every_flag_the_backend_relies_on_is_there(self):
        command = self._command()
        assert command[:5] == ["cli.exe", "-m", "m.bin", "-f", "a.wav"]
        assert command[command.index("-t") + 1] == "3"
        assert command[command.index("-of") + 1] == "out"
        assert "-pp" in command and "-oj" in command

    def test_the_processor_keeps_a_cuda_build_off_the_card(self):
        assert "-ng" in self._command(use_gpu=False)
        assert "-ng" not in self._command(use_gpu=True)

    def test_the_filter_is_asked_for_with_its_model(self):
        command = self._command(vad_model_path="vad.bin")
        assert command[-3:] == ["--vad", "-vm", "vad.bin"]
        assert "--vad" not in self._command()

    @pytest.mark.parametrize("cores, threads", [
        (None, 1), (0, 1), (1, 1), (2, 1), (4, 3), (8, 7), (9, 8), (64, 8), ("x", 1),
    ])
    def test_one_core_is_left_for_the_screen_reader(self, cores, threads):
        assert cli.default_thread_count(cores) == threads

    def test_paths_are_given_relative_to_the_programs_own_folder(self, tmp_path):
        # The user's profile folder (here: tmp_path) is never spelled out.
        program_dir = tmp_path / "runtime" / "cpu" / "Release"
        model = tmp_path / "models" / "m.bin"
        audio = tmp_path / "temp" / "a.wav"
        relative = cli.cli_paths(str(program_dir), [str(model), str(audio)])
        up = os.path.join("..", "..", "..")
        assert relative == [os.path.join(up, "models", "m.bin"),
                            os.path.join(up, "temp", "a.wav")]
        assert str(tmp_path) not in "".join(relative)

    @pytest.mark.skipif(sys.platform != "win32", reason="drives exist on Windows only")
    def test_a_path_on_another_drive_stays_absolute(self):
        relative = cli.cli_paths(r"C:\WinZapp\runtime", [r"D:\models\m.bin"])
        assert relative == [r"D:\models\m.bin"]


# ── What it prints ───────────────────────────────────────────────────────────


class TestReadingProgress:
    def test_the_last_complete_line_wins(self):
        text = "x: progress =  10%\nx: progress =  25%\n"
        assert cli.scan_progress("", text) == (25, "")

    def test_a_line_cut_in_half_waits_for_its_end(self):
        percent, carry = cli.scan_progress("", "x: progress =  10%\nx: progress = 4")
        assert (percent, carry) == (10, "x: progress = 4")
        assert cli.scan_progress(carry, "2%\n") == (42, "")

    def test_no_progress_is_none_and_over_a_hundred_is_clamped(self):
        assert cli.scan_progress("", "loading model\n") == (None, "")
        assert cli.scan_progress("", "progress = 120%\n")[0] == 100


class TestReadingTheOutput:
    def test_segments_times_and_language(self):
        segments, language = cli.parse_output_json(json.dumps(_PAYLOAD).encode())
        assert language == "pt"
        assert [(s.start, s.end, s.text) for s in segments] == [
            (0.0, 1.5, "Bom dia"), (1.5, 3.2, "tudo certo?"),
        ]

    def test_an_unescaped_control_character_does_not_cost_the_whole_text(self):
        raw = '{"result": {"language": "en"}, "transcription": [' \
              '{"offsets": {"from": 0, "to": 10}, "text": "a\tb"}]}'
        segments, _language = cli.parse_output_json(raw)
        assert segments[0].text == "a\tb"

    def test_missing_fields_degrade_instead_of_failing(self):
        segments, language = cli.parse_output_json(b'{"transcription": [{"text": " oi"}, 3]}')
        assert language is None
        assert [(s.start, s.end, s.text) for s in segments] == [(0.0, 0.0, "oi")]

    def test_bytes_that_are_not_utf8_are_replaced_not_fatal(self):
        raw = b'{"transcription": [{"offsets": {"from": 0, "to": 5}, "text": "ol\xe1"}]}'
        segments, _language = cli.parse_output_json(raw)
        assert segments[0].text.startswith("ol")

    @pytest.mark.parametrize("raw", [b"", b"[1, 2]", b"not json"])
    def test_anything_else_is_a_value_error(self, raw):
        with pytest.raises(ValueError):
            cli.parse_output_json(raw)

    def test_the_detected_language_line(self):
        assert cli.parse_detected_language(_PROGRESS_LINES[0]) == ("pt", 0.971234)
        assert cli.parse_detected_language("auto-detected language: en\n") == ("en", None)
        assert cli.parse_detected_language("nothing here") == (None, None)


class TestVadFailures:
    def test_the_filter_loading_normally_is_not_a_filter_failure(self):
        stderr = (
            "whisper_vad_init_from_file_with_params_no_state: loading VAD model\n"
            "whisper_vad_init_with_params: n_threads = 3\n"
            "ggml_aligned_malloc: insufficient memory (attempted to allocate 900 MB)\n"
        )
        assert cli.looks_like_vad_failure(stderr) is False

    @pytest.mark.parametrize("line", [
        "whisper_vad_init_from_file_with_params_no_state: failed to open VAD model\n",
        "error: failed to initialize VAD context\n",
        "error: unknown argument: --vad\n",
    ])
    def test_the_filter_failing_is(self, line):
        assert cli.looks_like_vad_failure(line) is True

    @pytest.mark.parametrize("stderr, unsupported", [
        ("error: unknown argument: --vad\nusage: whisper-cli [options]\n", True),
        ("error: unknown argument: -vm\n", True),
        ("error: unknown argument: --frobnicate\n", False),
        ("whisper_vad_init: failed to load\n", False),
    ])
    def test_a_build_that_does_not_know_the_flags_is_recognised(self, stderr, unsupported):
        assert cli.vad_unsupported(stderr) is unsupported


class TestFailureCodes:
    @pytest.mark.parametrize("stderr, device, code", [
        ("ggml_backend_cuda_buffer_type_alloc_buffer: allocating 3000 MiB on device 0: "
         "cudaMalloc failed: out of memory", "cuda", errors.INSUFFICIENT_VRAM),
        ("ggml_gallocr_reserve_n: failed to allocate CUDA0 buffer of size 1", "cuda",
         errors.INSUFFICIENT_VRAM),
        ("ggml_aligned_malloc: insufficient memory (attempted to allocate 3000 MB)", "cpu",
         errors.INSUFFICIENT_RAM),
        ("std::bad_alloc", "cpu", errors.INSUFFICIENT_RAM),
        ("out of memory", "cuda", errors.INSUFFICIENT_VRAM),
        ("out of memory", "cpu", errors.INSUFFICIENT_RAM),
        ("ggml_cuda_init: failed to initialize CUDA: no CUDA-capable device is detected",
         "cuda", errors.CUDA_UNAVAILABLE),
        ("CUDA error: CUDA driver version is insufficient for CUDA runtime version",
         "cuda", errors.CUDA_UNAVAILABLE),
        ("CUDA error: no kernel image is available for execution on the device", "cuda",
         errors.CUDA_UNAVAILABLE),
        ("error: failed to read audio file 'x.wav'", "cpu", errors.FFMPEG_FAILED),
        ("whisper_model_load: invalid model data (bad magic)\n"
         "error: failed to initialize whisper context", "cpu", errors.MODEL_CORRUPTED),
        ("something nobody has seen before", "cpu", errors.BACKEND_ERROR),
    ])
    def test_each_family_reaches_the_code_the_user_can_act_on(self, stderr, device, code):
        assert cli.classify_failure(1, stderr, device).code == code

    def test_windows_refusing_to_start_it_depends_on_the_build(self):
        # The CUDA build needs the NVIDIA driver's DLLs; the CPU build only
        # what came in its zip.
        assert cli.classify_failure(0xC0000135, "", "cuda").code == errors.CUDA_UNAVAILABLE
        assert cli.classify_failure(0xC0000135, "", "cpu").code == errors.WHISPER_CPP_CORRUPTED
        # The same status as a signed value, which some callers report.
        assert cli.classify_failure(-1073741515, "", "cpu").code == errors.WHISPER_CPP_CORRUPTED

    def test_an_old_processor_is_generic_but_said_in_the_log(self):
        failure = cli.classify_failure(0xC000001D, "", "cpu")
        assert failure.code == errors.BACKEND_ERROR
        assert "illegal instruction" in failure.detail

    def test_the_detail_keeps_the_evidence_and_drops_anything_like_a_segment(self):
        stderr = "[00:00:00.000 --> 00:00:01.000]  segredo\nwhisper_init: failed badly\n"
        failure = cli.classify_failure(3, stderr, "cpu")
        assert "failed badly" in failure.detail
        assert "segredo" not in failure.detail


# ── The backend, with a stand-in program ─────────────────────────────────────


def _fake_cli(tmp_path, record, payload=_PAYLOAD, lines=_PROGRESS_LINES, returncode=0,
              sleep=0.0, vad_fails=False, vad_unknown=False, write_json=True,
              name="whisper-cli", started=None, stop=None):
    """An executable that behaves like whisper-cli for one scenario.

    It lives in a folder of its own, like the real program in its build
    folder, since that folder is the working directory the backend runs it in.
    `started`/`stop` are for the cancellation test: the fake releases its
    stderr handle, says it is running, then sleeps until `stop` exists or
    `sleep` seconds pass.
    """
    folder = tmp_path / f"{name}-dir"
    folder.mkdir()
    script = folder / f"{name}.py"
    script.write_text(
        "import json, os, sys, time\n"
        "args = sys.argv[1:]\n"
        f"open({str(record)!r}, 'a', encoding='utf-8').write(json.dumps(args) + '\\n')\n"
        f"started, stop = {started!r}, {stop!r}\n"
        "if started:\n"
        # Behind a launcher on Windows the backend kills the launcher, not this
        # interpreter; a real whisper-cli is the direct child and dies with
        # the kill. So the stand-in lets go of what a dead process would.
        "    os.close(2)\n"
        "    open(started, 'w').close()\n"
        f"deadline = time.monotonic() + {sleep!r}\n"
        "while time.monotonic() < deadline and not (stop and os.path.exists(stop)):\n"
        "    time.sleep(0.02)\n"
        "if started:\n"
        "    sys.exit(0)\n"
        f"if {vad_unknown!r} and '--vad' in args:\n"
        "    sys.stderr.write('error: unknown argument: --vad\\n')\n"
        "    sys.exit(0)\n"
        f"if {vad_fails!r} and '--vad' in args:\n"
        "    sys.stderr.write('whisper_vad_init_from_file_with_params_no_state: loading\\n')\n"
        "    sys.stderr.write('whisper_print_progress_callback: progress =  30%\\n')\n"
        "    sys.stderr.write('error: failed to initialize VAD context\\n')\n"
        "    sys.exit(3)\n"
        f"for line in {list(lines)!r}:\n"
        "    sys.stderr.write(line)\n"
        "    sys.stderr.flush()\n"
        f"if {returncode!r}:\n"
        f"    sys.exit({returncode!r})\n"
        f"if {write_json!r}:\n"
        "    base = args[args.index('-of') + 1]\n"
        "    with open(base + '.json', 'w', encoding='utf-8') as fh:\n"
        f"        json.dump({payload!r}, fh)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        launcher = folder / f"{name}.bat"
        # The base interpreter, not a venv's: a venv's python.exe is itself a
        # launcher that starts the real one, which leaves a third process
        # holding the stderr file the kill was meant to free. The script uses
        # the standard library only.
        interpreter = getattr(sys, "_base_executable", sys.executable)
        launcher.write_text(
            f'@echo off\r\n"{interpreter}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = folder / f"{name}.sh"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        os.chmod(launcher, 0o755)
    return str(launcher)


def _runs(record):
    if not os.path.exists(record):
        return []
    with open(record, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@pytest.fixture
def own_temp_dir(tmp_path, monkeypatch):
    private = tmp_path / "temp"
    private.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private))
    return private


@pytest.fixture
def setup(tmp_path, monkeypatch, own_temp_dir):
    """A CPU build, a model file and a VAD model, as the stores would report them."""
    record = tmp_path / "runs.jsonl"
    models = tmp_path / "models"
    models.mkdir()
    model_file = models / "ggml-small-q5_1.bin"
    model_file.write_bytes(b"ggml")
    vad_file = models / "ggml-silero.bin"
    vad_file.write_bytes(b"vad")
    audio = tmp_path / "prepared.wav"
    audio.write_bytes(b"RIFF")
    state = {"cpu": None, "cuda": None, "vad": str(vad_file)}

    monkeypatch.setattr(
        whisper_cpp_runtime, "executable_path",
        lambda build, root=None: state["cuda" if build.uses_cuda else "cpu"],
    )
    # The stand-in is in no manifest; verify_executable has its own tests.
    monkeypatch.setattr(whisper_cpp_runtime, "verify_executable",
                        lambda build, root=None: None)
    monkeypatch.setattr(whisper_cpp_store, "ensure_ready",
                        lambda root, model_id: str(model_file))
    monkeypatch.setattr(whisper_cpp_store, "vad_model_path", lambda root: state["vad"])

    def request(**overrides):
        fields = dict(audio_path=str(audio), models_root=str(models),
                      model_id="ggml-small-q5_1", device="cpu", compute_type="int8",
                      duration_seconds=3.2)
        fields.update(overrides)
        return backend_module.TranscriptionRequest(**fields)

    return state, record, request, str(model_file)


def _backend():
    return whisper_cpp_backend.WhisperCppBackend(cpu_count=4)


class TestTranscribing:
    def test_the_result_carries_the_text_the_language_and_the_times(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)

        result = _backend().transcribe(request())

        assert result.text == "Bom dia tudo certo?"
        assert result.language == "pt"
        assert result.language_probability == pytest.approx(0.971234)
        assert [(s.start, s.end) for s in result.segments] == [(0.0, 1.5), (1.5, 3.2)]
        assert result.backend == backend_module.BACKEND_WHISPER_CPP == "whisper_cpp"
        assert result.model_id == "ggml-small-q5_1"
        # The precision is the file's quantization, not the requested compute type.
        assert result.compute_type == "q5_1"
        assert result.vad_used is True
        assert result.duration_seconds == 3.2

    def test_the_program_is_run_the_way_the_decisions_say(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)

        _backend().transcribe(request(language=None))

        (args,) = _runs(record)
        assert args[args.index("-l") + 1] == "auto"
        assert args[args.index("-t") + 1] == "3"
        assert "-ng" in args and "-pp" in args and "-oj" in args
        assert args[args.index("-vm") + 1].endswith("ggml-silero.bin")

    def test_a_language_the_user_chose_is_passed(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        _backend().transcribe(request(language="pl"))
        (args,) = _runs(record)
        assert args[args.index("-l") + 1] == "pl"

    def test_progress_only_moves_forward_and_ends_at_one(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        seen = []
        _backend().transcribe(request(), progress=seen.append)
        assert seen == sorted(seen)
        assert seen[-1] == 1.0
        assert 0.4 not in seen

    def test_without_the_vad_model_it_transcribes_and_says_so(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        state["vad"] = None
        result = _backend().transcribe(request())
        assert result.vad_used is False
        assert result.text
        (args,) = _runs(record)
        assert "--vad" not in args

    def test_the_filter_off_by_request_is_not_a_downgrade(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        result = _backend().transcribe(request(vad_filter=False))
        assert result.vad_used is False
        assert "--vad" not in _runs(record)[0]

    def test_a_filter_that_cannot_load_costs_the_filter_not_the_transcription(
        self, tmp_path, setup
    ):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record, vad_fails=True)
        seen = []
        result = _backend().transcribe(request(), progress=seen.append)
        assert result.text == "Bom dia tudo certo?"
        assert result.vad_used is False
        first, second = _runs(record)
        assert "--vad" in first and "--vad" not in second
        # The second run starts again at 10%; the user keeps hearing 30% and up.
        assert seen == sorted(seen) and seen[0] == pytest.approx(0.3)
        assert 0.1 not in seen

    def test_a_build_that_does_not_know_vad_falls_back_even_on_exit_zero(
        self, tmp_path, setup
    ):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record, vad_unknown=True)
        result = _backend().transcribe(request())
        assert result.vad_used is False
        assert result.text == "Bom dia tudo certo?"
        assert len(_runs(record)) == 2

    def test_a_real_failure_with_the_filter_on_is_not_retried(self, tmp_path, setup):
        state, record, request, _model = setup
        lines = ("whisper_vad_init_from_file_with_params_no_state: loading\n",
                 "ggml_aligned_malloc: insufficient memory (attempted to allocate 4 GB)\n")
        state["cpu"] = _fake_cli(tmp_path, record, lines=lines, returncode=1)
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request())
        assert caught.value.code == errors.INSUFFICIENT_RAM
        assert len(_runs(record)) == 1

    def test_nothing_said_is_an_empty_result_not_an_error(self, tmp_path, setup):
        state, record, request, _model = setup
        payload = {"result": {"language": "pt"}, "transcription": []}
        state["cpu"] = _fake_cli(tmp_path, record, payload=payload)
        result = _backend().transcribe(request())
        assert result.is_empty

    def test_a_clean_exit_without_output_is_an_internal_error(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record, write_json=False)
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request())
        assert caught.value.code == errors.BACKEND_ERROR

    def test_the_temporary_folder_is_gone_when_the_run_ends(self, tmp_path, setup, own_temp_dir):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        _backend().transcribe(request())
        assert os.listdir(own_temp_dir) == []

    def test_a_program_that_fails_verification_is_not_launched(
        self, tmp_path, setup, monkeypatch
    ):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)

        def _tampered(build, root=None):
            raise errors.TranscriptionError(errors.WHISPER_CPP_CORRUPTED, "sha256")

        monkeypatch.setattr(whisper_cpp_runtime, "verify_executable", _tampered)
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request())
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED
        assert _runs(record) == []

    def test_the_transcript_file_is_deleted_as_soon_as_it_is_read(
        self, tmp_path, setup, monkeypatch
    ):
        state, record, request, _model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        real_parse = cli.parse_output_json
        still_there = []

        def _spy(raw):
            result = real_parse(raw)
            still_there.extend(
                name for name in os.listdir(os.path.dirname(seen[0])) if name == "out.json"
            )
            return result

        seen = []
        real_unlink = _fileops.unlink

        def _note(path):
            seen.append(path)
            return real_unlink(path)

        monkeypatch.setattr(whisper_cpp_backend, "_unlink", _note)
        monkeypatch.setattr(cli, "parse_output_json", _spy)
        _backend().transcribe(request())
        assert seen and not still_there

    def test_cancelling_kills_the_program_and_leaves_nothing(
        self, tmp_path, setup, own_temp_dir, monkeypatch
    ):
        """The process the backend spawned is killed, and the folder goes.

        Cancelled only once the stand-in says it is running (a marker file),
        so the kill always lands on a live process. On Windows the backend's
        child is the .bat launcher and the interpreter outlives its kill; the
        stand-in therefore drops its stderr handle before saying it runs, as a
        killed whisper-cli would, and is told to stop afterwards so it does
        not outlive the test.
        """
        state, record, request, _model = setup
        started_marker = str(tmp_path / "running")
        stop_marker = str(tmp_path / "stop")
        state["cpu"] = _fake_cli(tmp_path, record, sleep=10.0,
                                 started=started_marker, stop=stop_marker)
        killed = []
        real_kill = _fileops.kill_process

        def _spy(process, program):
            killed.append(process)
            real_kill(process, program)

        monkeypatch.setattr(_fileops, "kill_process", _spy)

        began = time.monotonic()
        try:
            with pytest.raises(errors.TranscriptionError) as caught:
                _backend().transcribe(
                    request(), should_cancel=lambda: os.path.exists(started_marker)
                )
            elapsed = time.monotonic() - began
        finally:
            open(stop_marker, "w").close()

        assert caught.value.code == errors.CANCELLED
        assert elapsed < 8.0, "the cancel waited for the run"
        assert killed and killed[0].poll() is not None
        assert os.listdir(own_temp_dir) == []

    def test_the_transcribed_words_never_reach_the_log(self, tmp_path, setup, caplog):
        state, record, request, _model = setup
        secret = "zzqq um segredo que ninguem deveria ver yyww"
        payload = {"result": {"language": "pt"},
                   "transcription": [{"offsets": {"from": 0, "to": 900}, "text": secret}]}
        state["cpu"] = _fake_cli(tmp_path, record, payload=payload, vad_fails=True)
        caplog.set_level(logging.DEBUG)
        result = _backend().transcribe(request())
        assert result.text == secret
        assert "segredo" not in caplog.text


class TestWhichProgram:
    def test_the_gpu_without_the_cuda_build_offers_the_processor(self, setup):
        _state, _record, request, _model = setup
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request(device="cuda", compute_capability=(8, 6)))
        # The code the job answers with an offer to re-run on the processor.
        assert caught.value.code == errors.CUDA_UNAVAILABLE

    @pytest.mark.parametrize("capability", [None, (12, 0), (12, 1), (3, 7)])
    def test_the_cuda_build_is_never_run_where_it_cannot_work(
        self, tmp_path, setup, capability
    ):
        # Installed or not: on sm_120 it would load the model and then die.
        state, record, request, _model = setup
        state["cuda"] = _fake_cli(tmp_path, record, name="whisper-cli-cuda")
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request(device="cuda", compute_capability=capability))
        assert caught.value.code == errors.CUDA_UNAVAILABLE
        assert _runs(record) == []

    def test_the_processor_without_the_cpu_build_is_not_installed(self, setup):
        _state, _record, request, _model = setup
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().load_model(request())
        assert caught.value.code == errors.WHISPER_CPP_NOT_INSTALLED

    def test_the_gpu_runs_the_cuda_build_on_the_card(self, tmp_path, setup):
        state, record, request, _model = setup
        state["cuda"] = _fake_cli(tmp_path, record, name="whisper-cli-cuda")
        _backend().transcribe(request(device="cuda", compute_capability=(8, 9)))
        (args,) = _runs(record)
        assert "-ng" not in args

    def test_a_program_that_will_not_start_is_damaged(self, tmp_path, setup):
        state, _record, request, _model = setup
        state["cpu"] = str(tmp_path / "gone" / "whisper-cli.exe")
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().transcribe(request())
        assert caught.value.code == errors.WHISPER_CPP_CORRUPTED

    def test_availability_is_the_installed_builds_and_never_raises(self, tmp_path, monkeypatch):
        backend = whisper_cpp_backend.WhisperCppBackend(runtime_root=str(tmp_path))
        assert backend.is_available() is False

        installed = whisper_cpp_runtime.RuntimeState(whisper_cpp_runtime.STATE_INSTALLED)
        monkeypatch.setattr(whisper_cpp_runtime, "installation_state",
                            lambda build, root=None: installed)
        assert backend.is_available() is True

        def _boom(build, root=None):
            raise OSError("unreadable")

        monkeypatch.setattr(whisper_cpp_runtime, "installation_state", _boom)
        assert backend.is_available() is False

    def test_it_is_offered_after_faster_whisper(self):
        # Registered by part 9b, with the tab that installs its program and
        # models; faster-whisper stays the default and the first choice.
        assert backend_module.BACKEND_IDS[0] == backend_module.BACKEND_FASTER_WHISPER
        assert backend_module.BACKEND_WHISPER_CPP in backend_module.BACKEND_IDS
        built = backend_module.get_backend(backend_module.BACKEND_WHISPER_CPP)
        assert built is not None and built.id == backend_module.BACKEND_WHISPER_CPP


class TestTrialLoad:
    def test_the_file_is_opened_on_silence_with_nothing_detected_or_filtered(
        self, tmp_path, setup, own_temp_dir
    ):
        state, record, _request, model = setup
        state["cpu"] = _fake_cli(tmp_path, record)
        # Asked for the GPU, still answered on the CPU build: the file's
        # readability does not depend on the device.
        _backend().trial_load(model, "cuda", "float16")
        (args,) = _runs(record)
        assert args[args.index("-l") + 1] == "en"
        assert "--vad" not in args and "-ng" in args
        assert os.listdir(own_temp_dir) == []

    def test_a_path_that_is_not_a_file_is_refused(self, tmp_path, setup):
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().trial_load(str(tmp_path), "cpu", "int8")
        assert caught.value.code == errors.MODEL_CORRUPTED

    def test_a_file_the_program_cannot_load_says_so(self, tmp_path, setup):
        state, record, _request, model = setup
        lines = ("whisper_model_load: invalid model data (bad magic)\n",)
        state["cpu"] = _fake_cli(tmp_path, record, lines=lines, returncode=1)
        with pytest.raises(errors.TranscriptionError) as caught:
            _backend().trial_load(model, "cpu", "int8")
        assert caught.value.code == errors.MODEL_CORRUPTED
