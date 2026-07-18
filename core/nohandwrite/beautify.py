"""Beautification pipeline: CharacterData -> average (or smoothed) character."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .fourier import average_character, filter_matching_samples, smooth_stroke
from .metrics import place_glyph
from .strokes import (
    STANDARD_SIZE, CharacterData, normalize_strokes, normalize_to_field,
)


@dataclass
class BeautifyResult:
    strokes: list[np.ndarray]      # (N, 3) x, y, pressure in the 0–1000 box
    used_samples: int
    total_samples: int
    stroke_count: int
    mode: str                      # "average" or "smooth"

    def to_json(self) -> dict:
        return {
            "strokes": [s.round(2).tolist() for s in self.strokes],
            "size": STANDARD_SIZE,
            "usedSamples": self.used_samples,
            "totalSamples": self.total_samples,
            "strokeCount": self.stroke_count,
            "mode": self.mode,
        }


def beautify(data: CharacterData, threshold: float | None = None,
             place: bool = True) -> BeautifyResult:
    """User-average character when several samples exist (the paper's method);
    Fourier smoothing of the single sample otherwise.

    Samples whose stroke count differs from the majority are excluded.
    With `place=True` (default) each sample is bbox-normalized and the result
    is sized/positioned by the glyph metrics table, so all characters come out
    in consistent proportion with SDT-generated ones. With `place=False`
    normalization is field-relative — the character keeps the size and
    position it was written with (used by the library view, where the average
    must overlay the raw samples).
    """
    kwargs = {} if threshold is None else {"threshold": threshold}
    if place:
        normalized = [normalize_strokes(s.strokes) for s in data.samples]
    else:
        normalized = [normalize_to_field(s.strokes, s.canvas) for s in data.samples]
    kept, stroke_count = filter_matching_samples(normalized)
    if not kept:
        raise ValueError("no samples")
    if len(kept) == 1:
        strokes = [smooth_stroke(s, **kwargs) for s in kept[0]]
        mode = "smooth"
    else:
        strokes = average_character(kept, **kwargs)
        mode = "average"
    if place:
        strokes = place_glyph(strokes, data.char)
    return BeautifyResult(strokes=strokes, used_samples=len(kept),
                          total_samples=len(data.samples),
                          stroke_count=stroke_count, mode=mode)
