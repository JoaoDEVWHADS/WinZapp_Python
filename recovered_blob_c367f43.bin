import os
import subprocess
import time
import socket
import sys

def is_api_ready(port=6300):
    """Checks if the API port forwarded from QEMU is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    qemu_exe = os.path.join(base_dir, "qemu", "qemu-system-x86_64.exe")
    disk_img = os.path.join(base_dir, "system", "ubuntu-22.04.qcow2")
    frontend_exe = os.path.join(base_dir, "WinZappGUI.exe")

    # If running in development (script mode)
    if not os.path.isfile(qemu_exe):
        # Fallback to local QEMU install if available in PATH
        qemu_exe = "qemu-system-x86_64"

    # Start QEMU headless with port forwarding
    # hostfwd=tcp::6300-:6300 forwards host's 6300 to VM's 6300
    # hostfwd=tcp::4444-:4444 forwards QEMU monitor socket
    qemu_cmd = [
        qemu_exe,
        "-m", "512M",
        "-drive", f"file={disk_img},format=qcow2",
        "-net", "nic",
        "-net", "user,hostfwd=tcp::6300-:6300",
        "-nographic",
        "-monitor", "tcp:127.0.0.1:4444,server,nowait"
    ]

    print("[Launcher] Starting micro-VM in background...")
    
    # Hide the CMD console window on Windows
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE

    vm_process = subprocess.Popen(qemu_cmd, startupinfo=startupinfo)

    # Wait for the API to boot up (max 45 seconds)
    print("[Launcher] Waiting for WPPConnect API to be ready...")
    retries = 45
    api_ready = False
    while retries > 0:
        if is_api_ready():
            api_ready = True
            print("[Launcher] API is online!")
            break
        time.sleep(1)
        retries -= 1

    if not api_ready:
        print("[Launcher] Error: WPPConnect API failed to start in time.")
        # Attempt clean VM powerdown
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('127.0.0.1', 4444))
                s.sendall(b"system_powerdown\n")
        except Exception:
            vm_process.terminate()
        sys.exit(1)

    # Start GUI
    print("[Launcher] Starting WinZapp GUI...")
    env = os.environ.copy()
    env["WINZAPP_CONTAINER_MODE"] = "true"
    if sys.platform == "win32":
        gui_process = subprocess.Popen([frontend_exe], env=env)
    else:
        # Fallback for dev/linux environments
        dev_gui = os.path.join(base_dir, "main.py")
        gui_process = subprocess.Popen([sys.executable, dev_gui], env=env)

    # Wait for the GUI to close
    gui_process.wait()
    print("[Launcher] WinZapp GUI closed. Initiating VM shutdown...")

    # Order clean ACPI powerdown to avoid disk corruption in Ubuntu VM
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('127.0.0.1', 4444))
            s.sendall(b"system_powerdown\n")
    except Exception as e:
        print(f"[Launcher] Warning: Failed to send ACPI shutdown: {e}. Terminating QEMU process.")
        vm_process.terminate()

    # Wait for VM to save state and exit
    vm_process.wait()
    print("[Launcher] Shutdown complete. Exiting.")
    sys.exit(0)

if __name__ == "__main__":
    main()
