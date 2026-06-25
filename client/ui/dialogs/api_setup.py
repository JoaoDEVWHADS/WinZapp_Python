"""
api_setup.py — WinZapp first-run WPPConnect Server setup dialog.

Shown when api/dist/main.js is absent, meaning the WPPConnect Server has not yet
been downloaded and compiled.  Performs the full setup in a background thread:

  1. Download the WPPConnect Server source ZIP from GitHub (no git required)
       • No tag  → branch main  archive
       • With tag → specific tag archive
  2. Extract into client/api/, preserving our pre-included files (start.js, .env)
  3. npm install embedded-postgres --save  (add runtime dependency)
  4. npm install --no-audit --no-fund      (install all dependencies)
  5. npm run db:generate                   (only if the script is defined)
  6. npm run build                         (compile TypeScript → dist/main.js)

Note: db:deploy / db:deploy:win are NOT run here.  Prisma migrations require
a live PostgreSQL connection, which is only available at runtime.  The
migrations are applied automatically by start.js every time the API starts.

The WPPCONNECT_TAG_VERSION variable in the root .env optionally pins a specific
tag.  When unset the latest main branch is downloaded.

Uses only the standard library (zipfile, io, tempfile) plus the already-present
requests package for the HTTP download — no git installation required.

Modal result:
  wx.ID_OK     — setup succeeded; caller may proceed
  wx.ID_CANCEL — user cancelled or an error occurred; caller should exit
"""

import os
import shutil
import subprocess
import tempfile
import threading
import zipfile

import requests
import wx

from app_paths import resource_path

# GitHub download URLs — no git required
_REPO_ZIP_MAIN = (
    "https://github.com/wppconnect-team/wppconnect-server"
    "/archive/refs/heads/main.zip"
)
_REPO_ZIP_TAG  = (
    "https://github.com/wppconnect-team/wppconnect-server"
    "/archive/refs/tags/{tag}.zip"
)

# Root-level files whose pre-included content always takes precedence.
_PRESERVE = {"start.js", ".env", "config.json"}

# Runtime state dirs/files that should survive a re-download.
_KEEP_RUNTIME = {"wppconnect_tokens", "userDataDir", "wppconnect.log"}


class ApiSetupDialog(wx.Dialog):
    """Progress dialog for the WPPConnect Server download + build setup.

    Parameters
    ----------
    parent        : wx.Window
    title_override: str | None
        When provided, overrides the default hardcoded dialog title.
        Used by the update flow to show a different title.
    forced_tag    : str | None
        When provided, this tag is used for the GitHub download instead
        of reading WPPCONNECT_TAG_VERSION from the .env file.  Used by
        the update flow to pin the exact minimum-version tag.
    """

    _PULSE_MS = 80

    def __init__(self, parent, title_override=None, forced_tag=None):
        title = (title_override
                 or "WinZapp | Instalando e configurando os módulos necessários para o funcionamento do programa")
        style = wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX
        super().__init__(parent, title=title, style=style)

        self._proc        = None   # active npm subprocess (for kill on cancel)
        self._cancelled   = False
        self._forced_tag  = forced_tag   # overrides .env WPPCONNECT_TAG_VERSION

        self._build_ui()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse, self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)

        t = threading.Thread(target=self._run_setup, daemon=True)
        t.start()

        self._timer.Start(self._PULSE_MS)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._status_lbl = wx.StaticText(self, label="Aguarde enquanto os módulos necessários para o funcionamento do WinZapp são instalados e configurados.")

        self._gauge = wx.Gauge(self, range=100,
                               style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)

        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancelar")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._status_lbl, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(self._gauge,      0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(cancel_btn,       0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize((520, -1))
        self.Centre()

    def _set_status(self, text: str):
        wx.CallAfter(self._status_lbl.SetLabel, text)
        wx.CallAfter(self.Layout)

    # ── Timer / gauge ─────────────────────────────────────────────────────────

    def _on_pulse(self, _event):
        self._gauge.Pulse()

    # ── .env reader ───────────────────────────────────────────────────────────

    def _read_env_value(self, key: str, default: str = "") -> str:
        """Read a value from the nearest .env file; fall back to default."""
        for env_path in [
            resource_path(".env"),
            os.path.join(os.path.dirname(resource_path()), ".env"),
        ]:
            if not os.path.isfile(env_path):
                continue
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

    # ── Download helper ───────────────────────────────────────────────────────

    def _download_zip(self, url: str, dest_path: str) -> bool:
        """
        Stream-download the ZIP at *url* to *dest_path*.
        Updates the status label with download progress.
        Returns True on success, False on failure/cancel.
        """
        try:
            response = requests.get(url, stream=True, timeout=(30, 300))
            response.raise_for_status()
        except requests.RequestException as exc:
            if not self._cancelled:
                wx.CallAfter(
                    self._finish_error,
                    f"Falha ao iniciar o download:\n\n{exc}",
                )
            return False

        total     = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 512 * 1024   # 512 KB

        try:
            with open(dest_path, "wb") as fh:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self._cancelled:
                        return False
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    mb_down = downloaded / (1024 * 1024)
                    if total:
                        mb_total = total / (1024 * 1024)
                        self._set_status(
                            f"Baixando WPPConnect Server... "
                            f"{mb_down:.1f} MB / {mb_total:.1f} MB"
                        )
                    else:
                        self._set_status(
                            f"Baixando WPPConnect Server... {mb_down:.1f} MB"
                        )
        except Exception as exc:
            if not self._cancelled:
                wx.CallAfter(
                    self._finish_error,
                    f"Erro durante o download:\n\n{exc}",
                )
            return False

        return not self._cancelled

    # ── Extract helper ────────────────────────────────────────────────────────

    def _extract_zip(self, zip_path: str, api_dir: str) -> bool:
        """
        Extract the GitHub source ZIP into *api_dir*.

        GitHub archives wrap all content in a single top-level directory
        (e.g. "wppconnect-server-main/" or "wppconnect-server-2.10.0/").
        That prefix is stripped so files land directly in api_dir.

        Root-level entries matching _PRESERVE are skipped so our pre-included
        start.js and .env are never overwritten.
        """
        self._set_status("Extraindo arquivos da API...")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.infolist()

                # Detect the top-level directory from the first entry
                first_name = members[0].filename if members else ""
                top_dir    = first_name.split("/")[0] + "/"  # e.g. "wppconnect-server-main/"

                for member in members:
                    if self._cancelled:
                        return False

                    # Strip the top-level directory prefix
                    rel = member.filename
                    if rel.startswith(top_dir):
                        rel = rel[len(top_dir):]
                    if not rel:
                        # This was the top-level dir entry itself
                        continue

                    # Normalise to OS separators
                    rel_os = rel.replace("/", os.sep)

                    # Skip root-level preserved files
                    root_component = rel.split("/")[0]
                    if root_component in _PRESERVE and "/" not in rel.rstrip("/"):
                        continue

                    dest = os.path.join(api_dir, rel_os)

                    if member.is_dir() or rel.endswith("/"):
                        os.makedirs(dest, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(member) as src_fh, open(dest, "wb") as dst_fh:
                            shutil.copyfileobj(src_fh, dst_fh)

        except Exception as exc:
            if not self._cancelled:
                wx.CallAfter(
                    self._finish_error,
                    f"Falha ao extrair o arquivo ZIP:\n\n{exc}",
                )
            return False

        return not self._cancelled

    # ── npm subprocess helper ─────────────────────────────────────────────────

    def _run_subprocess(self, cmd, cwd=None, env=None):
        """
        Run a subprocess and wait for it to finish.
        Returns (success: bool, stderr: str).
        """
        import sys
        creation_flags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr_bytes = self._proc.communicate()
        except FileNotFoundError as exc:
            return False, str(exc)

        if self._cancelled:
            return False, ""
        rc     = self._proc.returncode
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        return (rc == 0), stderr

    # ── Background setup thread ───────────────────────────────────────────────

    def _run_setup(self):
        import sys
        import shutil

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

        api_dir  = resource_path("api")
        puppeteer_cache = resource_path("api", ".cache", "puppeteer")
        npm_env  = {
            **os.environ,
            "PATH": path_env,
            "PUPPETEER_CACHE_DIR": puppeteer_cache
        }
        tag      = self._forced_tag if self._forced_tag is not None else self._read_env_value("WPPCONNECT_TAG_VERSION")

        try:
            # ── Step 1: download source ZIP ───────────────────────────────
            if tag:
                url = _REPO_ZIP_TAG.format(tag=tag)
            else:
                url = _REPO_ZIP_MAIN

            tmp_zip = tempfile.mktemp(suffix=".zip", prefix="winzapp_api_")
            try:
                ok = self._download_zip(url, tmp_zip)
                if not ok:
                    return  # error already reported or cancelled

                if self._cancelled:
                    return

                # ── Step 2: clean previous partial setup ──────────────────
                self._set_status("Preparando pasta da API...")
                for item in os.listdir(api_dir):
                    if item in _PRESERVE or item in _KEEP_RUNTIME:
                        continue
                    target = os.path.join(api_dir, item)
                    try:
                        if os.path.isdir(target):
                            shutil.rmtree(target, ignore_errors=True)
                        else:
                            os.remove(target)
                    except Exception:
                        pass

                if self._cancelled:
                    return

                # ── Step 3: extract ZIP into client/api/ ──────────────────
                ok = self._extract_zip(tmp_zip, api_dir)
                if not ok:
                    return

            finally:
                try:
                    os.remove(tmp_zip)
                except Exception:
                    pass

            if self._cancelled:
                return

            # ── Step 4: npm install ───────────────────────────────────────
            self._set_status("Instalando dependências (npm install)...")
            ok, err = self._run_subprocess(
                npm_cmd + ["install", "--no-audit", "--no-fund", "--include=optional", "--legacy-peer-deps"],
                cwd=api_dir,
                env=npm_env,
            )
            if not ok:
                if not self._cancelled:
                    wx.CallAfter(self._finish_error,
                                 f"Falha em npm install:\n\n{err}")
                return

            if self._cancelled:
                return

            # ── Step 4.5: download chrome if using modern puppeteer ───────
            self._set_status("Baixando executável do Chrome (puppeteer)...")
            ok, err = self._run_subprocess(
                npm_cmd + ["exec", "puppeteer", "browsers", "install", "chrome"],
                cwd=api_dir,
                env=npm_env,
            )
            # Do not fail hard if this step fails (e.g. offline setup where Chrome was pre-copied)
            if not ok:
                logging.warning(f"Failed to install Chrome browser via Puppeteer CLI: {err}")

            if self._cancelled:
                return

            # ── Step 5: npm run build ─────────────────────────────────────
            self._set_status(
                "Compilando o WPPConnect Server (npm run build) — "
                "isso pode levar alguns minutos..."
            )
            ok, err = self._run_subprocess(
                npm_cmd + ["run", "build"],
                cwd=api_dir,
                env=npm_env,
            )
            if not ok:
                if not self._cancelled:
                    wx.CallAfter(self._finish_error,
                                 f"Falha em npm run build:\n\n{err}")
                return

            if not self._cancelled:
                wx.CallAfter(self._finish_success)

        except Exception as exc:
            if not self._cancelled:
                wx.CallAfter(self._finish_error, str(exc))

    # ── Process-tree kill ─────────────────────────────────────────────────────

    def _kill_proc_tree(self):
        """Kill the active npm process and all its spawned children."""
        if self._proc and self._proc.poll() is None:
            import sys
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self._proc.terminate()
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_cancel(self, _event=None):
        if self._cancelled:
            return
        self._cancelled = True
        self._timer.Stop()
        self._kill_proc_tree()
        self.EndModal(wx.ID_CANCEL)

    def _finish_success(self):
        self._timer.Stop()
        wx.MessageBox(
            "O WPPConnect Server foi configurado com sucesso!\n\n"
            "O WinZapp irá agora iniciar a API.",
            "Configuração concluída",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        self.EndModal(wx.ID_OK)

    def _finish_error(self, details: str = ""):
        self._timer.Stop()
        msg = "Ocorreu um erro durante a configuração do WPPConnect Server."
        if details:
            msg = f"{msg}\n\n{details}"
        wx.MessageBox(msg, "Erro de configuração", wx.OK | wx.ICON_ERROR, self)
        self.EndModal(wx.ID_CANCEL)
