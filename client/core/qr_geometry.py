"""Geometry of a pairing QR PNG, measured from its pixels.

WPPConnect's PNG has no quiet zone and a fractional module size; the Neonize
bridge's has a 6-module margin at 8 px per module (~490 px), which the dialog's
300 px box cannot hold once it adds its own margin on top. The dialog asks
this module what the image already has before padding or shrinking it.
Pure functions over RGB bytes (`wx.Image.GetData()`), so no window is needed.
"""

QUIET_MODULES = 4       # the QR standard's minimum quiet zone
FINDER_MODULES = 7      # a finder pattern's outer ring is 7 modules wide


def measure(rgb: bytes, width: int, height: int):
    """(margin_px, module_px) of a QR image, or None when it cannot be read.

    margin_px is the white border before the first dark pixel. module_px is
    exact only when the first dark run (the top of a finder pattern, 7
    modules) divides by 7; otherwise it is None, since the modules are not on
    whole pixels and the image must not be resampled."""
    if width <= 0 or height <= 0 or len(rgb) < width * height * 3:
        return None
    for y in range(height):
        row = rgb[y * width * 3:(y + 1) * width * 3]
        x = next((i for i in range(width) if row[i * 3] < 128), None)
        if x is None:
            continue
        end = x
        while end < width and row[end * 3] < 128:
            end += 1
        run = end - x
        module = run // FINDER_MODULES if run % FINDER_MODULES == 0 else None
        return min(x, y), module
    return None


def extra_margin(margin: int, module, fallback: int) -> int:
    """Pixels of white to add on each side: none when the image already has the
    standard's 4 modules, else `fallback` (the dialog's proportional rule)."""
    if module and margin >= QUIET_MODULES * module:
        return 0
    return fallback


def shrink_divisor(side: int, box: int, module, margin: int) -> int:
    """Smallest whole divisor of the module size that makes a `side`-px image
    fit the box with every module, and the margin, still on whole pixels. 1
    when it already fits or no such divisor exists (then it overflows rather
    than blur: shrinking by a fraction destroys the code)."""
    if side <= box or not module:
        return 1
    for d in range(2, module + 1):
        if module % d == 0 and side % d == 0 and margin % d == 0 and side // d <= box:
            return d
    return 1
