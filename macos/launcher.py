"""Start WinZapp on macOS: install the Mac layer, then run client/main.py
exactly as ``cd client && python main.py`` would."""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if getattr(sys, "frozen", False):
    CLIENT = os.path.join(sys._MEIPASS, "client")
else:
    CLIENT = os.path.join(ROOT, "client")
    pydeps = os.path.join(ROOT, ".pydeps")
    if os.path.isdir(pydeps) and pydeps not in sys.path:
        sys.path.insert(0, pydeps)

sys.path.insert(0, HERE)
sys.path.insert(0, CLIENT)

import winzapp_mac  # noqa: E402

winzapp_mac.install()

if not getattr(sys, "frozen", False):
    os.chdir(CLIENT)
sys.argv[0] = os.path.join(CLIENT, "main.py")
runpy.run_path(os.path.join(CLIENT, "main.py"), run_name="__main__")
