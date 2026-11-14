# Overrides the contrib hook: accessible_output2's bundled libraries are
# Windows DLLs. On macOS speech goes through winzapp_mac.speech instead.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("accessible_output2")
