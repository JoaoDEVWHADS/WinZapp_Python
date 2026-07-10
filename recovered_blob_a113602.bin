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
import ctypes
import subprocess
import requests
import wx
import logging

from app_paths import _outer_exe_dir, _is_frozen
from config import GITHUB_RELEASE_URL, UPDATE_ZIP_URL
from version import __version__


# ── Version helpers ───────────────────────────────────────────────────────────

_PRE_ORDER = {"dev": 0, "alpha": 1, "beta": 2, "": 3}


def parse_version(v: str):
    """Parse version string -> (nums_tuple, suffix) or None on failure."""
    if not v:
        return None
    v = v.strip()
    
    # Extract dev/alpha/beta suffix
    suffix = ""
    m_suf = re.search(r'(dev|alpha|beta)', v, re.IGNORECASE)
    if m_suf:
        suffix = m_suf.group(1).lower()
        v = re.sub(r'(dev|alpha|beta)', '', v, flags=re.IGNORECASE)
        
    # Extract all digits
    parts = [int(x) for x in re.findall(r'\d+', v)]
    if not parts:
        return None
        
    # Pad to length 4 for standard comparison
    while len(parts) < 4:
        parts.append(0)
        
    return (tuple(parts[:4]), suffix)


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


def _run_batch_installer(extracted_dir: str, install_dir: str, exe_name: str, pid: int):
    """
    Write a batch script that:
      1. Forcefully terminates the WinZapp client process and its children.
      2. Finds and terminates any leftover Evolution API (port 6300) and PostgreSQL (port 5433) processes to release file locks.
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
        f"taskkill /F /PID {pid} >NUL 2>&1\n"
        "for /f \"tokens=5\" %%a in ('netstat -aon ^| findstr :6300 ^| findstr LISTENING') do taskkill /F /PID %%a >NUL 2>&1\n"
        "for /f \"tokens=5\" %%a in ('netstat -aon ^| findstr :5433 ^| findstr LISTENING') do taskkill /F /PID %%a >NUL 2>&1\n"
        "timeout /t 2 /nobreak >NUL\n"
        f'xcopy /E /Y /I "{source_dir}\\*" "{install_dir}\\"\n'
        f'if exist "{exe_path}" start "" "{exe_path}"\n'
        'del "%~f0"\n'
    )

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat)
    logging.info("Auto-updater: Wrote batch installer script to %s", bat_path)

    if sys.platform == "win32":
        needs_admin = _needs_admin()
        if needs_admin:
            import ctypes
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


# ── UpdateProgressDialog ──────────────────────────────────────────────────────

class UpdateProgressDialog(wx.Dialog):
    """
    Shows download + install progress.
    Runs the download in a background thread, updates gauge via CallAfter.
    """

    def __init__(self, parent, new_version: str, main_window):
        i18n = main_window.i18n
        super().__init__(
            parent,
            title=i18n.t("update_progress_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._main_window  = main_window
        self._new_version  = new_version
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

            logging.info("Auto-updater: Downloading ZIP from %s to %s", UPDATE_ZIP_URL, zip_path)
            resp = requests.get(UPDATE_ZIP_URL, stream=True, timeout=60)
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
            _run_batch_installer(extract_dir, install_dir, exe_name, pid)
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
    Buttons: Sim | Nao
    """

    def __init__(self, parent, new_version: str):
        self._main_window = parent
        i18n = parent.i18n
        super().__init__(
            parent,
            title=i18n.t("update_available_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._new_version = new_version
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

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)

        self._yes_btn.Bind(wx.EVT_BUTTON, self._on_yes)
        self._no_btn.Bind(wx.EVT_BUTTON,  self._on_no)
        self._yes_btn.SetDefault()

    def _on_yes(self, event):
        self.EndModal(wx.ID_YES)

    def _on_no(self, event):
        self.EndModal(wx.ID_NO)


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
        logging.info("Auto-updater: Starting update check...")
        try:
            headers = {"User-Agent": "WinZapp-Updater"}
            logging.info("Auto-updater: Querying GITHUB_RELEASE_URL: %s", GITHUB_RELEASE_URL)
            resp = requests.get(GITHUB_RELEASE_URL, headers=headers, timeout=15)
            resp.raise_for_status()
            data           = resp.json()
            remote_version = data.get("tag_name", "").lstrip("vV")
            logging.info("Auto-updater: Latest remote version from GitHub is v%s", remote_version)
        except Exception as e:
            logging.exception("Auto-updater: Exception checking for updates")
            if self._force:
                self._force = False
                wx.CallAfter(self._show_error_message, str(e))
            self._schedule_retry()
            return

        local_version = __version__
        logging.info("Auto-updater: Local version is v%s", local_version)

        if not is_newer(remote_version, local_version):
            logging.info("Auto-updater: WinZapp is already up-to-date.")
            if self._force:
                self._force = False
                wx.CallAfter(self._show_no_update)
            else:
                self._schedule_retry()
            return

        logging.info("Auto-updater: Newer version v%s is available!", remote_version)
        self._force = False
        wx.CallAfter(self._show_update_dialog, remote_version)

    def _show_error_message(self, err_msg: str):
        i18n = self._mw.i18n
        wx.MessageBox(
            i18n.t("update_error_msg").format(error=err_msg),
            i18n.t("update_error_title"),
            wx.OK | wx.ICON_ERROR,
            self._mw,
        )

    def _show_no_update(self):
        i18n = self._mw.i18n
        wx.MessageBox(
            i18n.t("update_not_available"),
            i18n.t("update_not_available_title"),
            wx.OK | wx.ICON_INFORMATION,
            self._mw,
        )

    def _show_update_dialog(self, remote_version: str):
        dlg    = UpdateDialog(self._mw, remote_version)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_YES:
            self._do_install(remote_version)
        else:
            # User said No — retry in 3 hours
            self._schedule_retry()

    def _do_install(self, new_version: str):
        while True:
            prog = UpdateProgressDialog(self._mw, new_version, self._mw)
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
