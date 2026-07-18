"""G-code export for pen plotters.

Default dialect: pen up/down via Z moves (common for GRBL plotters);
override `pen_up_cmd` / `pen_down_cmd` for servo-based machines
(e.g. "M3 S40" / "M3 S90"). Y is flipped so the text reads top-down on
machines whose Y axis points away from the operator.

With `pressure_z=True`, strokes that carry pressure data are drawn with the
Z axis modulated between `z_light` (pressure 0) and `z_heavy` (pressure 1),
so a soft pen presses harder where the writer did. Machines without Z
control keep the default `pressure_z=False` and get the plain
pen_up_cmd/pen_down_cmd behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .layout import LayoutOptions, layout_text


@dataclass
class GCodeOptions:
    layout: LayoutOptions = field(default_factory=LayoutOptions)
    feed_draw: float = 1500.0      # mm/min while drawing
    feed_travel: float = 3000.0    # mm/min pen-up moves
    pen_up_cmd: str = "G0 Z5.0"
    pen_down_cmd: str = "G1 Z0.0 F300"
    flip_y: bool = True
    pressure_z: bool = False       # modulate Z with pen pressure
    z_light: float = 0.0           # Z at pressure 0 (lightest touch)
    z_heavy: float = -0.4          # Z at pressure 1
    z_feed: float = 300.0          # plunge feed for the pen-down move


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
        modulate = (opts.pressure_z and pts.shape[1] > 2
                    and bool(np.any(pts[:, 2] > 0)))
        lines.append(f"; char {p.char}")
        lines.append(f"G0 X{pts[0, 0]:.2f} Y{ys[0]:.2f} F{opts.feed_travel:.0f}")
        if modulate:
            z = (opts.z_light + (opts.z_heavy - opts.z_light)
                 * np.clip(pts[:, 2], 0.0, 1.0))
            lines.append(f"G1 Z{z[0]:.2f} F{opts.z_feed:.0f}")
            for (x, *_), y, zi in zip(pts[1:], ys[1:], z[1:]):
                lines.append(f"G1 X{x:.2f} Y{y:.2f} Z{zi:.2f} F{opts.feed_draw:.0f}")
        else:
            lines.append(opts.pen_down_cmd)
            for (x, *_), y in zip(pts[1:], ys[1:]):
                lines.append(f"G1 X{x:.2f} Y{y:.2f} F{opts.feed_draw:.0f}")
        lines.append(opts.pen_up_cmd)
    lines += ["G0 X0 Y0", "; end"]
    return "\n".join(lines) + "\n"
