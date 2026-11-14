"""Opt-in, user-operated AI media demo; no MainWindow/WhatsApp/account bootstrap.

Run with the repository's Python: .venv/Scripts/pythonw.exe client/ai_media_demo.py
This is a manual application entry point, never invoked by pytest or on import.
"""
import os

from app_paths import set_active_account
from core.ai_media.demo_fixture import DEMO_ACCOUNT, demo_directory


def main():
    runtime = demo_directory(__file__)
    runtime.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime)
    set_active_account(DEMO_ACCOUNT)
    from autostart import acquire_single_instance_mutex
    if not acquire_single_instance_mutex():
        return
    from core.ai_media.diagnostics import configure_demo_log
    configure_demo_log(runtime / "photo-diagnostics.log")
    import wx
    from ui.ai_media_demo import AIMediaDemoFrame
    app = wx.App(False)
    frame = AIMediaDemoFrame()
    app.SetTopWindow(frame)
    frame.Show()
    wx.CallAfter(frame.panel.focus_photo)
    app.MainLoop()


if __name__ == "__main__":
    main()
