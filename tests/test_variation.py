"""Tests for per-instance handwriting variation (jitter_strokes)."""
import numpy as np

from nohandwrite.variation import char_category, jitter_strokes


def _sample_char():
    t = np.linspace(0, 1, 50)
    s1 = np.stack([200 + 600 * t, 300 + 100 * np.sin(3 * t)], axis=1)
    s2 = np.stack([500 + 50 * np.cos(2 * t), 100 + 800 * t], axis=1)
    return [s1, s2]


def test_shapes_and_input_untouched():
    strokes = _sample_char()
    before = [s.copy() for s in strokes]
    out = jitter_strokes(strokes)
    assert len(out) == len(strokes)
    for o, s, b in zip(out, strokes, before):
        assert o.shape == s.shape
        np.testing.assert_array_equal(s, b)


def test_two_calls_differ():
    strokes = _sample_char()
    a = jitter_strokes(strokes)
    b = jitter_strokes(strokes)
    assert any(not np.allclose(x, y) for x, y in zip(a, b))


def test_deviation_is_small():
    strokes = _sample_char()
    rng = np.random.default_rng(0)
    for _ in range(20):
        out = jitter_strokes(strokes, rng)
        for o, s in zip(out, strokes):
            # letterform preserved: every point moves, but only slightly
            assert np.hypot(*(o - s).T).max() < 50  # 5% of the 1000 box
    # seeded rng is deterministic
    a = jitter_strokes(strokes, np.random.default_rng(7))
    b = jitter_strokes(strokes, np.random.default_rng(7))
    for x, y in zip(a, b):
        np.testing.assert_allclose(x, y)


def test_strength_zero_is_identity():
    strokes = _sample_char()
    out = jitter_strokes(strokes, strength=0.0)
    for o, s in zip(out, strokes):
        np.testing.assert_array_equal(o, s[:, :2])


def test_char_category():
    assert char_category("あ") == "hiragana"
    assert char_category("ゖ") == "hiragana"
    assert char_category("ア") == "katakana"
    assert char_category("ヶ") == "katakana"
    assert char_category("ｱ") == "katakana"
    assert char_category("木") == "kanji"
    assert char_category("々") == "kanji"
    assert char_category("A") == "alnum"
    assert char_category("7") == "alnum"
    assert char_category("Ａ") == "alnum"
    assert char_category("７") == "alnum"
    assert char_category("、") == "other"
    assert char_category("「") == "other"
    assert char_category("!") == "other"


def test_accepts_nested_lists():
    strokes = [s.tolist() for s in _sample_char()]
    out = jitter_strokes(strokes)
    assert all(isinstance(o, np.ndarray) and o.shape[1] == 2 for o in out)
