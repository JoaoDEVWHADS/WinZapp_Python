#!/usr/bin/env python3
"""
setup.py — Main environment orchestrator & WPPConnect Server API builder for WinZapp.

Executes all setup steps required for both local development (Dev) and CI/CD (GitHub Actions):
1. Ensures the configured Portable Node.js is in client/node/ (downloads if missing).
2. Ensures Portable MinGit (v2.44.0) is in client/git/ (downloads if missing).
3. Invokes setup_api.py to clone WPPConnect Server v2.10.0 and apply all custom WinZapp patches.
4. Runs `npm install` inside client/api/ (triggers postinstall Chrome download into .cache/).
5. Runs `npm run build` inside client/api/ to compile TypeScript into dist/server.js.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.join(ROOT_DIR, "client")
NODE_DIR = os.path.join(CLIENT_DIR, "node")
GIT_DIR = os.path.join(CLIENT_DIR, "git")
API_DIR = os.path.join(CLIENT_DIR, "api")

if CLIENT_DIR not in sys.path:
    sys.path.insert(0, CLIENT_DIR)

from node_download_config import NODE_TOP_DIR, NODE_URL, NODE_VERSION

NODE_ZIP_URL = NODE_URL

MINGIT_VERSION = "2.44.0"
MINGIT_ZIP_URL = f"https://github.com/git-for-windows/git/releases/download/v{MINGIT_VERSION}.windows.1/MinGit-{MINGIT_VERSION}-64-bit.zip"


def _log(msg: str) -> None:
    print(f"[SETUP] {msg}", flush=True)


def _download_and_extract(url: str, dest_dir: str, top_folder_to_strip: str = None) -> None:
    """Download a zip file and extract its content to dest_dir."""
    zip_path = os.path.join(ROOT_DIR, "temp_download.zip")
    try:
        _log(f"Downloading: {url} ...")
        urllib.request.urlretrieve(url, zip_path)
        _log(f"Extracting to: {dest_dir} ...")
        os.makedirs(dest_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, "r") as zf:
            if top_folder_to_strip:
                for member in zf.infolist():
                    rel_path = member.filename
                    if rel_path.startswith(top_folder_to_strip + "/"):
                        rel_path = rel_path[len(top_folder_to_strip) + 1:]
                    elif rel_path.startswith(top_folder_to_strip + "\\"):
                        rel_path = rel_path[len(top_folder_to_strip) + 1:]
                    else:
                        continue
                    if not rel_path:
                        continue
                    target_path = os.path.join(dest_dir, rel_path)
                    if member.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with zf.open(member) as source, open(target_path, "wb") as target:
                            shutil.copyfileobj(source, target)
            else:
                zf.extractall(dest_dir)
        _log("Download and extraction completed successfully.")
    finally:
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass


def ensure_node_portable() -> str:
    """Ensure portable Node.js exists in client/node/, returns node executable path."""
    node_exe_win = os.path.join(NODE_DIR, "node.exe")
    node_bin_nix = os.path.join(NODE_DIR, "bin", "node")
    
    if sys.platform == "win32":
        if os.path.isfile(node_exe_win):
            _log("Portable Node.js found in client/node/ (Win). Skipping download.")
            return node_exe_win
    else:
        if os.path.isfile(node_bin_nix) or os.path.isfile(os.path.join(NODE_DIR, "node")):
            _log("Portable Node.js found in client/node/ (Unix). Skipping download.")
            return node_bin_nix if os.path.isfile(node_bin_nix) else os.path.join(NODE_DIR, "node")
    
    _log("Portable Node.js not found in client/node/. Starting download...")
    _download_and_extract(NODE_ZIP_URL, NODE_DIR, top_folder_to_strip=NODE_TOP_DIR)
    return node_exe_win if sys.platform == "win32" else shutil.which("node") or "node"


def ensure_mingit_portable() -> None:
    """Ensure portable MinGit exists in client/git/ on Windows."""
    if sys.platform != "win32":
        return
    
    git_exe = os.path.join(GIT_DIR, "cmd", "git.exe")
    if os.path.isfile(git_exe):
        _log("Portable MinGit found in client/git/. Skipping download.")
        return
    
    _log("Portable MinGit not found in client/git/. Starting download...")
    _download_and_extract(MINGIT_ZIP_URL, GIT_DIR)


def run_setup_api() -> None:
    """Invoke setup_api.py to clone WPPConnect Server and apply custom patches."""
    _log("Running setup_api.py to clone WPPConnect Server and apply WinZapp patches...")
    setup_api_script = os.path.join(ROOT_DIR, "setup_api.py")
    env = dict(os.environ)
    if os.path.isdir(NODE_DIR):
        env["PATH"] = f"{NODE_DIR}{os.pathsep}{env.get('PATH', '')}"
    git_cmd_dir = os.path.join(GIT_DIR, "cmd")
    if os.path.isdir(git_cmd_dir):
        env["PATH"] = f"{git_cmd_dir}{os.pathsep}{env.get('PATH', '')}"
    res = subprocess.run([sys.executable, setup_api_script], cwd=ROOT_DIR, env=env)
    if res.returncode != 0:
        _log("ERROR: setup_api.py failed!")
        sys.exit(res.returncode)



def build_wppconnect_api(node_exe: str) -> None:
    """Run `npm install` and `npm run build` in client/api/ if not already compiled."""
    server_dist = os.path.join(API_DIR, "dist", "server.js")
    if os.path.isfile(server_dist):
        _log("WPPConnect API already compiled (dist/server.js exists). Skipping redundant build.")
        return

    _log("Building WPPConnect API in client/api/...")
    
    # Resolve npm executable / cli script
    npm_cli = os.path.join(NODE_DIR, "node_modules", "npm", "bin", "npm-cli.js")
    
    env = dict(os.environ)
    if os.path.isdir(NODE_DIR):
        env["PATH"] = f"{NODE_DIR}{os.pathsep}{env.get('PATH', '')}"
    
    if os.path.isfile(node_exe) and os.path.isfile(npm_cli):
        npm_cmd = [node_exe, npm_cli]
    else:
        system_npm = shutil.which("npm") or ("npm.cmd" if sys.platform == "win32" else "npm")
        npm_cmd = [system_npm]
    
    _log(f"Using NPM command: {npm_cmd}")
    
    # Step 1: npm install
    _log("Running npm install...")
    res_install = subprocess.run(
        npm_cmd + ["install", "--no-audit", "--no-fund", "--legacy-peer-deps"],
        cwd=API_DIR,
        env=env,
        shell=(sys.platform == "win32" and len(npm_cmd) == 1)
    )
    if res_install.returncode != 0:
        _log("ERROR: npm install failed!")
        sys.exit(res_install.returncode)
    
    # Step 2: npm run build
    _log("Running npm run build...")
    res_build = subprocess.run(
        npm_cmd + ["run", "build"],
        cwd=API_DIR,
        env=env,
        shell=(sys.platform == "win32" and len(npm_cmd) == 1)
    )
    if res_build.returncode != 0:
        _log("ERROR: npm run build failed!")
        sys.exit(res_build.returncode)
    
    _log("WPPConnect API successfully built!")


def main() -> None:
    _log("=== WinZapp Main Setup & Environment Builder ===")
    
    # 1. Ensure Portable Node.js
    node_exe = ensure_node_portable()
    
    # 2. Ensure Portable MinGit
    ensure_mingit_portable()
    
    # 3. Clone API & Apply Patches
    run_setup_api()
    
    # 4. Install Dependencies & Build API
    build_wppconnect_api(node_exe)
    
    _log("=== WinZapp Setup Completed Successfully! ===")


if __name__ == "__main__":
    main()
