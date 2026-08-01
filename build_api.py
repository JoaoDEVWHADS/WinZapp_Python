import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(base_dir, "client", "api")
    
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
        env = dict(os.environ)
        node_modules_dir = os.path.join(api_dir, "node_modules")
        bin_dir = os.path.join(node_modules_dir, ".bin")
        
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

        if not os.path.isdir(node_modules_dir):
            print("[INFO] node_modules missing in client/api — running npm install...")
            if node_exe and npm_cli:
                cmd_inst = [node_exe, npm_cli, "install", "--legacy-peer-deps"]
                subprocess.run(cmd_inst, cwd=api_dir, env=env, check=True)
            else:
                subprocess.run([npm_cmd, "install", "--legacy-peer-deps"], cwd=api_dir, env=env, shell=True if sys.platform == "win32" else False, check=True)

        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

        if node_exe and npm_cli:
            # Usa o node portátil para executar o npm run build
            cmd = [node_exe, npm_cli, "run", "build"]
            node_dir = os.path.dirname(node_exe)
            env["PATH"] = node_dir + os.pathsep + env["PATH"]
            subprocess.run(cmd, cwd=api_dir, env=env, check=True)
        else:
            # Caso contrário, usa o npm do sistema
            subprocess.run([npm_cmd, "run", "build"], cwd=api_dir, env=env, shell=True if sys.platform == "win32" else False, check=True)
            
        print("[OK] WPPConnect Server built successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to build API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
