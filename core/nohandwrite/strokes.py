"""Stroke data model and geometry helpers.

A character sample is a list of strokes; a stroke is an (N, 4) float array with
columns (x, y, t, p) — position, time in ms since the first pen-down of the
sample, and pen pressure in [0, 1] (0 when the device reports none).

Samples are stored losslessly in their original canvas coordinates; call
`normalize_strokes` to map into the standard 0–1000 box for processing
(the paper normalizes each axis independently, which distorts aspect ratio —
we scale uniformly and center instead).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

STANDARD_SIZE = 1000.0


@dataclass
class Sample:
    """One writing of a character."""
    strokes: list[np.ndarray]  # each (N, 4): x, y, t, p
    canvas: tuple[float, float] = (STANDARD_SIZE, STANDARD_SIZE)
    device: str = "unknown"
    recorded_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "recordedAt": self.recorded_at,
            "canvas": list(self.canvas),
            "strokes": [
                [{"x": float(x), "y": float(y), "t": float(t), "p": float(p)}
                 for x, y, t, p in stroke]
                for stroke in self.strokes
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Sample":
        strokes = [
            np.array([[pt["x"], pt["y"], pt.get("t", 0.0), pt.get("p", 0.0)]
                      for pt in stroke], dtype=np.float64).reshape(-1, 4)
            for stroke in data["strokes"]
        ]
        return cls(strokes=strokes,
                   canvas=tuple(data.get("canvas", (STANDARD_SIZE, STANDARD_SIZE))),
                   device=data.get("device", "unknown"),
                   recorded_at=data.get("recordedAt", ""))


@dataclass
class CharacterData:
    """All recorded writings of one character by one writer."""
    char: str
    writer: str
    samples: list[Sample] = field(default_factory=list)

    @property
    def codepoint(self) -> str:
        return f"U+{ord(self.char):04X}"

    def to_json(self) -> dict[str, Any]:
        return {
            "char": self.char,
            "codepoint": self.codepoint,
            "writer": self.writer,
            "samples": [s.to_json() for s in self.samples],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CharacterData":
        return cls(char=data["char"], writer=data["writer"],
                   samples=[Sample.from_json(s) for s in data["samples"]])


def bounding_box(strokes: list[np.ndarray]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) over all stroke points."""
    pts = np.concatenate(strokes, axis=0)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()))


def normalize_strokes(strokes: list[np.ndarray], size: float = STANDARD_SIZE) -> list[np.ndarray]:
    """Uniformly scale and center strokes into the [0, size] square.

    Aspect ratio is preserved; the longer side of the bounding box maps to
    `size` and the character is centered on the other axis. t and p columns
    are passed through unchanged.
    """
    min_x, min_y, max_x, max_y = bounding_box(strokes)
    w, h = max_x - min_x, max_y - min_y
    scale = size / max(w, h) if max(w, h) > 0 else 1.0
    off_x = (size - w * scale) / 2.0
    off_y = (size - h * scale) / 2.0
    out = []
    for s in strokes:
        r = s.copy()
        r[:, 0] = (r[:, 0] - min_x) * scale + off_x
        r[:, 1] = (r[:, 1] - min_y) * scale + off_y
        out.append(r)
    return out


def normalize_to_field(strokes: list[np.ndarray], canvas: tuple[float, float],
                       size: float = STANDARD_SIZE) -> list[np.ndarray]:
    """Map strokes from their capture field into the [0, size] square,
    preserving the character's size and position within the field.

    Unlike `normalize_strokes` (which fits the glyph's bounding box to the
    box and is right for comparing shapes), this keeps small kana, punctuation
    and their placement exactly as written: the whole input field maps to the
    standard box.
    """
    cw, ch = canvas
    scale = size / max(cw, ch) if max(cw, ch) > 0 else 1.0
    off_x = (size - cw * scale) / 2.0
    off_y = (size - ch * scale) / 2.0
    out = []
    for s in strokes:
        r = s.copy()
        r[:, 0] = r[:, 0] * scale + off_x
        r[:, 1] = r[:, 1] * scale + off_y
        out.append(r)
    return out


def stroke_length(stroke: np.ndarray) -> float:
    if len(stroke) < 2:
        return 0.0
    d = np.diff(stroke[:, :2], axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def resample_stroke(stroke: np.ndarray, num_points: int) -> np.ndarray:
    """Resample a stroke to `num_points` equally spaced along its arc length.

    All four columns (x, y, t, p) are linearly interpolated. A stroke with a
    single point (a dot) is repeated.
    """
    if len(stroke) == 1:
        return np.repeat(stroke, num_points, axis=0)
    d = np.diff(stroke[:, :2], axis=0)
    seg = np.hypot(d[:, 0], d[:, 1])
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    total = arc[-1]
    if total == 0:
        return np.repeat(stroke[:1], num_points, axis=0)
    targets = np.linspace(0.0, total, num_points)
    cols = [np.interp(targets, arc, stroke[:, c]) for c in range(stroke.shape[1])]
    return np.stack(cols, axis=1)
