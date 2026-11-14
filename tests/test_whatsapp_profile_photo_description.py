"""The photo state of WhatsApp settings > Profile reaches the screen reader.

"Current photo set" and the chosen file's name are static texts beside the
"Choose photo" button; reported: NVDA read them only through object
navigation. The button now carries both as its accessible description.
"""

from types import SimpleNamespace

import wx

from ui.dialogs.whatsapp_profile_panel import _PhotoButtonAccessible, photo_button_description


def test_the_description_says_the_current_photo_and_the_chosen_file():
    assert photo_button_description("Current photo set", "me.jpg") == "Current photo set. me.jpg"


def test_an_empty_part_is_left_out():
    """The current state is empty until the read answers."""
    assert photo_button_description("", "No photo chosen") == "No photo chosen"
    assert photo_button_description("  ", "") == ""


def test_the_button_reads_the_labels_as_they_are_now():
    labels = {"current": "No photo set", "chosen": "No photo chosen"}
    panel = SimpleNamespace(_photo_current=SimpleNamespace(GetLabel=lambda: labels["current"]),
                            _photo_label=SimpleNamespace(GetLabel=lambda: labels["chosen"]))
    accessible = _PhotoButtonAccessible(panel)
    assert accessible.GetDescription(0) == (wx.ACC_OK, "No photo set. No photo chosen")
    labels["chosen"] = "beach.png"
    assert accessible.GetDescription(0) == (wx.ACC_OK, "No photo set. beach.png")
