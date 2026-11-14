"""Transcription downloads that follow "download in the background".

The decision (`core.transcription.background`) and the window's half
(`main_window.transcription_background`), against a stub MainWindow: no window
is created, and the job is a fake that finishes when the test says so.
"""

import types

import pytest

from core.transcription import background, management, management_text
from main_window.transcription_background import TranscriptionBackgroundMixin


DOWNLOADS = (
    management.ACTION_DOWNLOAD_MODEL,
    management.ACTION_REPAIR_MODEL,
    management.ACTION_INSTALL_CUDA_RUNTIME,
    management.ACTION_REPAIR_CUDA_RUNTIME,
    management.ACTION_INSTALL_WHISPER_CPP,
    management.ACTION_REPAIR_WHISPER_CPP,
)


class TestWhichActionsRunInTheBackground:
    @pytest.mark.parametrize("action", DOWNLOADS)
    def test_every_download_follows_the_setting(self, action):
        assert background.runs_in_background(action, True)
        assert not background.runs_in_background(action, False)

    @pytest.mark.parametrize(
        "action", [a for a in management.ACTIONS if a not in DOWNLOADS]
    )
    def test_what_is_not_a_download_keeps_its_dialog(self, action):
        assert not background.runs_in_background(action, True)

    def test_the_six_are_exactly_what_fetches_bytes(self):
        assert set(background.BACKGROUND_ACTIONS) == set(DOWNLOADS)


class _FakeJob:
    action = management.ACTION_DOWNLOAD_MODEL
    build_id = None

    def __init__(self, on_finished, model_id="small"):
        self.on_finished = on_finished
        self.model_id = model_id
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def announcement(self, result, error):
        return management.announcement(
            self.action, result, error, model_id=self.model_id
        )


class _I18n:
    def t(self, key):
        return key


class _Window(TranscriptionBackgroundMixin):
    def __init__(self):
        self.i18n = _I18n()
        self.said = []
        self.error_sound = types.SimpleNamespace(
            play=lambda: self.said.append("<error sound>")
        )
        self.jobs = []

    def output(self, text, interrupt=False):
        self.said.append(text)

    def make_job(self, on_progress, on_finished):
        assert on_progress is None
        job = _FakeJob(on_finished)
        self.jobs.append(job)
        return job


@pytest.fixture
def window(monkeypatch):
    from main_window import transcription_background as module

    # The hop to the wx thread, run inline.
    monkeypatch.setattr(module.wx, "CallAfter", lambda func, *a: func(*a))
    return _Window()


class TestTheWindowRunsTheJob:
    def test_it_starts_the_job_and_says_so(self, window):
        assert window.start_transcription_background_job(window.make_job, "Baixando")
        assert window.jobs[0].started
        assert window.transcription_background_running()
        assert window.said == ["Baixando transcription_background_started"]

    def test_a_second_one_is_refused_while_the_first_runs(self, window):
        window.start_transcription_background_job(window.make_job, "um")
        assert not window.start_transcription_background_job(window.make_job, "dois")
        assert len(window.jobs) == 1

    def test_without_a_dialog_the_window_says_how_it_ended(self, window):
        window.start_transcription_background_job(window.make_job, "x")
        window.said.clear()
        window.jobs[0].on_finished(object(), None)
        assert not window.transcription_background_running()
        assert window.said == [
            management_text.announcement_text(
                window.i18n, window.jobs[0].announcement(object(), None)
            )
        ]

    def test_a_failure_plays_the_error_sound_first(self, window):
        from core.transcription import errors

        window.start_transcription_background_job(window.make_job, "x")
        window.said.clear()
        window.jobs[0].on_finished(None, errors.TranscriptionError(errors.NO_DISK_SPACE, "d"))
        assert window.said[0] == "<error sound>"
        assert len(window.said) == 2

    def test_a_listener_that_said_it_leaves_the_window_silent(self, window):
        window.start_transcription_background_job(window.make_job, "x")
        window.said.clear()
        calls = []
        window.watch_transcription_background(
            lambda job, result, error, last: calls.append(job) or True
        )
        window.jobs[0].on_finished("ok", None)
        assert calls == [window.jobs[0]]
        assert window.said == []

    def test_a_listener_that_did_not_say_it_does_not_silence_the_window(self, window):
        window.start_transcription_background_job(window.make_job, "x")
        window.said.clear()
        window.watch_transcription_background(lambda job, result, error, last: False)
        window.jobs[0].on_finished("ok", None)
        assert len(window.said) == 1

    def test_a_listener_that_raises_costs_nothing(self, window):
        window.start_transcription_background_job(window.make_job, "x")
        window.said.clear()

        def broken(job, result, error, last):
            raise RuntimeError("dialog gone")

        window.watch_transcription_background(broken)
        window.jobs[0].on_finished("ok", None)
        assert len(window.said) == 1
        assert not window.transcription_background_running()

    def test_listeners_are_forgotten_once_called(self, window):
        window.start_transcription_background_job(window.make_job, "x")
        calls = []
        window.watch_transcription_background(
            lambda *args: calls.append(1) or True
        )
        window.jobs[0].on_finished("ok", None)
        window.start_transcription_background_job(window.make_job, "y")
        window.jobs[1].on_finished("ok", None)
        assert calls == [1]

    def test_a_job_that_cannot_be_built_is_not_left_running(self, window):
        def broken(on_progress, on_finished):
            raise OSError("no thread")

        assert not window.start_transcription_background_job(broken, "x")
        assert not window.transcription_background_running()
        assert window.said == []


def _items(window, *model_ids):
    def factory(model_id):
        def make_job(on_progress, on_finished):
            assert on_progress is None
            job = _FakeJob(on_finished, model_id)
            window.jobs.append(job)
            return job
        return make_job
    return [(factory(model_id), f"baixando {model_id}") for model_id in model_ids]


class TestARunOfSeveralJobs:
    def test_they_go_one_after_the_other_never_together(self, window):
        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        assert [job.model_id for job in window.jobs] == ["tiny"]
        window.jobs[0].on_finished("ok", None)
        assert [job.model_id for job in window.jobs] == ["tiny", "base"]
        assert window.transcription_background_running()

    def test_the_note_is_said_once_and_each_job_says_what_it_is_doing(self, window):
        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        assert window.said == ["baixando tiny transcription_background_started"]
        window.said.clear()
        window.jobs[0].on_finished("ok", None)
        assert "baixando base" in window.said
        assert "baixando base transcription_background_started" not in window.said

    def test_the_listener_hears_every_job_and_which_is_the_last(self, window):
        heard = []
        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        window.watch_transcription_background(
            lambda job, result, error, last: heard.append((job.model_id, last)) or True
        )
        window.jobs[0].on_finished("ok", None)
        window.jobs[1].on_finished("ok", None)
        assert heard == [("tiny", False), ("base", True)]
        assert not window.transcription_background_running()

    def test_the_end_of_a_queue_says_how_many_arrived(self, window):
        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        window.jobs[0].on_finished("ok", None)
        window.said.clear()
        window.jobs[1].on_finished("ok", None)
        assert window.said[-1] == "transcription_queue_done"

    def test_a_single_job_does_not_announce_a_queue(self, window):
        window.start_transcription_background_jobs(_items(window, "tiny"))
        window.said.clear()
        window.jobs[0].on_finished("ok", None)
        assert "transcription_queue_done" not in window.said

    def test_the_first_failure_drops_what_was_behind_it(self, window):
        from core.transcription import errors

        window.start_transcription_background_jobs(_items(window, "tiny", "base", "small"))
        window.said.clear()
        window.jobs[0].on_finished(None, errors.TranscriptionError(errors.NO_DISK_SPACE, "d"))
        assert len(window.jobs) == 1
        assert not window.transcription_background_running()
        assert "transcription_queue_stopped" in window.said

    def test_a_next_job_that_cannot_start_ends_the_run_for_the_listeners(self, window):
        """The listener heard "more to come"; it must hear the end too, or the
        Settings tab would stay with every button off and a dead Cancel."""
        heard = []
        items = _items(window, "tiny", "base")

        def broken(on_progress, on_finished):
            raise RuntimeError("cannot build")

        items[1] = (broken,) + tuple(items[1][1:])
        window.start_transcription_background_jobs(items)
        window.watch_transcription_background(
            lambda job, result, error, last: heard.append(
                (getattr(job, "model_id", None), last)) or True)
        window.jobs[0].on_finished("ok", None)
        assert heard == [("tiny", False), (None, True)]
        assert not window.transcription_background_running()
        assert window.said[-1] == "transcription_queue_stopped"

    def test_a_stop_by_the_last_job_does_not_claim_a_rest(self, window):
        from core.transcription import errors

        window.start_transcription_background_jobs(_items(window, "tiny"))
        window.said.clear()
        window.jobs[0].on_finished(None, errors.TranscriptionError(errors.NO_DISK_SPACE, "d"))
        assert "transcription_queue_stopped" not in window.said


class TestCancelling:
    def test_nothing_running_is_nothing_to_cancel(self, window):
        assert window.cancel_transcription_background() is False

    def test_it_stops_the_job_and_drops_the_queue(self, window):
        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        assert window.cancel_transcription_background() is True
        assert window.jobs[0].cancelled
        # The job reports CANCELLED through the usual path, and nothing starts.
        from core.transcription import errors

        window.jobs[0].on_finished(None, errors.TranscriptionError(errors.CANCELLED, "x"))
        assert len(window.jobs) == 1
        assert not window.transcription_background_running()

    def test_a_cancelled_queue_does_not_claim_a_rest_it_was_told_to_drop(self, window):
        from core.transcription import errors

        window.start_transcription_background_jobs(_items(window, "tiny", "base"))
        window.cancel_transcription_background()
        window.said.clear()
        window.jobs[0].on_finished(None, errors.TranscriptionError(errors.CANCELLED, "x"))
        assert "transcription_queue_stopped" not in window.said


class TestATabJobThatNeverStarted:
    """The progress dialog can answer with no job (one that never started):
    the tab still reports the action it was asked for, by the caller's own
    action, model and build, as it did before the background mode."""

    def _tab(self):
        from ui.dialogs.transcription_background import TranscriptionBackgroundTabMixin

        tab = types.SimpleNamespace(finished=[], reported=[],
                                    _transcription_model_marks={"base"})
        tab._transcription_background_wanted = lambda action: False
        tab.ran = []
        tab._run_transcription_job = (
            lambda action, **kwargs: tab.ran.append((action, kwargs)) or (None, None, None))
        tab._finish_whisper_cpp_job = (
            lambda action, build_id, job, result, error, restore_focus=True:
            tab.finished.append((action, build_id, job)))
        tab._report_transcription_job = (
            lambda action, model_id, job, result, error, extra_keys=(), restore_focus=True:
            tab.reported.append((action, model_id, job)))
        tab._after_transcription_job = (
            lambda *a, **k: TranscriptionBackgroundTabMixin._after_transcription_job(tab, *a, **k))
        return tab, TranscriptionBackgroundTabMixin

    def test_a_whisper_cpp_action_is_finished_with_its_build(self):
        tab, mixin = self._tab()
        mixin._start_transcription_job(tab, management.ACTION_VERIFY_WHISPER_CPP, build_id="cpu",
                                       compute_capability=(8, 6))
        assert tab.ran == [(management.ACTION_VERIFY_WHISPER_CPP,
                            {"build_id": "cpu", "compute_capability": (8, 6)})]
        assert tab.finished == [(management.ACTION_VERIFY_WHISPER_CPP, "cpu", None)]

    def test_a_model_action_is_reported_with_its_model(self):
        tab, mixin = self._tab()
        mixin._start_transcription_job(tab, management.ACTION_DOWNLOAD_MODEL, model_id="base")
        assert tab.ran == [(management.ACTION_DOWNLOAD_MODEL, {"model_id": "base"})]
        assert tab.reported == [(management.ACTION_DOWNLOAD_MODEL, "base", None)]
        # Nothing ran, so nothing arrived: the model stays marked.
        assert tab._transcription_model_marks == {"base"}
