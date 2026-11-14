"""The updater may only quit the app when an installer is actually running.

Reported live, in dev mode: the app found a newer release, downloaded it,
extracted it, logged "Dev mode detected. Skipping real installation." — and
then exited, taking the WPPConnect server with it. A pairing was in progress at
the time, so the symptom was "Nenhum código de pareamento foi recebido": the
process generating the code had been killed by its own updater.

The cause is a lie in the dialog's answer. `_install_ok` means "a batch
installer is running and will relaunch this process", which is the caller's one
licence to call real_exit(). The dev-mode branch set it True while launching
nothing at all. The declined-UAC path used to tell the same lie and was fixed
the same way — see the run_elevated() call in updater._run_batch_installer().

UpdateProgressDialog is a wx.Dialog and UpdateChecker wants a real MainWindow,
so _do_install() is exercised as a plain function against stubs, the same way
tests/test_unread_reread_race.py drives MainWindow methods.
"""

import types

import pytest

import updater
from updater import UpdateChecker
from core.update_handoff import InstallHandoff
from update_progress import UpdateProgressLifecycle


class _Dialog:
    """Stands in for UpdateProgressDialog: whatever run() was told to answer."""

    def __init__(self, result, install_ok):
        self._result = result
        self._install_ok = install_ok
        self.destroyed = False
        self._error_msg = "boom"

    def run(self):
        return self._result

    def Destroy(self):
        self.destroyed = True


class _MainWindow:
    def __init__(self):
        self.exits = 0

    def real_exit(self):
        self.exits += 1


def _checker(monkeypatch, result, install_ok):
    """UpdateChecker with _do_install() bound, and its dialog replaced."""
    mw = _MainWindow()
    stub = types.SimpleNamespace(
        _mw=mw,
        _do_install=None,
        retries=0,
    )
    stub._schedule_retry = lambda: setattr(stub, "retries", stub.retries + 1)
    stub._get_active_parent = types.MethodType(UpdateChecker._get_active_parent, stub)
    # Every exit from _do_install() that leaves the app running hands the
    # cross-account prompt claim back, so the next account may be offered the
    # update. Counted here so a branch that stops doing it is visible.
    stub.releases = 0
    stub._release_prompt = lambda: setattr(stub, "releases", stub.releases + 1)
    stub._do_install = types.MethodType(UpdateChecker._do_install, stub)

    dialog = _Dialog(result, install_ok)
    monkeypatch.setattr(updater, "UpdateProgressDialog",
                        lambda *a, **kw: dialog)
    return stub, mw, dialog


class TestItOnlyExitsForAnInstallerThatIsActuallyRunning:
    @pytest.mark.parametrize("modal_result", [updater.wx.ID_CANCEL, updater.wx.ID_ABORT])
    def test_a_stale_modal_result_cannot_hide_a_running_installer(self, monkeypatch, modal_result):
        stub, mw, dialog = _checker(monkeypatch, modal_result, True)
        stub._do_install("9.9.9", "https://example.invalid/z.zip")
        assert mw.exits == 1 and dialog.destroyed
        assert (stub.retries, stub.releases) == (0, 0)
        assert stub._install_pending, "hold the in-process gate through real_exit"

    def test_a_real_install_still_quits_the_app(self, monkeypatch):
        """The frozen path: the batch script is running and is waiting for this
        process to exit before it can overwrite the files."""
        stub, mw, _dialog = _checker(monkeypatch, updater.wx.ID_OK, True)

        stub._do_install("9.9.9", "http://example/z.zip")

        assert mw.exits == 1

    def test_dev_mode_does_not_quit(self, monkeypatch):
        """Nothing was installed and nothing will relaunch us."""
        stub, mw, _dialog = _checker(monkeypatch, updater.wx.ID_OK, False)

        stub._do_install("9.9.9", "http://example/z.zip")

        assert mw.exits == 0

    def test_dev_mode_does_not_schedule_a_retry_either(self, monkeypatch):
        """There is nothing to retry: the download succeeded, the install is
        simply not applicable here. Re-prompting would reopen the dialog over
        and over for the rest of the dev session."""
        stub, mw, _dialog = _checker(monkeypatch, updater.wx.ID_OK, False)

        stub._do_install("9.9.9", "http://example/z.zip")

        assert stub.retries == 0

    def test_the_dialog_is_destroyed_either_way(self, monkeypatch):
        stub, _mw, dialog = _checker(monkeypatch, updater.wx.ID_OK, False)

        stub._do_install("9.9.9", "http://example/z.zip")

        assert dialog.destroyed

    def test_a_cancelled_update_retries_and_does_not_quit(self, monkeypatch):
        stub, mw, _dialog = _checker(monkeypatch, updater.wx.ID_CANCEL, False)

        stub._do_install("9.9.9", "http://example/z.zip")

        assert (mw.exits, stub.retries) == (0, 1)


class TestEarlyModalReturn:
    def test_pending_check_never_contacts_the_release_provider(self, monkeypatch):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_CANCEL, False)
        stub._install_pending = True
        stub._force = True
        UpdateChecker._check_once(stub)
        assert not stub._force and stub.retries == 1
        UpdateChecker._show_update_dialog(stub, "9.9.9", "zip", "sums")
        assert stub.releases == 0 and mw.exits == 0

    def test_retry_error_box_holds_the_gate_during_nested_events(self, monkeypatch):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_ABORT, False)
        mw.i18n = types.SimpleNamespace(t=lambda k: k)
        discarded = []
        monkeypatch.setattr(updater, "discard_package", discarded.append)
        def box(*a, **kw):
            assert stub._install_pending
            stub._do_install("9.9.9", "zip", extracted_dir="package")
            return updater.wx.NO
        monkeypatch.setattr(updater, "message_box", box)
        stub._do_install("9.9.9", "zip", extracted_dir="package")
        assert not stub._install_pending and discarded == ["package"]
        assert stub.releases == stub.retries == 1 and mw.exits == 0

    @pytest.mark.parametrize("launches", [False, True])
    def test_waits_for_worker_before_destroy_discard_release_or_exit(self, monkeypatch, launches):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_CANCEL, False)
        d._handoff = InstallHandoff()
        d.defer_until_settled = types.MethodType(UpdateProgressLifecycle.defer_until_settled, d)
        polls, discarded = [], []
        monkeypatch.setattr(updater.wx, "CallLater", lambda ms, fn: polls.append(fn))
        monkeypatch.setattr(updater, "discard_package", lambda p: discarded.append(p))
        stub._do_install("9.9.9", "https://example.invalid/z.zip", extracted_dir="package")
        assert stub._install_pending and not d.destroyed
        assert (mw.exits, stub.releases, stub.retries, discarded) == (0, 0, 0, [])
        # A second click/check must neither create a dialog nor release the
        # existing attempt's cross-account prompt claim.
        stub._do_install("9.9.9", "https://example.invalid/z.zip", extracted_dir="package")
        assert len(polls) == 1 and stub.releases == 0
        d._install_ok = launches
        d._handoff.settled.set()
        polls.pop(0)()
        assert d.destroyed
        assert mw.exits == int(launches)
        assert discarded == ([] if launches else ["package"])
        assert stub.releases == stub.retries == int(not launches)

    def test_already_destroyed_native_dialog_cannot_prevent_exit(self, monkeypatch):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_CANCEL, True)
        def destroyed():
            raise RuntimeError("native dialog deleted")
        d.Destroy = destroyed
        stub._do_install("9.9.9", "https://example.invalid/z.zip")
        assert mw.exits == 1

    def test_modal_exception_still_awaits_successful_handoff(self, monkeypatch):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_ABORT, False)
        d._handoff = InstallHandoff()
        assert d._handoff.begin(True)
        d._thread = object()  # a worker is still inside the committed launch
        d.defer_until_settled = types.MethodType(UpdateProgressLifecycle.defer_until_settled, d)
        polls = []
        monkeypatch.setattr(updater.wx, "CallLater", lambda ms, fn: polls.append(fn))
        def fail():
            raise RuntimeError("native loop failed")
        d.run = fail
        stub._do_install("9.9.9", "https://example.invalid/z.zip")
        assert mw.exits == 0 and not d.destroyed
        d._install_ok = True
        d._handoff.settled.set()
        polls.pop(0)()
        assert mw.exits == 1 and d.destroyed

    def test_constructor_failure_releases_prompt_and_inprocess_gate(self, monkeypatch):
        stub, mw, d = _checker(monkeypatch, updater.wx.ID_ABORT, False)
        def fail(*a, **kw):
            raise RuntimeError("constructor failed")
        monkeypatch.setattr(updater, "UpdateProgressDialog", fail)
        with pytest.raises(RuntimeError, match="constructor failed"):
            stub._do_install("9.9.9", "https://example.invalid/z.zip")
        assert not stub._install_pending and stub.releases == 1 and mw.exits == 0
