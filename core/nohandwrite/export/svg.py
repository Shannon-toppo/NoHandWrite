"""Single-line (stroke) SVG export for pen plotters.

Each pen stroke becomes one <path> with a polyline `d`; paths appear in
writing order, so plotter drivers that follow document order preserve the
stroke order. Units are millimeters.

With `pressure_width=True`, strokes that carry pressure data are split into
runs of segments whose stroke-width follows the pen pressure (for display
or raster printing — plotters want the default single-width output).
"""
from __future__ import annotations

import numpy as np

from .layout import LayoutOptions, layout_text


def _path_d(points) -> str:
    coords = [f"{x:.2f} {y:.2f}" for x, y, *_ in points]
    return "M " + " L ".join(coords)


def _pressure_paths(pts: np.ndarray, char: str,
                    width_min_mm: float, width_max_mm: float) -> list[str]:
    """One <path> per run of segments sharing the same (rounded) width."""
    p = np.clip(pts[:, 2], 0.0, 1.0)
    seg_w = np.round(width_min_mm
                     + (width_max_mm - width_min_mm) * (p[:-1] + p[1:]) / 2, 2)
    paths, start = [], 0
    for i in range(1, len(seg_w) + 1):
        if i == len(seg_w) or seg_w[i] != seg_w[start]:
            run = pts[start:i + 1]
            paths.append(f'  <path d="{_path_d(run)}" '
                         f'stroke-width="{seg_w[start]}" data-char="{char}"/>')
            start = i
    return paths


def strokes_to_svg(entries: list[dict], opts: LayoutOptions | None = None,
                   stroke_width_mm: float = 0.5,
                   pressure_width: bool = False,
                   width_min_mm: float = 0.2,
                   width_max_mm: float = 1.0) -> str:
    placed, (w, h) = layout_text(entries, opts)
    parts = []
    for p in placed:
        pts = p.points
        if (pressure_width and pts.shape[1] > 2 and len(pts) > 1
                and np.any(pts[:, 2] > 0)):
            parts.extend(_pressure_paths(pts, p.char, width_min_mm, width_max_mm))
        else:
            parts.append(f'  <path d="{_path_d(pts)}" data-char="{p.char}"/>')
    paths = "\n".join(parts)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" viewBox="0 0 {w:.2f} {h:.2f}">
<g fill="none" stroke="black" stroke-width="{stroke_width_mm}" stroke-linecap="round" stroke-linejoin="round">
{paths}
</g>
</svg>
"""
