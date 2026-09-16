"""
Build ONLY the portable WinZapp.zip (onedir layout) — no MSYS2/gcc needed.

Reuses build.py's onedir pipeline but skips the C installer/uninstaller stub
compilation (compile_uninstaller / compile_installer_stub / append_zip_to_stub),
which are the only steps that require gcc/windres. The result — dist/WinZapp.zip
with the full WinZapp/ onedir layout — is exactly what the auto-updater consumes
to overwrite an existing install, so it's what we want for testing overwrite +
migration on the old version.

Picks its interpreter the same way build.py does (WINZAPP_VENV, the running
virtual environment, then venv\\ / .venv\\), so any of these work:
  venv_build\\Scripts\\python.exe build_zip_only.py
  set WINZAPP_VENV=venv_build && python build_zip_only.py
  uv run python build_zip_only.py
"""

import os
import sys

if __name__ == "__main__":
    # Importing build.py never runs its own hand-over, and the import below
    # already reads site-packages, so it has to happen here first.
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from winzapp_tools.build_env import hand_over_to_build_python
    hand_over_to_build_python(__file__, _root)

import build  # noqa: E402  (build.py runs check-time module code on import)


def main():
    print("\nWinZapp Portable-ZIP Build (onedir layout, no installer stub)")
    print("=" * 60)
    # check_tools() would hard-fail on missing gcc/windres in onedir mode, so
    # replicate only the checks that matter for the ZIP (pyinstaller, python,
    # node, api). We call the pieces of the pipeline directly.
    build.ONEFILE = False

    # Minimal asset checks (skip gcc/windres — not needed for the ZIP).
    import os
    import sys
    problems = []
    import importlib.util
    if importlib.util.find_spec("PyInstaller") is None:
        problems.append(f"pyinstaller not installed for {build.PYTHON_CMD}")
    if not os.path.isfile(os.path.join(build.NODE_DIR, "node.exe")):
        problems.append("client/node/node.exe missing")
    if not os.path.isfile(os.path.join(build.API_DIR, "dist", "server.js")):
        problems.append("client/api/dist/server.js missing")
    if problems:
        for p in problems:
            print(f"  [ERROR] {p}")
        sys.exit(1)
    print("  Core assets present (pyinstaller, node, api/dist).")

    build.pyinstaller_compile()
    build.assemble_staging()
    build.create_portable_zip()

    print(f"\n{'='*60}")
    print("  Portable ZIP build complete!")
    print(f"  Portable : {build.PORTABLE_ZIP}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
