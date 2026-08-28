"""Tests that the WPPConnect update releases the session's Chrome profile.

Two field reports, the same failure: after accepting a WPPConnect Server
update, WinZapp "keeps syncing forever, flipping between offline and normal".
The reported workaround is to close the app, wipe the account's data folder,
reopen and let it sync from scratch.

That workaround is the clue. Wiping `data/` does not touch the WPPConnect
install — it clears the stored token, which forces a NEW session name on the
next pairing, and therefore a Chrome profile directory nothing holds a lock on.
The update itself preserves `userDataDir/` and `tokens/`
(ApiSetupDialog._KEEP_RUNTIME), so the reinstall was never the problem.

The mechanism: `_stop_wpp_server()` force-kills the Node process tree, but a
chrome.exe can outlive it — exactly as a hibernation-suspended one does. The
restarted server's /start-session then hits

    The browser is already running for ...\\userDataDir\\<session>
    Auto Close Called

the session dies, the health check starts another, and the app alternates
between offline and connecting indefinitely.

`_kill_orphaned_chrome_for_session()` already solved this for the
wake-from-hibernation path, and its own docstring names the same symptom. It
simply was not wired into the update path.
"""

import inspect

import pytest

from connection_state import chrome_cmdline_owns_session
from main import MainWindow


SESSION = "cc8d691021302649a11de45e07c70711"


class TestTheUpdateReleasesTheProfile:
    @staticmethod
    def _source():
        return inspect.getsource(MainWindow._update_wpp_server)

    def test_the_orphan_killer_runs_during_the_update(self):
        assert "_kill_orphaned_chrome_for_session()" in self._source()

    def test_it_runs_after_the_stop_and_before_the_restart(self):
        """Killing before the server is stopped would race the shutdown;
        killing after it is back up is too late — start-session has already
        failed by then."""
        source = self._source()
        stop = source.index("self._stop_wpp_server()")
        kill = source.index("self._kill_orphaned_chrome_for_session()")
        restart = source.index("self.ensure_wpp_running()")
        assert stop < kill < restart

    def test_it_covers_the_failed_update_path_too(self):
        """_update_wpp_server restarts the server on BOTH branches — a
        cancelled or failed reinstall still calls ensure_wpp_running(). A lock
        left over there strands the user just as badly."""
        source = self._source()
        kill = source.index("self._kill_orphaned_chrome_for_session()")
        # Every restart must come after the single kill.
        restarts = [
            i for i in range(len(source))
            if source.startswith("self.ensure_wpp_running()", i)
        ]
        assert len(restarts) >= 2
        assert all(i > kill for i in restarts)

    def test_the_helper_still_exists_with_that_name(self):
        assert callable(getattr(MainWindow, "_kill_orphaned_chrome_for_session"))


class TestTheKillIsNarrow:
    """The update path now kills processes on a machine where the user's own
    Chrome is very likely running. The matcher is what keeps that safe."""

    def test_it_matches_this_sessions_browser(self):
        cmdline = (
            r"chrome.exe --user-data-dir=C:\WinZapp\api\userDataDir\%s --headless"
            % SESSION
        )
        assert chrome_cmdline_owns_session(cmdline, SESSION) is True

    def test_it_ignores_the_users_own_chrome(self):
        cmdline = (
            r'"C:\Program Files\Google\Chrome\Application\chrome.exe" '
            r'--user-data-dir=C:\Users\User\AppData\Local\Google\Chrome\User Data'
        )
        assert chrome_cmdline_owns_session(cmdline, SESSION) is False

    def test_it_ignores_another_accounts_session(self):
        other = "526fc15cc3a49c21ca9572e1bf698705"
        cmdline = r"chrome.exe --user-data-dir=C:\WinZapp\api\userDataDir\%s" % other
        assert chrome_cmdline_owns_session(cmdline, SESSION) is False

    def test_it_requires_a_userdatadir_segment(self):
        """The session name appearing anywhere else in a command line — a log
        path, an argument — must not be enough to kill a process."""
        cmdline = r"node.exe server.js --log C:\logs\%s.log" % SESSION
        assert chrome_cmdline_owns_session(cmdline, SESSION) is False

    @pytest.mark.parametrize("cmdline,session", [("", SESSION), ("chrome.exe", ""), ("", "")])
    def test_missing_inputs_never_match(self, cmdline, session):
        assert chrome_cmdline_owns_session(cmdline, session) is False
