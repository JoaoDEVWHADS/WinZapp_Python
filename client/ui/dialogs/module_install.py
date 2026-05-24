"""
module_install.py — WinZapp first-run module installer dialog.

Shown when api/node_modules is absent on the first launch.
Runs `npm install --no-audit --no-fund` followed by
`npm run db:generate` inside api/ using the bundled Node runtime,
displays a pulsing progress bar, and offers a Cancel button.

Modal result:
  wx.ID_OK     — installation succeeded; caller may proceed
  wx.ID_CANCEL — user cancelled or an error occurred; caller should exit
"""

import json
import os
import shutil
import subprocess
import threading

import wx

from app_paths import resource_path


class ModuleInstallDialog(wx.Dialog):
    """Indeterminate-progress dialog that installs api/node_modules."""

    _PULSE_MS = 80   # timer interval for gauge pulse

    def __init__(self, parent):
        from core.i18n import I18n
        self._i18n = I18n(parent)
        self._i18n.get_language()

        title = self._i18n.t("module_install_title")
        # Remove the close button so the user can only Cancel via the button
        style = wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX
        super().__init__(parent, title=title, style=style)

        self._proc      = None   # active subprocess (npm)
        self._cancelled = False

        self._build_ui()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse, self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)   # still catch Alt-F4

        # Kick off the install thread before entering the modal loop
        t = threading.Thread(target=self._run_install, daemon=True)
        t.start()

        self._timer.Start(self._PULSE_MS)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # The dialog title already carries the full description; no body text
        # needed.  Only the gauge and Cancel button are shown.

        # ① Pulsing gauge (indeterminate)
        self._gauge = wx.Gauge(self, range=100,
                               style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)

        # ② Cancel button
        cancel_btn = wx.Button(self, wx.ID_CANCEL,
                               label=self._i18n.t("cancel"))
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._gauge, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(cancel_btn,  0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize((420, -1))
        self.Centre()

    # ── Timer / gauge ──────────────────────────────────────────────────────

    def _on_pulse(self, _event):
        self._gauge.Pulse()

    # ── Background installation thread ────────────────────────────────────

    def _run_install(self):
        """Run npm install then npm run db:generate; schedule UI updates via wx.CallAfter."""
        node_exe = resource_path("node", "node.exe")
        npm_cli  = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
        api_dir  = resource_path("api")

        try:
            # ── Step 1: npm install ──────────────────────────────────────
            self._proc = subprocess.Popen(
                [node_exe, npm_cli, "install", "--no-audit", "--no-fund"],
                cwd=api_dir,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr_bytes = self._proc.communicate()
            rc = self._proc.returncode

            if self._cancelled:
                return
            if rc != 0:
                details = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
                wx.CallAfter(self._finish_error, details)
                return

            # ── Step 2: npm run db:generate (only if script is defined) ────
            pkg_json_path = resource_path("api", "package.json")
            has_db_generate = False
            try:
                with open(pkg_json_path, encoding="utf-8") as f:
                    pkg = json.load(f)
                has_db_generate = "db:generate" in pkg.get("scripts", {})
            except Exception:
                pass

            if has_db_generate:
                env = {**os.environ, "DATABASE_PROVIDER": "postgresql"}
                self._proc = subprocess.Popen(
                    [node_exe, npm_cli, "run", "db:generate"],
                    cwd=api_dir,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                _, stderr_bytes = self._proc.communicate()
                rc = self._proc.returncode

                if self._cancelled:
                    return
                if rc != 0:
                    details = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
                    wx.CallAfter(self._finish_error, details)
                    return

            wx.CallAfter(self._finish_success)

        except Exception as exc:
            if not self._cancelled:
                wx.CallAfter(self._finish_error, str(exc))

    # ── Process-tree kill ──────────────────────────────────────────────────

    def _kill_proc_tree(self):
        """Kill the npm process and all its spawned children."""
        if self._proc and self._proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass

    def _remove_partial_modules(self):
        """Delete any partially-installed node_modules directory."""
        node_modules = resource_path("api", "node_modules")
        if os.path.isdir(node_modules):
            try:
                shutil.rmtree(node_modules, ignore_errors=True)
            except Exception:
                pass

    # ── Event handlers ─────────────────────────────────────────────────────

    def _on_cancel(self, _event=None):
        if self._cancelled:
            return
        self._cancelled = True
        self._timer.Stop()
        self._kill_proc_tree()
        self._remove_partial_modules()
        self.EndModal(wx.ID_CANCEL)

    def _finish_success(self):
        self._timer.Stop()
        wx.MessageBox(
            self._i18n.t("module_install_success"),
            self._i18n.t("app_name"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        self.EndModal(wx.ID_OK)

    def _finish_error(self, details=""):
        self._timer.Stop()
        msg = self._i18n.t("module_install_error")
        if details:
            msg = f"{msg}\n\n{details}"
        wx.MessageBox(
            msg,
            self._i18n.t("app_name"),
            wx.OK | wx.ICON_ERROR,
            self,
        )
        self.EndModal(wx.ID_CANCEL)
