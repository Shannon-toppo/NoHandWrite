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
                         max_width_mm=None, proportional=False)
    entries = [char_entry("a"), {"char": "\n"}, {"char": " ", "strokes": None}, char_entry("b")]
    placed, _ = layout_text(entries, opts)
    a = [p for p in placed if p.char == "a"][0]
    b = [p for p in placed if p.char == "b"][0]
    assert b.points[:, 1].min() >= a.points[:, 1].min() + 10   # next line
    assert b.points[:, 0].min() >= 10                           # after the blank

def test_layout_proportional_advance():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=None, simplify_mm=0)
    narrow = {"char": "i", "strokes": [np.array([[480, 0], [520, 1000]], dtype=float)]}
    wide = {"char": "w", "strokes": [np.array([[0, 0], [1000, 300]], dtype=float)]}
    placed, (w, _) = layout_text([narrow, wide, narrow], opts)
    # each glyph's left ink edge lands on the pen; advance = its ink width
    assert abs(placed[0].points[:, 0].min() - 0.0) < 1e-9
    assert abs(placed[1].points[:, 0].min() - 0.4) < 1e-9    # after narrow (40/1000*10)
    assert abs(placed[2].points[:, 0].min() - 10.4) < 1e-9   # after wide (full box)
    assert abs(w - 10.8) < 1e-9


def test_layout_proportional_ascii_space():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=None, simplify_mm=0)
    narrow = {"char": "i", "strokes": [np.array([[480, 0], [520, 1000]], dtype=float)]}
    placed, _ = layout_text([{"char": " ", "strokes": None}, narrow], opts)
    assert abs(placed[0].points[:, 0].min() - 4.0) < 1e-9    # 0.4 of a 10mm cell


def test_layout_vertical_columns_right_to_left():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=None, simplify_mm=0,
                         proportional=False, vertical=True)
    entries = [char_entry("a"), char_entry("b"), {"char": "\n"}, char_entry("c")]
    placed, (w, h) = layout_text(entries, opts)
    a = [p for p in placed if p.char == "a"][0]
    b = [p for p in placed if p.char == "b"][0]
    c = [p for p in placed if p.char == "c"][0]
    assert b.points[:, 1].min() >= a.points[:, 1].min() + 10   # b below a
    assert c.points[:, 0].max() <= a.points[:, 0].max() - 9    # new column left
    assert abs(c.points[:, 1].min() - a.points[:, 1].min()) < 1e-9  # top again
    assert w >= 20 and h >= 20


def test_layout_vertical_wraps_at_max_length():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=25, simplify_mm=0,
                         proportional=False, vertical=True)
    placed, _ = layout_text([char_entry(c) for c in "abc"], opts)
    c = [p for p in placed if p.char == "c"][0]
    a = [p for p in placed if p.char == "a"][0]
    assert abs(c.points[:, 1].min() - a.points[:, 1].min()) < 1e-9  # wrapped to top
    assert c.points[:, 0].max() < a.points[:, 0].max()              # next column


def test_layout_vertical_proportional_advance():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=None, simplify_mm=0,
                         vertical=True)
    short = {"char": "一", "strokes": [np.array([[0, 480], [1000, 520]], dtype=float)]}
    tall = {"char": "l", "strokes": [np.array([[480, 0], [520, 1000]], dtype=float)]}
    placed, _ = layout_text([short, tall], opts)
    # short glyph's ink lands at the pen (y=0) and advances only its height
    assert abs(placed[0].points[:, 1].min() - 0.0) < 1e-9
    assert abs(placed[1].points[:, 1].min() - 0.4) < 1e-9


def test_layout_vertical_glyph_adjustments():
    opts = LayoutOptions(char_size_mm=10, char_gap_mm=0, line_gap_mm=0,
                         margin_mm=0, max_width_mm=None, simplify_mm=0,
                         proportional=False, vertical=True)
    dash = {"char": "ー", "strokes": [np.array([[0, 480], [1000, 520]], dtype=float)]}
    ten = {"char": "、", "strokes": [np.array([[50, 800], [200, 950]], dtype=float)]}
    placed, _ = layout_text([dash, ten], opts)
    d, t = placed[0].points, placed[1].points
    # ー rotates to a vertical bar (taller than wide)
    assert (d[:, 1].max() - d[:, 1].min()) > (d[:, 0].max() - d[:, 0].min())
    # 、moves to the top right of its (second) cell
    assert t[:, 0].min() > 5 and t[:, 1].max() < 10 + 5


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
