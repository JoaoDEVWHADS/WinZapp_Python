"""
WppProcessManager — manages the WPPConnect (Node.js) server lifecycle.

Extracted from MainWindow (client/main.py) to keep the god class in check.
"""

import os
import sys
import time
import json as _json
import shutil
import logging
import subprocess
import socket as _socket
import atexit

import ctypes

import wx
import requests

from packaging.version import Version
from app_paths import resource_path, log_path


# ---------------------------------------------------------------------------
# Utility — Windows short-path helper (used by _start_wpp_background)
# ---------------------------------------------------------------------------

def _get_short_path_name(long_path: str) -> str:
    """Return Windows short (8.3) path to avoid PostgreSQL initdb failures
    when the install path contains accented characters (e.g. 'Área de Trabalho')."""
    try:
        buf_size = ctypes.windll.kernel32.GetShortPathNameW(long_path, None, 0)
        if buf_size:
            buf = ctypes.create_unicode_buffer(buf_size)
            if ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, buf_size):
                return buf.value
    except Exception:
        pass
    return long_path


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class WppProcessManager:
    """Manages the WPPConnect Server Node.js process lifecycle.

    Receives the **MainWindow** instance so it can reach configuration
    attributes (``wpp_port``, ``wpp_api_key``, ``background_mode``, …)
    without becoming tightly coupled to the wx window hierarchy.
    """

    def __init__(self, main_window):
        self.mw = main_window

    # ── API module / node_modules assurance ────────────────────────────────

    def ensure_api_modules_installed(self):
        """
        Ensure the WPPConnect is cloned, compiled, and has its node_modules.

        node/node.exe is mandatory in all scenarios — it is the portable Node.js
        runtime bundled with WinZapp that drives both npm and the API itself.
        Its absence is always a fatal error.

        Depending on what is present inside api/:

          dist/main.js absent  →  API not yet cloned/compiled.
                                   Show ApiSetupDialog (git clone + npm install
                                   + npm run build).  This is the expected state
                                   for a fresh install or first developer run.

          dist/main.js present
          node_modules absent  →  API compiled but modules were removed.
                                   Show ModuleInstallDialog (npm install only).

          Both present         →  Nothing to do.

        In background mode dialogs are never shown; if the setup is incomplete
        the process exits silently.
        """
        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        dist_server  = resource_path("api",  "dist", "server.js")
        node_modules = resource_path("api",  "node_modules")

        # Node.js is mandatory — without it neither npm nor the API can run.
        if not os.path.isfile(node_exe):
            wx.MessageBox(
                "O Node.js não foi encontrado.\n\n"
                "Este arquivo é essencial para o funcionamento do WinZapp. "
                "Por favor, instale o Node.js no sistema ou reinstale o programa.",
                "Node.js não encontrado",
                wx.OK | wx.ICON_ERROR,
            )
            sys.exit(1)

        # Detect and clean legacy node_modules from WPPConnect to force a clean install of WPPConnect
        wpp_marker = os.path.join(node_modules, "@wppconnect-team")
        if os.path.isdir(node_modules) and not os.path.isdir(wpp_marker):
            logging.info("[ensure_api_modules_installed] Legacy node_modules detected. Cleaning for WPPConnect...")
            try:
                shutil.rmtree(node_modules, ignore_errors=True)
            except Exception as e:
                logging.error("[ensure_api_modules_installed] Failed to remove legacy node_modules: %s", e)

        # ── Check for new required packages in an existing node_modules ──────
        # When we add a new npm dependency (e.g. @ffmpeg-installer/ffmpeg) the
        # user's node_modules is already installed from a previous run, so the
        # normal "node_modules absent" gate never fires.  We compare a list of
        # required package markers and run `npm install` silently in the
        # background if any are missing — no dialog needed.
        _REQUIRED_MARKERS = [
            os.path.join(node_modules, "@ffmpeg-installer", "ffmpeg"),
            os.path.join(node_modules, "@babel", "runtime"),
        ]
        if os.path.isfile(dist_server) and os.path.isdir(node_modules):
            missing = [m for m in _REQUIRED_MARKERS if not os.path.isdir(m)]
            if missing:
                logging.info(
                    "[ensure_api_modules_installed] Missing packages detected: %s — running npm install",
                    missing,
                )
                if sys.platform == "win32":
                    node_exe = resource_path("node", "node.exe")
                    npm_cli  = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    npm_cmd  = [node_exe, npm_cli]
                    node_dir = resource_path("node")
                    path_env = node_dir + os.pathsep + os.environ.get("PATH", "")
                else:
                    local_node = resource_path("node", "node")
                    if os.path.isfile(local_node):
                        node_exe = local_node
                    else:
                        node_exe = shutil.which("node") or "node"
                    local_npm = resource_path("node", "node_modules", "npm", "bin", "npm-cli.js")
                    if os.path.isfile(local_npm):
                        npm_cmd = [node_exe, local_npm]
                    else:
                        npm_cmd = [shutil.which("npm") or "npm"]
                    node_dir = os.path.dirname(node_exe) if os.path.isabs(node_exe) else ""
                    path_env = (node_dir + os.pathsep + os.environ.get("PATH", "")) if node_dir else os.environ.get("PATH", "")

                npm_env  = {
                    **os.environ,
                    "PATH": path_env,
                    "PUPPETEER_CACHE_DIR": resource_path("api", ".cache", "puppeteer"),
                }
                api_dir  = resource_path("api")
                creation_flags = 0
                if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creation_flags = subprocess.CREATE_NO_WINDOW

                try:
                    proc = subprocess.Popen(
                        npm_cmd + ["install", "--no-audit", "--no-fund", "--include=optional", "--legacy-peer-deps"],
                        cwd=api_dir,
                        env=npm_env,
                        creationflags=creation_flags,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    _, stderr_bytes = proc.communicate()
                    if proc.returncode != 0:
                        logging.error(
                            "[ensure_api_modules_installed] npm install failed: %s",
                            (stderr_bytes or b"").decode("utf-8", errors="replace"),
                        )
                    else:
                        logging.info("[ensure_api_modules_installed] npm install completed OK")
                except Exception as exc:
                    logging.error("[ensure_api_modules_installed] npm install error: %s", exc)
            return

        # Everything already set up — nothing to do.
        if os.path.isfile(dist_server) and os.path.isdir(node_modules):
            return

        if self.mw.background_mode:
            sys.exit(0)

        if not os.path.isfile(dist_server):
            from ui.dialogs.api_setup import ApiSetupDialog
            dlg    = ApiSetupDialog(self.mw)
            result = dlg.ShowModal()
            dlg.Destroy()
        else:
            from ui.dialogs.module_install import ModuleInstallDialog
            dlg    = ModuleInstallDialog(self.mw)
            result = dlg.ShowModal()
            dlg.Destroy()

        if result != wx.ID_OK:
            sys.exit(0)

    # ── WPPConnect version gate ───────────────────────────────────────────────

    def _read_env_value(self, key: str, default: str = "") -> str:
        """Read a value from the bundled client .env file."""
        env_path = resource_path(".env")
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip()
        except Exception:
            pass
        return default

    def _get_installed_wpp_version(self) -> str:
        """Read the WPPConnect Server version from api/package.json."""
        pkg_path = resource_path("api", "package.json")
        try:
            with open(pkg_path, encoding="utf-8") as fh:
                pkg = _json.load(fh)
            return pkg.get("version", "")
        except Exception:
            return ""

    @staticmethod
    def _version_is_below(installed: str, minimum: str) -> bool:
        """
        Return True when *installed* is strictly older than *minimum*.
        Handles standard semver and pre-release suffixes (e.g. "2.4.0-rc2").
        Returns False on any parsing error so the check never blocks startup
        due to an unexpected version string format.
        """
        if not installed or not minimum:
            return False
        try:
            return Version(installed) < Version(minimum)
        except Exception:
            return False

    def ensure_wpp_version(self):
        """
        Compare the installed WPPConnect version against the minimum required
        by this WinZapp build (WPP_MINIMUM_VERSION in client/.env).

        If the installed version is older the user is prompted to:
          • Update now   — re-download + rebuild via ApiSetupDialog, then continue
          • Exit         — terminate WinZapp
          • Continue     — proceed without updating (not recommended)

        The check is skipped when:
          - Running in background mode (no UI)
          - api/package.json is absent (setup not done yet)
          - WPP_MINIMUM_VERSION is not defined in the .env
        """
        if self.mw.background_mode:
            return

        dist_main = resource_path("api", "dist", "main.js")
        if not os.path.isfile(dist_main):
            return  # API not installed yet — setup dialog will handle it

        minimum  = self._read_env_value("WPP_MINIMUM_VERSION")
        if not minimum:
            return  # No minimum defined — nothing to check

        installed = self._get_installed_wpp_version()
        if not installed:
            return  # Could not determine installed version — skip silently

        if not self._version_is_below(installed, minimum):
            return  # Installed version meets (or exceeds) the minimum — all good

        # ── Installed version is older than the minimum ───────────────────────
        from ui.dialogs.api_version_check import (
            ApiVersionOutdatedDialog,
            RESULT_UPDATE, RESULT_EXIT, RESULT_CONTINUE,
        )

        dlg    = ApiVersionOutdatedDialog(self.mw, self.mw.i18n, installed, minimum)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == RESULT_EXIT:
            sys.exit(0)

        if result == RESULT_CONTINUE:
            return  # Proceed with the outdated version — user's choice

        # RESULT_UPDATE: re-download and rebuild using the minimum-version tag
        from ui.dialogs.api_setup import ApiSetupDialog
        update_dlg = ApiSetupDialog(
            self.mw,
            title_override=self.mw.i18n.t("api_update_dialog_title"),
            forced_tag=minimum,
        )
        update_result = update_dlg.ShowModal()
        update_dlg.Destroy()

        if update_result != wx.ID_OK:
            sys.exit(0)

    # ── WPPConnect lifecycle ─────────────────────────────────────────────────

    def _is_wpp_running(self):
        """Return True if the WPPConnect is already listening on the configured port."""
        try:
            with _socket.create_connection(("127.0.0.1", self.mw.wpp_port), timeout=1):
                return True
        except OSError:
            return False

    def _start_wpp_background(self):
        """
        Launch the bundled WPPConnect Server node process in the background.
        stdout and stderr are redirected to api/wppconnect.log so that startup
        errors can be shown to the user if the port never opens.
        Does nothing if the node or start.js files are not present (dev mode).

        When the current process is elevated (run as Administrator) the child
        is spawned using the non-elevated linked token via CreateProcessWithTokenW
        so that PostgreSQL's initdb can start (it refuses to run as root/admin).
        """
        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        start_js  = resource_path("api",  "start.js")
        if not os.path.isfile(node_exe) or not os.path.isfile(start_js):
            return  # Not bundled — developer runs WPPConnect separately
        try:
            self._wpp_log_path = log_path("wppconnect.log")
            log_fh = open(self._wpp_log_path, "w",
                          encoding="utf-8", errors="replace")
            cwd = _get_short_path_name(resource_path("api"))
            self.mw.wpp_process = None

            os.environ["AUTHENTICATION_API_KEY"] = self.mw.wpp_api_key
            os.environ["WPP_LID_MODE"] = "false"
            os.environ["PORT"] = str(self.mw.wpp_port)
            os.environ["PUPPETEER_CACHE_DIR"] = resource_path("api", ".cache", "puppeteer")

            try:
                _dist_cfg = resource_path("api", "dist", "config.js")
                if os.path.isfile(_dist_cfg):
                    with open(_dist_cfg, "r", encoding="utf-8") as _f:
                        _cfg_src = _f.read()
                    if "useChrome" not in _cfg_src:
                        _cfg_src = _cfg_src.replace(
                            "createOptions: {",
                            "createOptions: { useChrome: false,",
                            1,
                        )
                        with open(_dist_cfg, "w", encoding="utf-8") as _f:
                            _f.write(_cfg_src)
                        logging.info("[startup] Patched dist/config.js: useChrome → false")
            except Exception as _e:
                logging.warning("[startup] Could not patch dist/config.js: %s", _e)

            creation_flags = 0
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creation_flags = subprocess.CREATE_NO_WINDOW

            self.mw.wpp_process = subprocess.Popen(
                [node_exe, start_js],
                cwd=cwd,
                creationflags=creation_flags,
                stdout=log_fh,
                stderr=log_fh,
            )
            log_fh.close()
            self._wpp_log_fh = None
            atexit.register(self._stop_wpp_server)
        except Exception:
            pass

    def _stop_wpp_server(self):
        """Terminate the WPPConnect Server process and all its children.

        Calls /close-session first so WPPConnect asks Puppeteer to
        browser.close() Chrome gracefully, preventing stale Chrome windows.
        """
        token = getattr(self.mw, "token", "")
        if token:
            try:
                url = (
                    f"{self.mw.wpp_server}:{self.mw.wpp_port}"
                    f"/api/{token}/close-session"
                )
                requests.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5,
                )
                time.sleep(2)
            except Exception:
                pass

        proc = getattr(self.mw, "wpp_process", None)
        if proc and proc.poll() is None:
            try:
                pid = proc.pid
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                    )
                else:
                    proc.terminate()
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def ensure_wpp_running(self):
        """
        Start the local WPPConnect Server if it is not already listening.

        Normal mode   — shows a progress dialog while waiting (up to 3 min).
        Background mode — polls silently; exits with code 1 on timeout.

        Originally:
        wait up to 3 minutes for it to become ready via a progress dialog.
        On first launch the database initialisation and migrations can take
        60-90 s; subsequent starts are much faster.
        """
        if self._is_wpp_running():
            return  # Already up (e.g. left running from a previous session)

        if sys.platform == "win32":
            node_exe = resource_path("node", "node.exe")
        else:
            local_node = resource_path("node", "node")
            if os.path.isfile(local_node):
                node_exe = local_node
            else:
                node_exe = shutil.which("node") or "node"

        start_js  = resource_path("api",  "start.js")
        dist_server = resource_path("api",  "dist", "server.js")

        if not (os.path.isfile(node_exe)
                and os.path.isfile(start_js)
                and os.path.isfile(dist_server)):
            return

        self._wpp_log_path = None
        self._wpp_log_fh   = None
        self._start_wpp_background()

        if self.mw.background_mode:
            deadline = time.time() + 120
            while time.time() < deadline:
                if self._is_wpp_running():
                    return
                time.sleep(2)
            sys.exit(1)

        from ui.dialogs.api_startup import ApiStartupDialog
        dlg    = ApiStartupDialog(self.mw, self.mw.wpp_port)
        result = dlg.ShowModal()
        if dlg:
            dlg.Destroy()

        if result != wx.ID_OK:
            details = ""
            log_path = getattr(self, "_wpp_log_path", None)
            if log_path and os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    details = "".join(lines[-40:]).strip()
                except Exception:
                    pass
            msg = self.mw.i18n.t("api_startup_warning")
            if details:
                msg = f"{msg}\n\n{details}"
            wx.MessageBox(msg, self.mw.app_name, wx.OK | wx.ICON_ERROR)
            sys.exit(1)
