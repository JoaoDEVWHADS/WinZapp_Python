#!/usr/bin/env python3
"""
WinZapp — WPPConnect Server setup script (Docker variant).

Clones the WPPConnect Server repository into client/api/, applies patches,
and writes out the Dockerfile and docker-compose.yml for containerized build.

Configuration (via .env at the project root):
  WPPCONNECT_TAG_VERSION  — git tag to check out after cloning.
                            Leave unset or empty to keep the default branch (main).

Usage:
  python setup_api.py
"""

import os
import subprocess
import sys
import shutil

ROOT_DIR       = os.path.dirname(os.path.abspath(__file__))
CLIENT_API_DIR = os.path.join(ROOT_DIR, "client", "api")
WPPCONNECT_REPO = "https://github.com/wppconnect-team/wppconnect-server.git"

DOCKERFILE_CONTENT = """FROM node:20-slim

# Install system dependencies required for Chromium/Puppeteer in headless mode
RUN apt-get update && apt-get install -y \\
    chromium \\
    fonts-liberation \\
    libasound2 \\
    libatk-bridge2.0-0 \\
    libatk1.0-0 \\
    libc6 \\
    libcairo2 \\
    libcups2 \\
    libdbus-1-3 \\
    libexpat1 \\
    libfontconfig1 \\
    libgbm1 \\
    libglib2.0-0 \\
    libgtk-3-0 \\
    libnspr4 \\
    libnss3 \\
    libpango-1.0-0 \\
    libpangocairo-1.0-0 \\
    libstdc++6 \\
    libx11-6 \\
    libx11-xcb1 \\
    libxcb1 \\
    libxcomposite1 \\
    libxcursor1 \\
    libxdamage1 \\
    libxext6 \\
    libxfixes3 \\
    libxi6 \\
    libxrandr2 \\
    libxrender1 \\
    libxss1 \\
    libxtst6 \\
    lsb-release \\
    xdg-utils \\
    wget \\
    --no-install-recommends \\
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \\
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app
COPY package*.json ./
RUN npm install --no-audit --no-fund --legacy-peer-deps

COPY . .
# Copy our custom decrypt patch to the node_modules
RUN cp decrypt.js node_modules/@wppconnect-team/wppconnect/dist/api/helpers/decrypt.js || true

RUN npm run build

EXPOSE 6300
CMD ["node", "dist/server.js"]
"""

DOCKER_COMPOSE_CONTENT = """version: '3.8'
services:
  wppconnect-api:
    build: .
    container_name: wppconnect-api
    ports:
      - "6300:6300"
    restart: always
"""

def _load_env() -> dict:
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

    # Backup custom files if existing
    custom_contents = {}
    custom_files = [
        "src/config.ts",
        "src/index.ts",
        "src/util/createSessionUtil.ts",
        "src/util/functions.ts",
        "src/middleware/statusConnection.ts",
        "src/controller/deviceController.ts",
        "src/controller/messageController.ts",
        "src/controller/sessionController.ts",
        "src/routes/index.ts",
        "decrypt.js",
        "start.js",
        "package.json",
        "config.json"
    ]

    for rel_path in custom_files:
        full_path = os.path.join(CLIENT_API_DIR, rel_path)
        if os.path.isfile(full_path):
            with open(full_path, "rb") as f:
                custom_contents[rel_path] = f.read()
            print(f"[INFO] Stashed custom file: {rel_path}")

    if not already_cloned:
        if os.path.isfile(os.path.join(CLIENT_API_DIR, "package.json")):
            print("[INFO] WPPConnect Server files already exist in client/api/, skipping clone.")
        else:
            print(f"[INFO] Cloning WPPConnect Server …")
            if os.path.isdir(CLIENT_API_DIR):
                shutil.rmtree(CLIENT_API_DIR)
            os.makedirs(os.path.dirname(CLIENT_API_DIR), exist_ok=True)
            _run(["git", "clone", WPPCONNECT_REPO, CLIENT_API_DIR])

    # Restore custom files
    for rel_path, content in custom_contents.items():
        dest_path = os.path.join(CLIENT_API_DIR, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(content)
        print(f"[INFO] Restored custom file: {rel_path}")

    if tag:
        print(f"[INFO] Checking out tag: {tag}")
        _run(["git", "checkout", "-f", tag], cwd=CLIENT_API_DIR)
        # Re-apply custom files
        for rel_path, content in custom_contents.items():
            dest_path = os.path.join(CLIENT_API_DIR, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(content)
            print(f"[INFO] Re-applied: {rel_path}")
    else:
        print("[INFO] WPPCONNECT_TAG_VERSION not set — using default branch (main).")

    # Write out Dockerfile and docker-compose.yml
    print("[INFO] Writing Docker files for context...")
    with open(os.path.join(CLIENT_API_DIR, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(DOCKERFILE_CONTENT)
    with open(os.path.join(CLIENT_API_DIR, "docker-compose.yml"), "w", encoding="utf-8") as f:
        f.write(DOCKER_COMPOSE_CONTENT)

    print("[OK] WPPConnect Server Docker context prepared successfully.")

if __name__ == "__main__":
    main()
