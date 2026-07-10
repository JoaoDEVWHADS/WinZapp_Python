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

ROOT_DIR       = os.path.dirname(os.path.abspath(__file__))
CLIENT_API_DIR = os.path.join(ROOT_DIR, "client", "api")
WPPCONNECT_REPO = "https://github.com/wppconnect-team/wppconnect-server.git"


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

        # Backup our custom start.js, package.json and config.json if they exist
        start_js_src = os.path.join(CLIENT_API_DIR, "start.js")
        package_json_src = os.path.join(CLIENT_API_DIR, "package.json")
        config_json_src = os.path.join(CLIENT_API_DIR, "config.json")
        has_start_js = os.path.isfile(start_js_src)
        has_package_json = os.path.isfile(package_json_src)
        has_config_json = os.path.isfile(config_json_src)
        
        # Additional custom files to backup and restore
        custom_files = [
            "src/config.ts",
            "src/index.ts",
            "src/util/createSessionUtil.ts",
            "src/util/functions.ts",
            "src/middleware/statusConnection.ts",
            "src/controller/deviceController.ts",
            "src/controller/messageController.ts",
            "src/controller/sessionController.ts"
        ]
        custom_contents = {}
        for rel_path in custom_files:
            full_path = os.path.join(CLIENT_API_DIR, rel_path)
            if os.path.isfile(full_path):
                with open(full_path, "rb") as f:
                    custom_contents[rel_path] = f.read()
                print(f"[INFO] Stashed custom file: {rel_path}")
        
        start_js_content = None
        package_json_content = None
        config_json_content = None
        if has_start_js:
            with open(start_js_src, "rb") as f:
                start_js_content = f.read()
            print("[INFO] Stashed start.js contents.")
        if has_package_json:
            with open(package_json_src, "rb") as f:
                package_json_content = f.read()
            print("[INFO] Stashed package.json contents.")
        if has_config_json:
            with open(config_json_src, "rb") as f:
                config_json_content = f.read()
            print("[INFO] Stashed config.json contents.")

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

        # Restore start.js, package.json and config.json after cloning
        if start_js_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "start.js"), "wb") as f:
                f.write(start_js_content)
            print("[INFO] Restored custom start.js.")
        if package_json_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "package.json"), "wb") as f:
                f.write(package_json_content)
            print("[INFO] Restored custom package.json.")
        if config_json_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "config.json"), "wb") as f:
                f.write(config_json_content)
            print("[INFO] Restored custom config.json.")
            
        # Restore other custom files
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
        if start_js_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "start.js"), "wb") as f:
                f.write(start_js_content)
        if package_json_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "package.json"), "wb") as f:
                f.write(package_json_content)
        if config_json_content is not None:
            with open(os.path.join(CLIENT_API_DIR, "config.json"), "wb") as f:
                f.write(config_json_content)
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
                "libatk1.0-0", "libc6", "libcairo2", "libcups2", "libdbus-1-3", "libexpat1",
                "libfontconfig1", "libgbm1", "libglib2.0-0", "libgtk-3-0", "libnspr4",
                "libnss3", "libpango-1.0-0", "libpangocairo-1.0-0", "libstdc++6", "libx11-6",
                "libx11-xcb1", "libxcb1", "libxcomposite1", "libxcursor1", "libxdamage1",
                "libxext6", "libxfixes3", "libxi6", "libxrandr2", "libxrender1", "libxss1",
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
