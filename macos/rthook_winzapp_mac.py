# PyInstaller runtime hook: install the macOS layer before WinZapp's main.py runs.
import winzapp_mac

winzapp_mac.install()
