"""G-code export for pen plotters.

Default dialect: servo pen lift on the spindle PWM pin (``M3 S40`` / ``M3
S90``), which is what the common GRBL kits ship with; set `pen_up_cmd` /
`pen_down_cmd` to ``G0 Z5.0`` / ``G1 Z0.0 F300`` for machines with a real Z
axis. Y is flipped so the text reads top-down on machines whose Y axis
points away from the operator.

A servo needs time to travel: `dwell_s` emits a ``G4`` pause after every pen
command so the pen is on (or off) the paper before the next move starts.
Set it to 0 on machines that move the pen with the Z axis.

Give `paper_w_mm` / `paper_h_mm` to anchor the output to the sheet: the
machine origin is then the bottom-left corner of the paper and the text
lands in the same place no matter how many lines it has. Without them the
origin is the bottom-left of the text block itself, so the position on the
paper shifts as the text grows.

With `pressure_z=True`, strokes that carry pressure data are drawn with the
Z axis modulated between `z_light` (pressure 0) and `z_heavy` (pressure 1),
so a soft pen presses harder where the writer did. This replaces the
pen-down command, so it only works on machines with a real Z axis; servo
machines keep the default `pressure_z=False`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .layout import LayoutOptions, layout_text


@dataclass
class GCodeOptions:
    layout: LayoutOptions = field(default_factory=LayoutOptions)
    feed_draw: float = 750.0       # mm/min while drawing
    feed_travel: float = 3000.0    # mm/min pen-up moves
    pen_up_cmd: str = "M3 S40"
    pen_down_cmd: str = "M3 S90"
    dwell_s: float = 0.25          # pause after each pen command (servo travel)
    flip_y: bool = True
    paper_w_mm: float | None = None   # anchor to the sheet instead of the
    paper_h_mm: float | None = None   # text block (see module docstring)
    end_cmds: tuple[str, ...] = ("M5", "M2")   # spindle/servo off, program end
    pressure_z: bool = False       # modulate Z with pen pressure
    z_light: float = 0.0           # Z at pressure 0 (lightest touch)
    z_heavy: float = -0.4          # Z at pressure 1
    z_feed: float = 300.0          # plunge feed for the pen-down move


def strokes_to_gcode(entries: list[dict], opts: GCodeOptions | None = None) -> str:
    opts = opts or GCodeOptions()
    placed, (w, h) = layout_text(entries, opts.layout)
    dwell = f"G4 P{opts.dwell_s:.2f}" if opts.dwell_s > 0 else None
    # Y is measured down from the top of the reference box; flipping against
    # the paper height (when known) keeps the text in one spot on the sheet.
    ref_h = opts.paper_h_mm if opts.paper_h_mm else h

    lines = [
        "; NoHandWrite pen plotter output",
        f"; text block: {w:.1f} x {h:.1f} mm, {len(placed)} strokes",
    ]
    if opts.paper_w_mm and opts.paper_h_mm:
        lines.append(f"; paper: {opts.paper_w_mm:.1f} x {opts.paper_h_mm:.1f} mm"
                     " -- set machine zero at its bottom-left corner")
        if w > opts.paper_w_mm + 1e-6 or h > opts.paper_h_mm + 1e-6:
            lines.append("; WARNING: text block is larger than the paper")
    else:
        lines.append("; origin: bottom-left of the text block"
                     " (position on the paper shifts with the line count)")
    lines += [
        "G21 ; mm",
        "G90 ; absolute",
        "G94 ; feed in units/min",
        opts.pen_up_cmd,
    ]
    if dwell:
        lines.append(dwell)

    for p in placed:
        pts = p.points
        ys = (ref_h - pts[:, 1]) if opts.flip_y else pts[:, 1]
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
            if dwell:
                lines.append(dwell)
            for (x, *_), y in zip(pts[1:], ys[1:]):
                lines.append(f"G1 X{x:.2f} Y{y:.2f} F{opts.feed_draw:.0f}")
        lines.append(opts.pen_up_cmd)
        if dwell:
            lines.append(dwell)
    lines.append("G0 X0 Y0")
    lines += list(opts.end_cmds)
    lines.append("; end")
    return "\n".join(lines) + "\n"
