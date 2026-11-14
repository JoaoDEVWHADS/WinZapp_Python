"""A Mac menu bar for WinZapp, and no Windows self-updater.

* Settings, About and Exit move into the application menu as
  Settings… (Cmd-,), About WinZapp and Quit WinZapp (Cmd-Q).
* Chat and Message menus mirror the right-click menu of the selected chat
  and the selected message. They are rebuilt each time they open, from
  WinZapp's own context-menu handlers (native_rows' capture), so they always
  match what right-click and the VoiceOver actions offer.
* WinZapp's updater downloads Windows releases. On the Mac it is switched
  off, with its Help-menu entries, until releases carry a macOS build.
* A Mac release build (updater_mac.enabled()) also gets "Check for
  Updates…" in the application menu, under About WinZapp, where Mac apps
  keep it. It runs the same handler as Help > Check for updates, which stays.
"""

import logging

import wx

from . import native_rows


def _title(i18n, key, fallback):
    try:
        text = i18n.t(key)
    except Exception:
        return fallback
    return fallback if not text or text == key else text


class _MirrorMenu:
    """A menu-bar menu that shows a list control's current context menu."""

    def __init__(self, frame, menu, get_ctrl):
        self.frame = frame
        self.menu = menu
        self.get_ctrl = get_ctrl
        self.ids = {}

    def rebuild(self):
        for item in list(self.menu.GetMenuItems()):
            self.menu.Delete(item)
        self.ids = {}
        ctrl = self.get_ctrl()
        labels = []
        if ctrl is not None and ctrl.GetFocusedItem() != wx.NOT_FOUND:
            try:
                labels = native_rows.menu_actions(ctrl)
            except Exception:
                logging.debug("[menubar_mac] mirror failed", exc_info=True)
        for label in labels:
            item_id = wx.NewIdRef()
            self.menu.Append(item_id, label)
            self.ids[int(item_id)] = label
        if not labels:
            placeholder = self.menu.Append(wx.ID_ANY, "—")
            placeholder.Enable(False)

    def run(self, item_id):
        label = self.ids.get(item_id)
        ctrl = self.get_ctrl()
        if label and ctrl is not None:
            wx.CallAfter(native_rows.run_menu_action, ctrl, label)
            return True
        return False


def _hide(frame):
    frame._mac_hidden_pos = []
    for menu, item in getattr(frame, "_mac_hidden_items", []):
        items = list(menu.GetMenuItems())
        pos = next((i for i, it in enumerate(items) if it.GetId() == item.GetId()), None)
        if pos is not None:
            menu.Remove(item)
            frame._mac_hidden_pos.append((menu, pos, item))


def _unhide(frame):
    for menu, pos, item in reversed(getattr(frame, "_mac_hidden_pos", [])):
        menu.Insert(pos, item)
    frame._mac_hidden_pos = []


def _chat_list(frame):
    panel = getattr(frame, "conversations_panel", None)
    return getattr(panel, "conversations_list", None)


def _message_list(frame):
    panel = getattr(frame, "conversations_panel", None)
    return getattr(panel, "messages_list", None)


def _install_menubar(frame):
    mb = frame.GetMenuBar()
    if mb is None:
        return
    i18n = frame.i18n

    # Windows-updater entries: taken out (kept, so _refresh_menubar can
    # relabel them — see _hide/_unhide).
    frame._mac_hidden_items = []
    from . import updater_mac
    hidden = ["_ID_FORCE_REINSTALL_ZIP", "_ID_FORCE_REINSTALL_WPP"]
    if not updater_mac.enabled():
        hidden.insert(0, "_ID_FORCE_UPDATE")      # "Check for updates"
    if updater_mac.enabled():
        try:
            _add_app_menu_update_item(frame, mb)
        except Exception:
            logging.exception("[menubar_mac] could not add Check for Updates to the application menu")
    for attr in hidden:
        item_id = getattr(frame, attr, None)
        if item_id is not None:
            item, menu = mb.FindItem(int(item_id))
            if item is not None:
                frame._mac_hidden_items.append((menu, item))
    _hide(frame)

    # Chat / Message menus, just before Help.
    help_idx = mb.GetMenuCount() - 1
    mirrors = []
    for title, getter in ((_title(i18n, "conversations", "Chat"), _chat_list),
                          (_title(i18n, "messages", "Message"), _message_list)):
        menu = wx.Menu()
        mb.Insert(help_idx, menu, title.replace("&", ""))
        help_idx += 1
        mirrors.append(_MirrorMenu(frame, menu, lambda g=getter: g(frame)))

    def on_open(evt):
        # wx reinstalls the menu bar when the window activates, which
        # unhides items; re-hide as any menu opens (before it is shown).
        _hide_app_menu_duplicates(frame._mac_dup_labels)
        for m in mirrors:
            if evt.GetMenu() is m.menu:
                m.rebuild()
        evt.Skip()

    def on_menu(evt):
        for m in mirrors:
            if m.run(evt.GetId()):
                return
        evt.Skip()

    frame.Bind(wx.EVT_MENU_OPEN, on_open)
    frame.Bind(wx.EVT_MENU, on_menu)

    wx.CallLater(1500, _free_window_menu_keys)
    # Settings / Exit / About also appear in the application menu, which
    # dispatches through these very items — so they must stay in the menu
    # bar (removing them left Quit, Settings and About dead). Hide the
    # originals natively instead.
    labels = [mb.FindItemById(int(getattr(frame, a))).GetItemLabelText()
              for a in ("_ID_SETTINGS", "_ID_EXIT", "_ID_ABOUT")
              if getattr(frame, a, None) is not None and mb.FindItemById(int(getattr(frame, a)))]
    frame._mac_dup_labels = labels
    wx.CallLater(1500, _hide_app_menu_duplicates, labels)


def app_menu_update_label(i18n):
    """Help > Check for updates' own words, as a Mac application-menu item
    reads: no mnemonic, an ellipsis (it opens a window)."""
    text = _title(i18n, "menu_force_update", "Check for updates").replace("&", "").strip()
    return text.rstrip(".…").rstrip() + "…"


def _add_app_menu_update_item(frame, mb):
    """'Check for Updates…' right under About in the application menu; it
    calls the frame's _on_force_update, as the Help item does."""
    apple = mb.OSXGetAppleMenu()
    if apple is None:
        return
    if getattr(frame, "_mac_app_update_id", None) is None:
        frame._mac_app_update_id = wx.NewIdRef()
        frame.Bind(wx.EVT_MENU, lambda evt: frame._on_force_update(evt),
                   id=int(frame._mac_app_update_id))
    if apple.FindItemById(int(frame._mac_app_update_id)) is None:
        apple.Insert(1, int(frame._mac_app_update_id), app_menu_update_label(frame.i18n))


def _relabel_app_menu_update_item(frame):
    item_id = getattr(frame, "_mac_app_update_id", None)
    mb = frame.GetMenuBar()
    if item_id is None or mb is None:
        return
    item = mb.OSXGetAppleMenu().FindItemById(int(item_id))
    if item is not None:
        item.SetItemLabel(app_menu_update_label(frame.i18n))


def _hide_app_menu_duplicates(labels):
    try:
        from AppKit import NSApp
        tops = list(NSApp().mainMenu().itemArray())
        for top in tops[2:]:          # skip the Apple and application menus
            sub = top.submenu()
            if sub is None:
                continue
            items = list(sub.itemArray())
            cmd = 1 << 20
            for i, item in enumerate(items):
                key = str(item.keyEquivalent()).lower()
                bare_cmd = (item.keyEquivalentModifierMask() & 0xFFFF0000) == cmd
                # wx retitles the File copy of Exit to "Quit", so match the
                # app-menu shortcuts (Cmd-, / Cmd-Q) as well as the labels.
                if str(item.title()) in labels or (bare_cmd and key in (",", "q")):
                    item.setHidden_(True)
                    # a separator left dangling above a hidden last item
                    if i == len(items) - 1 and i > 0 and items[i - 1].isSeparatorItem():
                        items[i - 1].setHidden_(True)
    except Exception:
        logging.debug("[menubar_mac] could not hide duplicates", exc_info=True)


def _declare_app_menu_items(frame):
    """Must run before the menu bar is first installed: wx moves these
    items into the application menu only at SetMenuBar() time."""
    wx.PyApp.SetMacPreferencesMenuItemId(int(frame._ID_SETTINGS))
    wx.PyApp.SetMacAboutMenuItemId(int(frame._ID_ABOUT))
    wx.PyApp.SetMacExitMenuItemId(int(frame._ID_EXIT))
    wx.PyApp.SetMacHelpMenuTitleName(_title(frame.i18n, "menu_help", "Help").replace("&", ""))


def _free_window_menu_keys():
    """macOS's automatic Window menu gives Option-Command-M to Minimize All,
    which is WinZapp's Alt+M (focus the messages list) under the Mac rule."""
    try:
        from AppKit import NSApp
        option = 1 << 19
        for top in NSApp().mainMenu().itemArray():
            sub = top.submenu()
            if sub is None:
                continue
            for item in sub.itemArray():
                if (item.keyEquivalent().lower() == "m"
                        and item.keyEquivalentModifierMask() & option
                        and item.action() in ("miniaturizeAll:", b"miniaturizeAll:")):
                    item.setKeyEquivalent_("")
                    item.setAlternate_(False)
    except Exception:
        logging.debug("[menubar_mac] could not free Minimize All", exc_info=True)


def install():
    from main_window import window_chrome, updates

    orig_build = window_chrome.WindowChromeMixin._build_menubar

    def build(self, *args, **kwargs):
        orig_set = self.SetMenuBar

        def set_menubar(mb):
            try:
                _declare_app_menu_items(self)
            except Exception:
                logging.exception("[menubar_mac] app menu ids")
            return orig_set(mb)

        self.SetMenuBar = set_menubar
        try:
            result = orig_build(self, *args, **kwargs)
        finally:
            del self.SetMenuBar
        try:
            _install_menubar(self)
        except Exception:
            logging.exception("[menubar_mac] could not set up the Mac menu bar")
        return result

    window_chrome.WindowChromeMixin._build_menubar = build

    orig_refresh = window_chrome.WindowChromeMixin._refresh_menubar

    def refresh(self, *args, **kwargs):
        _unhide(self)
        try:
            return orig_refresh(self, *args, **kwargs)
        finally:
            _hide(self)
            try:
                _relabel_app_menu_update_item(self)
            except Exception:
                logging.debug("[menubar_mac] could not relabel Check for Updates", exc_info=True)

    window_chrome.WindowChromeMixin._refresh_menubar = refresh

    def no_updater(self, *args, **kwargs):
        logging.info("[menubar_mac] WinZapp's Windows updater is disabled on macOS")

    # WinZapp's own updater installs Windows releases; signed Mac release
    # builds redirect it to the Mac releases instead (updater_mac). The
    # WPPConnect updater and the ZIP/WPP reinstalls are Windows-only here:
    # the server is part of each Mac release.
    from . import updater_mac
    updates.UpdatesMixin._on_force_reinstall_zip = no_updater
    updates.UpdatesMixin._start_wpp_update_checker = no_updater
    updates.UpdatesMixin._on_force_reinstall_wpp = no_updater
    if not updater_mac.enabled():
        updates.UpdatesMixin._start_update_checker = no_updater
        updates.UpdatesMixin._on_force_update = no_updater
