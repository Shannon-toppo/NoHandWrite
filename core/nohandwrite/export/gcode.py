"""G-code export for pen plotters.

Default dialect: pen up/down via Z moves (common for GRBL plotters);
override `pen_up_cmd` / `pen_down_cmd` for servo-based machines
(e.g. "M3 S40" / "M3 S90"). Y is flipped so the text reads top-down on
machines whose Y axis points away from the operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .layout import LayoutOptions, layout_text


@dataclass
class GCodeOptions:
    layout: LayoutOptions = field(default_factory=LayoutOptions)
    feed_draw: float = 1500.0      # mm/min while drawing
    feed_travel: float = 3000.0    # mm/min pen-up moves
    pen_up_cmd: str = "G0 Z5.0"
    pen_down_cmd: str = "G1 Z0.0 F300"
    flip_y: bool = True


def strokes_to_gcode(entries: list[dict], opts: GCodeOptions | None = None) -> str:
    opts = opts or GCodeOptions()
    placed, (w, h) = layout_text(entries, opts.layout)
    lines = [
        "; NoHandWrite pen plotter output",
        f"; page: {w:.1f} x {h:.1f} mm, {len(placed)} strokes",
        "G21 ; mm",
        "G90 ; absolute",
        opts.pen_up_cmd,
    ]
    for p in placed:
        pts = p.points
        ys = (h - pts[:, 1]) if opts.flip_y else pts[:, 1]
        lines.append(f"; char {p.char}")
        lines.append(f"G0 X{pts[0, 0]:.2f} Y{ys[0]:.2f} F{opts.feed_travel:.0f}")
        lines.append(opts.pen_down_cmd)
        for (x, _), y in zip(pts[1:], ys[1:]):
            lines.append(f"G1 X{x:.2f} Y{y:.2f} F{opts.feed_draw:.0f}")
        lines.append(opts.pen_up_cmd)
    lines += ["G0 X0 Y0", "; end"]
    return "\n".join(lines) + "\n"
