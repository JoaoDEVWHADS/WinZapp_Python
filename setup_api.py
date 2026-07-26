#!/usr/bin/env python3
"""
WinZapp — WPPConnect Server setup script.

Clones the WPPConnect Server repository into client/api/ and optionally checks
out a specific tag. After cloning, follow the build instructions printed at
the end to compile the API before running build.py.

Configuration (via .env at the project root):
  WPPCONNECT_TAG_VERSION  — git tag to check out after cloning.
                            Leave unset or empty to keep the default branch (main).

Usage:
  venv\\Scripts\\python.exe setup_api.py
"""

import os
import subprocess
import sys

# ---------------------------------------------------------------------------

ROOT_DIR         = os.path.dirname(os.path.abspath(__file__))
CLIENT_API_DIR   = os.path.join(ROOT_DIR, "client", "api")
API_PATCHES_DIR  = os.path.join(ROOT_DIR, "client", "api_patches")
WPPCONNECT_REPO  = "https://github.com/wppconnect-team/wppconnect-server.git"

# Files WinZapp patches on top of upstream wppconnect-server. client/api_patches/
# is the permanent, always-git-tracked source of truth for all of these —
# preferred below over whatever (if anything) happens to still be sitting in
# client/api/ right before it gets wiped. That "stash what's currently there"
# fallback used to be the ONLY restore path, and is worthless the moment
# client/api/ is already gone (e.g. a user deletes it before reinstalling,
# reported live as every patch silently regressing to whatever old snapshot
# happened to get stashed months earlier) — client/api_patches/ never has
# that problem since it's never inside the folder that gets deleted.
CUSTOM_ROOT_FILES = ["start.js", "package.json", "config.json"]
CUSTOM_SRC_FILES = [
    "src/config.ts",
    "src/index.ts",
    "src/util/createSessionUtil.ts",
    "src/util/sessionUtil.ts",
    "src/util/functions.ts",
    "src/middleware/statusConnection.ts",
    "src/controller/deviceController.ts",
    "src/controller/messageController.ts",
    "src/controller/sessionController.ts",
    "src/routes/index.ts",
    "decrypt.js",
]


def _load_env() -> dict:
    """Parse the root .env file and return a key→value dict."""
    env_path = os.path.join(ROOT_DIR, ".env")
    result = {}
    if not os.path.isfile(env_path):
        return result
    with open(env_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _run(cmd: list, cwd: str = None):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\n[ERROR] Command failed (exit {result.returncode}).")
        sys.exit(result.returncode)


def main():
    env = _load_env()
    tag = env.get("WPPCONNECT_TAG_VERSION", "").strip()

    git_dir = os.path.join(CLIENT_API_DIR, ".git")
    already_cloned = os.path.isdir(git_dir)

    if already_cloned:
        print(f"[INFO] client/api/ already exists — skipping clone.")
    else:
        print(f"[INFO] Cloning WPPConnect Server …")
        import shutil
        temp_node_modules = os.path.join(ROOT_DIR, "temp_node_modules")
        node_modules_path = os.path.join(CLIENT_API_DIR, "node_modules")
        has_node_modules = os.path.isdir(node_modules_path)
        if has_node_modules:
            try:
                if os.path.exists(temp_node_modules):
                    shutil.rmtree(temp_node_modules)
                shutil.move(node_modules_path, temp_node_modules)
                print("[INFO] Temporarily moved node_modules to preserve cache.")
            except Exception as e:
                print(f"[WARNING] Failed to move node_modules: {e}")
                has_node_modules = False

        # Gather the content to restore for every patched file, preferring
        # client/api_patches/ (permanent, always-tracked) over whatever
        # happens to still be sitting in client/api/ right now — the latter
        # is worthless as a source the moment client/api/ has already been
        # deleted, which is exactly when this restore matters most.
        custom_contents = {}
        for rel_path in CUSTOM_ROOT_FILES + CUSTOM_SRC_FILES:
            patches_path = os.path.join(API_PATCHES_DIR, rel_path)
            stash_path = os.path.join(CLIENT_API_DIR, rel_path)
            if os.path.isfile(patches_path):
                with open(patches_path, "rb") as f:
                    custom_contents[rel_path] = f.read()
                print(f"[INFO] Loaded {rel_path} from client/api_patches/")
            elif os.path.isfile(stash_path):
                with open(stash_path, "rb") as f:
                    custom_contents[rel_path] = f.read()
                print(f"[INFO] client/api_patches/{rel_path} not found — stashed current client/api/{rel_path} instead")

        if os.path.isdir(CLIENT_API_DIR):
            try:
                shutil.rmtree(CLIENT_API_DIR)
            except Exception as e:
                print(f"[WARNING] Failed to remove client/api: {e}")
        os.makedirs(os.path.dirname(CLIENT_API_DIR), exist_ok=True)
        _run(["git", "clone", WPPCONNECT_REPO, CLIENT_API_DIR])

        if has_node_modules:
            try:
                shutil.move(temp_node_modules, os.path.join(CLIENT_API_DIR, "node_modules"))
                print("[INFO] Restored node_modules cache successfully.")
            except Exception as e:
                print(f"[WARNING] Failed to restore node_modules: {e}")

        # Restore every patched file after cloning
        for rel_path, content in custom_contents.items():
            dest_path = os.path.join(CLIENT_API_DIR, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(content)
            print(f"[INFO] Restored custom file: {rel_path}")

    if tag:
        print(f"[INFO] Checking out tag: {tag}")
        _run(["git", "checkout", "-f", tag], cwd=CLIENT_API_DIR)

        # Re-restore after checkout just in case git checkout overwrites files
        for rel_path, content in custom_contents.items():
            dest_path = os.path.join(CLIENT_API_DIR, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(content)
        print("[INFO] Re-applied custom files after checking out tag.")
    else:
        print("[INFO] WPPCONNECT_TAG_VERSION not set — using default branch (main).")

    print()
    print("[OK] WPPConnect Server ready at client/api/")
    print()

    # Platform-specific installations
    is_windows = sys.platform == "win32"

    # 1. Automating Node dependency installation and build
    print("[INFO] Automating Node.js dependency installation and compilation...")
    try:
        # Determine node/npm command
        # On Windows, check if portable node exists in client/node/node.exe
        node_bin = "node"
        npm_bin = "npm"
        if is_windows:
            win_node = os.path.join(ROOT_DIR, "client", "node", "node.exe")
            if os.path.isfile(win_node):
                node_bin = win_node
                # Try to locate npm CLI
                win_npm = os.path.join(ROOT_DIR, "client", "node", "node_modules", "npm", "bin", "npm-cli.js")
                if os.path.isfile(win_npm):
                    npm_bin = win_npm

        # Run npm install
        print("[INFO] Running npm install...")
        if npm_bin.endswith("npm-cli.js"):
            _run([node_bin, npm_bin, "install", "--no-audit", "--no-fund", "--legacy-peer-deps"], cwd=CLIENT_API_DIR)
        else:
            _run([npm_bin, "install", "--no-audit", "--no-fund", "--legacy-peer-deps"], cwd=CLIENT_API_DIR)

        # Apply the RangeError/memory-leak patch to @wppconnect-team/wppconnect decrypt.js by copying our modified file
        try:
            import shutil as _shutil
            custom_decrypt = os.path.join(CLIENT_API_DIR, "decrypt.js")
            decrypt_js_path = os.path.join(CLIENT_API_DIR, "node_modules", "@wppconnect-team", "wppconnect", "dist", "api", "helpers", "decrypt.js")
            if os.path.isfile(custom_decrypt):
                print("[INFO] Copying custom decrypt.js patch to node_modules...")
                # Ensure the destination directory exists (should exist due to npm install)
                os.makedirs(os.path.dirname(decrypt_js_path), exist_ok=True)
                _shutil.copy2(custom_decrypt, decrypt_js_path)
                print("[OK] Copied decrypt.js patch successfully.")
            else:
                print("[WARNING] Custom decrypt.js patch not found in client/api. Skipping patch.")
        except Exception as e:
            print(f"[WARNING] Failed to copy decrypt.js patch: {e}")



        # Download Chromium (Puppeteer postinstall)
        print("[INFO] Downloading Chromium (Puppeteer)...")
        install_js = os.path.join(CLIENT_API_DIR, "node_modules", "puppeteer", "install.mjs")
        if os.path.isfile(install_js):
            _run([node_bin, install_js], cwd=CLIENT_API_DIR)
        else:
            print("[WARNING] puppeteer install.mjs not found. Attempting fallback browser download...")
            _run([npm_bin, "run", "postinstall"], cwd=CLIENT_API_DIR)

        # Run npm run build
        print("[INFO] Compiling WPPConnect Server...")
        if npm_bin.endswith("npm-cli.js"):
            _run([node_bin, npm_bin, "run", "build"], cwd=CLIENT_API_DIR)
        else:
            _run([npm_bin, "run", "build"], cwd=CLIENT_API_DIR)

        print("[OK] WPPConnect Server dependencies installed and built successfully.")

    except Exception as e:
        print(f"[ERROR] Node.js dependencies installation/build failed: {e}")
        print("Please resolve the error above or install manually by running:")
        print(f"  cd {CLIENT_API_DIR}")
        print("  npm install")
        print("  npm run build")

    # 2. Linux OS dependencies installation (Debian/Ubuntu)
    if not is_windows:
        print("\n[INFO] Detecting Linux OS and installing system dependencies for Chromium...")
        # Check if apt-get is available
        import shutil
        if shutil.which("apt-get"):
            # Check if running as root or has sudo
            try:
                getuid = os.getuid
            except AttributeError:
                getuid = lambda: -1
            is_root = getuid() == 0
            apt_cmd = ["apt-get", "update"]
            install_cmd = [
                "apt-get", "install", "-y", "--no-install-recommends",
                "ca-certificates", "fonts-liberation", "libasound2", "libatk-bridge2.0-0",
                "libatk1.0-0", "libc6", "libcairo2", "libcups2", "libdbus-1-3", "libdrm2", "libexpat1",
                "libfontconfig1", "libgbm1", "libglib2.0-0", "libgtk-3-0", "libnspr4",
                "libnss3", "libpango-1.0-0", "libpangocairo-1.0-0", "libstdc++6", "libx11-6",
                "libx11-xcb1", "libxcb1", "libxcomposite1", "libxcursor1", "libxdamage1",
                "libxext6", "libxfixes3", "libxi6", "libxkbcommon0", "libxrandr2", "libxrender1", "libxshmfence1", "libxss1",
                "libxtst6", "lsb-release", "xdg-utils", "wget"
            ]
            if not is_root:
                if shutil.which("sudo"):
                    print("[INFO] Requesting root privileges via sudo for apt-get...")
                    apt_cmd = ["sudo"] + apt_cmd
                    install_cmd = ["sudo", "env", "DEBIAN_FRONTEND=noninteractive"] + install_cmd
                else:
                    print("[WARNING] Not running as root and sudo is not available. Please install system dependencies manually:")
                    print("  apt-get update && apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 libxshmfence1")
                    apt_cmd = None

            if apt_cmd:
                try:
                    # Set noninteractive environment variable
                    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
                    print("[INFO] Updating package lists...")
                    subprocess.run(apt_cmd, check=True)
                    print("[INFO] Installing system libraries for Chrome/Puppeteer...")
                    subprocess.run(install_cmd, check=True)
                    print("[OK] Linux system dependencies for Chromium installed successfully!")
                except Exception as e:
                    print(f"[WARNING] Failed to automatically install system packages: {e}")
                    print("Please install them manually using:")
                    print("  sudo apt-get update && sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 libxshmfence1")
        else:
            print("[INFO] Package manager apt-get not found (non-Debian/Ubuntu system).")
            print("Please ensure your system has all required Chromium dependencies installed:")
            print("https://pptr.dev/troubleshooting#chrome-headless-doesnt-launch-on-unix")


if __name__ == "__main__":
    main()
