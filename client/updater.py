"""
Auto-updater for WinZapp.

Flow:
  1. UpdateChecker runs in a background thread at startup (if updates_enabled).
  2. If a newer version is found, show UpdateDialog on the main thread.
  3. User clicks "Sim" -> UpdateProgressDialog downloads the ZIP then installs.
  4. User clicks "Nao" -> retry in 3 hours.
  5. User clicks "Quais as novidades?" -> WhatsNewDialog shows changelog.
  6. After install: batch script waits for our PID, copies files, restarts.
"""

import os
import re
import sys
import time
import zipfile
import tempfile
import threading
import logging
import ctypes
import subprocess
import requests
import wx

from app_paths import _outer_exe_dir, _is_frozen
from config import GITHUB_API_LATEST_RELEASE
from version import __version__


# ── Version helpers ───────────────────────────────────────────────────────────

_PRE_ORDER = {"dev": 0, "alpha": 1, "beta": 2, "": 3}

_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)(dev|alpha|beta)?$", re.IGNORECASE)


def parse_version(v: str):
    """Parse "1.2.3.4suffix" -> ((1,2,3,4), suffix) or None on failure."""
    if not v:
        return None
    m = _VER_RE.match(v.strip())
    if not m:
        return None
    nums   = tuple(int(m.group(i)) for i in range(1, 5))
    suffix = (m.group(5) or "").lower()
    return (nums, suffix)


def is_newer(remote: str, local: str) -> bool:
    """Return True if remote version is strictly newer than local."""
    r = parse_version(remote)
    lo = parse_version(local)
    if r is None or lo is None:
        return False
    r_nums, r_suf = r
    l_nums, l_suf = lo
    r_key = (r_nums, _PRE_ORDER.get(r_suf, 0))
    l_key = (l_nums, _PRE_ORDER.get(l_suf, 0))
    return r_key > l_key


# ── Changelog parser ──────────────────────────────────────────────────────────

_HDR_RE = re.compile(r"^V(\d+\.\d+\.\d+\.(?:\d+)(?:dev|alpha|beta)?)\s*$", re.IGNORECASE)


def get_changelog_for_update(changelog_text: str, current: str, new: str) -> str:
    """
    Extract changelog entries for all versions > current and <= new.
    Returns empty string if no relevant entries found.
    """
    c_parsed = parse_version(current)
    n_parsed = parse_version(new)
    if c_parsed is None or n_parsed is None:
        return ""

    c_key = (c_parsed[0], _PRE_ORDER.get(c_parsed[1], 0))
    n_key = (n_parsed[0], _PRE_ORDER.get(n_parsed[1], 0))

    # Split into sections by "V1.2.3.4" header lines
    sections = []
    cur_ver   = None
    cur_lines = []
    for line in changelog_text.splitlines():
        m = _HDR_RE.match(line.strip())
        if m:
            if cur_ver is not None:
                sections.append((cur_ver, cur_lines))
            cur_ver   = m.group(1)
            cur_lines = []
        else:
            if cur_ver is not None:
                cur_lines.append(line)
    if cur_ver is not None:
        sections.append((cur_ver, cur_lines))

    result_parts = []
    for ver_str, lines in sections:
        parsed = parse_version(ver_str)
        if parsed is None:
            continue
        key = (parsed[0], _PRE_ORDER.get(parsed[1], 0))
        if c_key < key <= n_key:
            body = "\n".join(lines).strip()
            if body:
                result_parts.append(f"V{ver_str}\n{body}")

    return "\n\n".join(result_parts)


# ── Install helpers ───────────────────────────────────────────────────────────

def _needs_admin() -> bool:
    """Return True if the install directory is not writable by the current user."""
    install_dir = _outer_exe_dir()
    test_path   = os.path.join(install_dir, ".wz_write_test")
    try:
        with open(test_path, "w") as f:
            f.write("x")
        os.remove(test_path)
        return False
    except OSError:
        return True


def _run_batch_installer(extracted_dir: str, install_dir: str, exe_name: str, pid: int, api_port: int = 6300):
    """
    Write a batch script that:
      1. Waits for PID to exit.
      2. Kills any leftover WPPConnect Server (api_port) and PostgreSQL (5433) processes.
      3. Copies all extracted files to install_dir.
      4. Restarts the client executable.
    Then launches it (elevated if the directory needs admin).
    """
    source_dir = extracted_dir
    winzapp_sub = os.path.join(extracted_dir, "WinZapp")
    if os.path.isdir(winzapp_sub):
        source_dir = winzapp_sub

    bat_fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="winzapp_upd_")
    os.close(bat_fd)

    exe_path = os.path.join(install_dir, exe_name)

    bat = (
        "@echo off\n"
        ":WAIT\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\n'
        "if not errorlevel 1 (\n"
        "    timeout /t 1 /nobreak >NUL\n"
        "    goto WAIT\n"
        ")\n"
        # Give child processes a moment to exit, then kill stragglers holding file locks.
        "timeout /t 2 /nobreak >NUL\n"
        f"for /f \"tokens=5\" %%a in ('netstat -aon ^| findstr :{api_port} ^| findstr LISTENING') do taskkill /F /PID %%a >NUL 2>&1\n"
        "for /f \"tokens=5\" %%a in ('netstat -aon ^| findstr :5433 ^| findstr LISTENING') do taskkill /F /PID %%a >NUL 2>&1\n"
        f'taskkill /F /FI "WINDOWTITLE eq WinZapp*" /IM node.exe >NUL 2>&1\n'
        "timeout /t 1 /nobreak >NUL\n"
        f'xcopy /E /Y /I /H "{source_dir}\\*" "{install_dir}\\"\n'
        f'if exist "{exe_path}" start "" "{exe_path}"\n'
        'del "%~f0"\n'
    )

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)
    logging.info("Auto-updater: Wrote batch installer script to %s", bat_path)

    if sys.platform == "win32":
        needs_admin = _needs_admin()
        if needs_admin:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "cmd.exe", f'/c "{bat_path}"', None, 0
            )
        else:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACH_PROCESS", 0)
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=flags,
            )
    else:
        logging.warning("Auto-updater: Platform %s is not supported for batch installer execution.", sys.platform)


# ── WhatsNewDialog ────────────────────────────────────────────────────────────

class WhatsNewDialog(wx.Dialog):
    """Shows the changelog entries between the current and new version."""

    def __init__(self, parent, changelog: str):
        i18n = parent.main_window.i18n if hasattr(parent, "main_window") else parent.i18n
        super().__init__(
            parent,
            title=i18n.t("whats_new_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build(parent, changelog, i18n)
        self.SetMinSize((400, 300))
        self.SetSize((520, 400))
        self.Centre()

    def _build(self, parent, changelog, i18n):
        sizer = wx.BoxSizer(wx.VERTICAL)

        text_ctrl = wx.TextCtrl(
            self,
            value=changelog,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        close_btn = wx.Button(self, wx.ID_CLOSE, label=i18n.t("whats_new_close"))
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

        self.SetSizer(sizer)


# ── UpdateProgressDialog ──────────────────────────────────────────────────────

class UpdateProgressDialog(wx.Dialog):
    """
    Shows download + install progress.
    Runs the download in a background thread, updates gauge via CallAfter.
    """

    def __init__(self, parent, new_version: str, main_window, zip_url: str):
        i18n = main_window.i18n
        super().__init__(
            parent,
            title=i18n.t("update_progress_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._main_window  = main_window
        self._new_version  = new_version
        self._zip_url      = zip_url
        self._cancelled    = False
        self._install_ok   = False
        self._error_msg    = ""
        self._build(i18n)
        self.SetMinSize((400, -1))
        self.Fit()
        self.Centre()

    def _build(self, i18n):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._status_label = wx.StaticText(self, label=i18n.t("update_downloading"))
        sizer.Add(self._status_label, 0, wx.ALL, 12)

        self._gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        sizer.Add(self._gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self._cancel_btn = wx.Button(self, wx.ID_CANCEL, label=i18n.t("cancel"))
        self._cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        sizer.Add(self._cancel_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)

    def _on_cancel(self, event):
        self._cancelled = True
        self.EndModal(wx.ID_CANCEL)

    def run(self):
        """Start the download thread and show the dialog modally."""
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        return self.ShowModal()

    def _worker(self):
        """Download, extract, and launch installer — all in a background thread."""
        try:
            # ── Download ──────────────────────────────────────────────────────
            zip_fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="winzapp_upd_")
            os.close(zip_fd)

            logging.info("Auto-updater: Downloading ZIP from %s to %s", self._zip_url, zip_path)
            resp = requests.get(self._zip_url, stream=True, timeout=60)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._cancelled:
                        logging.info("Auto-updater: Download cancelled by user.")
                        return
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = min(int(downloaded * 100 / total), 99)
                        wx.CallAfter(self._gauge.SetValue, pct)

            if self._cancelled:
                logging.info("Auto-updater: Download cancelled by user.")
                return

            logging.info("Auto-updater: Download completed successfully.")

            # ── Extract ───────────────────────────────────────────────────────
            extract_dir = tempfile.mkdtemp(prefix="winzapp_ext_")
            logging.info("Auto-updater: Extracting update to %s", extract_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            os.remove(zip_path)

            # If the ZIP placed all files inside a single top-level folder,
            # point extract_dir at that folder so xcopy copies the contents.
            _entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
            if len(_entries) == 1 and os.path.isdir(
                os.path.join(extract_dir, _entries[0])
            ):
                extract_dir = os.path.join(extract_dir, _entries[0])

            if self._cancelled:
                logging.info("Auto-updater: Extraction cancelled by user.")
                return

            # ── Install ───────────────────────────────────────────────────────
            wx.CallAfter(
                self._status_label.SetLabel,
                self._main_window.i18n.t("update_installing"),
            )
            wx.CallAfter(self._gauge.SetValue, 100)

            if not _is_frozen():
                logging.info("Auto-updater: Dev mode detected. Skipping real installation.")
                time.sleep(1)
                self._install_ok = True
                wx.CallAfter(self.EndModal, wx.ID_OK)
                return

            install_dir = _outer_exe_dir()
            exe_name    = os.path.basename(sys.argv[0]) if sys.argv else "WinZapp.exe"
            pid         = os.getpid()

            logging.info("Auto-updater: Launching batch installer from %s (PID %d)", install_dir, pid)
            _run_batch_installer(extract_dir, install_dir, exe_name, pid, api_port=getattr(self._main_window, "wpp_port", 6300))
            self._install_ok = True
            wx.CallAfter(self.EndModal, wx.ID_OK)

        except Exception as exc:
            logging.exception("Auto-updater: Exception during update installation")
            self._error_msg = str(exc)
            wx.CallAfter(self.EndModal, wx.ID_ABORT)


# ── UpdateDialog ──────────────────────────────────────────────────────────────

class UpdateDialog(wx.Dialog):
    """
    Prompts the user to install an available update.
    Buttons: Sim | Nao | Quais as novidades? (hidden when no changelog)
    """

    def __init__(self, parent, new_version: str, changelog: str):
        self._main_window = parent
        i18n = parent.i18n
        super().__init__(
            parent,
            title=i18n.t("update_available_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._new_version = new_version
        self._changelog   = changelog
        self._build(i18n)
        self.Fit()
        self.SetMinSize((360, -1))
        self.Centre()

    def _build(self, i18n):
        sizer = wx.BoxSizer(wx.VERTICAL)

        msg = i18n.t("update_available_msg").format(new_version=self._new_version)
        label = wx.StaticText(self, label=msg)
        label.Wrap(380)
        sizer.Add(label, 0, wx.ALL, 12)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._yes_btn = wx.Button(self, wx.ID_YES, label=i18n.t("update_yes"))
        self._no_btn  = wx.Button(self, wx.ID_NO,  label=i18n.t("update_no"))
        btn_sizer.Add(self._yes_btn, 0, wx.RIGHT, 4)
        btn_sizer.Add(self._no_btn,  0, wx.RIGHT, 4)

        if self._changelog:
            self._news_btn = wx.Button(self, wx.ID_MORE, label=i18n.t("whats_new_btn"))
            btn_sizer.Add(self._news_btn, 0)
            self._news_btn.Bind(wx.EVT_BUTTON, self._on_whats_new)
        else:
            self._news_btn = None

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)

        self._yes_btn.Bind(wx.EVT_BUTTON, self._on_yes)
        self._no_btn.Bind(wx.EVT_BUTTON,  self._on_no)
        self._yes_btn.SetDefault()

    def _on_yes(self, event):
        self.EndModal(wx.ID_YES)

    def _on_no(self, event):
        self.EndModal(wx.ID_NO)

    def _on_whats_new(self, event):
        dlg = WhatsNewDialog(self, self._changelog)
        dlg.ShowModal()
        dlg.Destroy()


# ── UpdateChecker ─────────────────────────────────────────────────────────────

class UpdateChecker:
    """
    Runs version checks in a background thread.
    Shows UpdateDialog on the main thread when a newer version is found.
    Retries every 3 hours on decline or when already up-to-date.
    """

    _RETRY_INTERVAL = 3 * 60 * 60  # 3 hours in seconds

    def __init__(self, main_window):
        self._mw           = main_window
        self._retry_timer  = None
        self._force        = False

    def start(self):
        """Launch the first check in a background thread."""
        t = threading.Thread(target=self._check_once, daemon=True)
        t.start()

    def force_check(self):
        """Called from the Help > Force Update menu item."""
        self._force = True
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        t = threading.Thread(target=self._check_once, daemon=True)
        t.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_once(self):
        logging.info("Auto-updater: Checking GitHub Releases for updates...")
        try:
            resp = requests.get(
                GITHUB_API_LATEST_RELEASE,
                headers={"User-Agent": f"WinZapp/{__version__}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logging.exception("Auto-updater: Exception checking for updates")
            self._schedule_retry()
            return

        tag_name       = data.get("tag_name", "")
        remote_version = tag_name.lstrip("vV")
        logging.info("Auto-updater: Latest release tag=%s version=%s", tag_name, remote_version)

        if not remote_version:
            logging.warning("Auto-updater: Could not parse version from tag_name=%r", tag_name)
            self._schedule_retry()
            return

        # Find the portable ZIP asset (prefer WinZapp.zip by exact name)
        zip_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            url  = asset.get("browser_download_url", "")
            if name == "winzapp.zip":
                zip_url = url
                break
            if name.endswith(".zip") and not zip_url:
                zip_url = url

        if not zip_url:
            logging.warning("Auto-updater: No ZIP asset found in release %s", tag_name)
            self._schedule_retry()
            return

        local_version = __version__
        logging.info("Auto-updater: Local version is %s", local_version)

        if not is_newer(remote_version, local_version):
            logging.info("Auto-updater: WinZapp is already up-to-date.")
            if self._force:
                self._force = False
                wx.CallAfter(self._show_no_update)
            else:
                self._schedule_retry()
            return

        logging.info("Auto-updater: Newer version %s is available!", remote_version)
        self._force = False

        # Use the GitHub release body (notes written at release creation time)
        changelog = data.get("body", "").strip()

        wx.CallAfter(self._show_update_dialog, remote_version, changelog, zip_url)

    def _show_no_update(self):
        i18n = self._mw.i18n
        wx.MessageBox(
            i18n.t("update_not_available"),
            i18n.t("update_not_available_title"),
            wx.OK | wx.ICON_INFORMATION,
            self._mw,
        )

    def _show_update_dialog(self, remote_version: str, changelog: str, zip_url: str):
        dlg    = UpdateDialog(self._mw, remote_version, changelog)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_YES:
            self._do_install(remote_version, zip_url)
        else:
            # User said No — retry in 3 hours
            self._schedule_retry()

    def _do_install(self, new_version: str, zip_url: str):
        while True:
            prog = UpdateProgressDialog(self._mw, new_version, self._mw, zip_url)
            result = prog.run()
            prog.Destroy()

            if result == wx.ID_OK:
                # Install launched — quit the app so the batch script can run
                self._mw.real_exit()
                return

            if result == wx.ID_CANCEL:
                # User cancelled
                self._schedule_retry()
                return

            # wx.ID_ABORT: error occurred
            error_msg = prog._error_msg
            i18n = self._mw.i18n
            retry = wx.MessageBox(
                i18n.t("update_error_msg").format(error=error_msg),
                i18n.t("update_error_title"),
                wx.YES_NO | wx.ICON_ERROR,
                self._mw,
            )
            if retry != wx.YES:
                self._schedule_retry()
                return
            # else: loop and retry the download

    def _schedule_retry(self):
        self._retry_timer = threading.Timer(self._RETRY_INTERVAL, self._check_once)
        self._retry_timer.daemon = True
        self._retry_timer.start()

    def stop(self):
        """Cancel any pending retry timer."""
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
