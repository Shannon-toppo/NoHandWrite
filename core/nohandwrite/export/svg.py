"""Single-line (stroke) SVG export for pen plotters.

Each pen stroke becomes one <path> with a polyline `d`; paths appear in
writing order, so plotter drivers that follow document order preserve the
stroke order. Units are millimeters.
"""
from __future__ import annotations

from .layout import LayoutOptions, PlacedStroke, layout_text


def _path_d(points) -> str:
    coords = [f"{x:.2f} {y:.2f}" for x, y in points]
    return "M " + " L ".join(coords)


def strokes_to_svg(entries: list[dict], opts: LayoutOptions | None = None,
                   stroke_width_mm: float = 0.5) -> str:
    placed, (w, h) = layout_text(entries, opts)
    paths = "\n".join(
        f'  <path d="{_path_d(p.points)}" data-char="{p.char}"/>'
        for p in placed
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" viewBox="0 0 {w:.2f} {h:.2f}">
<g fill="none" stroke="black" stroke-width="{stroke_width_mm}" stroke-linecap="round" stroke-linejoin="round">
{paths}
</g>
</svg>
"""
