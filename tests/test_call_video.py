from io import BytesIO
import json
from pathlib import Path
from threading import Event

from core.call_logic import active_call_label_key, incoming_call_can_answer
from core.call_video import camera_names, jpeg_frames


def test_camera_names_only_reads_video_devices():
    listing = '''[dshow @ 000] DirectShow video devices (some may be both video and audio devices)
[dshow @ 000] "Integrated Camera"
[dshow @ 000]   Alternative name "@device_pnp_abc"
[dshow @ 000] "USB Camera"
[dshow @ 000] DirectShow audio devices
[dshow @ 000] "Microphone"
'''
    assert camera_names(listing) == ["Integrated Camera", "USB Camera"]


def test_jpeg_pipe_discards_noise_and_yields_complete_frames():
    frame_a = b'\xff\xd8first\xff\xd9'
    frame_b = b'\xff\xd8second\xff\xd9'
    assert list(jpeg_frames(BytesIO(b'junk' + frame_a + frame_b), Event())) == [
        frame_a, frame_b,
    ]


def test_individual_video_is_answerable_and_has_video_label():
    assert incoming_call_can_answer({"is_video": True})
    assert not incoming_call_can_answer({"is_group": True})
    assert active_call_label_key({"is_video": True}) == "video_call_active_label"


def test_video_button_and_labels_exist_in_all_languages():
    languages = Path(__file__).parents[1] / 'client' / 'languages'
    for path in languages.glob('*.json'):
        entries = json.loads(path.read_text(encoding='utf-8'))
        assert entries['video_call_button']
        assert entries['video_call_window_title']
        assert '{name}' in entries['incoming_video_call_announcement']


def test_video_button_is_restricted_to_individual_chats():
    source = (Path(__file__).parents[1] / 'client' / 'ui' / 'conversations.py').read_text(encoding='utf-8')
    assert 'unavailable = jid.endswith(("@g.us", "@newsletter", "@broadcast"))' in source
    assert 'self._video_call_btn.Show(bool(jid) and not unavailable)' in source
    assert 'self.main_window.start_video_call(jid, name)' in source
