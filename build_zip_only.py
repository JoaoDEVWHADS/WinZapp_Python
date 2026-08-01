"""
Build ONLY the portable WinZapp.zip (onedir layout) — no MSYS2/gcc needed.

Reuses build.py's onedir pipeline but skips the C installer/uninstaller stub
compilation (compile_uninstaller / compile_installer_stub / append_zip_to_stub),
which are the only steps that require gcc/windres. The result — dist/WinZapp.zip
with the full WinZapp/ onedir layout — is exactly what the auto-updater consumes
to overwrite an existing install, so it's what we want for testing overwrite +
migration on the old version.

Run with the SAME interpreter/venv build.py expects:
  venv_build\\Scripts\\python.exe build_zip_only.py
"""

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
    if not os.path.isfile(build.PYINSTALLER_CMD):
        problems.append(f"pyinstaller missing at {build.PYINSTALLER_CMD}")
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
