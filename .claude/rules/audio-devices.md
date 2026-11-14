---
paths:
  - "client/core/sound_system.py"
  - "client/ui/conversation_panel/audio_playback.py"
  - "client/ui/conversation_panel/voice_recording.py"
  - "client/status_tab/status_voice.py"
---

# Audio devices

**Read `docs/traps/audio-devices.md` before changing these files.** Short form:

One process-wide BASS device; a reinit invalidates every stream, so apply the device before `load_sounds()` and skip the reinit when `_output_device_is_healthy()`. Error 14 is success. Wrap any sound played from an error path.
