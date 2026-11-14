"""The progress dialog a management action runs behind, and the two ways it
can go wrong without ever failing a test that only looks at the end result.

* **A wx control driven from the job's thread.** `ManagementJob` imports no wx
  on purpose and calls back from its own thread; every one of those callbacks
  has to cross to the wx thread through `wx.CallAfter`. Touching a control
  from two threads does not raise, does not log, and does not reproduce on the
  machine of whoever wrote it — it crashes somebody else's session.

* **One `wx.CallAfter` per megabyte.** model_store reports progress per 1 MB
  chunk, which is ~3000 reports for large-v3. Unthrottled that is ~3000
  cross-thread posts *and* a screen reader reading numbers for the length of
  the download; the throttle is what makes it a gauge move twice a second and
  three spoken figures, and the dialog gets it by not passing a throttle of
  its own.

* **A job that could not be started at all.** `RuntimeError: can't start new
  thread` inside the `wx.CallAfter` that starts it is caught by nothing: no
  report ever arrives, there is no close box, Cancel waits for that report and
  Escape reaches a Cancel that does not close — the settings window is locked
  behind a modal with no way out. It becomes a finished report instead.

Plus the two wx rules this dialog is shaped around: `EndModal()` on a loop
that is not running asserts, so the job is started from inside the loop; and
Cancel is cooperative, so the dialog stays until the job says it stopped — the
finished report is the only thing that can say what it managed to do first.

`TranscriptionProgressDialog` itself is never constructed here: it is a
wx.Dialog, which this suite may not put on the desktop at all (see
tests/test_no_desktop_visible_windows.py). Its own methods are bound onto a
plain stub instead — the house pattern.
"""


from tests.locales import load_strings, registered_locale_codes
import pytest

from core.transcription import errors, management
from ui.dialogs import transcription_progress
from ui.dialogs.transcription_progress import TranscriptionProgressDialog

_MB = 1024 * 1024


LOCALES = registered_locale_codes()


class _I18n:
    """The real translation table, so the assertions are about real strings."""

    def __init__(self, locale="pt-BR"):
        self.language = locale
        self._table = load_strings(locale)

    def t(self, key):
        return self._table.get(key, key)


class _SpeakOutput:
    """MainWindow.speak_output, minus accessible_output2.

    Spelled `output()` and nothing else: that is the single funnel every
    announcement in the app goes through, and what makes the two Settings >
    Acessibilidade toggles apply to this dialog too.
    """

    def __init__(self):
        self.spoken = []
        self.interrupts = []

    def output(self, text, interrupt=False):
        self.spoken.append(text)
        self.interrupts.append(interrupt)


class _Gauge:
    def __init__(self):
        self.values = []
        self.pulses = 0

    def SetValue(self, value):
        self.values.append(value)

    def Pulse(self):
        self.pulses += 1


class _Label:
    def __init__(self, label=""):
        self._label = label

    def SetLabel(self, label):
        self._label = label

    def GetLabel(self):
        return self._label


class _Button:
    def __init__(self):
        self.enabled = True

    def Disable(self):
        self.enabled = False


class _Dialog:
    """The dialog's own methods on a plain object, with wx swapped for lists."""

    def __init__(self, action=management.ACTION_DOWNLOAD_MODEL, model_id="small",
                 locale="pt-BR", job=None, modal=True, status="Baixando..."):
        self._i18n = _I18n(locale)
        self._speak_output = _SpeakOutput()
        self._status = status
        self._gauge = _Gauge()
        self._status_label = _Label(status)
        self._cancel_btn = _Button()
        self._cancel_requested = False
        self.result = None
        self.error = None
        self.job = job if job is not None else management.ManagementJob(
            action, model_id=model_id
        )
        self._modal = modal
        self.ended = None
        self.layouts = 0

    # The wx.Dialog half this stub stands in for.
    def IsModal(self):
        return self._modal

    def EndModal(self, code):
        self.ended = code

    def Layout(self):
        self.layouts += 1

    _post_progress = TranscriptionProgressDialog._post_progress
    _post_finished = TranscriptionProgressDialog._post_finished
    _on_progress = TranscriptionProgressDialog._on_progress
    _on_finished = TranscriptionProgressDialog._on_finished
    _on_cancel = TranscriptionProgressDialog._on_cancel
    _start_job = TranscriptionProgressDialog._start_job
    set_status = TranscriptionProgressDialog.set_status


@pytest.fixture
def posted(monkeypatch):
    """Everything handed to wx.CallAfter, as (callable, args) in order."""
    calls = []
    monkeypatch.setattr(
        transcription_progress.wx,
        "CallAfter",
        lambda func, *args, **kwargs: calls.append((func, args)),
    )
    return calls


def _tick(done, total, percent, update_bar=True, speak=False):
    return management.ProgressTick(done, total, percent, update_bar, speak)


class TestNothingFromTheJobsThreadTouchesAControl:
    """The whole reason `_post_*` exists as a separate pair of methods."""

    def test_progress_crosses_to_the_wx_thread(self, posted):
        dialog = _Dialog()
        tick = _tick(1, 2, 50, speak=True)
        dialog._post_progress(tick)
        assert [func for func, _args in posted] == [dialog._on_progress]
        assert posted[0][1] == (tick,)
        # And nothing was drawn or said on the way past.
        assert dialog._gauge.values == []
        assert dialog._speak_output.spoken == []

    def test_the_finished_report_crosses_too(self, posted):
        dialog = _Dialog()
        failure = errors.TranscriptionError(errors.MODEL_DOWNLOAD_FAILED, "no")
        dialog._post_finished("done", failure)
        assert [func for func, _args in posted] == [dialog._on_finished]
        assert posted[0][1] == ("done", failure)
        assert dialog.ended is None

    def test_the_dialog_hands_the_factory_the_posting_pair(self):
        """A regression guard with teeth: handing `_on_progress` straight to
        the factory would pass every test that only checks what the gauge ends
        up at."""
        import ast
        import inspect

        source = inspect.getsource(TranscriptionProgressDialog.__init__)
        tree = ast.parse(source.lstrip())
        handed = [
            [getattr(arg, "attr", None) for arg in node.args]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "make_job"
        ]
        assert handed == [["_post_progress", "_post_finished"]]


class TestTheThrottleIsWhatKeepsThisUsable:
    """~3000 reports for large-v3, and the dialog must not post 3000 times."""

    def test_a_three_gigabyte_download_does_not_post_once_per_megabyte(self, posted):
        dialog = _Dialog()
        now = [0.0]
        # The real job, with its real default throttle — the dialog gets the
        # throttling by *not* supplying one, so a dialog that passed its own
        # would fail here rather than in the field.
        job = management.ManagementJob(
            management.ACTION_DOWNLOAD_MODEL,
            model_id="large-v3",
            on_progress=dialog._post_progress,
            clock=lambda: now[0],
        )
        total = 3000 * _MB
        for chunk in range(1, 3001):
            now[0] = chunk * 0.01  # a 30-second download
            job._report_progress(chunk * _MB, total)

        assert posted, "the bar has to move at all"
        # 30 seconds at one bar move per half second, plus the three spoken
        # milestones. Two orders of magnitude below one per chunk.
        assert len(posted) < 100

    def test_the_three_quarters_are_the_only_thing_said_out_loud(self, posted):
        dialog = _Dialog()
        now = [0.0]
        job = management.ManagementJob(
            management.ACTION_DOWNLOAD_MODEL,
            model_id="large-v3",
            on_progress=dialog._post_progress,
            clock=lambda: now[0],
        )
        for chunk in range(1, 1001):
            now[0] = chunk * 0.01
            job._report_progress(chunk * _MB, 1000 * _MB)
        for func, args in posted:
            func(*args)
        assert dialog._speak_output.spoken == ["25%", "50%", "75%"]
        # The end belongs to the finished sentence, never to the progress.
        assert dialog._gauge.values[-1] == 100


class TestWhatTheDialogShows:
    def test_a_measured_percentage_moves_the_bar(self):
        dialog = _Dialog()
        dialog._on_progress(_tick(1, 4, 25))
        assert dialog._gauge.values == [25]
        assert dialog._gauge.pulses == 0

    def test_an_unknown_total_pulses_instead_of_claiming_a_figure(self):
        dialog = _Dialog()
        dialog._on_progress(_tick(17, None, None))
        assert dialog._gauge.pulses == 1
        assert dialog._gauge.values == []

    def test_a_tick_the_throttle_did_not_pass_for_the_bar_draws_nothing(self):
        dialog = _Dialog()
        dialog._on_progress(_tick(1, 4, 25, update_bar=False, speak=True))
        assert dialog._gauge.values == []
        assert dialog._speak_output.spoken == ["25%"]

    def test_the_figure_never_interrupts_the_screen_reader(self):
        """Cutting the reader off mid-sentence to say "50%" is worse than the
        figure arriving a moment later."""
        dialog = _Dialog()
        dialog._on_progress(_tick(1, 2, 50, speak=True))
        assert dialog._speak_output.interrupts == [False]

    def test_the_bar_moving_is_not_on_its_own_a_reason_to_speak(self):
        dialog = _Dialog()
        dialog._on_progress(_tick(1, 3, 33))
        assert dialog._speak_output.spoken == []

    @pytest.mark.parametrize("locale", LOCALES)
    def test_every_action_says_what_it_is_doing_in_every_language(self, locale):
        i18n = _I18n(locale)
        for action in management.ACTIONS:
            text = transcription_progress.progress_status_text(i18n, action, "medium")
            assert text, (locale, action)
            assert "{" not in text and "}" not in text, (locale, action)
        for action in management.MODEL_ACTIONS:
            # A model action that does not name the model leaves the user with
            # four buttons and no way to tell which one is running.
            assert "medium" in transcription_progress.progress_status_text(
                i18n, action, "medium"
            ), (locale, action)
        for action in management.WHISPER_CPP_ACTIONS:
            # The same for the program: two builds, and the line says which.
            assert "BUILD" in transcription_progress.progress_status_text(
                i18n, action, build="BUILD"
            ), (locale, action)


class TestTheEnd:
    def test_a_finished_action_closes_the_dialog_and_keeps_its_answer(self):
        dialog = _Dialog()
        dialog._on_finished(("ok",), None)
        assert dialog.result == ("ok",)
        assert dialog.error is None
        assert dialog.ended is not None

    def test_a_failure_keeps_its_error_and_still_closes(self):
        dialog = _Dialog()
        failure = errors.TranscriptionError(errors.NO_DISK_SPACE, "full")
        dialog._on_finished(None, failure)
        assert dialog.error is failure
        assert dialog.ended is not None

    def test_a_report_arriving_before_the_loop_runs_does_not_call_endmodal(self):
        """EndModal() on a loop that is not running asserts — the same wx rule
        the pairing dialogs are built around. Unreachable while run() starts
        the job from inside the loop, which is exactly why it must stay that
        way."""
        dialog = _Dialog(modal=False)
        dialog._on_finished("whatever", None)
        assert dialog.ended is None
        assert dialog.result == "whatever"

    def test_the_job_is_started_from_inside_the_modal_loop(self):
        """`run()` may not call `job.start()` directly: a job that finished
        between start() and ShowModal() would have nothing to end."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(TranscriptionProgressDialog.run).lstrip())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        names = [node.func.attr for node in calls]
        assert "CallAfter" in names
        assert "ShowModal" in names
        assert "start" not in names


class TestCancelling:
    def test_cancel_asks_the_job_and_leaves_the_dialog_open(self):
        dialog = _Dialog()
        dialog._on_cancel()
        assert dialog.job.cancelled
        # Still open: the finished report is the only thing that can say what
        # the action managed to do before it stopped.
        assert dialog.ended is None

    def test_cancel_says_so_and_stops_offering_itself(self):
        dialog = _Dialog()
        dialog._on_cancel()
        assert dialog._status_label.GetLabel() == _I18n().t(
            "transcription_progress_cancelling"
        )
        assert dialog._cancel_btn.enabled is False

    def test_pressing_it_again_changes_nothing(self):
        """Not about Escape — wx only turns that into a click while the button
        is enabled and shown. It is about EVT_CLOSE: Alt+F4 reaches a dialog
        with no close box at any time, including after Cancel was pressed."""
        dialog = _Dialog()
        dialog._on_cancel()
        dialog.job.cancel = lambda: pytest.fail("cancelled twice")
        dialog._on_cancel()

    def test_a_cancelled_job_still_closes_through_its_own_report(self):
        dialog = _Dialog()
        dialog._on_cancel()
        dialog._on_finished(
            None, errors.TranscriptionError(errors.CANCELLED, "by the user")
        )
        assert dialog.ended is not None


class TestStartingTheJob:
    """A dialog with no close box whose Cancel waits for a report that never
    comes is the settings window locked shut."""

    def test_a_job_that_cannot_be_started_is_reported_rather_than_raised(self):
        """`RuntimeError: can't start new thread` is the real one. Nothing
        above a wx.CallAfter catches anything, so an exception here would end
        the dialog's only route to closing itself."""

        class _WillNotStart:
            def start(self):
                raise RuntimeError("can't start new thread")

            def cancel(self):
                pass

        dialog = _Dialog(job=_WillNotStart())
        dialog._start_job()
        assert dialog.error is not None
        assert dialog.error.code == errors.BACKEND_ERROR
        assert dialog.ended is not None

    def test_a_cancel_that_beat_the_start_still_closes_the_dialog(self):
        """A job cancelled before start() reports nothing at all, by design —
        so the dialog has to report that one itself or wait forever."""

        class _NeverStarted:
            def __init__(self):
                self.started = False

            def start(self):
                self.started = True

            def cancel(self):
                pass

        job = _NeverStarted()
        dialog = _Dialog(job=job)
        dialog._on_cancel()
        dialog._start_job()
        assert job.started is False
        assert dialog.error is not None
        assert dialog.error.code == errors.CANCELLED
        assert dialog.ended is not None

    def test_the_line_saying_what_is_running_is_spoken_when_it_starts(self):
        """A wx.StaticText is silent under JAWS and Narrator, and this line is
        the only thing that says *which* action is running."""

        class _Idle:
            def start(self):
                pass

            def cancel(self):
                pass

        dialog = _Dialog(job=_Idle(), status="Baixando o modelo small...")
        dialog._start_job()
        assert dialog._speak_output.spoken == ["Baixando o modelo small..."]
        assert dialog._speak_output.interrupts == [False]


class TestTheStatusLineCanChange:
    """Part 6's job has three phases, two of them with no fraction to report,
    and the line is what tells them apart."""

    def test_it_crosses_to_the_wx_thread_when_it_is_not_on_it(
        self, posted, monkeypatch
    ):
        """`set_status` is public, so part 6 reaches it from
        `TranscriptionJob.on_phase` — which runs on the job's thread, exactly
        like the two `_post_*` callbacks. The hop belongs here rather than in
        every caller's memory."""
        monkeypatch.setattr(transcription_progress.wx, "IsMainThread", lambda: False)
        dialog = _Dialog()
        dialog.set_status("A carregar o modelo...")

        assert [func for func, _args in posted] == [dialog.set_status]
        assert posted[0][1] == ("A carregar o modelo...",)
        # And nothing was drawn or said on the way past.
        assert dialog._status_label.GetLabel() != "A carregar o modelo..."
        assert dialog._speak_output.spoken == []

    def test_on_the_wx_thread_it_simply_does_it(self, posted, monkeypatch):
        monkeypatch.setattr(transcription_progress.wx, "IsMainThread", lambda: True)
        dialog = _Dialog()
        dialog.set_status("A carregar o modelo...")
        assert posted == []
        assert dialog._status_label.GetLabel() == "A carregar o modelo..."

    def test_setting_it_shows_and_says_it(self):
        dialog = _Dialog()
        dialog.set_status("A carregar o modelo...")
        assert dialog._status_label.GetLabel() == "A carregar o modelo..."
        assert dialog._speak_output.spoken == ["A carregar o modelo..."]
        assert dialog._speak_output.interrupts == [False]

    def test_cancelling_says_so_out_loud_and_not_only_on_screen(self):
        dialog = _Dialog()
        dialog._on_cancel()
        assert dialog._speak_output.spoken == [
            _I18n().t("transcription_progress_cancelling")
        ]
