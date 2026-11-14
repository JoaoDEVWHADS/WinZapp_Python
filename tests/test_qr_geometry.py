"""The pairing QR must fit the dialog's 300 px box with whole-pixel modules.

The Neonize bridge draws a ~490 px PNG that already has a 6-module margin; the
dialog used to add another 15% and overflow the box, so the phone could not
capture it. Pure functions over RGB bytes: no window.
"""

from core import qr_geometry as g

BOX = 300


def _rgb(size, margin, module, modules=21):
    """A synthetic square: white, with a 7-module finder at the top left of the
    symbol (enough for measure(), which only reads the first dark run)."""
    px = bytearray(b"\xff" * (size * size * 3))
    for y in range(margin, margin + module):
        for x in range(margin, margin + 7 * module):
            i = (y * size + x) * 3
            px[i:i + 3] = b"\x00\x00\x00"
    return bytes(px)


def test_measures_margin_and_module():
    size = (21 + 12) * 8                      # version 1, margin 6, 8 px
    assert g.measure(_rgb(size, 48, 8), size, size) == (48, 8)


def test_a_fractional_module_size_is_reported_as_unknown():
    size = 100
    assert g.measure(_rgb(size, 0, 3), size, size)[1] == 3
    px = bytearray(_rgb(size, 0, 3))
    px[(0 * size + 21) * 3:(0 * size + 21) * 3 + 3] = b"\x00\x00\x00"     # run of 22: not a multiple of 7
    assert g.measure(bytes(px), size, size)[1] is None


def test_a_blank_or_short_buffer_cannot_be_measured():
    assert g.measure(b"\xff" * 30, 10, 10) is None
    assert g.measure(b"", 0, 0) is None


def test_no_extra_margin_when_the_image_already_has_four_modules():
    assert g.extra_margin(48, 8, 73) == 0
    assert g.extra_margin(32, 8, 73) == 0


def test_the_fallback_margin_applies_to_a_borderless_image():
    assert g.extra_margin(0, 3, 34) == 34       # WPPConnect: unchanged
    assert g.extra_margin(0, None, 34) == 34


def test_the_bridge_png_shrinks_by_two_and_fits():
    side = (49 + 12) * 8                        # 488 px
    d = g.shrink_divisor(side, BOX, 8, 48)
    assert d == 2 and side // d <= BOX


def test_an_image_that_fits_is_left_alone():
    assert g.shrink_divisor(282, BOX, 3, 0) == 1


def test_it_never_shrinks_by_a_fraction():
    assert g.shrink_divisor(634, BOX, None, 0) == 1     # unknown module: overflow, not blur
    assert g.shrink_divisor(488, BOX, 7, 48) == 1       # no whole divisor fits
