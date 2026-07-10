class UpdateManager:

    def __init__(self, main_window):
        self.mw = main_window

    def _on_force_update(self, event):
        if self.mw._update_checker is None:
            self._start_update_checker(force=True)
        else:
            self.mw._update_checker.force_check()

    def _start_update_checker(self, force: bool = False):
        updates_enabled = self.mw.settings.get("general", {}).get("updates_enabled", True)
        if not updates_enabled and not force:
            return
        from updater import UpdateChecker
        self.mw._update_checker = UpdateChecker(self.mw)
        if force:
            self.mw._update_checker.force_check()
        else:
            self.mw._update_checker.start()
