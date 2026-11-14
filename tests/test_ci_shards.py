"""CI splits the suite across jobs and workers without leaving a test out.

tests/ci_shards.py explains the split. What has to stay true is checked here:
every test module lands in exactly one shard, every workflow that shards runs
all of them and fails when one does, and the modules that put real windows up
are kept on one worker.
"""

import pathlib
import re
from types import SimpleNamespace

import pytest
import yaml

from tests import conftest
from tests.ci_shards import (SHARD_SALT, WX_DESKTOP_GROUP, creates_real_windows, parse_shard,
                             shard_of)

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
WORKFLOWS = ROOT / ".github" / "workflows"
SHARDED = ("ci.yml", "alpha-release.yml", "release.yml", "test-build.yml")


def _modules():
    return sorted(p.name for p in TESTS.glob("test_*.py"))


class TestTheShardOption:
    def test_k_of_n(self):
        assert parse_shard("2/4") == (2, 4) and parse_shard(" 1 / 1 ") == (1, 1)
        assert parse_shard(None) is None and parse_shard("") is None

    @pytest.mark.parametrize("value", ["0/4", "5/4", "4", "a/b", "2-4"])
    def test_anything_else_is_refused(self, value):
        with pytest.raises(ValueError):
            parse_shard(value)

    def test_without_it_nothing_is_ignored(self):
        config = SimpleNamespace(getoption=lambda name: None)
        assert conftest.pytest_ignore_collect(TESTS / "test_database.py", config) is None


class TestEveryModuleRunsOnce:
    @pytest.mark.parametrize("count", [1, 2, 3, 4, 7])
    def test_every_module_lands_in_exactly_one_shard(self, count):
        for name in _modules():
            kept = []
            for index in range(1, count + 1):
                config = SimpleNamespace(getoption=lambda option, i=index: f"{i}/{count}")
                if conftest.pytest_ignore_collect(TESTS / name, config) is None:
                    kept.append(index)
            assert kept == [shard_of(name, count)], name

    def test_the_shard_of_a_module_never_changes(self):
        """Stable across machines and runs: crc32, not Python's salted hash()."""
        assert shard_of("test_database.py", 4) == shard_of("test_database.py", 4)
        assert SHARD_SALT == "22"

    def test_what_is_not_a_test_module_is_left_to_pytest(self):
        config = SimpleNamespace(getoption=lambda name: "1/4")
        for path in (TESTS / "conftest.py", TESTS / "ci_shards.py", TESTS / "locales.py",
                     TESTS, ROOT / "macos" / "tests"):
            assert conftest.pytest_ignore_collect(path, config) is None, path

    def test_no_shard_is_left_empty_or_far_heavier(self):
        loads = [0, 0, 0, 0]
        for name in _modules():
            loads[shard_of(name, 4) - 1] += 1
        assert min(loads) > 0 and max(loads) <= 2 * min(loads), loads


class TestTheWorkflowsRunEveryShard:
    @pytest.mark.parametrize("workflow", SHARDED)
    def test_the_matrix_covers_the_n_the_command_splits_into(self, workflow):
        jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"]
        shard_job = jobs["test-shard"]
        commands = [step["run"] for step in shard_job["steps"] if "pytest" in str(step.get("run", ""))]
        [command] = commands
        count = int(re.search(r"--shard \$\{\{ matrix\.shard \}\}/(\d+)", command).group(1))
        assert shard_job["strategy"]["matrix"]["shard"] == list(range(1, count + 1))
        assert shard_job["strategy"]["fail-fast"] is False
        assert "--run-wx-gui" in command and "-n auto" in command

    @pytest.mark.parametrize("workflow", SHARDED)
    def test_one_verdict_under_the_old_name_fails_when_a_shard_does(self, workflow):
        jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"]
        verdict = jobs["test"]
        assert verdict["name"] == "Run test suite" and verdict["needs"] == "test-shard"
        assert "always()" in str(verdict["if"])
        assert verdict["steps"][-1]["run"] == 'test "${{ needs.test-shard.result }}" = "success"'

    def test_only_ci_workflows_use_workers(self):
        """-n froze a developer machine next to a live WinZapp (CLAUDE.md)."""
        assert "-n " not in (ROOT / "pytest.ini").read_text(encoding="utf-8")


class TestRealWindowsShareOneWorker:
    def test_every_module_marked_wxgui_is_detected(self):
        marked = [name for name in _modules()
                  if "pytest.mark.wxgui" in (TESTS / name).read_text(encoding="utf-8")]
        assert marked
        for name in marked:
            assert creates_real_windows((TESTS / name).read_text(encoding="utf-8")), name

    @pytest.mark.parametrize("source, expected", [
        ("with hidden_frame() as frame:", True),
        ("app = wx.App()", True),
        ("def test_x(wx_app):", True),
        ("dialog = wx.Dialog(None)", True),
        ("assert 'stub' in panel", False),
    ])
    def test_the_detection(self, source, expected):
        assert creates_real_windows(source) is expected

    def test_the_group_reaches_xdist_before_xdist_reads_it(self):
        """xdist turns the marker into the item's group in its own
        collection_modifyitems; ours must run first."""
        source = (TESTS / "conftest.py").read_text(encoding="utf-8")
        assert "@pytest.hookimpl(tryfirst=True)\ndef pytest_collection_modifyitems" in source
        assert f"xdist_group(WX_DESKTOP_GROUP)" in source and WX_DESKTOP_GROUP == "wx_desktop"
