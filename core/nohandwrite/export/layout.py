"""Text layout: place per-character strokes (0–1000 box) onto a page.

Output units are millimeters (native for pen plotters; SVG uses the same
numbers with a mm viewBox). Line breaks happen at '\n' and when a line
exceeds `max_width_mm` (in vertical mode that limit is the column height).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..metrics import SMALL_KANA
from ..strokes import STANDARD_SIZE


@dataclass
class LayoutOptions:
    char_size_mm: float = 15.0     # edge of one character cell
    char_gap_mm: float = 1.5
    line_gap_mm: float = 4.0
    max_width_mm: float | None = 180.0   # line length: width, or column
                                         # height in vertical mode
    margin_mm: float = 10.0
    simplify_mm: float = 0.05      # RDP tolerance; 0 disables
    proportional: bool = True      # advance by each glyph's ink width
                                   # (False: fixed char_size_mm cells)
    vertical: bool = False         # columns top-to-bottom, right-to-left

ASCII_SPACE_ADVANCE = 0.4          # of char_size_mm, proportional mode only

# Vertical-writing glyph adjustments (JIS vertical forms, simplified):
# these characters are drawn rotated 90° clockwise in a column...
VERTICAL_ROTATE = set("ー〜-−–—=…‥「」『』()()[]〈〉《》【】{}")
# ...and these move to the top right of their cell: (ax, ay) anchors of the
# leftover box space, same convention as metrics.GlyphMetrics.
VERTICAL_REANCHOR = {
    **{c: (0.75, 0.10) for c in SMALL_KANA},
    "、": (0.80, 0.05), "。": (0.80, 0.05),
    ",": (0.80, 0.05), ".": (0.80, 0.05),
}


def _vertical_glyph(strokes: list[np.ndarray], char: str,
                    size: float = STANDARD_SIZE) -> list[np.ndarray]:
    """Adjust a glyph (0–1000 box) for vertical writing."""
    if char in VERTICAL_ROTATE:
        return [np.stack([size - s[:, 1], s[:, 0]], axis=1) for s in strokes]
    anchor = VERTICAL_REANCHOR.get(char)
    if anchor is None:
        return strokes
    pts = np.concatenate(strokes)
    min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
    w, h = pts[:, 0].max() - min_x, pts[:, 1].max() - min_y
    off = np.array([(size - w) * anchor[0] - min_x,
                    (size - h) * anchor[1] - min_y])
    return [s + off for s in strokes]


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
    """Place characters left-to-right, top-to-bottom (or top-to-bottom,
    right-to-left with `vertical=True`).

    `entries`: [{"char": str, "strokes": list of (N,2) arrays | None}, ...] —
    entries whose strokes are None advance the pen position but draw nothing
    (unavailable characters render as blank space); '\n' chars force a break.

    In proportional mode (default) each glyph advances by its own ink width;
    ASCII spaces take `ASCII_SPACE_ADVANCE` of a cell, other blanks a full
    cell. In fixed mode every character advances by char_size_mm.

    Returns (placed strokes, (page_width_mm, page_height_mm)).
    """
    opts = opts or LayoutOptions()
    if opts.vertical:
        return _layout_vertical(entries, opts)
    scale = opts.char_size_mm / STANDARD_SIZE
    line_step = opts.char_size_mm + opts.line_gap_mm
    x, y = opts.margin_mm, opts.margin_mm
    max_x = x
    placed: list[PlacedStroke] = []
    for e in entries:
        if e["char"] == "\n":
            x = opts.margin_mm
            y += line_step
            continue
        strokes = e.get("strokes")
        # advance width and horizontal draw offset of this character
        advance, x_offset = opts.char_size_mm, 0.0
        if opts.proportional:
            if strokes:
                xs = np.concatenate([np.asarray(s, dtype=float)[:, 0] for s in strokes])
                advance = (xs.max() - xs.min()) * scale
                x_offset = -xs.min() * scale     # left ink edge lands on the pen
            elif e["char"] == " ":
                advance = opts.char_size_mm * ASCII_SPACE_ADVANCE
        if opts.max_width_mm is not None and x + advance > opts.max_width_mm + opts.margin_mm:
            x = opts.margin_mm
            y += line_step
        if strokes:
            for s in strokes:
                pts = np.asarray(s, dtype=float)[:, :2] * scale
                pts = pts + np.array([x + x_offset, y])
                if opts.simplify_mm > 0:
                    pts = _rdp(pts, opts.simplify_mm)
                placed.append(PlacedStroke(char=e["char"], points=pts))
        x += advance + opts.char_gap_mm
        max_x = max(max_x, x)
    width = max_x - opts.char_gap_mm + opts.margin_mm
    height = y + opts.char_size_mm + opts.margin_mm
    return placed, (width, height)


def _layout_vertical(entries: list[dict], opts: LayoutOptions
                     ) -> tuple[list[PlacedStroke], tuple[float, float]]:
    """Vertical writing: characters top-to-bottom, columns right-to-left.

    Columns are laid out with provisional x (0 for the first, negative for
    the following ones) and shifted right once the column count is known.
    """
    scale = opts.char_size_mm / STANDARD_SIZE
    col_step = opts.char_size_mm + opts.line_gap_mm
    col, y = 0, opts.margin_mm
    max_col, max_y = 0, y
    placed: list[PlacedStroke] = []
    for e in entries:
        if e["char"] == "\n":
            col += 1
            y = opts.margin_mm
            continue
        strokes = e.get("strokes")
        if strokes:
            strokes = _vertical_glyph(
                [np.asarray(s, dtype=float)[:, :2] for s in strokes], e["char"])
        # advance height and vertical draw offset of this character
        advance, y_offset = opts.char_size_mm, 0.0
        if opts.proportional:
            if strokes:
                ys = np.concatenate([s[:, 1] for s in strokes])
                advance = (ys.max() - ys.min()) * scale
                y_offset = -ys.min() * scale     # top ink edge lands on the pen
            elif e["char"] == " ":
                advance = opts.char_size_mm * ASCII_SPACE_ADVANCE
        if opts.max_width_mm is not None and y + advance > opts.max_width_mm + opts.margin_mm:
            col += 1
            y = opts.margin_mm
        if strokes:
            for s in strokes:
                pts = s * scale + np.array([-col * col_step, y + y_offset])
                if opts.simplify_mm > 0:
                    pts = _rdp(pts, opts.simplify_mm)
                placed.append(PlacedStroke(char=e["char"], points=pts))
        y += advance + opts.char_gap_mm
        max_col = max(max_col, col)
        max_y = max(max_y, y)
    # shift so the leftmost (last) column starts at the margin
    x_shift = opts.margin_mm + max_col * col_step
    for p in placed:
        p.points[:, 0] += x_shift
    width = max_col * col_step + opts.char_size_mm + 2 * opts.margin_mm
    height = max_y - opts.char_gap_mm + opts.margin_mm
    return placed, (width, height)
