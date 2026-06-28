"""
WinZapp build script — PyInstaller variant.

Build modes:
  --onedir (default):  PyInstaller --onedir -> WinZapp.exe + _internal/
                       Then assemble staging dir + create installer + portable zip.

  --onefile:           PyInstaller --onefile -> WinZapp.exe (single file)
                       All Python deps + external resources (node/, api/, lib/,
                       sounds/, languages/, data/, .env) are embedded in the exe
                       and extracted to a temp directory at runtime.

Steps (onedir default):
  1. Check required tools (pyinstaller, gcc, windres) and pre-built api/ + client/node/
  2. Compile client with PyInstaller -> build/pyinstaller_out/
  3. Assemble staging dir -> WinZapp.exe + _internal/ + lib/ + sounds/ + languages/
                            + data/ + .env + node/ + api/
  4. Compile uninstaller -> build/uninstall.exe
  5. Create payload ZIP (ZIP_STORED) from staging/
  6. Compile installer stub -> build/installer_stub.exe
  7. Append payload ZIP to stub -> dist/WinZappInstaller.exe
  8. Create portable dist/WinZapp.zip

Steps (onefile):
  1. Check tools (no gcc/windres needed)
  2. Compile client with PyInstaller --onefile -> dist/WinZapp.exe
  3. Create portable dist/WinZapp.zip from the single .exe

Before running this script you must prepare:
  venv/  - activate the venv and install pyinstaller:
             venv\Scripts\pip install pyinstaller

  client/node/  - download the Windows x64 portable Node.js zip from
                  https://nodejs.org/dist/ (node-vXX.X.X-win-x64.zip)
                  and extract its contents into client/node/.

  client/api/ - run setup_api.py, then inside client/api/ run:
                  npm install
                  npm run build
                Verify: client/api/dist/server.js must exist.

Usage:
  venv\Scripts\python.exe build.py                  (onedir, default)
  venv\Scripts\python.exe build.py --onefile         (single-file exe)
"""

import os
import sys
import shutil
import subprocess
import zipfile
import argparse

# -- Paths -------------------------------------------------------------------

ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR    = os.path.join(ROOT_DIR, "client")
INSTALLER_DIR = os.path.join(ROOT_DIR, "installer")
BUILD_DIR     = os.path.join(ROOT_DIR, "build")
DIST_DIR      = os.path.join(ROOT_DIR, "dist")
VENV_DIR      = os.path.join(ROOT_DIR, "venv")

# External pre-built assets
NODE_DIR      = os.path.join(CLIENT_DIR, "node")
API_DIR       = os.path.join(CLIENT_DIR, "api")

PYINSTALLER_CMD = os.path.join(VENV_DIR, "Scripts", "pyinstaller.exe")
PYTHON_CMD      = os.path.join(VENV_DIR, "Scripts", "python.exe")
GCC_CMD         = "gcc"
WINDRES_CMD     = "windres"

# PyInstaller output directories
PYINST_OUTDIR   = os.path.join(BUILD_DIR, "pyinstaller_out")
PYINST_APP_DIR  = os.path.join(PYINST_OUTDIR, "WinZapp")
PYINST_EXE      = os.path.join(PYINST_APP_DIR, "WinZapp.exe")
PYINST_INTERNAL = os.path.join(PYINST_APP_DIR, "_internal")

# Onefile output
ONEFILE_EXE     = os.path.join(DIST_DIR, "WinZapp.exe")

# Staging dir (onedir only)
STAGING_DIR     = os.path.join(BUILD_DIR, "staging_pyinstaller")

# Installer paths (onedir only)
PAYLOAD_ZIP     = os.path.join(BUILD_DIR, "payload_pyinstaller.zip")
INSTALLER_STUB  = os.path.join(BUILD_DIR, "installer_stub.exe")
INSTALLER_RES   = os.path.join(BUILD_DIR, "installer_res.o")
UNINSTALLER_RES = os.path.join(BUILD_DIR, "uninstaller_res.o")
UNINSTALLER_EXE = os.path.join(BUILD_DIR, "uninstall.exe")
INSTALLER_OUT   = os.path.join(DIST_DIR,  "WinZappInstaller.exe")
PORTABLE_ZIP    = os.path.join(DIST_DIR,  "WinZapp.zip")

SETTINGS_DEFAULT = os.path.join(CLIENT_DIR, "data", "settings_default.json")

SITE_PACKAGES = os.path.join(VENV_DIR, "Lib", "site-packages")
SOUND_LIB_X64 = os.path.join(SITE_PACKAGES, "sound_lib", "lib", "x64")
AO2_LIB       = os.path.join(SITE_PACKAGES, "accessible_output2", "lib")

# libopus-0.dll — required by client/core/ogg_opus.py for OGG Opus encoding.
# The build searches for it in client/lib/ first, then the MSYS2 UCRT64 location
# (set up by the GitHub Actions workflow / local MSYS2 installation).
_OPUS_SEARCH = [
    os.path.join(CLIENT_DIR, "lib", "libopus-0.dll"),
    os.path.join(CLIENT_DIR, "lib", "opus.dll"),
    r"C:\msys64\ucrt64\bin\libopus-0.dll",   # MSYS2 UCRT64 (CI + local devs)
    r"C:\msys64\mingw64\bin\libopus-0.dll",  # MSYS2 MinGW64 fallback
]
OPUS_DLL = next((p for p in _OPUS_SEARCH if os.path.isfile(p)), None)

# Directories inside api/ that must NOT be copied
API_EXCLUDE_DIRS  = {
    "wppconnect_tokens", "userDataDir", ".git", "__pycache__", "node_modules",
    ".github", ".husky", ".vscode", "src", "log", "tokens", "uploads",
    "WhatsAppImages", "tests", "coverage",
    ".cache",
}
API_EXCLUDE_FILES = {
    ".gitignore", "README-SETUP.md", ".babelrc", ".eslintignore", ".eslintrc.js",
    ".eslintrc.json", ".prettierrc", ".prettierignore", "jest.config.js",
    "tsconfig.json", "tsconfig.tsbuildinfo", "README.md", "CHANGELOG.md",
    "LICENSE", "LICENSE.header", "license-checker-config.json",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".yarnrc.yml",
    ".env.example", "nodemon.json", ".npmignore", ".npmrc",
    ".commitlintrc.json", ".dockerignore", ".release-it.yml",
    "Dockerfile", "docker-compose.yml", "requests.http",
    "swagger-backup.json",
}
API_EXCLUDE_SUB_DIRS = {"tests", "types"}

# -- CLI --------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="WinZapp build script — PyInstaller variant"
)
parser.add_argument(
    "--onefile", action="store_true",
    help="Build single-file .exe with all resources embedded (default: onedir)"
)
args = parser.parse_args()
ONEFILE = args.onefile

# -- Helpers ----------------------------------------------------------------

def step(msg):
    print(f"\n{'-'*60}")
    print(f"  {msg}")
    print('-'*60)

def run(cmd, cwd=None):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\n[ERROR] Command failed with exit code {result.returncode}.")
        sys.exit(result.returncode)

def walk_dir(root, exclude_top_dirs=None, exclude_top_files=None, exclude_sub_dirs=None):
    exclude_top_dirs  = exclude_top_dirs  or set()
    exclude_top_files = exclude_top_files or set()
    exclude_sub_dirs  = exclude_sub_dirs  or set()
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        top = rel_dir.split(os.sep)[0] if rel_dir != "." else ""
        if top in exclude_top_dirs:
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if not (
            (rel_dir == "." and d in exclude_top_dirs) or
            d in exclude_sub_dirs
        )]
        for fname in files:
            if rel_dir == "." and fname in exclude_top_files:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            yield abs_path, rel_path

# -- Step 1: Check tools and pre-built assets --------------------------------

def check_tools():
    step("1/8  Checking required tools and pre-built assets")
    missing = []

    if not os.path.isfile(PYINSTALLER_CMD):
        missing.append(
            f"pyinstaller  (expected at {PYINSTALLER_CMD})\n"
            f"    Install with: venv\\Scripts\\pip install pyinstaller"
        )
    if not os.path.isfile(PYTHON_CMD):
        missing.append(f"python  (expected at {PYTHON_CMD})")

    if not ONEFILE:
        for tool, name in [(GCC_CMD, "gcc"), (WINDRES_CMD, "windres")]:
            if shutil.which(tool) is None:
                missing.append(f"{name}  (not found in PATH)")

    node_exe = os.path.join(NODE_DIR, "node.exe")
    if not os.path.isfile(node_exe):
        missing.append(
            f"client/node/node.exe  (download portable Node.js for Windows x64 and "
            f"extract to {NODE_DIR})"
        )

    api_main = os.path.join(API_DIR, "dist", "server.js")
    if not os.path.isfile(api_main):
        missing.append(
            "client/api/dist/server.js  -- WPPConnect Server API not built.\n"
            "    1. Run:  venv\\Scripts\\python.exe setup_api.py\n"
            "    2. Then inside client/api/ run:\n"
            "         npm install\n"
            "         npm run build"
        )

    if OPUS_DLL:
        print(f"  [opus] libopus found: {OPUS_DLL}")
    else:
        print(
            "  [WARN] libopus-0.dll not found — voice messages will fail in the built app.\n"
            "         Install MSYS2 and run: pacman -S mingw-w64-ucrt-x86_64-opus\n"
            "         Or copy libopus-0.dll to client/lib/"
        )

    if missing:
        print("\n[ERROR] Missing required tools or pre-built assets:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    print("  All tools and assets found.")

# -- Step 2: PyInstaller compile --------------------------------------------

def pyinstaller_compile():
    mode = "onefile" if ONEFILE else "onedir"
    step(f"2/8  Compiling client with PyInstaller (--{mode})")

    os.makedirs(BUILD_DIR, exist_ok=True)

    if ONEFILE:
        os.makedirs(DIST_DIR, exist_ok=True)
    else:
        os.makedirs(PYINST_OUTDIR, exist_ok=True)
        if os.path.isdir(PYINST_APP_DIR):
            shutil.rmtree(PYINST_APP_DIR)

    work_dir = os.path.join(BUILD_DIR, "pyinstaller_work")

    collect_all = [
        "sound_lib",
        "accessible_output2",
        "platform_utils",
        "libloader",
        "wx",
        "cryptography",
        "requests",
        "socketio",
        "engineio",
        "pyperclip",
        "packaging",
        "windows_toasts",
        "winrt",
        "pyaudio",
        "aiosqlite",
    ]

    cmd = [
        PYINSTALLER_CMD,
        "--onefile" if ONEFILE else "--onedir",
        "--windowed",
        "--name", "WinZapp",
        "--distpath", DIST_DIR if ONEFILE else PYINST_OUTDIR,
        "--workpath", work_dir,
        "--noconfirm",
    ]

    for pkg in collect_all:
        cmd += ["--collect-all", pkg]

    cmd += ["--paths", CLIENT_DIR]

    # In onefile mode, embed external resources as --add-data / --add-binary
    if ONEFILE:
        add_data_pairs = [
            (NODE_DIR, "node"),
            (API_DIR, "api"),
            (SOUND_LIB_X64, "lib"),
            (AO2_LIB, "lib"),
            (os.path.join(CLIENT_DIR, "sounds"), "sounds"),
            (os.path.join(CLIENT_DIR, "languages"), "languages"),
            (SETTINGS_DEFAULT, os.path.join("data", "settings_default.json")),
        ]
        if os.path.isfile(os.path.join(CLIENT_DIR, ".env")):
            add_data_pairs.append(
                (os.path.join(CLIENT_DIR, ".env"), ".env")
            )

        for src, dst in add_data_pairs:
            if os.path.exists(src):
                cmd += ["--add-data", f"{src};{dst}"]

        # libopus DLL must be bundled as a binary so ctypes can load it at runtime
        if OPUS_DLL:
            cmd += ["--add-binary", f"{OPUS_DLL};lib"]

    cmd.append(os.path.join(CLIENT_DIR, "main.py"))

    run(cmd, cwd=CLIENT_DIR)

    if ONEFILE:
        if not os.path.isfile(ONEFILE_EXE):
            print(f"[ERROR] PyInstaller did not produce {ONEFILE_EXE}")
            sys.exit(1)
        size_mb = os.path.getsize(ONEFILE_EXE) / (1024 * 1024)
        print(f"  -> {ONEFILE_EXE}  ({size_mb:.1f} MB)")
    else:
        if not os.path.isfile(PYINST_EXE):
            print(f"[ERROR] PyInstaller did not produce {PYINST_EXE}")
            sys.exit(1)
        size_mb = os.path.getsize(PYINST_EXE) / (1024 * 1024)
        print(f"  -> {PYINST_EXE}  ({size_mb:.1f} MB)")
        if os.path.isdir(PYINST_INTERNAL):
            count = sum(1 for _, _, fs in os.walk(PYINST_INTERNAL) for _ in fs)
            print(f"  -> {PYINST_INTERNAL}  ({count} files)")

# -- Step 3: Assemble staging dir (onedir only) -----------------------------

def assemble_staging():
    step("3/8  Assembling staging distribution")

    if os.path.isdir(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
    os.makedirs(STAGING_DIR)

    shutil.copy2(PYINST_EXE, os.path.join(STAGING_DIR, "WinZapp.exe"))
    print(f"  -> WinZapp.exe")

    if os.path.isdir(PYINST_INTERNAL):
        dst_internal = os.path.join(STAGING_DIR, "_internal")
        shutil.copytree(PYINST_INTERNAL, dst_internal)
        count = sum(1 for _, _, fs in os.walk(dst_internal) for _ in fs)
        print(f"  -> _internal/  ({count} files)")
    else:
        print("  [WARN] _internal/ directory not found in PyInstaller output")

    lib_dir = os.path.join(STAGING_DIR, "lib")
    os.makedirs(lib_dir)
    dll_count = 0
    if os.path.isdir(SOUND_LIB_X64):
        for fname in os.listdir(SOUND_LIB_X64):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(SOUND_LIB_X64, fname),
                             os.path.join(lib_dir, fname))
                dll_count += 1
    if os.path.isdir(AO2_LIB):
        for fname in os.listdir(AO2_LIB):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(AO2_LIB, fname),
                             os.path.join(lib_dir, fname))
                dll_count += 1
    # libopus for OGG Opus encoding (client/core/ogg_opus.py)
    if OPUS_DLL:
        shutil.copy2(OPUS_DLL, os.path.join(lib_dir, "libopus-0.dll"))
        dll_count += 1
        print(f"  -> lib/libopus-0.dll")
    else:
        print("  [WARN] libopus-0.dll not found — voice message encoding will fail")
    print(f"  -> lib/  ({dll_count} DLLs total)")

    sounds_src = os.path.join(CLIENT_DIR, "sounds")
    shutil.copytree(sounds_src, os.path.join(STAGING_DIR, "sounds"))
    sounds_count = len(os.listdir(sounds_src))
    print(f"  -> sounds/  ({sounds_count} files)")

    langs_src = os.path.join(CLIENT_DIR, "languages")
    shutil.copytree(langs_src, os.path.join(STAGING_DIR, "languages"))
    langs_count = len(os.listdir(langs_src))
    print(f"  -> languages/  ({langs_count} files)")

    data_dir = os.path.join(STAGING_DIR, "data")
    os.makedirs(data_dir)
    shutil.copy2(SETTINGS_DEFAULT, os.path.join(data_dir, "settings_default.json"))
    print(f"  -> data/settings_default.json")

    client_env = os.path.join(CLIENT_DIR, ".env")
    if os.path.isfile(client_env):
        shutil.copy2(client_env, os.path.join(STAGING_DIR, ".env"))
        print(f"  -> .env")
    else:
        print(f"  [WARN] client/.env not found — skipping")

    node_dst = os.path.join(STAGING_DIR, "node")
    shutil.copytree(NODE_DIR, node_dst,
                    ignore=shutil.ignore_patterns("corepack"))
    node_count = sum(1 for _, _, fs in os.walk(node_dst) for _ in fs)
    print(f"  -> node/  ({node_count} files)")

    api_dst = os.path.join(STAGING_DIR, "api")
    os.makedirs(api_dst)
    api_count = 0
    for abs_path, rel_path in walk_dir(API_DIR,
                                       exclude_top_dirs=API_EXCLUDE_DIRS,
                                       exclude_top_files=API_EXCLUDE_FILES,
                                       exclude_sub_dirs=API_EXCLUDE_SUB_DIRS):
        dst = os.path.join(api_dst, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_path, dst)
        api_count += 1
    print(f"  -> api/  ({api_count} files)")

# -- Step 4-7: Installer (onedir only) -------------------------------------

def compile_uninstaller():
    step("4/8  Compiling uninstaller")
    run([
        WINDRES_CMD, "--codepage", "65001",
        os.path.join(INSTALLER_DIR, "uninstaller.rc"),
        "-o", UNINSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])
    run([
        GCC_CMD, "-finput-charset=UTF-8", "-fwide-exec-charset=UTF-16LE",
        os.path.join(INSTALLER_DIR, "uninstaller.c"),
        UNINSTALLER_RES, "-o", UNINSTALLER_EXE, "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])
    print(f"  -> {UNINSTALLER_EXE}")

def create_payload_zip():
    step("5/8  Creating payload ZIP (ZIP_STORED)")
    count = 0
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
        for abs_path, rel_path in walk_dir(STAGING_DIR):
            zf.write(abs_path, rel_path)
            count += 1
        zf.write(UNINSTALLER_EXE, "uninstall.exe")
        count += 1
    size_mb = os.path.getsize(PAYLOAD_ZIP) / (1024 * 1024)
    print(f"  -> {PAYLOAD_ZIP}  ({size_mb:.1f} MB, {count} entries)")

def compile_installer_stub():
    step("6/8  Compiling installer stub")
    run([
        WINDRES_CMD, "--codepage", "65001",
        os.path.join(INSTALLER_DIR, "installer.rc"),
        "-o", INSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])
    run([
        GCC_CMD, "-finput-charset=UTF-8", "-fwide-exec-charset=UTF-16LE",
        os.path.join(INSTALLER_DIR, "installer.c"),
        INSTALLER_RES, "-o", INSTALLER_STUB, "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32", "-luuid",
    ])
    print(f"  -> {INSTALLER_STUB}")

def append_zip_to_stub():
    step("7/8  Appending payload to installer stub")
    os.makedirs(DIST_DIR, exist_ok=True)
    with open(INSTALLER_OUT, "wb") as out:
        with open(INSTALLER_STUB, "rb") as stub:
            shutil.copyfileobj(stub, out)
        with open(PAYLOAD_ZIP, "rb") as payload:
            shutil.copyfileobj(payload, out)
    size_mb = os.path.getsize(INSTALLER_OUT) / (1024 * 1024)
    print(f"  -> {INSTALLER_OUT}  ({size_mb:.1f} MB)")

# -- Step 8: Create portable ZIP -------------------------------------------

def create_portable_zip():
    step("8/8  Creating portable WinZapp.zip")
    os.makedirs(DIST_DIR, exist_ok=True)

    if ONEFILE:
        count = 0
        with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            zf.write(ONEFILE_EXE, "WinZapp/WinZapp.exe")
            count += 1
        size_mb = os.path.getsize(PORTABLE_ZIP) / (1024 * 1024)
        print(f"  -> {PORTABLE_ZIP}  ({size_mb:.1f} MB, {count} entries)")
    else:
        count = 0
        with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for abs_path, rel_path in walk_dir(STAGING_DIR):
                zf.write(abs_path, "WinZapp/" + rel_path)
                count += 1
        size_mb = os.path.getsize(PORTABLE_ZIP) / (1024 * 1024)
        print(f"  -> {PORTABLE_ZIP}  ({size_mb:.1f} MB, {count} entries)")

# -- Main --------------------------------------------------------------------

if __name__ == "__main__":
    mode_str = "onefile" if ONEFILE else "onedir"
    print(f"\nWinZapp Build Script — PyInstaller ({mode_str})")
    print("=" * 60)

    if ONEFILE:
        check_tools()
        pyinstaller_compile()
        create_portable_zip()
        print(f"\n{'='*60}")
        print(f"  Onefile build complete!")
        print(f"  WinZapp.exe : {ONEFILE_EXE}")
        print(f"  Portable    : {PORTABLE_ZIP}")
        print(f"{'='*60}\n")
    else:
        check_tools()
        pyinstaller_compile()
        assemble_staging()
        compile_uninstaller()
        create_payload_zip()
        compile_installer_stub()
        append_zip_to_stub()
        create_portable_zip()
        print(f"\n{'='*60}")
        print(f"  Build complete!")
        print(f"  Installer  : {INSTALLER_OUT}")
        print(f"  Portable   : {PORTABLE_ZIP}")
        print(f"{'='*60}\n")
