"""Text layout: place per-character strokes (0–1000 box) onto a page.

Output units are millimeters (native for pen plotters; SVG uses the same
numbers with a mm viewBox). Line breaks happen at '\n' and when a line
exceeds `max_width_mm` (in vertical mode that limit is the column height),
with simplified kinsoku shori: characters that may not start a line are
either pushed to the next line together with the character before them
(追い出し) or, for 、。,. , allowed to hang past the limit (ぶら下げ);
opening brackets may not end a line.

Stroke rows are (x, y) or (x, y, pressure); the pressure column is carried
through placement and simplification untouched.
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

# Kinsoku shori (simplified JIS X 4051 sets).
LINE_HEAD_FORBIDDEN = (set("、。,..,!?!?ー〜ゝゞヽヾ々」』)]}〉》】〕・::;;")
                       | SMALL_KANA)
LINE_END_FORBIDDEN = set("「『([{〈《【〔((")
HANGING = set("、。,..,")          # may hang past the line limit (ぶら下げ)

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
        out = []
        for s in strokes:
            r = s.copy()
            r[:, 0] = size - s[:, 1]
            r[:, 1] = s[:, 0]
            out.append(r)
        return out
    anchor = VERTICAL_REANCHOR.get(char)
    if anchor is None:
        return strokes
    pts = np.concatenate(strokes)
    min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
    w, h = pts[:, 0].max() - min_x, pts[:, 1].max() - min_y
    off = np.array([(size - w) * anchor[0] - min_x,
                    (size - h) * anchor[1] - min_y])
    out = []
    for s in strokes:
        r = s.copy()
        r[:, :2] += off
        out.append(r)
    return out


def _rdp(points: np.ndarray, eps: float) -> np.ndarray:
    """Ramer–Douglas–Peucker polyline simplification (iterative).

    Distances are measured on x/y; kept rows retain their extra columns."""
    n = len(points)
    if n < 3:
        return points
    xy = points[:, :2]
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = xy[b] - xy[a]
        norm = np.hypot(seg[0], seg[1])
        pts = xy[a + 1:b]
        if norm == 0:
            d = np.hypot(*(pts - xy[a]).T)
        else:
            rel = pts - xy[a]
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
    points: np.ndarray             # (N, 2|3) in mm, absolute page coordinates


@dataclass
class _Item:
    """One character prepared for layout."""
    char: str
    strokes: list[np.ndarray] | None   # 0–1000 box, vertical-adjusted
    advance: float                     # mm along the writing direction
    offset: float                      # mm from pen position to ink start


def _prepare(entries: list[dict], opts: LayoutOptions) -> list[_Item]:
    """Glyph strokes, advance width and draw offset for every entry."""
    axis = 1 if opts.vertical else 0
    scale = opts.char_size_mm / STANDARD_SIZE
    items = []
    for e in entries:
        char = e["char"]
        if char == "\n":
            items.append(_Item("\n", None, 0.0, 0.0))
            continue
        strokes = e.get("strokes")
        if strokes:
            strokes = [np.asarray(s, dtype=float)[:, :3] for s in strokes]
            if opts.vertical:
                strokes = _vertical_glyph(strokes, char)
        advance, offset = opts.char_size_mm, 0.0
        if opts.proportional:
            if strokes:
                v = np.concatenate([s[:, axis] for s in strokes])
                advance = (v.max() - v.min()) * scale
                offset = -v.min() * scale    # ink edge lands on the pen
            elif char == " ":
                advance = opts.char_size_mm * ASCII_SPACE_ADVANCE
        items.append(_Item(char, strokes, advance, offset))
    return items


def _break_lines(items: list[_Item], opts: LayoutOptions) -> list[list[_Item]]:
    """Split items into lines at '\n' and the length limit, with kinsoku."""
    limit = opts.max_width_mm
    lines: list[list[_Item]] = []
    line: list[_Item] = []
    pos = 0.0
    emit_last = True     # emit the final line even when empty ('\n' made it)
    for it in items:
        if it.char == "\n":
            lines.append(line)
            line, pos = [], 0.0
            emit_last = True
            continue
        if limit is None or not line or pos + it.advance <= limit:
            line.append(it)
            pos += it.advance + opts.char_gap_mm
            emit_last = True
            continue
        if it.char in HANGING:
            # ぶら下げ: the punctuation hangs past the limit, break after it
            line.append(it)
            lines.append(line)
            line, pos = [], 0.0
            emit_last = False
            continue
        # 追い出し: keep line-head-forbidden characters attached to the
        # character before them, and pull back characters that may not
        # end a line
        carry = [it]
        while line and (carry[0].char in LINE_HEAD_FORBIDDEN
                        or line[-1].char in LINE_END_FORBIDDEN):
            carry.insert(0, line.pop())
        lines.append(line)
        line = carry
        pos = sum(c.advance + opts.char_gap_mm for c in carry)
        emit_last = True
    if line or emit_last:
        lines.append(line)
    return lines


def layout_text(entries: list[dict], opts: LayoutOptions | None = None
                ) -> tuple[list[PlacedStroke], tuple[float, float]]:
    """Place characters left-to-right, top-to-bottom (or top-to-bottom,
    right-to-left with `vertical=True`).

    `entries`: [{"char": str, "strokes": list of (N,2|3) arrays | None}, ...]
    — entries whose strokes are None advance the pen position but draw
    nothing (unavailable characters render as blank space); '\n' chars force
    a break.

    In proportional mode (default) each glyph advances by its own ink width;
    ASCII spaces take `ASCII_SPACE_ADVANCE` of a cell, other blanks a full
    cell. In fixed mode every character advances by char_size_mm.

    Returns (placed strokes, (page_width_mm, page_height_mm)).
    """
    opts = opts or LayoutOptions()
    if opts.vertical:
        return _layout_vertical(entries, opts)
    scale = opts.char_size_mm / STANDARD_SIZE
    lines = _break_lines(_prepare(entries, opts), opts)
    line_step = opts.char_size_mm + opts.line_gap_mm
    placed: list[PlacedStroke] = []
    max_x = opts.margin_mm
    for row, line in enumerate(lines):
        x = opts.margin_mm
        y = opts.margin_mm + row * line_step
        for it in line:
            if it.strokes:
                for s in it.strokes:
                    pts = s.copy()
                    pts[:, :2] *= scale
                    pts[:, 0] += x + it.offset
                    pts[:, 1] += y
                    if opts.simplify_mm > 0:
                        pts = _rdp(pts, opts.simplify_mm)
                    placed.append(PlacedStroke(char=it.char, points=pts))
            x += it.advance + opts.char_gap_mm
            max_x = max(max_x, x)
    width = max_x - opts.char_gap_mm + opts.margin_mm
    height = (opts.margin_mm + (len(lines) - 1) * line_step
              + opts.char_size_mm + opts.margin_mm)
    return placed, (width, height)


def _layout_vertical(entries: list[dict], opts: LayoutOptions
                     ) -> tuple[list[PlacedStroke], tuple[float, float]]:
    """Vertical writing: characters top-to-bottom, columns right-to-left.

    Columns are laid out with provisional x (0 for the first, negative for
    the following ones) and shifted right once the column count is known.
    """
    scale = opts.char_size_mm / STANDARD_SIZE
    lines = _break_lines(_prepare(entries, opts), opts)
    col_step = opts.char_size_mm + opts.line_gap_mm
    placed: list[PlacedStroke] = []
    max_y = opts.margin_mm
    for col, line in enumerate(lines):
        y = opts.margin_mm
        for it in line:
            if it.strokes:
                for s in it.strokes:
                    pts = s.copy()
                    pts[:, :2] *= scale
                    pts[:, 0] += -col * col_step
                    pts[:, 1] += y + it.offset
                    if opts.simplify_mm > 0:
                        pts = _rdp(pts, opts.simplify_mm)
                    placed.append(PlacedStroke(char=it.char, points=pts))
            y += it.advance + opts.char_gap_mm
            max_y = max(max_y, y)
    # shift so the leftmost (last) column starts at the margin
    max_col = len(lines) - 1
    x_shift = opts.margin_mm + max_col * col_step
    for p in placed:
        p.points[:, 0] += x_shift
    width = max_col * col_step + opts.char_size_mm + 2 * opts.margin_mm
    height = max_y - opts.char_gap_mm + opts.margin_mm
    return placed, (width, height)
