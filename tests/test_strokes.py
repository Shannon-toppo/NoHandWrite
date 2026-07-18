import numpy as np
import pytest

from nohandwrite.strokes import (
    CharacterData, Sample, normalize_strokes, normalize_to_field,
    resample_stroke, stroke_length,
)
from nohandwrite.store import Store


def square_stroke():
    return np.array([[0, 0, 0, 0.5], [10, 0, 10, 0.5], [10, 20, 20, 0.5]], dtype=float)


def test_normalize_preserves_aspect():
    out = normalize_strokes([square_stroke()], size=1000)
    pts = out[0]
    # taller than wide (10 x 20) -> y spans full range, x centered
    assert pts[:, 1].min() == pytest.approx(0)
    assert pts[:, 1].max() == pytest.approx(1000)
    width = pts[:, 0].max() - pts[:, 0].min()
    assert width == pytest.approx(500)
    center = (pts[:, 0].max() + pts[:, 0].min()) / 2
    assert center == pytest.approx(500)
    # t/p untouched
    assert list(pts[:, 3]) == [0.5, 0.5, 0.5]


def test_normalize_to_field_keeps_size_and_position():
    # a small mark in the bottom-left of a 450px field (like 。)
    dot = np.array([[40, 380, 0, 0.5], [80, 420, 10, 0.5]], dtype=float)
    out = normalize_to_field([dot], canvas=(450, 450))[0]
    scale = 1000 / 450
    assert out[0, 0] == pytest.approx(40 * scale)
    assert out[1, 1] == pytest.approx(420 * scale)
    # stays small: ~89 units, not blown up to the full box
    assert (out[1, 0] - out[0, 0]) == pytest.approx(40 * scale)


def test_resample_equal_spacing():
    s = resample_stroke(square_stroke(), 31)
    assert s.shape == (31, 4)
    d = np.diff(s[:, :2], axis=0)
    seg = np.hypot(d[:, 0], d[:, 1])
    assert np.allclose(seg, seg[0], atol=1e-9)
    assert stroke_length(s) == pytest.approx(30.0)


def test_resample_dot():
    dot = np.array([[5, 5, 0, 1.0]])
    s = resample_stroke(dot, 8)
    assert s.shape == (8, 4)
    assert np.allclose(s[:, 0], 5)


def test_store_round_trip(tmp_path):
    store = Store(tmp_path)
    sample = Sample(strokes=[square_stroke()], canvas=(450, 450), device="test")
    store.add_sample("alice", "木", sample)
    store.add_sample("alice", "木", sample)
    data = store.load_character("alice", "木")
    assert data is not None
    assert data.char == "木" and len(data.samples) == 2
    assert np.allclose(data.samples[0].strokes[0], square_stroke())
    assert store.summary("alice") == {"木": 2}

    store.delete_last_sample("alice", "木")
    assert store.summary("alice") == {"木": 1}
    store.delete_last_sample("alice", "木")
    assert store.summary("alice") == {}


def test_store_rejects_bad_writer(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        store.add_sample("../evil", "木", Sample(strokes=[square_stroke()]))


def test_character_json_round_trip():
    data = CharacterData(char="あ", writer="w1",
                         samples=[Sample(strokes=[square_stroke()])])
    back = CharacterData.from_json(data.to_json())
    assert back.char == "あ"
    assert back.codepoint == "U+3042"
    assert np.allclose(back.samples[0].strokes[0], square_stroke())
