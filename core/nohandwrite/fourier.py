"""Fourier-series representation of strokes and average characters.

Implements the method of Nakamura et al., "平均文字は美しい" (EC2014):
each stroke is a parametric plane curve (x, y) = (f1(t), f2(t)) expanded as a
Fourier series; averaging the series coefficients of several writings of the
same character yields the "average character".

A pen stroke is an open curve, so treating it directly as 2π-periodic leaves a
jump between its endpoints and the truncated series rings badly (Gibbs). We
therefore use the even (cosine) extension: the stroke is parameterized on
[0, π], mirrored onto [-π, 0], which makes the periodic extension continuous.
Only cosine coefficients remain, and reconstruction evaluates t in [0, π].

Strokes are resampled to equal arc-length spacing before analysis, so the
discrete coefficient sums approximate the paper's integrals.

Pen pressure rides along as a third coordinate: it is expanded, averaged and
truncated exactly like x and y (the truncation order is still chosen from the
geometry alone), so the average character keeps an averaged pressure profile.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .strokes import resample_stroke

DEFAULT_SAMPLES = 256          # points per stroke used for analysis/rendering
MAX_ORDER = 96
# The paper truncates at order n when the mean pointwise gap between the
# order-n and order-(n+1) reconstructions is <= 2 px (360 px canvas).
# Scaled to our 0–1000 standard box that is ~5.6 units; we default a bit
# stricter.
DEFAULT_TRUNCATION_THRESHOLD = 4.0


@dataclass
class StrokeSeries:
    """Truncated cosine series of one stroke.

    a[c, 0] is the constant term; a[c, n] the cos(nt) coefficient for
    coordinate c (0=x, 1=y, 2=pressure).
    """
    a: np.ndarray  # (3, order + 1)

    @property
    def order(self) -> int:
        return self.a.shape[1] - 1

    def truncated(self, order: int) -> "StrokeSeries":
        return StrokeSeries(self.a[:, :min(order, self.order) + 1].copy())

    def reconstruct(self, num_points: int = DEFAULT_SAMPLES) -> np.ndarray:
        """Evaluate the series at `num_points` values of t in [0, π] -> (N, C)."""
        t = np.linspace(0.0, np.pi, num_points)
        n = np.arange(self.order + 1)[:, None]          # (order+1, 1)
        cos = np.cos(n * t)                              # (order+1, N)
        return (self.a @ cos).T


def analyze_stroke(stroke: np.ndarray, order: int = MAX_ORDER,
                   num_samples: int = DEFAULT_SAMPLES) -> StrokeSeries:
    """Cosine-series coefficients of a stroke's (x, y, p) columns up to `order`.

    Accepts (N, 2) x,y; (N, 3) x,y,p; or (N, 4) x,y,t,p rows — missing
    pressure becomes 0. The stroke is resampled to equal arc-length spacing
    and parameterized uniformly on [0, π]; coefficients of the even extension
    are a_n = (2/π) ∫_0^π f(t) cos(nt) dt (a_0 halved into the constant term).
    """
    res = resample_stroke(stroke, num_samples)
    if res.shape[1] >= 4:
        pts = res[:, [0, 1, 3]]                          # (x, y, t, p) rows
    elif res.shape[1] == 3:
        pts = res
    else:
        pts = np.concatenate([res, np.zeros((len(res), 1))], axis=1)
    n_pts = pts.shape[0]
    t = np.linspace(0.0, np.pi, n_pts)
    dt = np.pi / (n_pts - 1)
    w = np.full(n_pts, dt)                               # trapezoid weights
    w[0] = w[-1] = dt / 2
    orders = np.arange(order + 1)[:, None]               # (order+1, 1)
    cos = np.cos(orders * t)                             # (order+1, N)
    f = pts.T * w                                        # (3, N) weighted
    a = 2.0 * (f @ cos.T) / np.pi                        # (3, order+1)
    a[:, 0] /= 2.0                                       # constant term a0/2
    return StrokeSeries(a)


def auto_truncation_order(series: StrokeSeries,
                          threshold: float = DEFAULT_TRUNCATION_THRESHOLD,
                          num_points: int = DEFAULT_SAMPLES) -> int:
    """Smallest order n where the reconstruction has converged.

    The paper's rule is "mean gap between order n and n+1 <= threshold"; we
    require it for two consecutive steps, since spectra with missing harmonics
    (e.g. only odd orders present) make a single small step meaningless.
    """
    prev = series.truncated(1).reconstruct(num_points)
    small_steps = 0
    for n in range(1, series.order):
        nxt = series.truncated(n + 1).reconstruct(num_points)
        gap = np.hypot(*(nxt - prev)[:, :2].T).mean()    # geometry only
        small_steps = small_steps + 1 if gap <= threshold else 0
        if small_steps >= 2:
            return n - 1
        prev = nxt
    return series.order


def smooth_stroke(stroke: np.ndarray,
                  threshold: float = DEFAULT_TRUNCATION_THRESHOLD,
                  num_points: int = DEFAULT_SAMPLES) -> np.ndarray:
    """Beautify a single stroke: analyze, auto-truncate, reconstruct.

    Returns (N, 3) rows of x, y, pressure (pressure clipped to [0, 1])."""
    series = analyze_stroke(stroke)
    order = auto_truncation_order(series, threshold)
    out = series.truncated(order).reconstruct(num_points)
    out[:, 2] = np.clip(out[:, 2], 0.0, 1.0)
    return out


def _maybe_reverse(stroke: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Flip a stroke when it was written in the opposite direction of `reference`
    (the paper corrects such samples by reversing the parameterization)."""
    fwd = (np.linalg.norm(stroke[0, :2] - reference[0, :2])
           + np.linalg.norm(stroke[-1, :2] - reference[-1, :2]))
    rev = (np.linalg.norm(stroke[-1, :2] - reference[0, :2])
           + np.linalg.norm(stroke[0, :2] - reference[-1, :2]))
    return stroke[::-1] if rev < fwd else stroke


def average_character(samples: list[list[np.ndarray]],
                      threshold: float = DEFAULT_TRUNCATION_THRESHOLD,
                      num_points: int = DEFAULT_SAMPLES) -> list[np.ndarray]:
    """Average character from several writings (lists of strokes).

    All samples must have the same stroke count (filter first with
    `filter_matching_samples`). Per stroke: coefficients of every sample are
    averaged, then the averaged series is truncated at the order chosen for it
    and reconstructed. Returns a list of (num_points, 3) arrays of x, y,
    pressure (pressure clipped to [0, 1]).
    """
    if not samples:
        raise ValueError("no samples")
    counts = {len(s) for s in samples}
    if len(counts) != 1:
        raise ValueError(f"stroke counts differ: {sorted(counts)}")
    n_strokes = counts.pop()
    result = []
    for i in range(n_strokes):
        ref = samples[0][i]
        series_list = [analyze_stroke(_maybe_reverse(s[i], ref)) for s in samples]
        mean = StrokeSeries(a=np.mean([sr.a for sr in series_list], axis=0))
        order = auto_truncation_order(mean, threshold)
        rec = mean.truncated(order).reconstruct(num_points)
        rec[:, 2] = np.clip(rec[:, 2], 0.0, 1.0)
        result.append(rec)
    return result


def filter_matching_samples(samples: list[list[np.ndarray]]) -> tuple[list[list[np.ndarray]], int]:
    """Keep only samples with the majority stroke count.

    Returns (kept_samples, stroke_count). Ties resolve to the smaller count.
    """
    if not samples:
        return [], 0
    counts = [len(s) for s in samples]
    values, freqs = np.unique(counts, return_counts=True)
    majority = int(values[np.argmax(freqs)])
    kept = [s for s in samples if len(s) == majority]
    return kept, majority
