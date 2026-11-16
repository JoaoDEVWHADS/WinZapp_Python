"""Exit must never depend on the optional update-on-exit implementation.

The fork's legacy updater predates the upstream ``install_staged_on_exit()``
hook. A checker without that method must therefore fall through to the normal
quit path instead of raising AttributeError before WinZapp exits.
"""

from unittest.mock import Mock

from main import MainWindow


def test_exit_without_update_on_exit_support_calls_real_exit():
    stub = Mock()
    stub._update_checker = object()  # Deliberately has no install_staged_on_exit().
    stub.global_dir = None
    stub.account_id = None

    MainWindow.quit_all_accounts(stub)

    stub.real_exit.assert_called_once_with()


def test_update_on_exit_hook_can_take_over_exit_when_present():
    stub = Mock()
    stub._update_checker = Mock()
    stub._update_checker.install_staged_on_exit.return_value = True

    MainWindow.quit_all_accounts(stub)

    stub.real_exit.assert_not_called()
