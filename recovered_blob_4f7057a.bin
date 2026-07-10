# WinZapp's Sound System Module (sounddevice + soundfile + FFmpeg backup)
# Compatible BASS simulator API

import logging
import os
import sys
import tempfile
import subprocess
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf

# Ensure soundfile is loaded and ready
try:
    import soundfile as sf
except Exception as e:
    logging.error("[sound_system] Failed to import soundfile: %s", e)


class SoundSystem:
    def __init__(self, main_window, sound_dir):
        self.enabled = False
        self.main_window = main_window
        self.sound_dir = sound_dir
        self._current_streams = []
        logging.info("[sound_system] Initialized. sound_dir = %s", sound_dir)

    def start(self):
        self.enabled = True
        logging.info("[sound_system] Sound system started with sounddevice simulator.")

    def register_stream(self, stream_obj):
        self._current_streams.append(stream_obj)

    def unregister_stream(self, stream_obj):
        if stream_obj in self._current_streams:
            self._current_streams.remove(stream_obj)

    def stop_all(self):
        sd.stop()
        for s in list(self._current_streams):
            try:
                s.stop()
            except:
                pass


class NullSound:
    """Returned when a sound file can't be loaded — all methods are no-ops."""
    def play(self): pass
    def stop(self): pass


class Sound:
    """Sound object for quick UI feedback sounds."""
    def __init__(self, sound_system, file):
        self.sound_system = sound_system
        self.file_path = None
        self._temp_wav = None
        self._playing = False

        if os.path.isfile(os.path.join(self.sound_system.sound_dir, file)):
            self.file_path = os.path.join(self.sound_system.sound_dir, file)
        elif os.path.isfile(file):
            self.file_path = file
        else:
            self.file_path = file

        self._load_and_prepare()

    def _load_and_prepare(self):
        if not self.file_path or not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"Sound file not found: {self.file_path}")
        if self.file_path.lower().endswith('.ogg') or self.file_path.lower().endswith('.msv'):
            try:
                sf.info(self.file_path)
            except Exception:
                self._convert_to_temp_wav()

    def _convert_to_temp_wav(self):
        ffmpeg_bin = getattr(self.sound_system.main_window, "_find_api_ffmpeg", None)
        ffmpeg = ffmpeg_bin() if ffmpeg_bin else None
        if not ffmpeg or not os.path.isfile(ffmpeg):
            import shutil
            ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg not found.")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        self._temp_wav = tmp.name

        creationflags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", self.file_path, self._temp_wav],
                capture_output=True,
                creationflags=creationflags,
                check=True
            )
        except Exception as exc:
            if os.path.isfile(self._temp_wav):
                try: os.unlink(self._temp_wav)
                except: pass
            self._temp_wav = None
            raise RuntimeError(f"FFmpeg conversion failed: {exc}")

    def play(self):
        self.stop()
        settings = getattr(self.sound_system.main_window, "settings", {})
        if not settings.get("general", {}).get("sounds_enabled", False):
            return

        target_file = self._temp_wav if self._temp_wav else self.file_path
        if not target_file or not os.path.isfile(target_file):
            return

        def _play_thread():
            self.sound_system.register_stream(self)
            self._playing = True
            try:
                data, fs = sf.read(target_file)
                sd.play(data, fs)
                sd.wait()
            except Exception as e:
                logging.error("[sound_system] Error playing sound %s: %s", target_file, e)
            finally:
                self._playing = False
                self.sound_system.unregister_stream(self)

        threading.Thread(target=_play_thread, daemon=True).start()

    def stop(self):
        if self._playing:
            sd.stop()
            self._playing = False

    def __del__(self):
        if self._temp_wav and os.path.isfile(self._temp_wav):
            try: os.unlink(self._temp_wav)
            except: pass


def load_sound(sound_system, file):
    try:
        return Sound(sound_system, file)
    except Exception as e:
        logging.warning("[sound_system] Could not load sound '%s': %s", file, e)
        return NullSound()


class FileStream:
    """BASS-compatible FileStream simulator using sounddevice/soundfile."""
    def __init__(self, file, decode=False):
        self.file_path = file
        self.decode = decode
        self.data = None
        self.fs = 48000
        self._current_pos = 0
        self._playing = False
        self._stream = None
        self._lock = threading.Lock()
        
        # Load and verify file
        self._load_file()

    def _load_file(self):
        if not os.path.isfile(self.file_path):
            raise FileNotFoundError(f"Audio file not found: {self.file_path}")
        
        try:
            # Check natively
            self.data, self.fs = sf.read(self.file_path, dtype='float32')
        except Exception:
            # Decode via FFmpeg backup
            self._decode_via_ffmpeg()

        if self.data is not None and len(self.data.shape) == 1:
            # Mono to stereo for general sounddevice compatibility
            self.data = np.column_stack((self.data, self.data))

    def _decode_via_ffmpeg(self):
        # Locate FFmpeg
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            # Search common relative paths
            for path in ["lib/ffmpeg", "lib/ffmpeg.exe", "api/node_modules/@ffmpeg-installer/win32-x64/bin/ffmpeg.exe"]:
                if os.path.isfile(path):
                    ffmpeg = path
                    break

        if not ffmpeg:
            raise RuntimeError("FFmpeg needed to decode file not found.")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        
        creationflags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", self.file_path, tmp.name],
                capture_output=True,
                creationflags=creationflags,
                check=True
            )
            self.data, self.fs = sf.read(tmp.name, dtype='float32')
        finally:
            try: os.unlink(tmp.name)
            except: pass

    def play(self):
        with self._lock:
            if self._playing:
                return
            
            self._playing = True
            
            def callback(outdata, frames, time_info, status):
                if status:
                    logging.debug("[sound_system] stream status: %s", status)
                
                with self._lock:
                    if not self._playing or self.data is None:
                        outdata.fill(0)
                        return
                    
                    remaining = len(self.data) - self._current_pos
                    if remaining <= 0:
                        outdata.fill(0)
                        raise sd.CallbackStop()
                    
                    chunk_size = min(frames, remaining)
                    outdata[:chunk_size] = self.data[self._current_pos:self._current_pos + chunk_size]
                    if chunk_size < frames:
                        outdata[chunk_size:] = 0
                    
                    self._current_pos += chunk_size

            self._stream = sd.OutputStream(
                samplerate=self.fs,
                channels=2,
                callback=callback,
                finished_callback=self._on_finished
            )
            self._stream.start()

    def _on_finished(self):
        with self._lock:
            self._playing = False

    def stop(self):
        with self._lock:
            self._playing = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except:
                    pass
                self._stream = None

    def get_position(self) -> int:
        with self._lock:
            # Map frames (samples) to bytes for BASS API compatibility
            # BASS uses 4 bytes per sample (stereo 16-bit)
            return self._current_pos * 4

    def set_position(self, pos: int):
        with self._lock:
            # Map bytes back to frame index
            target_pos = max(0, min(int(pos / 4), len(self.data) if self.data is not None else 0))
            self._current_pos = target_pos

    def get_length(self) -> int:
        with self._lock:
            return (len(self.data) if self.data is not None else 0) * 4


class Tempo:
    """BASS FX Tempo simulator using FFmpeg speed filtering."""
    def __init__(self, filestream):
        self.filestream = filestream
        self._tempo = 0 # 0 = 1.0x, 50 = 1.5x, 100 = 2.0x
        self._original_data = filestream.data.copy() if filestream.data is not None else None
        self._original_fs = filestream.fs
        self._original_file = filestream.file_path

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, val):
        self._tempo = val
        speed = 1.0 + (val / 100.0)
        
        # Stop playback to apply speed change
        was_playing = self.filestream._playing
        current_ratio = 0.0
        
        with self.filestream._lock:
            if self.filestream.data is not None and len(self.filestream.data) > 0:
                current_ratio = self.filestream._current_pos / len(self.filestream.data)
        
        self.filestream.stop()
        
        # Apply speed change via FFmpeg atempo filter
        if abs(speed - 1.0) < 0.01:
            # Normal speed, restore original
            self.filestream.data = self._original_data.copy()
            self.filestream.fs = self._original_fs
        else:
            # Accelerated speed
            self._apply_speed_filter(speed)

        # Restore playback state and position
        with self.filestream._lock:
            if self.filestream.data is not None:
                self.filestream._current_pos = int(current_ratio * len(self.filestream.data))
        
        if was_playing:
            self.filestream.play()

    def _apply_speed_filter(self, speed: float):
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            for path in ["lib/ffmpeg", "lib/ffmpeg.exe", "api/node_modules/@ffmpeg-installer/win32-x64/bin/ffmpeg.exe"]:
                if os.path.isfile(path):
                    ffmpeg = path
                    break

        if not ffmpeg:
            logging.error("[sound_system] FFmpeg not found, cannot apply tempo FX.")
            return

        tmp_in = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_in.close()
        tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_out.close()

        creationflags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            # Write current original data to tmp_in
            sf.write(tmp_in.name, self._original_data, self._original_fs)
            
            # Run FFmpeg atempo
            subprocess.run(
                [ffmpeg, "-y", "-i", tmp_in.name, "-filter:a", f"atempo={speed}", tmp_out.name],
                capture_output=True,
                creationflags=creationflags,
                check=True
            )
            
            # Read new speed data
            data, fs = sf.read(tmp_out.name, dtype='float32')
            if len(data.shape) == 1:
                data = np.column_stack((data, data))
                
            self.filestream.data = data
            self.filestream.fs = fs
        except Exception as e:
            logging.error("[sound_system] Failed to apply tempo speed filter: %s", e)
        finally:
            for f in [tmp_in.name, tmp_out.name]:
                try: os.unlink(f)
                except: pass

    # Pass-through methods to inner filestream
    def play(self):
        self.filestream.play()

    def stop(self):
        self.filestream.stop()

    def get_position(self) -> int:
        return self.filestream.get_position()

    def set_position(self, pos: int):
        self.filestream.set_position(pos)

    def get_length(self) -> int:
        return self.filestream.get_length()
