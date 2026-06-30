import os
import sys
import subprocess

def start_api():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(base_dir, "client", "api")
    
    if not os.path.exists(os.path.join(api_dir, "start.js")):
        print(f"Error: start.js not found in {api_dir}")
        sys.exit(1)
        
    print("Starting API server (node start.js)...")
    # Launch node start.js in a separate process
    try:
        if sys.platform == "win32":
            # On Windows, start in a new console window so it runs in background
            subprocess.Popen(["node", "start.js"], cwd=api_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            # On Linux, run as background process
            subprocess.Popen(["node", "start.js"], cwd=api_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("API started successfully in the background.")
    except Exception as e:
        print(f"Failed to start API: {e}")
        sys.exit(1)

if __name__ == "__main__":
    start_api()
