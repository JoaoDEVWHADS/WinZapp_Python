"""Quick audio-device switch: Ctrl+Alt+Shift+H (output), Ctrl+Alt+Shift+G
(recording), then a digit.

The list numbers the devices 1..9 and 0 for the tenth, the way the digit row
reads; "system default" follows them without a digit (arrows and Enter reach
it). Pure so it is tested without a window; ui/dialogs/quick_audio_device_dialog.py
shows it and main_window/quick_audio_devices.py applies the choice.
"""

from __future__ import annotations

KIND_OUTPUT = "output"
KIND_INPUT = "input"

#: Devices a digit can pick directly: 1..9, then 0.
DIGIT_SLOTS = 10


def digit_for_slot(slot: int) -> str:
    """The digit that picks the device at zero-based *slot*: 0 -> "1" ...
    8 -> "9", 9 -> "0"."""
    return str((slot + 1) % 10)


def slot_for_digit(digit: str) -> int | None:
    """Zero-based slot a typed digit picks, or None for anything else."""
    if len(digit) != 1 or not digit.isdigit():
        return None
    return 9 if digit == "0" else int(digit) - 1


def quick_device_rows(device_names, current_name: str, default_label: str,
                      current_suffix: str):
    """Rows for the list and the row that starts focused.

    Returns ``(rows, focus)``: ``rows`` is ``[(label, device_name), ...]`` —
    the first DIGIT_SLOTS devices labelled "<digit>. <name>", any further ones
    unnumbered, then the system default as ``(default_label, "")``. The row in
    use is marked with *current_suffix*; an empty *current_name* means the
    default is in use. ``focus`` is that row's index.
    """
    rows = []
    focus = None
    names = [n for n in (device_names or []) if n]
    for slot, name in enumerate(names):
        label = f"{digit_for_slot(slot)}. {name}" if slot < DIGIT_SLOTS else name
        if current_name and name == current_name:
            label = f"{label} {current_suffix}"
            focus = len(rows)
        rows.append((label, name))
    default_row = default_label
    if not current_name or focus is None:
        # Default in use, or the saved device is not connected right now —
        # WinZapp is on the system default either way.
        default_row = f"{default_label} {current_suffix}"
        focus = len(rows)
    rows.append((default_row, ""))
    return rows, focus
