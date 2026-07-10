"""
WinZapp — Evolution API setup script.

Clones the Evolution API repository into client/api/ and optionally checks
out a specific tag.  After cloning, follow the build instructions printed at
the end to compile the API before running build.py.

Configuration (via .env at the project root):
  EVOLUTION_TAG_VERSION  — git tag to check out after cloning.
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
EVOLUTION_REPO = "https://github.com/EvolutionAPI/evolution-api.git"


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
    tag = env.get("EVOLUTION_TAG_VERSION", "").strip()

    git_dir = os.path.join(CLIENT_API_DIR, ".git")
    already_cloned = os.path.isdir(git_dir)

    if already_cloned:
        print(f"[INFO] client/api/ already exists — skipping clone.")
    else:
        print(f"[INFO] Cloning Evolution API …")
        import shutil
        if os.path.isdir(CLIENT_API_DIR):
            try:
                shutil.rmtree(CLIENT_API_DIR)
            except Exception as e:
                print(f"[WARNING] Failed to remove client/api: {e}")
        os.makedirs(os.path.dirname(CLIENT_API_DIR), exist_ok=True)
        _run(["git", "clone", EVOLUTION_REPO, CLIENT_API_DIR])

    if tag:
        print(f"[INFO] Checking out tag: {tag}")
        _run(["git", "checkout", tag], cwd=CLIENT_API_DIR)
    else:
        print("[INFO] EVOLUTION_TAG_VERSION not set — using default branch (main).")

    print()
    print("[OK] Evolution API ready at client/api/")
    print()
    print("Next steps — build the API before running build.py:")
    print(f"  cd {CLIENT_API_DIR}")
    print("  npm install embedded-postgres --save")
    print("  npm install")
    print("  npm run db:generate")
    print("  npm run build")


if __name__ == "__main__":
    main()
