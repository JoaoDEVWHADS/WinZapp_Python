"""Video-call camera on macOS: AVFoundation through the bundled ffmpeg.

core/call_video.py enumerates and captures the camera with ffmpeg's
DirectShow input (`-f dshow`), Windows-only. The Mac equivalent is ffmpeg's
AVFoundation input; everything downstream (the MJPEG frame pipe, size cap,
readiness wait) is WinZapp's own and unchanged. AVFoundation also lists
"Capture screen N" pseudo-devices, which are not cameras.

Mac cameras commonly reject ffmpeg's default 29.97 fps, so capture tries
the usual rates until one produces frames. The first capture triggers the
macOS camera permission prompt (NSCameraUsageDescription in Info.plist).
"""

import logging
import re
import subprocess
import threading
import time

FRAMERATES = ("30", "25", "15")


def camera_names(ffmpeg_output):
    names, in_video = [], False
    for line in ffmpeg_output.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            in_video = False
        if not in_video:
            continue
        m = re.search(r"\]\s+\[\d+\]\s+(.+?)\s*$", line)
        if m and not m.group(1).startswith("Capture screen"):
            names.append(m.group(1))
    return names


def list_camera_devices(ffmpeg):
    if not ffmpeg:
        return []
    try:
        listed = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, errors="replace", timeout=10)
    except Exception:
        return []
    return camera_names(listed.stderr)


def capture_command(ffmpeg, device, framerate):
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
            "-framerate", framerate, "-i", f"{device}:none", "-an",
            "-vf", "fps=10,scale=640:360:force_original_aspect_ratio=decrease",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "7", "-"]


def start(self, preferred_name=""):
    if not self.ffmpeg:
        raise RuntimeError("FFmpeg is required for camera capture")
    devices = list_camera_devices(self.ffmpeg)
    if not devices:
        raise RuntimeError("No camera found")
    device = preferred_name if preferred_name in devices else devices[0]
    logging.info("[camera_mac] camera selected: %s (detected=%d)", device, len(devices))
    for rate in FRAMERATES:
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.process = subprocess.Popen(capture_command(self.ffmpeg, device, rate),
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.ready.wait(0.1) or self.process.poll() is not None:
                break
        if self.ready.is_set():
            logging.info("[camera_mac] capturing at %s fps", rate)
            return
        self.stop()
    raise RuntimeError("Camera did not produce video frames")


def install():
    from core import call_video
    call_video.camera_names = camera_names
    call_video.list_camera_devices = list_camera_devices
    call_video.CameraCapture.start = start
