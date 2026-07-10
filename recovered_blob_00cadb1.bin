import os
import sys
import shutil
import subprocess
import signal

def kill_port(port):
    print(f"Attempting to kill process on port {port}...")
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(f'netstat -ano | findstr :{port}', shell=True).decode()
            pids = set()
            for line in output.strip().split('\n'):
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if pid.isdigit() and pid != '0':
                        pids.add(int(pid))
            for pid in pids:
                print(f"Killing PID {pid} (Windows)")
                os.system(f"taskkill /F /PID {pid}")
        except Exception as e:
            print(f"No process found on port {port} or failed to kill: {e}")
    else:
        try:
            output = subprocess.check_output(f'lsof -t -i:{port}', shell=True).decode()
            for pid in output.strip().split('\n'):
                if pid.isdigit():
                    print(f"Killing PID {pid} (Linux)")
                    os.kill(int(pid), signal.SIGKILL)
        except Exception as e:
            print(f"No process found on port {port} or failed to kill: {e}")

def kill_process_by_name(name):
    print(f"Killing processes matching '{name}'...")
    if sys.platform == "win32":
        os.system(f"taskkill /F /IM {name}.exe /T")
    else:
        os.system(f"pkill -9 -f {name}")

if __name__ == "__main__":
    # 1. Encerrar os processos ativos da API e do Chrome/Chromium
    kill_port(6300)
    kill_process_by_name("chrome")
    kill_process_by_name("chromium")
    kill_process_by_name("node start.js")
    
    # 2. Remover as pastas de sessões salvas
    base_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(base_dir, "client", "api", "userDataDir")
    if os.path.exists(user_data_dir):
        print(f"Cleaning all WPPConnect sessions in {user_data_dir}...")
        try:
            shutil.rmtree(user_data_dir)
            os.makedirs(user_data_dir, exist_ok=True)
            print("Successfully cleared all sessions.")
        except Exception as e:
            print(f"Failed to clear sessions: {e}")
    else:
        os.makedirs(user_data_dir, exist_ok=True)
        print("Sessions folder was already empty.")
