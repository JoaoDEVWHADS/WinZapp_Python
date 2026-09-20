"""Two user-visible promises about the WPPConnect version, both broken.

Reported together by a user trying to move an install onto a newer
wppconnect-server:

1. **Force reinstall reinstalled the same version.** Help > "Forçar
   reinstalação da WPPConnect" documents, in two places, "always fetches
   whatever is currently the latest release, regardless of version". It called
   `_fetch_latest_tag()`, which returned the *homologated* tag whenever one was
   bundled — which is always, in a release build. Three forced reinstalls, each
   reported successful, `package.json` unchanged at 2.10.16.

2. **The outdated-version warning never appeared.** Raising
   `client/wpp_minimum_version.txt` above the installed version produced no
   prompt at all: WinZapp came up on the old server without a word.
   `ensure_wpp_version()` guarded on `api/dist/main.js`, and WPPConnect Server
   has never built a file by that name — `npm run build` produces
   `dist/server.js`. The guard was always false, so the method always returned
   on its first statement and the entire prompt has never run for anyone.

Fixing (2) exposed a third defect underneath it, which is the reason a dead
code path is worth being suspicious of rather than merely fixing: the prompt's
own "Update now" button passed the bare version ("2.10.18") as
ApiSetupDialog's forced_tag, which goes straight into
`.../archive/refs/tags/{tag}.zip`. The release is tagged "v2.10.18", so that
URL is a 404. The button could never have worked.
"""

import inspect
import re

import pytest

import main
import updater
from main import MainWindow


class TestForceReinstallTracksLatestMain:
    def test_force_reinstall_uses_the_shared_latest_lookup(self):
        source = inspect.getsource(updater.WppUpdateChecker._force_reinstall_worker)
        assert "tag = self._fetch_latest_tag()" in source

    def test_the_lookup_delegates_to_api_setup(self):
        source = inspect.getsource(updater.WppUpdateChecker._fetch_latest_tag)
        assert "fetch_latest_wpp_tag()" in source

    def test_the_periodic_check_uses_the_same_remote_lookup(self):
        source = inspect.getsource(updater.WppUpdateChecker._check_once)
        assert "tag = self._fetch_latest_tag()" in source

    def test_the_periodic_check_compares_commit_identity(self):
        source = inspect.getsource(updater.WppUpdateChecker._check_once)
        assert "remote_version != installed" in source
        assert "_version_is_older" not in source


class TestRollingCommitMarker:
    def test_a_fresh_semver_install_can_be_seeded_with_the_remote_sha(self):
        source = inspect.getsource(updater.WppUpdateChecker._check_once)
        assert 'if "." in installed and "." not in remote_version' in source
        assert '".commit_sha"' in source

    def test_the_remote_identifier_is_not_parsed_as_semver(self):
        source = inspect.getsource(updater.WppUpdateChecker._check_once)
        assert "Version(" not in source
        assert "parse_version(" not in source


class TestTheStartupGateCanActuallyRun:
    @staticmethod
    def _source():
        return inspect.getsource(MainWindow.ensure_wpp_version)

    def test_it_no_longer_guards_on_a_file_that_is_never_built(self):
        """`npm run build` produces dist/server.js. dist/main.js has never
        existed, so this guard was always false and the whole method returned
        on its first statement."""
        source = self._source()
        assert '"main.js"' not in source

    def test_it_guards_on_the_built_entry_point(self):
        source = self._source()
        assert re.search(r'resource_path\(\s*"api",\s*"dist",\s*"server\.js"\s*\)',
                         source)

    def test_the_update_button_passes_a_real_git_tag(self):
        """forced_tag goes straight into .../archive/refs/tags/{tag}.zip. The
        bare version built a 404, which nobody could discover while the guard
        above kept this code unreachable."""
        source = self._source()
        assert "homologated_wpp_tag(" in source
        assert not re.search(r"forced_tag\s*=\s*minimum\s*,", source)


class TestTheGuardMatchesWhatTheInstallerBuilds:
    def test_the_setup_dialog_uses_the_same_file_as_its_built_marker(self):
        """Both answer "is the API installed and built". Two different files
        for one question is how the startup gate ended up watching a name that
        is never produced."""
        from ui.dialogs import api_setup
        source = inspect.getsource(api_setup.ApiSetupDialog._run_setup)
        assert '"dist", "server.js"' in source
