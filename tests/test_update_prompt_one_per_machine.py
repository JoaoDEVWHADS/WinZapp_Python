"""Tests for the machine-wide update-prompt claim primitives.

The prompt claim lives in update_coord.py.  Older versions of this test also
copied private UpdateChecker helpers that are no longer part of the current
updater implementation; keeping those copies made test collection fail before
any assertions could run.  This module now tests the coordination contract at
the layer that actually owns it.
"""

import json
import os
import types

import pytest

import update_coord
import updater
from updater import UpdateChecker


@pytest.fixture
def gd(tmp_path):
    return str(tmp_path)


def _alive(pid, create_time):
    return True


def _dead(pid, create_time):
    return False


class TestTheClaim:
    def test_the_first_caller_gets_it(self, gd):
        token = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert token is not None
        assert len(token["owner_token"]) == 32

    def test_a_second_process_is_refused_while_the_first_is_live(self, gd):
        update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=222, create_time=2.0, is_alive=_alive
        ) is None

    def test_it_blocks_regardless_of_the_version_being_offered(self, gd):
        update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert update_coord.try_claim_update_prompt(
            gd, "0.27.0.0beta", pid=222, create_time=2.0, is_alive=_alive
        ) is None

    def test_a_dead_holder_never_blocks_anyone(self, gd):
        update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=222, create_time=2.0, is_alive=_dead
        ) is not None

    def test_the_same_process_may_re_claim(self, gd):
        first = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        second = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert second is not None
        assert second["owner_token"] != first["owner_token"]


class TestTheRelease:
    def test_releasing_lets_the_next_account_ask(self, gd):
        token = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        assert update_coord.release_update_prompt(gd, token) is True
        assert update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=222, create_time=2.0, is_alive=_alive
        ) is not None

    def test_a_stale_token_cannot_release_a_newer_claim(self, gd):
        old = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )
        update_coord.release_update_prompt(gd, old)
        update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )

        assert update_coord.release_update_prompt(gd, old) is False
        assert update_coord.update_prompt_holder(gd, is_alive=_alive) is not None


class TestItFailsInTheSafeDirection:
    def test_a_corrupt_claim_does_not_suppress_the_prompt(self, gd):
        path = os.path.join(gd, "update_prompt.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json at all")

        assert update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        ) is not None

    def test_a_claim_with_a_bad_owner_is_cleared_rather_than_trusted(self, gd):
        path = os.path.join(gd, "update_prompt.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "owner_pid": "not-a-pid",
                    "owner_create_time": 1.0,
                    "owner_token": "0" * 32,
                },
                f,
            )

        assert update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        ) is not None


class TestHolderInspection:
    def test_live_holder_is_reported(self, gd):
        token = update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )

        holder = update_coord.update_prompt_holder(gd, is_alive=_alive)

        assert holder is not None
        assert holder["owner_token"] == token["owner_token"]
        assert holder["owner_pid"] == 111

    def test_dead_holder_is_cleaned_up(self, gd):
        update_coord.try_claim_update_prompt(
            gd, "0.26.0.0beta", pid=111, create_time=1.0, is_alive=_alive
        )


@pytest.fixture
def as_separate_processes(monkeypatch):
    """Route the checker's claim through the real coordinator, but with each
    stub's own pid and a liveness answer that does not depend on those pids
    existing on the machine running the tests."""
    real = update_coord.try_claim_update_prompt

    def _claim(global_dir, version, **kw):
        import inspect as _inspect
        caller = _inspect.currentframe().f_back.f_locals.get("self")
        pid = getattr(caller, "_pid", None) or 111
        return real(global_dir, version, pid=pid, create_time=float(pid),
                    is_alive=_alive)

    monkeypatch.setattr(update_coord, "try_claim_update_prompt", _claim)


class TestTheCheckerUsesIt:
    def test_two_accounts_only_one_prompt(self, gd, as_separate_processes):
        a, b = _StubChecker(gd, pid=111), _StubChecker(gd, pid=222)
        assert a._claim_prompt("0.26.0.0beta") is True
        assert b._claim_prompt("0.26.0.0beta") is False

    def test_declining_hands_it_back(self, gd, as_separate_processes):
        a, b = _StubChecker(gd, pid=111), _StubChecker(gd, pid=222)
        a._claim_prompt("0.26.0.0beta")
        a._release_prompt()
        assert b._claim_prompt("0.26.0.0beta") is True

    def test_no_global_dir_means_no_coordination(self, tmp_path):
        """A single-account or dev run has no shared directory — and no second
        account to duplicate the dialog for."""
        checker = _StubChecker(None)
        assert checker._claim_prompt("0.26.0.0beta") is True
        assert checker._prompt_token is None

    def test_it_fails_open(self, gd, monkeypatch):
        """A prompt that cannot be coordinated is worth far more than a prompt
        suppressed by a bug in the coordination."""
        def _boom(*a, **kw):
            raise RuntimeError("coordination is broken")
        monkeypatch.setattr(update_coord, "try_claim_update_prompt", _boom)

        assert _StubChecker(gd)._claim_prompt("0.26.0.0beta") is True


class TestTheClaimIsHeldAcrossTheInstall:
    def test_saying_yes_does_not_release_before_installing(self):
        """Releasing on ID_YES would let another account open its own dialog
        while this one is already downloading and about to relaunch the shared
        install directory."""
        src = inspect.getsource(UpdateChecker._show_update_dialog)
        yes_branch = src[src.index("if result == wx.ID_YES:"):src.index("else:")]
        assert "_release_prompt" not in yes_branch
        assert "_do_install" in yes_branch

    @pytest.mark.parametrize("modal_result, retries", [
        (updater.wx.ID_CANCEL, 1),
        (updater.wx.ID_OK, 0),
        (updater.wx.ID_ABORT, 1),
    ], ids=["cancelled", "dev-mode", "declined-retry"])
    def test_every_install_exit_that_leaves_us_running_releases_it(
            self, gd, as_separate_processes, monkeypatch, modal_result, retries):
        """Exercise settled non-launch outcomes through the public install
        entry point: another account must be able to prompt afterwards.
        Completion may live in a helper without weakening this invariant."""
        checker = _StubChecker(gd, pid=111)
        other = _StubChecker(gd, pid=222)
        assert checker._claim_prompt("9.9.9")
        assert not other._claim_prompt("9.9.9")
        exits, scheduled, discarded, destroyed = [], [], [], []
        checker._mw.real_exit = lambda: exits.append(True)
        checker._mw.i18n = types.SimpleNamespace(t=lambda key: key)
        checker._schedule_retry = lambda: scheduled.append(True)
        checker._do_install = types.MethodType(UpdateChecker._do_install, checker)
        dialog = types.SimpleNamespace(
            _install_ok=False, _error_msg="synthetic prelaunch failure",
            run=lambda: modal_result, Destroy=lambda: destroyed.append(True),
        )
        monkeypatch.setattr(updater, "UpdateProgressDialog", lambda *a, **kw: dialog)
        monkeypatch.setattr(updater, "bring_to_front_if_hidden", lambda *a: None)
        monkeypatch.setattr(updater, "message_box", lambda *a, **kw: updater.wx.NO)
        monkeypatch.setattr(updater, "discard_package", discarded.append)

        checker._do_install("9.9.9", "https://example.invalid/update.zip",
                            extracted_dir="synthetic-package")

        assert not exits and not checker._install_pending
        assert len(scheduled) == retries
        assert destroyed == [True] and discarded == ["synthetic-package"]
        assert checker._prompt_token is None
        assert other._claim_prompt("9.9.9"), "settled non-launch must hand the prompt back"
