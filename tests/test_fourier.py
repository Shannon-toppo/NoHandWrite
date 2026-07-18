import numpy as np
import pytest

from nohandwrite.beautify import beautify
from nohandwrite.fourier import (
    analyze_stroke, auto_truncation_order, average_character,
    filter_matching_samples, smooth_stroke,
)
from nohandwrite.strokes import CharacterData, Sample


def circle(n=100, r=200.0, cx=500.0, cy=500.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    th = np.linspace(0, 2 * np.pi, n)
    x = cx + r * np.cos(th) + rng.normal(0, noise, n)
    y = cy + r * np.sin(th) + rng.normal(0, noise, n)
    return np.stack([x, y, np.linspace(0, 1000, n), np.full(n, 0.5)], axis=1)


def zigzag(n=60, offset=0.0):
    x = np.linspace(100, 900, n)
    y = 500 + 150 * np.sign(np.sin(x / 80.0)) + offset
    return np.stack([x, y, np.linspace(0, 500, n), np.zeros(n)], axis=1)


def test_reconstruction_converges():
    s = circle()
    series = analyze_stroke(s, order=32)
    rec = series.reconstruct(100)
    err = np.hypot(*(rec[:, :2] - s[:, :2]).T)
    assert err.mean() < 8.0  # tight fit on the 0-1000 scale


def test_smooth_stroke_keeps_pressure():
    out = smooth_stroke(circle())               # constant pressure 0.5
    assert out.shape[1] == 3
    np.testing.assert_allclose(out[:, 2], 0.5, atol=0.02)
    # strokes without a pressure column come back with pressure 0
    out = smooth_stroke(circle()[:, :2])
    assert np.all(out[:, 2] == 0.0)


def test_average_averages_pressure():
    a = [circle()]                              # p = 0.5
    b = [circle()]
    b[0][:, 3] = 0.9
    avg = average_character([a, b])
    np.testing.assert_allclose(avg[0][:, 2], 0.7, atol=0.02)


def test_truncation_smooths_noise():
    noisy = circle(noise=6.0)
    smoothed = smooth_stroke(noisy)
    clean = circle()
    # distance from the smoothed curve to the ideal circle radius
    r = np.hypot(smoothed[:, 0] - 500, smoothed[:, 1] - 500)
    assert abs(r.mean() - 200) < 5
    assert r.std() < np.hypot(noisy[:, 0] - 500, noisy[:, 1] - 500).std()


def test_auto_truncation_reasonable():
    series = analyze_stroke(circle(), order=64)
    order = auto_truncation_order(series)
    assert 1 <= order < 64


def test_average_of_translated_strokes_is_midpoint():
    a = [circle(cx=480.0)]
    b = [circle(cx=520.0)]
    avg = average_character([a, b])
    assert len(avg) == 1
    cx = avg[0][:, 0].mean()
    assert cx == pytest.approx(500.0, abs=2.0)


def test_average_corrects_reversed_direction():
    fwd = [zigzag()]
    rev = [zigzag(offset=20.0)[::-1].copy()]
    avg = average_character([fwd, rev])
    y = avg[0][:, 1]
    # if the reversed stroke were not flipped, averaging would collapse the
    # zigzag toward a flat line; corrected averaging keeps the amplitude
    assert y.max() - y.min() > 200


def test_filter_matching_samples():
    two = [zigzag(), zigzag()]
    three = [zigzag(), zigzag(), zigzag()]
    kept, count = filter_matching_samples([two, three, two])
    assert count == 2 and len(kept) == 2


def test_beautify_modes():
    single = CharacterData(char="一", writer="w",
                           samples=[Sample(strokes=[zigzag()])])
    r = beautify(single)
    assert r.mode == "smooth" and r.used_samples == 1

    multi = CharacterData(char="一", writer="w",
                          samples=[Sample(strokes=[zigzag()]),
                                   Sample(strokes=[zigzag(offset=30.0)])])
    r = beautify(multi)
    assert r.mode == "average" and r.used_samples == 2
    body = r.to_json()
    assert body["strokeCount"] == 1
    assert len(body["strokes"][0]) > 10


def test_beautify_keeps_small_characters_small():
    # 。-like small mark in the bottom-left of a 450px field
    arc = np.stack([60 + 30 * np.cos(np.linspace(0, 2 * np.pi, 40)),
                    390 + 30 * np.sin(np.linspace(0, 2 * np.pi, 40)),
                    np.linspace(0, 200, 40), np.full(40, 0.5)], axis=1)
    data = CharacterData(char="。", writer="w",
                         samples=[Sample(strokes=[arc.copy()], canvas=(450, 450)),
                                  Sample(strokes=[arc + [4, -3, 0, 0]], canvas=(450, 450))])
    r = beautify(data)
    pts = np.concatenate(r.strokes)
    width = pts[:, 0].max() - pts[:, 0].min()
    assert width < 250                      # not blown up to the full box
    assert pts[:, 1].mean() > 700           # stays in the lower part
    assert pts[:, 0].mean() < 300           # …and on the left
