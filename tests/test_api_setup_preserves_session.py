"""Tests that reinstalling/updating WPPConnect does not destroy the paired
WhatsApp session.

ApiSetupDialog's full-setup path wipes client/api/ before extracting the
freshly downloaded upstream ZIP, keeping only what _PRESERVE and
_KEEP_RUNTIME name. The session's stored token lives in client/api/tokens/
— wppconnect-server runs with `tokenStoreType: 'file'` (src/config.ts) and
its FileTokenStore defaults to `path: './tokens'` resolved against
process.cwd(), which _start_wpp_background() sets to client/api/.

That folder was missing from _KEEP_RUNTIME, so every full reinstall or
version update deleted the saved WhatsApp Web credentials while leaving the
Chrome profile (userDataDir) behind, and WinZapp's own settings still
claiming the account was paired. createSessionUtil.ts's own WinZapp patch
spells out what that costs: "The saved WhatsApp Web credentials are then
gone for good and the next start looks like a logout, even though the phone
still lists the linked device." Reported live as "ao reinstalar a
WPPConnect o programa fica em modo offline permanente, mesmo ao reiniciar".

The dialog itself needs wx, so these tests read the module's constants and
exercise the keep/delete decision directly rather than running the install.
"""

import os
import re

import pytest

wx = pytest.importorskip("wx")

from ui.dialogs.api_setup import _KEEP_RUNTIME, _PRESERVE


def _survives_the_clean_step(name: str) -> bool:
    """The exact condition ApiSetupDialog._run_setup()'s clean loop uses."""
    return name in _PRESERVE or name in _KEEP_RUNTIME


class TestRuntimeStateSurvivesAReinstall:
    def test_the_session_token_store_is_kept(self):
        assert _survives_the_clean_step("tokens")

    def test_the_chrome_profile_is_kept(self):
        assert _survives_the_clean_step("userDataDir")

    def test_winzapps_own_root_files_are_kept(self):
        assert _survives_the_clean_step("start.js")
        assert _survives_the_clean_step("config.json")

    def test_the_legacy_token_folder_name_is_still_kept(self):
        """Nothing writes to it any more, but an old install may still have
        one — deleting it would be the same data loss under an older name."""
        assert _survives_the_clean_step("wppconnect_tokens")

    def test_upstream_source_is_still_replaced(self):
        """The clean step has to keep doing its actual job: everything that
        comes from the downloaded ZIP gets wiped so a re-download really
        replaces it."""
        for name in ("src", "dist", "package.json", "node_modules", "prisma"):
            assert not _survives_the_clean_step(name)


class TestTokenStorePathMatchesWppconnectServer:
    """Pins the folder name against the vendored WPPConnect source rather
    than against a comment, so an upstream change to the default token-store
    path is caught here instead of silently costing users their session on
    the next reinstall. Skipped when client/api/ has not been set up (it is
    git-ignored — see setup_api.py)."""

    _SOURCE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "client", "api", "src", "util", "tokenStore",
        "FileTokenStore", "FileTokenStore.ts",
    )

    def test_the_default_path_is_the_folder_we_preserve(self):
        if not os.path.isfile(self._SOURCE):
            pytest.skip("client/api/ is not set up (run setup_api.py)")
        with open(self._SOURCE, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        match = re.search(r"path:\s*'\./([A-Za-z0-9_.-]+)'", source)
        assert match, "FileTokenStore no longer declares a default token path"
        assert _survives_the_clean_step(match.group(1))
