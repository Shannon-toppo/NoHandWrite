import numpy as np

from nohandwrite.generate import shrink_small_kana
from nohandwrite.generate.sdt_adapter import SMALL_KANA


def test_small_kana_set_contains_common_chars():
    for c in "っゃゅょッァ":
        assert c in SMALL_KANA
    assert "つ" not in SMALL_KANA


def test_shrink_small_kana_scales_and_anchors_bottom_left():
    full = [np.array([[0, 0], [1000, 1000]], dtype=float)]
    out = shrink_small_kana(full)[0]
    w = out[1, 0] - out[0, 0]
    assert w < 700                          # scaled down
    assert out[1, 1] <= 1000 and out[1, 1] > 900   # bottom-anchored
    assert out[0, 0] < 100                  # left-anchored
