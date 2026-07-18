"""Glyph metrics: rule-based size and placement in the standard box.

Every glyph — the user's beautified characters and SDT-generated ones — is
first bbox-normalized to the full 0–1000 box (`normalize_strokes`), which
makes its size independent of how it was captured or generated. It is then
scaled down and anchored inside the box using this table: a per-character
override when one exists, otherwise the default for its script category
(see `variation.char_category`). This is what keeps 漢字/かな/英数字/記号
in consistent proportion regardless of which pipeline produced them.

Anchors are fractions of the leftover space: ax 0 = left, 1 = right;
ay 0 = top, 1 = bottom (0.5 centers). Values are typographic rules of
thumb for horizontal writing, not exact font metrics — handwriting output
tolerates (and benefits from) a little looseness.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .strokes import STANDARD_SIZE, bounding_box, normalize_strokes
from .variation import char_category


@dataclass(frozen=True)
class GlyphMetrics:
    scale: float           # of the full box
    ax: float = 0.5        # horizontal anchor in the leftover space
    ay: float = 0.5        # vertical anchor in the leftover space


CATEGORY_METRICS: dict[str, GlyphMetrics] = {
    "kanji": GlyphMetrics(0.90),
    "hiragana": GlyphMetrics(0.82, ay=0.55),
    "katakana": GlyphMetrics(0.82, ay=0.55),
    "alnum": GlyphMetrics(0.72, ay=0.57),   # bottom lands near a 0.88 baseline
    "other": GlyphMetrics(0.70),
}

SMALL_KANA = set("っゃゅょぁぃぅぇぉゎゕゖッャュョァィゥェォヮヵヶ")

CHAR_METRICS: dict[str, GlyphMetrics] = {
    **{c: GlyphMetrics(0.62, ax=0.15, ay=0.90) for c in SMALL_KANA},
    # x-height / ascender / descender latin lowercase (baseline ~0.88)
    **{c: GlyphMetrics(0.45, ay=0.78) for c in "aceimnorsuvwxz"},
    **{c: GlyphMetrics(0.70, ay=0.60) for c in "bdfhklt"},
    **{c: GlyphMetrics(0.60, ay=0.97) for c in "gjpqy"},
    "、": GlyphMetrics(0.18, ax=0.10, ay=0.85),
    "。": GlyphMetrics(0.18, ax=0.10, ay=0.85),
    "・": GlyphMetrics(0.15),
    "「": GlyphMetrics(0.50, ax=0.95, ay=0.05),
    "」": GlyphMetrics(0.50, ax=0.05, ay=0.95),
    "『": GlyphMetrics(0.55, ax=0.95, ay=0.05),
    "』": GlyphMetrics(0.55, ax=0.05, ay=0.95),
    "ー": GlyphMetrics(0.72),
    "〜": GlyphMetrics(0.72),
    ".": GlyphMetrics(0.10, ax=0.25, ay=0.88),
    ",": GlyphMetrics(0.12, ax=0.25, ay=0.88),
    "'": GlyphMetrics(0.15, ax=0.35, ay=0.05),
    '"': GlyphMetrics(0.18, ax=0.40, ay=0.05),
    "!": GlyphMetrics(0.72, ay=0.57),
    "?": GlyphMetrics(0.72, ay=0.57),
}


def metrics_for(char: str) -> GlyphMetrics:
    return CHAR_METRICS.get(char, CATEGORY_METRICS[char_category(char)])


def place_glyph(strokes: list[np.ndarray], char: str,
                size: float = STANDARD_SIZE) -> list[np.ndarray]:
    """Fit a glyph's bounding box to the full box, then scale and anchor it
    per its metrics. Extra columns (t, p) pass through unchanged."""
    full = normalize_strokes(strokes, size)
    m = metrics_for(char)
    min_x, min_y, max_x, max_y = bounding_box(full)
    w, h = (max_x - min_x) * m.scale, (max_y - min_y) * m.scale
    off = np.array([(size - w) * m.ax - min_x * m.scale,
                    (size - h) * m.ay - min_y * m.scale])
    out = []
    for s in full:
        r = s.copy()
        r[:, :2] = r[:, :2] * m.scale + off
        out.append(r)
    return out
