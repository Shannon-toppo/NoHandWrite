"""Beautification pipeline: CharacterData -> average (or smoothed) character."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .fourier import average_character, filter_matching_samples, smooth_stroke
from .strokes import STANDARD_SIZE, CharacterData, normalize_strokes


@dataclass
class BeautifyResult:
    strokes: list[np.ndarray]      # (N, 2) arrays in the 0–1000 standard box
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


def beautify(data: CharacterData, threshold: float | None = None) -> BeautifyResult:
    """User-average character when several samples exist (the paper's method);
    Fourier smoothing of the single sample otherwise.

    Samples whose stroke count differs from the majority are excluded.
    """
    kwargs = {} if threshold is None else {"threshold": threshold}
    normalized = [normalize_strokes(s.strokes) for s in data.samples]
    kept, stroke_count = filter_matching_samples(normalized)
    if not kept:
        raise ValueError("no samples")
    if len(kept) == 1:
        strokes = [smooth_stroke(s, **kwargs) for s in kept[0]]
        mode = "smooth"
    else:
        strokes = average_character(kept, **kwargs)
        mode = "average"
    return BeautifyResult(strokes=strokes, used_samples=len(kept),
                          total_samples=len(data.samples),
                          stroke_count=stroke_count, mode=mode)
