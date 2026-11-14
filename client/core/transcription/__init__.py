# Local (offline) transcription of voice/audio messages — pure logic only.
#
# Nothing in this package may import faster_whisper/ctranslate2 at module
# level. They ship in requirements.txt, but a copy where they are missing or
# their DLLs will not load must still open. If they are missing, the run falls
# back to whisper.cpp when its program is installed, or answers BACKEND_MISSING
# (backend.available_backend_ids(), which is_available()'s find_spec() feeds).
# If they are present but their DLLs will not load, is_available() cannot
# tell, and the first load answers BACKEND_MISSING
# (faster_whisper_backend._whisper_model_class()). Either way, nothing takes
# the conversation window down at import. Every backend import lives inside
# the function that needs it.
