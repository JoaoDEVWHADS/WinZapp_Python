import os
import shutil
import subprocess
import sys

CUSTOM_ROOT_FILES = ["start.js", "package.json", "config.json", "tsconfig.json", "babel.config.js"]
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
    "src/routes/index.ts"
]
CUSTOM_DIST_PATCHES = [
    "dist/controller/sessionController.js",
    "dist/index.js",
    "decrypt.js"
]

def copy_custom_files(base_dir, api_dir):
    patches_dir = os.path.join(base_dir, "client", "api_patches")
    if not os.path.isdir(patches_dir):
        print(f"[WARNING] Patches directory not found: {patches_dir}")
        return

    print("[INFO] Syncing all custom files from client/api_patches to client/api...")
    all_files = CUSTOM_ROOT_FILES + CUSTOM_SRC_FILES + CUSTOM_DIST_PATCHES
    os.makedirs(api_dir, exist_ok=True)

    for rel_path in all_files:
        src = os.path.join(patches_dir, rel_path)
        dest = os.path.join(api_dir, rel_path)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            print(f"[INFO] Copied custom file: {rel_path}")

    # Copy decrypt.js to node_modules if present
    custom_decrypt = os.path.join(api_dir, "decrypt.js")
    decrypt_js_path = os.path.join(api_dir, "node_modules", "@wppconnect-team", "wppconnect", "dist", "api", "helpers", "decrypt.js")
    if os.path.isfile(custom_decrypt) and os.path.isdir(os.path.dirname(decrypt_js_path)):
        try:
            shutil.copy2(custom_decrypt, decrypt_js_path)
            print("[INFO] Copied custom decrypt.js patch to node_modules.")
        except Exception as e:
            print(f"[WARNING] Could not copy decrypt.js to node_modules: {e}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(base_dir, "client", "api")

    # 1. Copiar incondicionalmente todos os arquivos customizados antes do build
    copy_custom_files(base_dir, api_dir)

    # Resolvendo o caminho do node portátil
    node_exe = None
    npm_cli = None

    if sys.platform == "win32":
        portable_node = os.path.join(base_dir, "client", "node", "node.exe")
        portable_npm = os.path.join(base_dir, "client", "node", "node_modules", "npm", "bin", "npm-cli.js")
        if os.path.isfile(portable_node) and os.path.isfile(portable_npm):
            node_exe = portable_node
            npm_cli = portable_npm
            print(f"[INFO] Using portable Node: {node_exe}")

    print("[INFO] Running build inside client/api...")
    try:
        env = dict(os.environ)
        node_modules_dir = os.path.join(api_dir, "node_modules")
        bin_dir = os.path.join(node_modules_dir, ".bin")

        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

        if not os.path.isdir(node_modules_dir):
            print("[INFO] node_modules missing in client/api — running npm install...")
            env["PUPPETEER_SKIP_DOWNLOAD"] = "true"
            if node_exe and npm_cli:
                cmd_inst = [node_exe, npm_cli, "install", "--no-audit", "--no-fund", "--legacy-peer-deps", "--include=dev"]
                subprocess.run(cmd_inst, cwd=api_dir, env=env, check=True)
            else:
                subprocess.run([npm_cmd, "install", "--no-audit", "--no-fund", "--legacy-peer-deps", "--include=dev"], cwd=api_dir, env=env, shell=True if sys.platform == "win32" else False, check=True)

        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

        if node_exe and npm_cli:
            cmd = [node_exe, npm_cli, "run", "build"]
            node_dir = os.path.dirname(node_exe)
            env["PATH"] = node_dir + os.pathsep + env["PATH"]
            subprocess.run(cmd, cwd=api_dir, env=env, check=True)
        else:
            subprocess.run([npm_cmd, "run", "build"], cwd=api_dir, env=env, shell=True if sys.platform == "win32" else False, check=True)

        # 2. Re-aplicar patches nos arquivos compilados em dist/
        copy_custom_files(base_dir, api_dir)

        print("[OK] WPPConnect Server built successfully with all patches applied.")
    except Exception as e:
        print(f"[ERROR] Failed to build API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
