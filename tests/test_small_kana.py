"""Tests for the glyph metrics table (size + placement rules)."""
import numpy as np

from nohandwrite.metrics import SMALL_KANA, metrics_for, place_glyph


def _bbox(strokes):
    pts = np.concatenate([s[:, :2] for s in strokes])
    return (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())


def test_small_kana_set_contains_common_chars():
    for c in "っゃゅょッァ":
        assert c in SMALL_KANA
    assert "つ" not in SMALL_KANA


def test_small_kana_scales_and_anchors_bottom_left():
    full = [np.array([[0, 0], [1000, 1000]], dtype=float)]
    x0, y0, x1, y1 = _bbox(place_glyph(full, "っ"))
    assert x1 - x0 < 700                    # scaled down
    assert y1 > 850                         # bottom-anchored
    assert x0 < 150                         # left-anchored


def test_placement_is_consistent_across_scripts():
    # any input size/position ends up at the metrics size for that char
    small = [np.array([[400, 400], [430, 450], [460, 400]], dtype=float)]
    kanji = place_glyph(small, "木")
    period = place_glyph(small, "。")
    kw = _bbox(kanji)[2] - _bbox(kanji)[0]
    pw = _bbox(period)[2] - _bbox(period)[0]
    assert kw == 900                        # kanji fills 90% of the box
    assert pw == 180                        # 。 is tiny, regardless of input
    x0, y0, x1, y1 = _bbox(period)
    assert x0 < 200 and y1 > 800            # 。 sits bottom-left


def test_lowercase_smaller_than_uppercase():
    stroke = [np.array([[0, 0], [600, 1000]], dtype=float)]
    upper = _bbox(place_glyph(stroke, "A"))
    lower = _bbox(place_glyph(stroke, "a"))
    assert (lower[3] - lower[1]) < (upper[3] - upper[1])
    assert metrics_for("g").ay > metrics_for("b").ay   # descender sits lower


def test_extra_columns_pass_through():
    full = [np.array([[0, 0, 1.0, 0.5], [1000, 1000, 2.0, 0.6]])]
    out = place_glyph(full, "木")[0]
    assert out.shape == (2, 4)
    np.testing.assert_array_equal(out[:, 2:], full[0][:, 2:])
