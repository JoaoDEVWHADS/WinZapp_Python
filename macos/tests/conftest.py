"""macOS layer test configuration.

WinZapp's own tests skip dialog tests unless run with --run-wx-gui, and
tests/test_no_desktop_visible_windows.py requires every CI workflow that
runs pytest to pass it. The macOS layer's tests never show a window (frames
are created but never Show()n), so the flag changes nothing here; it is
accepted so the macOS workflow satisfies that guard like every other.
"""


def pytest_addoption(parser):
    parser.addoption("--run-wx-gui", action="store_true", default=False,
                     help="accepted for parity with WinZapp's suite; no effect here")
