"""
node_download.py — WinZapp automatic portable Node.js download dialog.

Shown when client/node/node.exe is absent.  Downloads the Windows x64
portable Node.js distribution from nodejs.org and extracts it into
client/node/ so the bundled WPPConnect Server can run.

The user never needs to install Node.js manually.
"""

import io
import logging
import os
import shutil
import sys
import tempfile
import threading
import zipfile

import requests
import wx

from app_paths import resource_path

log = logging.getLogger(__name__)

_NODE_VERSION = "18.20.4"
_NODE_URL = (
    f"https://nodejs.org/dist/v{_NODE_VERSION}/"
    f"node-v{_NODE_VERSION}-win-x64.zip"
)

_TOP_DIR = f"node-v{_NODE_VERSION}-win-x64"


class NodeDownloadDialog(wx.Dialog):
    """Progress dialog for downloading + extracting portable Node.js.

    Modal result:
      wx.ID_OK     — Node.js is ready; caller may continue
      wx.ID_CANCEL — user cancelled or an error occurred; caller should exit
    """

    _PULSE_MS = 80

    def __init__(self, parent):
        title = "WinZapp | Baixando Node.js portátil..."
        style = wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX
        super().__init__(parent, title=title, style=style)

        self._cancelled = False

        self._build_ui()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse, self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)

        t = threading.Thread(target=self._run_download, daemon=True)
        t.start()

        self._timer.Start(self._PULSE_MS)

    def _build_ui(self):
        self._status_lbl = wx.StaticText(
            self,
            label="A preparar o download do Node.js...",
        )

        self._gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)

        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancelar")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._status_lbl, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(self._gauge, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(cancel_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize((520, -1))
        self.Centre()

    def _set_status(self, text: str):
        wx.CallAfter(self._status_lbl.SetLabel, text)
        wx.CallAfter(self.Layout)

    def _on_pulse(self, _event):
        self._gauge.Pulse()

    def _on_cancel(self, _event=None):
        if self._cancelled:
            return
        self._cancelled = True
        self._timer.Stop()
        self.EndModal(wx.ID_CANCEL)

    def _finish_success(self):
        self._timer.Stop()
        self.EndModal(wx.ID_OK)

    def _finish_error(self, details: str = ""):
        self._timer.Stop()
        msg = (
            "Ocorreu um erro ao descarregar o Node.js portátil.\n\n"
            "Verifique a sua ligação à Internet e tente novamente.\n"
            "Se o problema persistir, instale o Node.js manualmente "
            "a partir de https://nodejs.org"
        )
        if details:
            msg = f"{msg}\n\n{details}"
        wx.MessageBox(msg, "Erro de download", wx.OK | wx.ICON_ERROR, self)
        self.EndModal(wx.ID_CANCEL)

    def _download_zip(self, url: str, dest_path: str) -> bool:
        try:
            response = requests.get(url, stream=True, timeout=(30, 300))
            response.raise_for_status()
        except requests.RequestException as exc:
            if not self._cancelled:
                self._finish_error(str(exc))
            return False

        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 512 * 1024

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
                            f"Baixando Node.js portátil... "
                            f"{mb_down:.1f} MB / {mb_total:.1f} MB"
                        )
                    else:
                        self._set_status(
                            f"Baixando Node.js portátil... {mb_down:.1f} MB"
                        )
        except Exception as exc:
            if not self._cancelled:
                self._finish_error(str(exc))
            return False

        return not self._cancelled

    def _extract_node(self, zip_path: str, node_dir: str) -> bool:
        self._set_status("Extraindo Node.js...")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.infolist():
                    if self._cancelled:
                        return False

                    rel = member.filename
                    if rel.startswith(_TOP_DIR + "/"):
                        rel = rel[len(_TOP_DIR) + 1:]
                    else:
                        continue
                    if not rel:
                        continue

                    rel_os = rel.replace("/", os.sep)
                    dest = os.path.join(node_dir, rel_os)

                    if member.is_dir() or rel.endswith("/"):
                        os.makedirs(dest, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(member) as src_fh, open(dest, "wb") as dst_fh:
                            shutil.copyfileobj(src_fh, dst_fh)
        except Exception as exc:
            if not self._cancelled:
                self._finish_error(f"Falha ao extrair Node.js:\n\n{exc}")
            return False

        return not self._cancelled

    def _run_download(self):
        node_dir = resource_path("node")
        os.makedirs(node_dir, exist_ok=True)

        tmp_zip = tempfile.mktemp(suffix=".zip", prefix="winzapp_node_")
        try:
            ok = self._download_zip(_NODE_URL, tmp_zip)
            if not ok:
                return

            if self._cancelled:
                return

            ok = self._extract_node(tmp_zip, node_dir)
            if not ok:
                return

            node_exe = os.path.join(node_dir, "node.exe")
            if not os.path.isfile(node_exe):
                if not self._cancelled:
                    self._finish_error(
                        "O ZIP do Node.js não continha node.exe. "
                        "O download pode estar corrompido."
                    )
                return

            if not self._cancelled:
                wx.CallAfter(self._finish_success)

        finally:
            try:
                os.remove(tmp_zip)
            except Exception:
                pass
