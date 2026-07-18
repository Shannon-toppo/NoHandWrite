"""Per-instance handwriting variation ("ゆらぎ").

The beautify/generate pipelines are deterministic, so the same character
rendered twice is pixel-identical — which reads as machine-made. This module
perturbs a character's strokes slightly (identical letterform, different
instance): a small random affine transform of the whole character plus a
smooth low-frequency wobble per stroke. Amplitudes are relative to the
0–1000 standard box and stay well below what would change the glyph.
"""
from __future__ import annotations

import numpy as np

from .strokes import STANDARD_SIZE

#: Categories used for per-script jitter strength settings.
CATEGORIES = ("hiragana", "katakana", "kanji", "alnum", "other")


def char_category(c: str) -> str:
    """Script category of a character: hiragana / katakana / kanji /
    alnum (ASCII + fullwidth letters and digits) / other (symbols etc.)."""
    o = ord(c)
    if 0x3041 <= o <= 0x309F:
        return "hiragana"
    if 0x30A0 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
        return "katakana"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or o == 0x3005:  # 々
        return "kanji"
    if (c.isascii() and c.isalnum()) or 0xFF10 <= o <= 0xFF19 \
            or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
        return "alnum"
    return "other"


# Standard deviations at strength 1.0
_ROTATION_SD_DEG = 0.8
_SCALE_SD = 0.015          # per-axis
_OFFSET_SD = 0.006         # fraction of the box size
_WOBBLE_SD = 0.004         # fraction of the box size, per harmonic
_WOBBLE_HARMONICS = 3


def jitter_strokes(strokes: list, rng: np.random.Generator | None = None,
                   strength: float = 1.0,
                   size: float = STANDARD_SIZE) -> list[np.ndarray]:
    """Return a slightly perturbed copy of a character's strokes.

    `strokes` is a list of (N, >=2) arrays or nested lists; only x/y are
    perturbed, extra columns (e.g. pressure) pass through unchanged.
    `strength` scales all amplitudes (0 disables). Each call with a fresh
    (or advanced) `rng` yields a different instance of the same letterform.
    """
    arrs = [np.asarray(s, dtype=float) for s in strokes]
    if strength <= 0 or not arrs:
        return [a.copy() for a in arrs]
    rng = rng if rng is not None else np.random.default_rng()

    center = np.concatenate([a[:, :2] for a in arrs]).mean(axis=0)
    angle = np.deg2rad(rng.normal(0.0, _ROTATION_SD_DEG)) * strength
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    scale = 1.0 + rng.normal(0.0, _SCALE_SD, 2) * strength
    offset = rng.normal(0.0, _OFFSET_SD * size, 2) * strength

    out = []
    for a in arrs:
        p = ((a[:, :2] - center) * scale) @ rot.T + center + offset
        t = np.linspace(0.0, np.pi, len(p))
        for k in range(1, _WOBBLE_HARMONICS + 1):
            amp = rng.normal(0.0, _WOBBLE_SD * size / k, 2) * strength
            phase = rng.uniform(0.0, 2.0 * np.pi)
            p = p + amp * np.cos(k * t + phase)[:, None]
        r = a.copy()
        r[:, :2] = p
        out.append(r)
    return out
