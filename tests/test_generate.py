import numpy as np

from nohandwrite.generate import render_style_image, seq_to_strokes


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
