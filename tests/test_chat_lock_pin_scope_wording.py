"""Locked chats have ONE PIN, and every PIN field has to say so.

Reported: locking a chat read as setting a PIN for that conversation, while
opening locked chats spoke of the PIN of all locked conversations. The vault
is the truth — ChatLockVault holds a single "pin" record and every locked
chat opens with it — so the setup field, reached from "Lock chat" on one
conversation, was the misleading one: its label was a bare "6-12 digit PIN".
The label is what the screen reader speaks on focus, so that is where the
scope is stated. Window-free: dialog sources are read, never built.
"""

import inspect

import pytest
from cryptography.fernet import Fernet

from core.chat_lock_vault import ChatLockVault
from ui.chat_lock import (
    ChatLockChangePinDialog,
    ChatLockRecoveryDialog,
    ChatLockRevealDialog,
    ChatLockSetupDialog,
    ChatLockUnlockDialog,
)

from tests.locales import load_strings, registered_locale_codes

LOCALES = list(registered_locale_codes())


def _strings(locale):
    return load_strings(locale)


def test_the_vault_really_has_one_pin_for_every_locked_chat():
    """What the wording below is being made to agree with."""
    vault = ChatLockVault(Fernet.generate_key())
    vault.configure("123456", "segredo")
    vault.lock_chat("a@s.whatsapp.net")
    vault.lock_chat("b@s.whatsapp.net")
    assert vault.verify_pin("123456")
    assert not hasattr(vault, "verify_chat_pin")


def test_setup_names_the_pin_as_the_one_for_all_locked_chats():
    source = inspect.getsource(ChatLockSetupDialog.__init__)
    assert 'i18n.t("chat_lock_setup_pin_label")' in source
    assert 'i18n.t("chat_lock_pin_label")' not in source


@pytest.mark.parametrize("dialog, key", [
    (ChatLockUnlockDialog, "chat_lock_pin_label"),
    (ChatLockRevealDialog, "chat_lock_pin_label"),
    (ChatLockRecoveryDialog, "chat_lock_new_pin_label"),
    (ChatLockChangePinDialog, "chat_lock_new_pin_label"),
])
def test_every_other_pin_field_uses_the_scoped_label(dialog, key):
    assert f'i18n.t("{key}")' in inspect.getsource(dialog.__init__)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_three_labels_are_distinct_in_every_locale(locale):
    """A translation collapsing setup back onto the plain label would bring
    the ambiguity back without any other test noticing."""
    s = _strings(locale)
    labels = [s["chat_lock_setup_pin_label"], s["chat_lock_pin_label"], s["chat_lock_new_pin_label"]]
    assert len(set(labels)) == 3


def test_pt_br_says_all_locked_chats_at_setup_and_locked_chats_everywhere():
    s = _strings("pt-BR")
    assert "todas as conversas trancadas" in s["chat_lock_setup_pin_label"]
    assert "conversas trancadas" in s["chat_lock_pin_label"]
    assert "conversas trancadas" in s["chat_lock_new_pin_label"]
