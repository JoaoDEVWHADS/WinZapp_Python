import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(base_dir, "client", "api")
    
    print("[INFO] Running 'npm run build' inside client/api...")
    try:
        # Executa diretamente o npm run build
        subprocess.run(["npm", "run", "build"], cwd=api_dir, shell=False, check=True)
        print("[OK] WPPConnect Server built successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to build API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
