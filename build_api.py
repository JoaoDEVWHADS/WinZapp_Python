import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(base_dir, "client", "api")
    
    api_patches_dir = os.path.join(base_dir, "client", "api_patches")
    
    # 1. Copiar/substituir todos os custom files de client/api_patches para client/api se existirem
    if os.path.isdir(api_patches_dir):
        print("[INFO] Syncing custom patch files from client/api_patches to client/api...")
        synced_count = 0
        for root, _, files in os.walk(api_patches_dir):
            for file in files:
                src_path = os.path.join(root, file)
                rel_path = os.path.relpath(src_path, api_patches_dir)
                dest_path = os.path.join(api_dir, rel_path)
                
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                import shutil
                shutil.copy2(src_path, dest_path)
                synced_count += 1
        print(f"[OK] Synced {synced_count} custom patch file(s).")
    else:
        print("[WARN] client/api_patches directory not found. Skipping patch sync.")

    # Copia o patch custom do decrypt.js para node_modules se existir
    custom_decrypt = os.path.join(api_dir, "decrypt.js")
    decrypt_js_target = os.path.join(api_dir, "node_modules", "@wppconnect-team", "wppconnect", "dist", "api", "helpers", "decrypt.js")
    if os.path.isfile(custom_decrypt) and os.path.isdir(os.path.dirname(decrypt_js_target)):
        try:
            import shutil
            shutil.copy2(custom_decrypt, decrypt_js_target)
            print("[OK] Copied decrypt.js patch to node_modules.")
        except Exception as e:
            print(f"[WARNING] Could not copy decrypt.js patch: {e}")

    # Resolvendo o caminho do node portátil
    node_exe = None
    npm_cli = None
    
    # Se estiver no Windows, procura no diretório 'client/node'
    if sys.platform == "win32":
        portable_node = os.path.join(base_dir, "client", "node", "node.exe")
        portable_npm = os.path.join(base_dir, "client", "node", "node_modules", "npm", "bin", "npm-cli.js")
        if os.path.isfile(portable_node) and os.path.isfile(portable_npm):
            node_exe = portable_node
            npm_cli = portable_npm
            print(f"[INFO] Using portable Node: {node_exe}")

    print("[INFO] Running build inside client/api...")
    try:
        if node_exe and npm_cli:
            # Usa o node portátil para executar o npm run build
            cmd = [node_exe, npm_cli, "run", "build"]
            
            # Adiciona o diretório do node portátil ao PATH para que scripts do npm funcionem
            env = dict(os.environ)
            node_dir = os.path.dirname(node_exe)
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
            
            subprocess.run(cmd, cwd=api_dir, env=env, check=True)
        else:
            # Caso contrário, usa o npm do sistema
            npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            subprocess.run([npm_cmd, "run", "build"], cwd=api_dir, shell=True if sys.platform == "win32" else False, check=True)
            
        print("[OK] WPPConnect Server built successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to build API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
