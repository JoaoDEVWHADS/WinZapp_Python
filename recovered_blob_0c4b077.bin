"""
WinZapp build script.

Steps:
  1. Check required tools (nuitka, gcc, windres) and pre-built api/ + client/node/
  2. Compile client with Nuitka --mode=onefile -> build/WinZapp.exe
       (sounds, languages, lib are external; only Python + wx etc. go inside)
  3. Assemble staging dir:
       WinZapp.exe + lib/ + sounds/ + languages/ + data/ + .env + node/ + api/
  4. Compile uninstaller -> build/uninstall.exe
  5. Create payload ZIP (ZIP_STORED) from staging/ + uninstall.exe
  6. Compile installer stub -> build/installer_stub.exe
  7. Append payload ZIP to stub -> dist/WinZappInstaller.exe
  8. Create portable dist/WinZapp.zip (WinZapp/ prefix, ZIP_DEFLATED)

Visible structure after install / extraction:
  WinZapp.exe
  lib/          <- BASS DLLs + screen-reader DLLs (found by sound_lib / ao2)
  sounds/       <- OGG audio files
  languages/    <- JSON translation files
  data/         <- settings_default.json (bootstrap); settings.json created on first run
  node/         <- portable Node.js runtime (node.exe + runtime files)
  api/          <- Evolution API (dist/ + node_modules/ + prisma/ + start.js + .env)

Before running this script you must prepare:

  client/node/  - download the Windows x64 portable Node.js zip from
                  https://nodejs.org/dist/ (node-vXX.X.X-win-x64.zip)
                  and extract its contents into client/node/ (inside the client folder).
                  Verify: client/node/node.exe must exist.

  client/api/ - run setup_api.py to clone the Evolution API (honours the
                EVOLUTION_TAG_VERSION variable in .env), then inside client/api/ run:
                  npm install embedded-postgres --save
                  npm install
                  npm run db:generate
                  npm run build
                Verify: client/api/dist/main.js must exist.

Usage:
  venv\\Scripts\\python.exe build.py
"""

import os
import sys
import shutil
import subprocess
import zipfile

# -- Paths -------------------------------------------------------------------

ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR    = os.path.join(ROOT_DIR, "client")
INSTALLER_DIR = os.path.join(ROOT_DIR, "installer")
BUILD_DIR     = os.path.join(ROOT_DIR, "build")
DIST_DIR      = os.path.join(ROOT_DIR, "dist")
VENV_DIR      = os.path.join(ROOT_DIR, "venv")

# External pre-built assets (developer prepares these once)
NODE_DIR      = os.path.join(CLIENT_DIR, "node")        # portable Node.js (lives inside client/)
API_DIR       = os.path.join(CLIENT_DIR, "api")         # Evolution API (set up via setup_api.py)

NUITKA_CMD  = os.path.join(VENV_DIR, "Scripts", "nuitka.cmd")
PYTHON_CMD  = os.path.join(VENV_DIR, "Scripts", "python.exe")
GCC_CMD     = "gcc"
WINDRES_CMD = "windres"

# Nuitka onefile output: a single build/WinZapp.exe
NUITKA_EXE      = os.path.join(BUILD_DIR, "WinZapp.exe")

# Staging dir: assembled tree that mirrors the installed layout
STAGING_DIR     = os.path.join(BUILD_DIR, "staging")

PAYLOAD_ZIP     = os.path.join(BUILD_DIR, "payload.zip")
INSTALLER_STUB  = os.path.join(BUILD_DIR, "installer_stub.exe")
INSTALLER_RES   = os.path.join(BUILD_DIR, "installer_res.o")
UNINSTALLER_RES = os.path.join(BUILD_DIR, "uninstaller_res.o")
UNINSTALLER_EXE = os.path.join(BUILD_DIR, "uninstall.exe")
INSTALLER_OUT   = os.path.join(DIST_DIR,  "WinZappInstaller.exe")
PORTABLE_ZIP    = os.path.join(DIST_DIR,  "WinZapp.zip")

SETTINGS_DEFAULT = os.path.join(CLIENT_DIR, "data", "settings_default.json")

SITE_PACKAGES = os.path.join(VENV_DIR, "Lib", "site-packages")
# BASS DLLs (sound_lib) and screen-reader DLLs (accessible_output2) that go in lib/
SOUND_LIB_X64 = os.path.join(SITE_PACKAGES, "sound_lib", "lib", "x64")
AO2_LIB       = os.path.join(SITE_PACKAGES, "accessible_output2", "lib")

# Directories inside api/ that must NOT be copied into the distribution
# (they are runtime data created on first launch)
API_EXCLUDE_DIRS = {"pgdata", "instances", "store", ".git", "__pycache__", "node_modules"}
API_EXCLUDE_FILES = {".gitignore", "README-SETUP.md"}

# -- Helpers -----------------------------------------------------------------

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

def walk_dir(root, exclude_top_dirs=None, exclude_top_files=None):
    """Yield (absolute_path, relative_path) for every file under root.

    exclude_top_dirs  - set of directory names (relative to root) to skip.
    exclude_top_files - set of file names (relative to root) to skip.
    """
    exclude_top_dirs  = exclude_top_dirs  or set()
    exclude_top_files = exclude_top_files or set()
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        # Skip excluded top-level directories
        top = rel_dir.split(os.sep)[0] if rel_dir != "." else ""
        if top in exclude_top_dirs:
            dirs.clear()
            continue
        # Prune excluded dirs in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if not (rel_dir == "." and d in exclude_top_dirs)]
        for fname in files:
            # Skip excluded top-level files
            if rel_dir == "." and fname in exclude_top_files:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            yield abs_path, rel_path

# -- Step 1: Check tools and pre-built assets --------------------------------

def check_tools():
    step("1/8  Checking required tools and pre-built assets")
    missing = []

    if not os.path.isfile(NUITKA_CMD):
        missing.append(f"nuitka  (expected at {NUITKA_CMD})")
    if not os.path.isfile(PYTHON_CMD):
        missing.append(f"python  (expected at {PYTHON_CMD})")

    for tool, name in [(GCC_CMD, "gcc"), (WINDRES_CMD, "windres")]:
        if shutil.which(tool) is None:
            missing.append(f"{name}  (not found in PATH)")

    # Portable Node.js
    node_exe = os.path.join(NODE_DIR, "node.exe")
    if not os.path.isfile(node_exe):
        missing.append(
            f"client/node/node.exe  (download portable Node.js for Windows x64 and "
            f"extract to {NODE_DIR})"
        )

    # Pre-built Evolution API
    api_main = os.path.join(API_DIR, "dist", "main.js")
    if not os.path.isfile(api_main):
        missing.append(
            "client/api/dist/main.js  -- Evolution API not built.\n"
            "    1. Run:  venv\\Scripts\\python.exe setup_api.py\n"
            "       (set EVOLUTION_TAG_VERSION in .env to pin a specific release tag)\n"
            "    2. Then inside client/api/ run:\n"
            "         npm install embedded-postgres --save\n"
            "         npm install\n"
            "         npm run db:generate\n"
            "         npm run build"
        )

    # Prisma client must be generated before building (npm run db:generate in client/api/)
    prisma_client = os.path.join(API_DIR, "node_modules", ".prisma", "client", "index.js")
    if not os.path.isfile(prisma_client) and os.path.isfile(api_main):
        # dist exists but generated client is missing – warn, don't fail
        print("  [WARN] api/node_modules/.prisma/client not found.")
        print("         If the API crashes at runtime, run 'npm run db:generate' in api/.")

    if missing:
        print("\n[ERROR] Missing required tools or pre-built assets:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    print("  All tools and assets found.")

# -- Step 2: Nuitka onefile compile ------------------------------------------

def nuitka_compile():
    step("2/8  Compiling client with Nuitka (--mode=onefile)")

    os.makedirs(BUILD_DIR, exist_ok=True)

    # Remove previous onefile output if present
    if os.path.isfile(NUITKA_EXE):
        os.remove(NUITKA_EXE)

    cmd = [
        NUITKA_CMD,
        "--mode=onefile",
        "--windows-console-mode=disable",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=WinZapp",
        # Extract to a persistent cache location (faster re-launches)
        "--onefile-tempdir-spec={CACHE_DIR}/WinZapp",
        # Packages to include inside the exe
        "--include-package=sound_lib",
        "--include-package=accessible_output2",
        "--include-package=platform_utils",
        "--include-package=libloader",
        "--include-package=wx",
        "--include-package=cryptography",
        "--include-package=requests",
        "--include-package=socketio",
        "--include-package=engineio",
        "--include-package=pyperclip",
        "--include-package=packaging",
        # Exclude BASS DLLs from the exe - they live in the external lib/ folder
        "--noinclude-dlls=bass*.dll",
        "--noinclude-dlls=tags.dll",
        # Entry point
        os.path.join(CLIENT_DIR, "main.py"),
    ]
    run(cmd, cwd=CLIENT_DIR)

    if not os.path.isfile(NUITKA_EXE):
        print(f"[ERROR] Nuitka did not produce {NUITKA_EXE}")
        sys.exit(1)

    size_mb = os.path.getsize(NUITKA_EXE) / (1024 * 1024)
    print(f"  -> {NUITKA_EXE}  ({size_mb:.1f} MB)")

# -- Step 3: Assemble staging dir --------------------------------------------

def assemble_staging():
    step("3/8  Assembling staging distribution")

    # Clean and recreate
    if os.path.isdir(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
    os.makedirs(STAGING_DIR)

    # WinZapp.exe (the onefile)
    shutil.copy2(NUITKA_EXE, os.path.join(STAGING_DIR, "WinZapp.exe"))

    # lib/ - BASS DLLs from sound_lib + screen-reader DLLs from accessible_output2
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
    print(f"  -> lib/  ({dll_count} DLLs)")

    # sounds/ - OGG files from client
    sounds_src = os.path.join(CLIENT_DIR, "sounds")
    shutil.copytree(sounds_src, os.path.join(STAGING_DIR, "sounds"))
    sounds_count = len(os.listdir(sounds_src))
    print(f"  -> sounds/  ({sounds_count} files)")

    # languages/ - JSON files from client
    langs_src = os.path.join(CLIENT_DIR, "languages")
    shutil.copytree(langs_src, os.path.join(STAGING_DIR, "languages"))
    langs_count = len(os.listdir(langs_src))
    print(f"  -> languages/  ({langs_count} files)")

    # data/settings_default.json
    data_dir = os.path.join(STAGING_DIR, "data")
    os.makedirs(data_dir)
    shutil.copy2(SETTINGS_DEFAULT, os.path.join(data_dir, "settings_default.json"))
    print(f"  -> data/settings_default.json")

    # .env - WinZapp runtime configuration (EVOLUTION_API_MINIMUM_VERSION, update URLs, etc.)
    client_env = os.path.join(CLIENT_DIR, ".env")
    if os.path.isfile(client_env):
        shutil.copy2(client_env, os.path.join(STAGING_DIR, ".env"))
        print(f"  -> .env")
    else:
        print(f"  [WARN] client/.env not found — skipping (version check will be disabled at runtime)")

    # node/ - portable Node.js runtime
    node_dst = os.path.join(STAGING_DIR, "node")
    shutil.copytree(NODE_DIR, node_dst)
    node_count = sum(1 for _, _, fs in os.walk(node_dst) for _ in fs)
    print(f"  -> node/  ({node_count} files)")

    # api/ - pre-built Evolution API (exclude runtime data directories)
    api_dst = os.path.join(STAGING_DIR, "api")
    os.makedirs(api_dst)
    api_count = 0
    for abs_path, rel_path in walk_dir(API_DIR,
                                       exclude_top_dirs=API_EXCLUDE_DIRS,
                                       exclude_top_files=API_EXCLUDE_FILES):
        dst = os.path.join(api_dst, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_path, dst)
        api_count += 1
    print(f"  -> api/  ({api_count} files)")

# -- Step 4: Compile uninstaller ---------------------------------------------

def compile_uninstaller():
    step("4/8  Compiling uninstaller")

    run([
        WINDRES_CMD,
        "--codepage", "65001",          # source .rc is UTF-8
        os.path.join(INSTALLER_DIR, "uninstaller.rc"),
        "-o", UNINSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])

    run([
        GCC_CMD,
        "-finput-charset=UTF-8",        # source .c is UTF-8
        "-fwide-exec-charset=UTF-16LE", # wchar_t → UTF-16 LE (Windows native)
        os.path.join(INSTALLER_DIR, "uninstaller.c"),
        UNINSTALLER_RES,
        "-o", UNINSTALLER_EXE,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])
    print(f"  -> {UNINSTALLER_EXE}")

# -- Step 5: Create payload ZIP ----------------------------------------------

def create_payload_zip():
    step("5/8  Creating payload ZIP (ZIP_STORED)")

    count = 0
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
        # All staging files at the ZIP root (preserving sub-folders)
        for abs_path, rel_path in walk_dir(STAGING_DIR):
            zf.write(abs_path, rel_path)
            count += 1
        # Uninstaller at root
        zf.write(UNINSTALLER_EXE, "uninstall.exe")
        count += 1

    size_mb = os.path.getsize(PAYLOAD_ZIP) / (1024 * 1024)
    print(f"  -> {PAYLOAD_ZIP}  ({size_mb:.1f} MB, {count} entries)")

# -- Step 6: Compile installer stub ------------------------------------------

def compile_installer_stub():
    step("6/8  Compiling installer stub")

    run([
        WINDRES_CMD,
        "--codepage", "65001",          # source .rc is UTF-8
        os.path.join(INSTALLER_DIR, "installer.rc"),
        "-o", INSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])

    run([
        GCC_CMD,
        "-finput-charset=UTF-8",        # source .c is UTF-8
        "-fwide-exec-charset=UTF-16LE", # wchar_t → UTF-16 LE (Windows native)
        os.path.join(INSTALLER_DIR, "installer.c"),
        INSTALLER_RES,
        "-o", INSTALLER_STUB,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32", "-luuid",
    ])
    print(f"  -> {INSTALLER_STUB}")

# -- Step 7: Append ZIP to stub ----------------------------------------------

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

# -- Step 8: Create portable ZIP ---------------------------------------------

def create_portable_zip():
    step("8/8  Creating portable WinZapp.zip")
    os.makedirs(DIST_DIR, exist_ok=True)

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
    print("\nWinZapp Build Script")
    print("=" * 60)

    check_tools()
    nuitka_compile()
    assemble_staging()
    compile_uninstaller()
    create_payload_zip()
    compile_installer_stub()
    append_zip_to_stub()
    create_portable_zip()

    print("\n" + "=" * 60)
    print("  Build complete!")
    print(f"  Installer  : {INSTALLER_OUT}")
    print(f"  Portable   : {PORTABLE_ZIP}")
    print("=" * 60 + "\n")
