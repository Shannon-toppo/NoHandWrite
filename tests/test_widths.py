import pytest

from nohandwrite.export.layout import (
    HANGING, LINE_END_FORBIDDEN, LINE_HEAD_FORBIDDEN, VERTICAL_ROTATE,
)
from nohandwrite.metrics import metrics_for
from nohandwrite.widths import both_widths, width_variant


@pytest.mark.parametrize("a,b", [("(", "（"), (")", "）"), (";", "；"),
                                 (":", "："), ("!", "！"), (",", "，"),
                                 ("｢", "「"), ("｡", "。"), ("ｰ", "ー")])
def test_pairs_map_both_ways(a, b):
    assert width_variant(a) == b
    assert width_variant(b) == a


def test_characters_without_a_counterpart():
    # kana and kanji are single-width; 〜(U+301C) is not the full-width form
    # of ~ (that is ～ U+FF5E), so it stands alone too
    for c in "あ漢字〜":
        assert width_variant(c) is None


def test_both_widths_expands_a_table():
    assert both_widths("(;") == {"(", "（", ";", "；"}


def test_kinsoku_covers_both_widths():
    """Line-breaking rules must not depend on which width was typed."""
    for c in "）］｝！？：；，．":
        assert c in LINE_HEAD_FORBIDDEN
    for c in "（［｛([{":
        assert c in LINE_END_FORBIDDEN
    assert {"，", "．"} <= HANGING
    assert {"（", "）", "［", "］"} <= VERTICAL_ROTATE


def test_full_width_punctuation_keeps_punctuation_metrics():
    """A substituted ．must not come out as a full-em dot."""
    assert metrics_for("．").scale < 0.2
    assert metrics_for("，").scale < 0.2
    assert metrics_for("！").scale == pytest.approx(metrics_for("!").scale, abs=0.1)
