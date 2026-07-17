"""Text layout: place per-character strokes (0–1000 box) onto a page.

Output units are millimeters (native for pen plotters; SVG uses the same
numbers with a mm viewBox). Line breaks happen at '\n' and when a line
exceeds `max_width_mm`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..strokes import STANDARD_SIZE


@dataclass
class LayoutOptions:
    char_size_mm: float = 15.0     # edge of one character cell
    char_gap_mm: float = 1.5
    line_gap_mm: float = 4.0
    max_width_mm: float | None = 180.0
    margin_mm: float = 10.0
    simplify_mm: float = 0.05      # RDP tolerance; 0 disables


def _rdp(points: np.ndarray, eps: float) -> np.ndarray:
    """Ramer–Douglas–Peucker polyline simplification (iterative)."""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = points[b] - points[a]
        norm = np.hypot(*seg)
        pts = points[a + 1:b]
        if norm == 0:
            d = np.hypot(*(pts - points[a]).T)
        else:
            rel = pts - points[a]
            d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / norm
        i = int(np.argmax(d))
        if d[i] > eps:
            idx = a + 1 + i
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return points[keep]


@dataclass
class PlacedStroke:
    char: str
    points: np.ndarray             # (N, 2) in mm, absolute page coordinates


def layout_text(entries: list[dict], opts: LayoutOptions | None = None
                ) -> tuple[list[PlacedStroke], tuple[float, float]]:
    """Place characters left-to-right, top-to-bottom.

    `entries`: [{"char": str, "strokes": list of (N,2) arrays | None}, ...] —
    entries whose strokes are None advance the pen position but draw nothing
    (unavailable characters render as blank space); '\n' chars force a break.

    Returns (placed strokes, (page_width_mm, page_height_mm)).
    """
    opts = opts or LayoutOptions()
    scale = opts.char_size_mm / STANDARD_SIZE
    step = opts.char_size_mm + opts.char_gap_mm
    line_step = opts.char_size_mm + opts.line_gap_mm
    x, y = opts.margin_mm, opts.margin_mm
    max_x = x
    placed: list[PlacedStroke] = []
    for e in entries:
        if e["char"] == "\n":
            x = opts.margin_mm
            y += line_step
            continue
        if opts.max_width_mm is not None and x + opts.char_size_mm > opts.max_width_mm + opts.margin_mm:
            x = opts.margin_mm
            y += line_step
        strokes = e.get("strokes")
        if strokes:
            for s in strokes:
                pts = np.asarray(s, dtype=float)[:, :2] * scale
                pts = pts + np.array([x, y])
                if opts.simplify_mm > 0:
                    pts = _rdp(pts, opts.simplify_mm)
                placed.append(PlacedStroke(char=e["char"], points=pts))
        x += step
        max_x = max(max_x, x)
    width = max_x - opts.char_gap_mm + opts.margin_mm
    height = y + opts.char_size_mm + opts.margin_mm
    return placed, (width, height)
