"""Tests for the machine-wide update-prompt claim primitives.

The prompt claim lives in update_coord.py.  Older versions of this test also
copied private UpdateChecker helpers that are no longer part of the current
updater implementation; keeping those copies made test collection fail before
any assertions could run.  This module now tests the coordination contract at
the layer that actually owns it.
"""

import json
import os

import pytest

import update_coord


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

        assert update_coord.update_prompt_holder(gd, is_alive=_dead) is None
        assert not os.path.exists(os.path.join(gd, "update_prompt.json"))
