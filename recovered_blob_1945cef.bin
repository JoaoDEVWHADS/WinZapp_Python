"""Tests for rendering the pairing QR code so a phone can actually read it.

display_qrcode_image() used to call Scale(300, 300, wx.IMAGE_QUALITY_HIGH) on
the PNG WPPConnect emits (264 px square). Two things went wrong at once:

  * IMAGE_QUALITY_HIGH resamples with interpolation, so the hard black/white
    module edges become gradients — measured below, a pure 2-level image comes
    out with 256 grey levels;
  * 300/264 is a fractional 1.136x, so module widths end up uneven.

A phone camera reads the result as a damaged code and refuses it, which is the
"QR Code inválido" users reported. A QR may only be magnified by a whole number
with no smoothing, or left alone.

The scale-factor rule is pure and tested directly. The blurring claim is
verified against wx itself, since that is the thing whose behaviour matters.
"""

import pytest

from ui.dialogs.connect import Connect


factor = Connect._qr_scale_factor


class TestScaleFactor:
    def test_the_real_case_is_left_unscaled(self):
        """WPPConnect's 264 px QR in a 300 px box: 1x, not 1.136x."""
        assert factor(264, 300) == 1

    def test_a_small_qr_is_magnified_by_a_whole_number(self):
        assert factor(100, 300) == 3
        assert factor(150, 300) == 2

    def test_it_never_shrinks(self):
        """Shrinking merges neighbouring modules and destroys the code — better
        to overflow the panel and stay readable."""
        assert factor(400, 300) == 1
        assert factor(1000, 300) == 1

    def test_it_never_returns_zero(self):
        for src in (0, -5, 1, 299, 301):
            assert factor(src, 300) >= 1

    @pytest.mark.parametrize("src,box,expected", [
        (264, 300, 1), (264, 528, 2), (264, 792, 3), (33, 300, 9),
    ])
    def test_known_pairs(self, src, box, expected):
        assert factor(src, box) == expected


class TestQuietZone:
    """WPPConnect's QR PNG ships with no quiet zone at all.

    Measured on a real code captured from a live session: the symbol runs from
    x=-1 to x=228 of a 228px image — zero border. The QR standard requires 4
    modules on every side. A decoder handed a clean file coped (jsQR read it),
    which is why the image looked innocent; a phone camera did not, because that
    border is what separates the finder patterns from the dialog behind them.

    The captured code is version 11: 61 modules, 3.74px each, so 4 modules is
    15px. The 12% rule gives 27px — about 7 modules.
    """

    quiet = staticmethod(Connect._qr_quiet_zone)

    def test_the_real_case_clears_the_four_module_minimum(self):
        side, modules = 228, 61
        module_px = side / modules
        assert self.quiet(side) >= 4 * module_px

    @pytest.mark.parametrize("version,modules", [(3, 29), (7, 45), (11, 61), (15, 77)])
    def test_it_clears_the_minimum_for_every_plausible_version(self, version, modules):
        side = 228
        assert self.quiet(side) >= 4 * (side / modules), f"version {version} underserved"

    def test_a_floor_protects_tiny_images(self):
        assert self.quiet(20) >= 8
        assert self.quiet(1) >= 8

    def test_no_border_for_a_degenerate_size(self):
        assert self.quiet(0) == 0
        assert self.quiet(-5) == 0

    def test_it_scales_with_the_image(self):
        """Proportional, give or take the rounding of a single pixel."""
        assert abs(self.quiet(456) - 2 * self.quiet(228)) <= 1

    def test_the_padded_qr_still_fits_the_display_box(self):
        """228 + 2x27 = 282, inside the 300px box — no clipping, no shrinking."""
        side = 228
        assert side + 2 * self.quiet(side) <= Connect._QR_BOX


def _levels(image):
    """Distinct grey levels in a wx.Image — 2 for a clean black/white QR."""
    data = image.GetData()
    return len({data[i] for i in range(0, len(data), 3)})


def _synthetic_qr(side=264, module=8, seed=7):
    import random
    import wx
    rng = random.Random(seed)
    img = wx.Image(side, side)
    for by in range(0, side, module):
        for bx in range(0, side, module):
            v = 0 if rng.random() < 0.5 else 255
            for y in range(by, by + module):
                for x in range(bx, bx + module):
                    img.SetRGB(x, y, v, v, v)
    return img


@pytest.fixture(scope="module")
def wx_app():
    import wx
    return wx.App()


class TestScalingPreservesTheCode:
    def test_the_old_path_destroyed_the_module_edges(self, wx_app):
        import wx
        src = _synthetic_qr()
        assert _levels(src) == 2, "a QR is pure black and white to begin with"
        blurred = src.Scale(300, 300, wx.IMAGE_QUALITY_HIGH)
        assert _levels(blurred) > 2, (
            "interpolated scaling must be shown to introduce intermediate greys — "
            "if this ever stops being true the guard below is pointless"
        )

    @pytest.mark.parametrize("mult", [1, 2, 3])
    def test_nearest_neighbour_keeps_it_pure(self, wx_app, mult):
        import wx
        src = _synthetic_qr()
        out = src.Scale(src.GetWidth() * mult, src.GetHeight() * mult,
                        wx.IMAGE_QUALITY_NEAREST)
        assert _levels(out) == 2, "no smoothing may be introduced"
        assert out.GetWidth() == 264 * mult
