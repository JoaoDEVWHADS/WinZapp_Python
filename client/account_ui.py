"""
Account switcher / manager UI for WinZapp multi-account (client/account_ui.py)
==============================================================================

wx dialogs + menu wiring for switching between accounts and managing them
(plan Zad 4.2-4.6). Accessibility-first (the app's core differentiator): plain
wx controls only (wx.ListCtrl / standard dialogs), human-readable account names
never raw ids, explicit labels, initial focus on the current account, Enter/Esc.

The pure, wx-free helpers (accelerator map, menu model, filtering) live at the
bottom and are unit-tested without a wx.App. The dialog classes are only
imported/exercised on Windows with a running wx.App (verified there).

Switching is activation-first (plan Zad 4.1): ask a running process for that
account to foreground via IPC; only spawn a new process if none answers. The
current window stays open (accounts run in the background, choice 1b).
"""

from __future__ import annotations

import logging

# ── pure helpers (unit-tested, no wx) ────────────────────────────────────────

# Ctrl+Shift+1..9 (NOT Ctrl+Alt — that clashes with AltGr on a PL keyboard).
_MAX_HOTKEY_SLOTS = 9


def accelerator_slots(paired_accounts: list[dict]) -> list[tuple[int, dict]]:
    """Map the first 9 paired accounts (by stable 'order') to slots 1..9.

    Returns [(slot_number, account), ...]. Slots are assigned by the account's
    'order' field so the mapping is stable across renames / last_used changes
    (plan Zad 4.2 / GPT r2 #8)."""
    ordered = sorted(paired_accounts, key=lambda a: a.get("order", 0))
    return [(i + 1, acc) for i, acc in enumerate(ordered[:_MAX_HOTKEY_SLOTS])]


def switchable_accounts(accounts: list[dict]) -> list[dict]:
    """Accounts that may appear in the 'Switch account' dialog: paired only,
    ordered (plan Zad 4.3 / GPT r6 #5). Archived/pending/deleting excluded — an
    archived account offers 'Restore' in the manager instead."""
    return sorted([a for a in accounts if a.get("state") == "paired"],
                  key=lambda a: a.get("order", 0))


def unpaired_start_options(accounts: list[dict], current_account_id: str) -> list[dict]:
    """Other paired accounts the user could switch to when the CURRENT account
    starts up unpaired (its saved session was lost / never completed).

    When this is non-empty, startup must NOT trap the user in the pairing dialog
    of the dead account with no way out: it should first offer 'connect this
    account / switch to a working one / quit'. Excludes the current account
    itself. Pure/wx-free so the decision is unit-tested."""
    return [a for a in switchable_accounts(accounts) if a.get("id") != current_account_id]


def accounts_menu_signature(accounts: list[dict]) -> tuple:
    """Stable fingerprint of what the Accounts menu renders, so a window can
    tell whether a live registry change means its menu is stale and must be
    rebuilt. Captures exactly the fields the menu shows for each switchable
    (paired, ordered) account: id, display name and slot order. Two registries
    with the same signature produce an identical menu, so rebuilding is a no-op
    and can be skipped (avoids needless menu flicker / screen-reader churn)."""
    return tuple(
        (a.get("id"), a.get("name", a.get("id")), a.get("order", 0))
        for a in switchable_accounts(accounts)
    )


def manager_rows(accounts: list[dict]) -> list[dict]:
    """Rows for the manager list: every non-deleting account, ordered, with a
    display state. 'deleting' accounts are hidden (mid-removal)."""
    visible = [a for a in accounts if a.get("state") != "deleting"]
    return sorted(visible, key=lambda a: a.get("order", 0))


def can_archive(account: dict, current_account_id: str) -> tuple[bool, str]:
    """(allowed, reason_key). Archiving is paired-only and never the account of
    the current process (plan Zad 4.5 / GPT r7 #2)."""
    if account.get("id") == current_account_id:
        return False, "acc_err_archive_current"
    if account.get("state") != "paired":
        return False, "acc_err_archive_not_paired"
    return True, ""


def can_hard_delete(account: dict, current_account_id: str) -> tuple[bool, str]:
    """(allowed, reason_key). Hard-delete is never the current process's account
    (must switch away first — plan Zad 4.5)."""
    if account.get("id") == current_account_id:
        return False, "acc_err_delete_current"
    return True, ""


def can_pair(account: dict, current_account_id: str) -> tuple[bool, str]:
    """(allowed, reason_key). 'Connect/Pair' launches a pending account so the
    user can finish pairing it. Only meaningful for a pending account other than
    the current process's own (the current one is already being handled here)."""
    if account.get("id") == current_account_id:
        return False, "acc_err_pair_current"
    if account.get("state") != "pending":
        return False, "acc_err_pair_not_pending"
    return True, ""


# ── wx dialogs (Windows / running wx.App only) ───────────────────────────────
def _wx():
    import wx
    return wx


class SwitchAccountDialog:
    """Accessible 'Switch account' chooser (plan Zad 4.3).

    A thin builder around wx.SingleChoiceDialog-style construction using a
    ListCtrl so screen readers announce state. Returns the chosen account id or
    None. Only paired accounts are listed; initial focus is the current one.
    """

    def __init__(self, parent, accounts, current_account_id, i18n):
        wx = _wx()
        self.i18n = i18n
        self._accounts = switchable_accounts(accounts)
        self._current = current_account_id
        self.dlg = wx.Dialog(parent, title=i18n.t("acc_switch_title"),
                             style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self.dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(panel, label=i18n.t("acc_switch_label"))
        vbox.Add(label, 0, wx.ALL, 8)
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        for slot, acc in accelerator_slots(self._accounts):
            self.listbox.Append(f"{slot}. {acc.get('name', acc['id'])}", acc)
        # accounts beyond slot 9 (no hotkey) still listed
        for acc in self._accounts[_MAX_HOTKEY_SLOTS:]:
            self.listbox.Append(acc.get("name", acc["id"]), acc)
        vbox.Add(self.listbox, 1, wx.EXPAND | wx.ALL, 8)
        # OK/Cancel buttons parented to the panel (same window as the sizer),
        # not the dialog — mixing parents trips wxAssertionError
        # CheckExpectedParentIs and the dialog silently fails to open.
        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_ok = wx.Button(panel, wx.ID_OK)
        self.btn_cancel = wx.Button(panel, wx.ID_CANCEL)
        btns.Add(self.btn_ok, 0, wx.ALL, 4)
        btns.Add(self.btn_cancel, 0, wx.ALL, 4)
        vbox.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(vbox)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.dlg.SetSizer(outer)
        self.dlg.SetSize((360, 380))
        self.btn_ok.Bind(wx.EVT_BUTTON, lambda e: self.dlg.EndModal(wx.ID_OK))
        self.btn_cancel.Bind(wx.EVT_BUTTON, lambda e: self.dlg.EndModal(wx.ID_CANCEL))
        self.dlg.SetAffirmativeId(wx.ID_OK)
        self.dlg.SetEscapeId(wx.ID_CANCEL)
        # initial focus on the current account
        self._select_current()
        self.listbox.SetFocus()
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.dlg.EndModal(wx.ID_OK))

    def _select_current(self):
        for i in range(self.listbox.GetCount()):
            acc = self.listbox.GetClientData(i)
            if acc and acc.get("id") == self._current:
                self.listbox.SetSelection(i)
                return
        if self.listbox.GetCount():
            self.listbox.SetSelection(0)

    def show(self):
        """Return the chosen account id, or None if cancelled."""
        wx = _wx()
        try:
            if self.dlg.ShowModal() != wx.ID_OK:
                return None
            sel = self.listbox.GetSelection()
            if sel == wx.NOT_FOUND:
                return None
            acc = self.listbox.GetClientData(sel)
            return acc.get("id") if acc else None
        finally:
            self.dlg.Destroy()


class UnpairedStartDialog:
    """Shown at startup when the CURRENT account is unpaired but OTHER paired
    accounts exist (plan: don't trap the user in the dead account's pairing
    dialog with no way to reach a working account or the menu).

    Three accessible choices: connect (pair) THIS account, switch to another
    account, or quit. Returns one of: 'pair' | 'switch' | 'quit'. When 'switch',
    .chosen_account_id holds the picked account id. All buttons share the panel
    parent (mixing dialog/panel parents trips wxAssertionError CheckExpectedParentIs
    and the dialog silently fails to open — see SwitchAccountDialog)."""

    RESULT_PAIR = "pair"
    RESULT_SWITCH = "switch"
    RESULT_QUIT = "quit"

    def __init__(self, parent, accounts, current_account_id, current_account_name, i18n):
        wx = _wx()
        self.i18n = i18n
        self._options = unpaired_start_options(accounts, current_account_id)
        self.chosen_account_id = None
        self._result = self.RESULT_QUIT
        self.dlg = wx.Dialog(parent, title=i18n.t("acc_unpaired_title"),
                             style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self.dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(
            panel,
            label=i18n.t("acc_unpaired_label").format(name=current_account_name),
        )
        vbox.Add(label, 0, wx.ALL, 8)
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        for acc in self._options:
            self.listbox.Append(acc.get("name", acc["id"]), acc)
        if self.listbox.GetCount():
            self.listbox.SetSelection(0)
        vbox.Add(self.listbox, 1, wx.EXPAND | wx.ALL, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_pair = wx.Button(panel, label=i18n.t("acc_unpaired_pair"))
        self.btn_switch = wx.Button(panel, label=i18n.t("acc_unpaired_switch"))
        self.btn_quit = wx.Button(panel, wx.ID_CANCEL, i18n.t("acc_unpaired_quit"))
        btns.Add(self.btn_pair, 0, wx.ALL, 4)
        btns.Add(self.btn_switch, 0, wx.ALL, 4)
        btns.Add(self.btn_quit, 0, wx.ALL, 4)
        vbox.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(vbox)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.dlg.SetSizer(outer)
        self.dlg.SetSize((380, 340))

        self.btn_pair.Bind(wx.EVT_BUTTON, self._on_pair)
        self.btn_switch.Bind(wx.EVT_BUTTON, self._on_switch)
        self.btn_quit.Bind(wx.EVT_BUTTON, lambda e: self.dlg.EndModal(wx.ID_CANCEL))
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_switch)
        # Enter connects this account (most common intent for the account the
        # user actually launched); Esc quits.
        self.dlg.SetAffirmativeId(self.btn_pair.GetId())
        self.dlg.SetEscapeId(wx.ID_CANCEL)
        self.btn_pair.SetFocus()

    def _on_pair(self, event):
        wx = _wx()
        self._result = self.RESULT_PAIR
        self.dlg.EndModal(wx.ID_OK)

    def _on_switch(self, event):
        wx = _wx()
        sel = self.listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        acc = self.listbox.GetClientData(sel)
        self.chosen_account_id = acc.get("id") if acc else None
        if not self.chosen_account_id:
            return
        self._result = self.RESULT_SWITCH
        self.dlg.EndModal(wx.ID_OK)

    def show(self):
        """Return 'pair' | 'switch' | 'quit'. On 'switch', read
        .chosen_account_id for the picked account."""
        try:
            self.dlg.ShowModal()
            return self._result
        finally:
            self.dlg.Destroy()


def build_accounts_menu(menu, accounts, current_account_id, i18n, id_factory):
    """Populate a wx 'Accounts' menu (plan Zad 4.2). Adds a radio-style item per
    paired account with Ctrl+Shift+<n> for the first 9, a separator, then
    'Switch account…' and 'Manage accounts…'. Returns a dict mapping wx ids to
    an action: {'switch': account_id} or {'open_switch': True}/{'open_manager': True}.
    """
    wx = _wx()
    id_map: dict = {}
    for slot, acc in accelerator_slots(switchable_accounts(accounts)):
        item_id = id_factory()
        label = f"&{slot} {acc.get('name', acc['id'])}\tCtrl+Shift+{slot}"
        item = menu.AppendRadioItem(item_id, label)
        if acc.get("id") == current_account_id:
            item.Check(True)
        id_map[item_id] = {"switch": acc["id"]}
    menu.AppendSeparator()
    sw_id = id_factory()
    menu.Append(sw_id, f"{i18n.t('acc_menu_switch')}\tCtrl+Shift+A")
    id_map[sw_id] = {"open_switch": True}
    mg_id = id_factory()
    menu.Append(mg_id, i18n.t("acc_menu_manage"))
    id_map[mg_id] = {"open_manager": True}
    return id_map


class AccountManagerDialog:
    """Accessible account manager (plan Zad 4.5): list + add / rename / archive /
    restore / hard-delete. Uses a plain wx.ListCtrl (report view) so the screen
    reader announces name + state per row. All destructive ops confirm and
    respect the can_archive / can_hard_delete guards; hard-delete coordinates
    Node teardown of the account's userDataDir under node_lock.
    """

    def __init__(self, parent, registry, current_account_id, i18n, global_dir,
                 on_pair=None):
        wx = _wx()
        self.registry = registry
        self.current = current_account_id
        self.i18n = i18n
        self.global_dir = global_dir
        # Callback(account_id) to launch/pair an account (activation-first switch).
        # Injected by main.py so the manager can start a pending account's pairing.
        self._pair_cb = on_pair
        self.dlg = wx.Dialog(parent, title=i18n.t("acc_mgr_title"),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self.dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(wx.StaticText(panel, label=i18n.t("acc_mgr_label")), 0, wx.ALL, 8)
        self.lst = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.lst.InsertColumn(0, i18n.t("acc_col_name"), width=220)
        self.lst.InsertColumn(1, i18n.t("acc_col_state"), width=120)
        vbox.Add(self.lst, 1, wx.EXPAND | wx.ALL, 8)
        # buttons
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(panel, label=i18n.t("acc_btn_add"))
        self.btn_pair = wx.Button(panel, label=i18n.t("acc_btn_pair"))
        self.btn_rename = wx.Button(panel, label=i18n.t("acc_btn_rename"))
        self.btn_archive = wx.Button(panel, label=i18n.t("acc_btn_archive"))
        self.btn_restore = wx.Button(panel, label=i18n.t("acc_btn_restore"))
        self.btn_delete = wx.Button(panel, label=i18n.t("acc_btn_delete"))
        for b in (self.btn_add, self.btn_pair, self.btn_rename, self.btn_archive,
                  self.btn_restore, self.btn_delete):
            hbox.Add(b, 0, wx.ALL, 4)
        vbox.Add(hbox, 0, wx.ALL, 4)
        # Close button parented to the SAME panel as the sizer (wx requires the
        # sizer's managed widgets to share the sizer's window as parent, else
        # wxAssertionError CheckExpectedParentIs and the dialog never shows).
        self.btn_close = wx.Button(panel, wx.ID_CLOSE)
        vbox.Add(self.btn_close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(vbox)
        # Panel fills the dialog.
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.dlg.SetSizer(outer)
        self.dlg.SetSize((480, 420))
        self.btn_close.Bind(wx.EVT_BUTTON, lambda e: self.dlg.EndModal(wx.ID_CLOSE))
        self.dlg.SetAffirmativeId(wx.ID_CLOSE)
        self.dlg.SetEscapeId(wx.ID_CLOSE)
        self.btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self.btn_pair.Bind(wx.EVT_BUTTON, self._on_pair)
        self.btn_rename.Bind(wx.EVT_BUTTON, self._on_rename)
        self.btn_archive.Bind(wx.EVT_BUTTON, self._on_archive)
        self.btn_restore.Bind(wx.EVT_BUTTON, self._on_restore)
        self.btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
        self._reload()
        self.lst.SetFocus()

    # ── data ─────────────────────────────────────────────────────────────
    def _reload(self):
        self.lst.DeleteAllItems()
        self._rows = manager_rows(self.registry.list())
        for row in self._rows:
            idx = self.lst.InsertItem(self.lst.GetItemCount(), row.get("name", row["id"]))
            state = row.get("state", "")
            label = self.i18n.t(f"acc_state_{state}") if state else state
            self.lst.SetItem(idx, 1, label)
        if self.lst.GetItemCount():
            self.lst.Select(0)
            self.lst.Focus(0)

    def _selected(self):
        i = self.lst.GetFirstSelected()
        if i < 0 or i >= len(self._rows):
            return None
        return self._rows[i]

    # ── actions ──────────────────────────────────────────────────────────
    def _on_add(self, _e):
        wx = _wx()
        dlg = wx.TextEntryDialog(self.dlg, self.i18n.t("acc_add_prompt"),
                                 self.i18n.t("acc_btn_add"))
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name = dlg.GetValue().strip()
                if name:
                    acc = self.registry.add(name, state="pending")
                    self._reload()
                    # Offer to pair the freshly-added account right away, so the
                    # user isn't stuck with a pending account they can't reach
                    # (a pending account is not in the switch list by design).
                    if self._pair_cb and wx.MessageBox(
                            self.i18n.t("acc_pair_now_prompt").format(name=name),
                            self.i18n.t("acc_btn_pair"),
                            wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self._pair_cb(acc["id"])
                        self.dlg.EndModal(wx.ID_CLOSE)
        finally:
            dlg.Destroy()

    def _on_pair(self, _e):
        acc = self._selected()
        if not acc:
            return
        ok, reason = can_pair(acc, self.current)
        if not ok:
            self._error(reason)
            return
        if self._pair_cb:
            self._pair_cb(acc["id"])
            self.dlg.EndModal(_wx().ID_CLOSE)

    def _on_rename(self, _e):
        wx = _wx()
        acc = self._selected()
        if not acc:
            return
        dlg = wx.TextEntryDialog(self.dlg, self.i18n.t("acc_rename_prompt"),
                                 self.i18n.t("acc_btn_rename"), acc.get("name", ""))
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name = dlg.GetValue().strip()
                if name:
                    self.registry.update_fields(acc["id"], name=name)
                    self._reload()
                    if acc["id"] == self.current and hasattr(self.dlg.GetParent(), "update_account_name"):
                        self.dlg.GetParent().update_account_name(name)
        finally:
            dlg.Destroy()

    def _on_archive(self, _e):
        acc = self._selected()
        if not acc:
            return
        ok, reason = can_archive(acc, self.current)
        if not ok:
            self._error(reason)
            return
        # transaction: state+autostart together (plan Zad 4.5 / GPT r6 #4)
        self.registry.update_fields(acc["id"], state="archived", autostart=False)
        self._reload()

    def _on_restore(self, _e):
        acc = self._selected()
        if not acc or acc.get("state") != "archived":
            return
        # archived only ever came from paired, so restore -> paired (GPT r8 #2)
        self.registry.update_fields(acc["id"], state="paired")
        self._reload()

    def _on_delete(self, _e):
        wx = _wx()
        acc = self._selected()
        if not acc:
            return
        ok, reason = can_hard_delete(acc, self.current)
        if not ok:
            self._error(reason)
            return
        if wx.MessageBox(self.i18n.t("acc_delete_confirm").format(name=acc.get("name", "")),
                         self.i18n.t("acc_btn_delete"),
                         wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        try:
            _hard_delete_account(self.registry, self.global_dir, acc["id"])
        except Exception:
            logging.exception("[account manager] hard delete failed")
            self._error("acc_err_delete_failed")
        self._reload()

    def _error(self, key):
        wx = _wx()
        wx.MessageBox(self.i18n.t(key), self.i18n.t("error").format(app_name="WinZapp"),
                      wx.OK | wx.ICON_ERROR)

    def show(self):
        try:
            self.dlg.ShowModal()
        finally:
            self.dlg.Destroy()


def _hard_delete_account(registry, global_dir, account_id) -> None:
    """Remove an account's data dir + registry entry, coordinating Node teardown
    (plan Zad 4.5 / GPT r7 #3): the account's WPPConnect userDataDir must not be
    deleted while the shared Node might be using it. We mark 'deleting' first
    (blocks bootstrap), verify under node_lock that no live lease belongs to it,
    then rmtree + remove from the registry.
    """
    import shutil
    import node_coord

    registry.set_state(account_id, "deleting")
    # Ensure this account holds no live node-lease.
    node_coord.release_node_lease(global_dir, account_id)
    data_dir = registry.data_dir_for(account_id)
    try:
        shutil.rmtree(data_dir, ignore_errors=True)
    finally:
        registry.remove(account_id)
