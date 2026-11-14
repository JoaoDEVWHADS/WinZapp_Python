"""Splitting the suite across CI jobs, and keeping real windows apart.

CI ran all ~22,000 tests in one process on a 4-vCPU runner: ~25 minutes, about
4 of them collecting (pytest rewrites the asserts of every test module, and a
fresh checkout has no cache to read them from) and the rest running one test
at a time. Two things now split that work, without leaving any test out:

* **Shards.** ``--shard K/N`` runs only the test modules whose stable hash
  lands on shard K, and conftest's ``pytest_ignore_collect`` skips the others
  before they are imported, so collection is split too, not just the run.
  Every module lands on exactly one shard of the N (``shard_of``), and the
  workflows run all N (tests/test_ci_shards.py checks both). Without the
  option nothing is left out: a developer's plain ``pytest`` is unchanged.
* **Workers.** Inside a shard CI adds ``-n auto`` (pytest-xdist). The
  modules that put real wx windows up — dialogs (the ``wxgui`` marker),
  ``conftest.hidden_frame()`` frames, a ``wx.App`` — share one ``xdist_group``
  so they run one after another on a single worker: windows of several
  processes at once would race for the desktop's focus, and a test that
  checks focus would pass or fail by luck.

``-n`` is for CI and cloud sessions only. In a local session, on a developer's
machine next to a live WinZapp, an ``-n auto`` run froze it (CLAUDE.md,
rule 7); a cloud session has nothing to freeze and may use it, with
``--shard`` too.
"""

import re
import zlib

#: The xdist group of every module that creates real wx windows.
WX_DESKTOP_GROUP = "wx_desktop"

_REAL_WINDOWS = re.compile(
    r"hidden_frame\(|wx\.App\(|\bwx_app\b|pytest\.mark\.wxgui|wx\.Frame\(|wx\.Dialog\(")


def parse_shard(value):
    """``"2/4"`` as ``(2, 4)``; None for no value. ValueError for anything
    that is not ``K/N`` with 1 <= K <= N."""
    if value in (None, ""):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(value))
    if not match:
        raise ValueError(f"--shard takes K/N, got {value!r}")
    index, count = int(match.group(1)), int(match.group(2))
    if not 1 <= index <= count:
        raise ValueError(f"--shard {value!r}: K must be between 1 and N")
    return index, count


#: Mixed into the hash only to even the shards out. Unsalted, 4 shards held
#: 7,471 / 4,846 / 4,626 / 5,644 tests (the slowest one sets CI's time); this
#: one, the best of 200 tried on 2026-10-18, gives 5,427 / 6,029 / 5,649 /
#: 5,482. Changing it moves files between shards and leaves none out.
SHARD_SALT = "22"


def shard_of(module_name, count) -> int:
    """The shard (1-based) a test module belongs to, out of *count*. Stable:
    the same file always lands on the same shard, on every machine."""
    return zlib.crc32((SHARD_SALT + module_name).encode("utf-8")) % count + 1


def creates_real_windows(source) -> bool:
    """Whether a test module's source puts real wx windows up."""
    return bool(_REAL_WINDOWS.search(source))
