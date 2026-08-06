import numpy as np

from nohandwrite.generate import (
    Generated, SDTGenerator, content_similarity, decode_sequence,
    expected_strokes, render_style_image, seq_to_strokes,
)
from nohandwrite.generate.sdt_adapter import MIN_STROKE_RATIO, SCORE_OK


def test_render_style_image_matches_dataset_format():
    stroke = np.array([[0, 500, 0, 0], [1000, 500, 100, 0.5]], dtype=float)
    vert = np.array([[500, 0, 200, 0], [500, 1000, 300, 0.5]], dtype=float)
    img = render_style_image([stroke, vert])
    assert img.shape == (64, 64) and img.dtype == np.uint8
    assert img.max() == 255                    # white background
    dark = (img < 128).mean()
    assert 0.01 < dark < 0.2                    # thin dark lines


def test_seq_to_strokes_splits_and_accumulates():
    seq = np.array([
        [0, 0, 1, 0, 0],       # SOS (pen down at origin)
        [10, 0, 1, 0, 0],
        [10, 0, 0, 1, 0],      # pen up -> stroke 1 ends here
        [0, 20, 1, 0, 0],
        [5, 5, 1, 0, 0],
        [0, 0, 0, 0, 1],       # end of character
        [99, 99, 1, 0, 0],     # garbage after EOS must be ignored
    ], dtype=float)
    strokes = seq_to_strokes(seq)
    assert len(strokes) == 2
    assert np.allclose(strokes[0], [[0, 0], [10, 0], [20, 0]])
    assert np.allclose(strokes[1], [[20, 20], [25, 25]])


def test_decode_sequence_flags_truncation():
    rows = [[0, 0, 1, 0, 0], [10, 0, 1, 0, 0], [10, 0, 0, 1, 0],
            [0, 20, 1, 0, 0], [5, 5, 1, 0, 0]]
    strokes, completed = decode_sequence(np.array(rows, dtype=float))
    assert not completed                        # ran out with no s3
    assert len(strokes) == 2                    # the open stroke is kept as-is

    finished = np.array(rows + [[0, 0, 0, 0, 1]], dtype=float)
    strokes, completed = decode_sequence(finished)
    assert completed and len(strokes) == 2


def cross(size=1000.0):
    """A + shape, as normalized strokes."""
    return [np.array([[0.1 * size, 0.5 * size], [0.9 * size, 0.5 * size]]),
            np.array([[0.5 * size, 0.1 * size], [0.5 * size, 0.9 * size]])]


def test_content_similarity_rewards_the_matching_shape():
    content = render_style_image(cross(), width=8)     # stand-in for a font glyph
    same = content_similarity(cross(), content)
    # one arm missing is what truncation looks like: recall drops
    partial = content_similarity(cross()[:1], content)
    other = content_similarity([np.array([[0.0, 0.0], [1000.0, 1000.0]])], content)
    assert same > 0.9
    assert partial < same - 0.2
    assert other < 0.5


def test_content_similarity_handles_flat_glyphs():
    """一-like glyphs must align to the reference box on both axes, or a
    perfectly good horizontal bar scores zero."""
    bar = [np.array([[0.0, 500.0], [1000.0, 500.0]])]
    content = render_style_image(bar, width=8)
    assert content_similarity(bar, content) > 0.9


def test_expected_strokes_table():
    assert expected_strokes("一") == 1
    assert expected_strokes("鬱") > 20            # long-trajectory kanji
    assert expected_strokes("") is None     # not in the TUAT data


def make(char="鬱", completed=True, score=0.9, n=30, expected=30):
    return Generated(char=char, strokes=[np.zeros((2, 2))], completed=completed,
                     score=score, n_strokes=n, expected_strokes=expected)


def test_generated_quality_flags():
    assert make().ok
    assert not make(completed=False).ok                         # cut off
    assert not make(score=SCORE_OK - 0.01).ok                   # unlike the glyph
    assert not make(n=int(MIN_STROKE_RATIO * 30) - 1).ok        # too few strokes
    assert make(n=1, expected=None).ok                          # no reference
    # a finished candidate outranks a truncated one that scored higher
    assert make(score=0.7).rank > make(completed=False, score=0.95).rank


class FakeGenerator(SDTGenerator):
    """SDTGenerator with the model swapped out for a canned attempt list."""

    def __init__(self, attempts_out):
        super().__init__()
        self.attempts_out = attempts_out
        self.calls = []
        self.style_draws = 0

    def supports(self, char):
        return char in "AB"

    def build_style_batch(self, style_strokes, rng=None):
        self.style_draws += 1
        return np.zeros((1, 64, 64), dtype=np.float32)

    def _run(self, style, chars, batch_size):
        self.calls.append("".join(chars))
        return self.attempts_out[len(self.calls) - 1]


def test_generate_retries_only_the_bad_characters():
    g = FakeGenerator([
        {"A": make("A", score=0.9), "B": make("B", completed=False)},
        {"B": make("B", score=0.8)},
    ])
    out = g.generate([[np.zeros((2, 2))]], "ABZ", attempts=3)
    assert g.calls == ["AB", "B"]          # A was fine; Z isn't supported
    assert out["A"].score == 0.9
    assert out["B"].completed and out["B"].score == 0.8
    assert "Z" not in out


def test_generate_keeps_the_best_of_the_attempts():
    g = FakeGenerator([{"A": make("A", score=0.30)},
                       {"A": make("A", score=0.55)},
                       {"A": make("A", score=0.40)}])
    out = g.generate([[np.zeros((2, 2))]], "A", attempts=3)
    assert g.calls == ["A", "A", "A"]      # never good enough, so it used them all
    assert out["A"].score == 0.55          # best candidate wins
    # SDT decodes deterministically, so a retry is only a new attempt if the
    # style references are drawn again
    assert g.style_draws == 3


def test_style_batch_draw_varies():
    """Two draws from a writer with plenty of characters differ — otherwise
    retrying would just reproduce the same glyph."""
    g = SDTGenerator()
    strokes = [[np.array([[0.0, float(i)], [1000.0, 1000.0 - i]])] for i in range(40)]
    rng = np.random.default_rng(1)
    a = g.build_style_batch(strokes, rng)
    b = g.build_style_batch(strokes, rng)
    assert a.shape == b.shape and not np.array_equal(a, b)
