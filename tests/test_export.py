import numpy as np

from nohandwrite.export import (
    GCodeOptions, LayoutOptions, layout_text, strokes_to_gcode, strokes_to_svg,
)


def char_entry(char="木", n_strokes=2):
    strokes = [np.array([[0, 0], [500, 500], [1000, 1000]], dtype=float) + i * 10
               for i in range(n_strokes)]
    return {"char": char, "strokes": strokes}


def test_layout_places_and_wraps():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         max_width_mm=25, margin_mm=0)
    entries = [char_entry(c) for c in "abc"]  # 3 chars, 10mm each, wrap at 25
    placed, (w, h) = layout_text(entries, opts)
    assert len(placed) == 6
    # third char wraps to second line
    assert placed[4].points[:, 1].min() >= 10
    assert h >= 20


def test_layout_newline_and_blank():
    opts = LayoutOptions(char_size_mm=10, margin_mm=0, char_gap_mm=0, line_gap_mm=0,
                         max_width_mm=None)
    entries = [char_entry("a"), {"char": "\n"}, {"char": " ", "strokes": None}, char_entry("b")]
    placed, _ = layout_text(entries, opts)
    a = [p for p in placed if p.char == "a"][0]
    b = [p for p in placed if p.char == "b"][0]
    assert b.points[:, 1].min() >= a.points[:, 1].min() + 10   # next line
    assert b.points[:, 0].min() >= 10                           # after the blank

def test_svg_output():
    svg = strokes_to_svg([char_entry(n_strokes=3)])
    assert svg.count("<path") == 3
    assert 'viewBox="0 0' in svg and "mm" in svg
    assert "fill=\"none\"" in svg


def test_gcode_output():
    g = strokes_to_gcode([char_entry(n_strokes=2)],
                         GCodeOptions(pen_up_cmd="M3 S40", pen_down_cmd="M3 S90"))
    assert g.count("M3 S90") == 2                # one pen-down per stroke
    assert g.count("M3 S40") == 3                # initial + one per stroke
    assert "G21" in g and "G90" in g
    assert "G0 X" in g and "G1 X" in g
