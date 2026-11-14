"""How long a loaded transcription model stays in memory.

The timers are fakes the test fires by hand: nothing here sleeps, and nothing
starts a thread.
"""

import json
import os

from core.transcription import preferences, residency
from core.utils import DEFAULT_SETTINGS


class _Timer:
    def __init__(self, interval, function, args=()):
        self.interval = interval
        self.function = function
        self.args = args
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        assert self.started and not self.cancelled
        self.function(*self.args)


class _Backend:
    def __init__(self, fail=False):
        self.released = 0
        self.fail = fail

    def release(self):
        self.released += 1
        if self.fail:
            raise RuntimeError("boom")


def _residency(idle=60.0):
    timers = []

    def factory(interval, function, args=()):
        timer = _Timer(interval, function, args)
        timers.append(timer)
        return timer

    return residency.ModelResidency(idle_seconds=idle, timer_factory=factory), timers


def _live(timers):
    return [t for t in timers if t.started and not t.cancelled]


class TestTheSetting:
    def test_it_is_off_by_default_and_in_all_three_copies(self):
        assert preferences.DEFAULTS[preferences.SETTING_KEEP_MODEL_LOADED] is False
        assert DEFAULT_SETTINGS["transcription"]["keep_model_loaded"] is False
        base = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(base, "client", "data", "settings_default.json"),
                  encoding="utf-8") as handle:
            assert json.load(handle)["transcription"]["keep_model_loaded"] is False

    def test_the_key_is_spelled_the_same_in_both_modules(self):
        assert residency.SETTING_KEEP_MODEL_LOADED == preferences.SETTING_KEEP_MODEL_LOADED

    def test_only_a_real_true_turns_it_on(self):
        read = residency.keep_loaded_from_settings
        assert read({"transcription": {"keep_model_loaded": True}}) is True
        for stored in (False, None, "yes", 1, "true", []):
            assert read({"transcription": {"keep_model_loaded": stored}}) is False
        assert read({}) is False
        assert read({"transcription": "junk"}) is False
        assert read(None) is False


class TestIdleRelease:
    def test_the_model_is_released_after_the_idle_time(self):
        manager, timers = _residency(idle=42.0)
        backend = _Backend()
        with manager.using(backend):
            assert _live(timers) == []
        [timer] = _live(timers)
        assert timer.interval == 42.0 and timer.daemon is True
        timer.fire()
        assert backend.released == 1

    def test_nothing_is_released_while_a_run_uses_it(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            with manager.using(backend):
                pass
            assert _live(timers) == []
        assert len(_live(timers)) == 1

    def test_a_new_run_cancels_the_pending_release(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        [pending] = _live(timers)
        manager.begin_use(backend)
        assert pending.cancelled
        assert _live(timers) == []

    def test_a_timer_that_fires_during_a_run_releases_nothing(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        [pending] = _live(timers)
        manager.begin_use(backend)
        pending.cancelled = False  # the timer already fired as the run began
        pending.function(*pending.args)
        assert backend.released == 0

    def test_a_failed_run_still_starts_the_clock(self):
        manager, timers = _residency()
        backend = _Backend()
        try:
            with manager.using(backend):
                raise ValueError("the run failed")
        except ValueError:
            pass
        assert len(_live(timers)) == 1

    def test_each_backend_has_its_own_clock(self):
        manager, timers = _residency()
        first, second = _Backend(), _Backend()
        with manager.using(first):
            pass
        with manager.using(second):
            pass
        assert len(_live(timers)) == 2
        _live(timers)[0].fire()
        assert (first.released, second.released) == (1, 0)

    def test_a_backend_that_cannot_release_does_not_break_the_timer(self):
        manager, timers = _residency()
        backend = _Backend(fail=True)
        with manager.using(backend):
            pass
        _live(timers)[0].fire()
        assert backend.released == 1


class TestAStaleTimer:
    def test_a_timer_firing_late_does_not_take_the_next_ones_place(self):
        """begin_use() cancelled a timer that was already firing; it must not
        pop the timer the next run's end armed and release at once."""
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        stale = _live(timers)[0]
        with manager.using(backend):
            pass
        fresh = _live(timers)[0]
        assert fresh is not stale
        stale.function(*stale.args)  # the cancelled one runs anyway
        assert backend.released == 0
        assert _live(timers) == [fresh]
        fresh.fire()
        assert backend.released == 1


class TestKeepingItLoaded:
    def test_no_clock_starts_while_it_is_kept(self):
        manager, timers = _residency()
        manager.configure(True)
        backend = _Backend()
        with manager.using(backend):
            pass
        assert timers == []
        assert backend.released == 0

    def test_turning_it_on_cancels_what_is_pending(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        [pending] = _live(timers)
        manager.configure(True)
        assert pending.cancelled
        assert manager.keep_loaded is True

    def test_a_timer_already_fired_when_it_is_turned_on_releases_nothing(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        [pending] = _live(timers)
        manager.configure(True)
        pending.function(*pending.args)
        assert backend.released == 0

    def test_turning_it_off_starts_the_clock_for_an_idle_model(self):
        manager, timers = _residency()
        manager.configure(True)
        backend = _Backend()
        with manager.using(backend):
            pass
        manager.configure(False)
        [timer] = _live(timers)
        timer.fire()
        assert backend.released == 1

    def test_turning_it_off_leaves_a_model_in_use_alone(self):
        manager, timers = _residency()
        manager.configure(True)
        backend = _Backend()
        manager.begin_use(backend)
        manager.configure(False)
        assert _live(timers) == []
        manager.end_use(backend)
        assert len(_live(timers)) == 1

    def test_configuring_the_same_value_changes_nothing(self):
        manager, timers = _residency()
        backend = _Backend()
        with manager.using(backend):
            pass
        manager.configure(False)
        assert len(_live(timers)) == 1
