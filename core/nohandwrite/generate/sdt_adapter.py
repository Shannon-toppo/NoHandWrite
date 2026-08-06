"""Adapter around the vendored SDT model (third_party/SDT).

Turns the user's captured strokes into SDT style-reference images, runs the
pretrained Japanese checkpoint, and converts the predicted (dx, dy, pen-state)
sequences back into stroke arrays in our standard 0–1000 box.

SDT's row format is (dx, dy, s1, s2, s3): s1 = pen down, s2 = last point of a
stroke (pen up), s3 = end of character.

Long-trajectory characters (鬱・鑑・驚 …) sometimes run past `MAX_SEQ_LEN`
without ever emitting s3, and the result is a glyph missing its tail. Every
candidate is therefore scored against the content image and, when it looks
bad, generated again from a different draw of style references — see
`Generated` and `generate()`.

Note that SDT's decoding is *deterministic*: `get_seq_from_gmm` takes the
argmax mixture and the argmax pen state rather than sampling, so the same
style images and content image always give the same trajectory. Redrawing
the style references is what makes a retry a genuinely new attempt.
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..metrics import place_glyph
from ..strokes import STANDARD_SIZE, bounding_box, normalize_strokes

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
SDT_ROOT = REPO / "third_party" / "SDT"
DATA_DIR = SDT_ROOT / "data" / "TUATHANDS_JAPANESE"
DEFAULT_CKPT = SDT_ROOT / "model_zoo" / "saved_weights" / "Japanese" / "checkpoint-iter147999.pth"
STROKE_COUNTS = Path(__file__).with_name("stroke_counts.json")

NUM_STYLE_IMGS = 15   # matches MODEL.NUM_IMGS of the Japanese config
IMG_SIZE = 64
#: Decoding stops early on s3, so a generous cap only costs time on the
#: characters that need it. Training filtered trajectories at 150 points,
#: so anything past that is outside the checkpoint's experience.
MAX_SEQ_LEN = 200

#: How many times a character may be generated before we take what we have.
DEFAULT_ATTEMPTS = 3
#: Content-image similarity (see `content_similarity`) a candidate needs to
#: be accepted without another attempt. Clean output over a 58-character
#: sample ran 0.55–1.00 (median 0.81), so this retries roughly the worst
#: tenth — mostly かな and low-stroke kanji, where handwriting legitimately
#: departs from the 明朝 content image.
SCORE_OK = 0.65
#: A candidate with fewer than this fraction of the expected strokes is
#: retried even if it finished cleanly.
MIN_STROKE_RATIO = 0.6


@dataclass(frozen=True)
class Generated:
    """One generated character plus the evidence for whether it worked."""

    char: str
    strokes: list[np.ndarray]      # placed in the 0–1000 box
    completed: bool                # the model emitted end-of-character (s3)
    score: float                   # content-image similarity, 0–1
    n_strokes: int
    expected_strokes: int | None   # median over TUAT writers, None if unknown

    @property
    def enough_strokes(self) -> bool:
        if not self.expected_strokes:
            return True
        return self.n_strokes >= MIN_STROKE_RATIO * self.expected_strokes

    @property
    def ok(self) -> bool:
        return self.completed and self.enough_strokes and self.score >= SCORE_OK

    @property
    def rank(self) -> float:
        """Single number for picking the best of several attempts."""
        r = self.score
        if not self.completed:
            r -= 0.5
        if self.expected_strokes:
            r -= 0.3 * max(0.0, 1 - self.n_strokes / self.expected_strokes)
        return r

    def to_json(self) -> dict:
        return {"completed": self.completed, "score": round(self.score, 3),
                "n_strokes": self.n_strokes,
                "expected_strokes": self.expected_strokes}


_stroke_counts: dict[str, int] | None = None


def expected_strokes(char: str) -> int | None:
    """Median stroke count of `char` across TUAT writers, or None.

    Built by `scripts/build_stroke_counts.py` from the training trajectories,
    so it reflects how people actually write (連綿でつながる分だけ辞書の画数
    より少なめ) rather than a dictionary 画数.
    """
    global _stroke_counts
    if _stroke_counts is None:
        try:
            _stroke_counts = json.loads(STROKE_COUNTS.read_text(encoding="utf-8"))
        except OSError:
            _stroke_counts = {}
    return _stroke_counts.get(char)


def _raster(strokes_px: list[np.ndarray], size: int, supersample: int,
            width: int) -> np.ndarray:
    """Draw polylines given in output-pixel coordinates as a white-background
    uint8 grayscale image."""
    big = size * supersample
    canvas = Image.new("L", (big, big), 255)
    draw = ImageDraw.Draw(canvas)
    for s in strokes_px:
        pts = [(float(x) * supersample, float(y) * supersample) for x, y in s[:, :2]]
        if len(pts) == 1:
            pts = [pts[0], (pts[0][0] + 1, pts[0][1])]
        draw.line(pts, fill=0, width=width, joint="curve")
    return np.array(canvas.resize((size, size), Image.LANCZOS))


def _fit(strokes: list[np.ndarray],
         box: tuple[float, float, float, float]) -> list[np.ndarray]:
    """Map the strokes' bounding box onto `box`, stretching each axis on its
    own. Aspect is deliberately not preserved: this is for comparing a glyph
    against a reference whose bounding box is already known, where a flat
    character (一, 二) must line up with a flat reference."""
    x0, y0, x1, y1 = box
    min_x, min_y, max_x, max_y = bounding_box(strokes)
    w, h = max_x - min_x, max_y - min_y
    out = []
    for s in strokes:
        r = np.empty((len(s), 2))
        r[:, 0] = (s[:, 0] - min_x) * (x1 - x0) / w + x0 if w > 0 else (x0 + x1) / 2
        r[:, 1] = (s[:, 1] - min_y) * (y1 - y0) / h + y0 if h > 0 else (y0 + y1) / 2
        out.append(r)
    return out


def render_style_image(strokes: list[np.ndarray], size: int = IMG_SIZE,
                       supersample: int = 4, width: int = 5) -> np.ndarray:
    """Render normalized (0–1000) strokes as a white-background grayscale image
    matching the TUAT style-sample appearance (thin dark lines, uint8)."""
    m = size * 0.08
    scale = (size - 2 * m) / STANDARD_SIZE
    return _raster([s[:, :2] * scale + m for s in strokes], size, supersample, width)


def _ink(img: np.ndarray, thresh: int = 160) -> np.ndarray:
    return np.asarray(img) < thresh


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation with a (2r+1)² square, without pulling in scipy."""
    h, w = mask.shape
    pad = np.zeros((h + 2 * r, w + 2 * r), dtype=bool)
    pad[r:r + h, r:r + w] = mask
    out = np.zeros_like(mask)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= pad[dy:dy + h, dx:dx + w]
    return out


def content_similarity(strokes: list[np.ndarray], content: np.ndarray,
                       tol: int = 2) -> float:
    """How well `strokes` cover the glyph in the content image, 0–1.

    Both are reduced to ink masks and compared inside the content glyph's own
    bounding box, so this measures shape rather than placement. The score is
    the mean of two coverages — generated ink that lands on the font glyph
    (penalizes garbage) and font ink that a generated line passes through
    (penalizes missing strokes, which is what truncation produces).
    """
    ref = _ink(content)
    if not ref.any() or not strokes:
        return 0.0
    ys, xs = np.where(ref)
    box = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
    gen = _ink(_raster(_fit(strokes, box), content.shape[0], 4, 3))
    if not gen.any():
        return 0.0
    precision = (gen & _dilate(ref, tol)).sum() / gen.sum()
    recall = (ref & _dilate(gen, tol)).sum() / ref.sum()
    return float((precision + recall) / 2)


def decode_sequence(seq: np.ndarray) -> tuple[list[np.ndarray], bool]:
    """Convert an SDT output sequence (T, 5) of (dx, dy, s1, s2, s3) rows into
    absolute-coordinate strokes, plus whether the model ended the character
    itself. `False` means decoding hit the end of the sequence with no s3 —
    the glyph is cut off mid-character.
    """
    seq = np.asarray(seq, dtype=np.float64).copy()
    seq[:, 0] = np.cumsum(seq[:, 0])
    seq[:, 1] = np.cumsum(seq[:, 1])
    end = np.where(seq[:, 4] == 1)[0]
    completed = bool(len(end))
    if completed:
        seq = seq[:end[0]]
    strokes, start = [], 0
    for i in range(len(seq)):
        if seq[i, 3] == 1:                       # pen up: last point of stroke
            strokes.append(seq[start:i + 1, :2])
            start = i + 1
    if start < len(seq):
        strokes.append(seq[start:, :2])
    return [s for s in strokes if len(s) >= 2], completed


def seq_to_strokes(seq: np.ndarray) -> list[np.ndarray]:
    """`decode_sequence` without the completion flag."""
    return decode_sequence(seq)[0]


def _pick_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class SDTGenerator:
    """Lazy-loading wrapper around the pretrained SDT Japanese model."""

    def __init__(self, ckpt: Path = DEFAULT_CKPT, data_dir: Path = DATA_DIR,
                 device: str | None = None):
        self.ckpt = Path(ckpt)
        self.data_dir = Path(data_dir)
        self.device = device or _pick_device()
        self._model = None
        self._content: dict | None = None

    @property
    def available(self) -> bool:
        return self.ckpt.exists() and (self.data_dir / "Japanese_content.pkl").exists()

    @property
    def content(self) -> dict:
        if self._content is None:
            with open(self.data_dir / "Japanese_content.pkl", "rb") as f:
                self._content = pickle.load(f)
        return self._content

    def supports(self, char: str) -> bool:
        return char in self.content

    def _load_model(self):
        if self._model is not None:
            return self._model
        import torch
        if str(SDT_ROOT) not in sys.path:
            sys.path.insert(0, str(SDT_ROOT))
        from models.model import SDT_Generator  # SDT repo module
        # layer counts from configs/Japanese_TUATHANDS.yml
        model = SDT_Generator(num_encoder_layers=2, num_head_layers=1,
                              wri_dec_layers=2, gly_dec_layers=2).to(self.device)
        state = torch.load(self.ckpt, map_location="cpu")
        model.load_state_dict(state)
        model.eval()
        self._model = model
        return model

    def build_style_batch(self, style_strokes: list[list[np.ndarray]],
                          rng: np.random.Generator | None = None) -> np.ndarray:
        """Render style reference characters to a (NUM_STYLE_IMGS, 64, 64)
        float array in [0, 1]. Samples with replacement when fewer than
        NUM_STYLE_IMGS characters are supplied.

        Which characters get drawn is the one thing that varies between
        generation attempts (see the module docstring), so a writer with more
        than NUM_STYLE_IMGS characters on file gets the most out of retries.
        """
        if not style_strokes:
            raise ValueError("need at least one style character")
        rng = rng or np.random.default_rng()
        idx = np.arange(len(style_strokes))
        if len(idx) >= NUM_STYLE_IMGS:
            idx = rng.choice(idx, NUM_STYLE_IMGS, replace=False)
        else:
            idx = np.concatenate([idx, rng.choice(idx, NUM_STYLE_IMGS - len(idx), replace=True)])
        imgs = [render_style_image(normalize_strokes(style_strokes[i])) for i in idx]
        return np.stack(imgs).astype(np.float32) / 255.0

    def _run(self, style: np.ndarray, chars: list[str],
             batch_size: int) -> dict[str, Generated]:
        """One generation pass over `chars` (this is what `generate` retries)."""
        import torch
        model = self._load_model()
        style_t = torch.from_numpy(style).unsqueeze(1)          # (15, 1, 64, 64)
        out: dict[str, Generated] = {}
        with torch.no_grad():
            for i in range(0, len(chars), batch_size):
                batch = chars[i:i + batch_size]
                bs = len(batch)
                img_list = style_t.unsqueeze(0).repeat(bs, 1, 1, 1, 1).to(self.device)
                char_imgs = np.stack([self.content[c] for c in batch]).astype(np.float32) / 255.0
                char_t = torch.from_numpy(char_imgs).unsqueeze(1).to(self.device)
                preds = model.inference(img_list, char_t, MAX_SEQ_LEN)
                sos = torch.tensor(bs * [[0, 0, 1, 0, 0]]).unsqueeze(1).to(preds)
                preds = torch.cat((sos, preds), 1).cpu().numpy()
                for c, seq in zip(batch, preds):
                    strokes, completed = decode_sequence(seq)
                    if not strokes:
                        continue
                    # SDT output has no absolute scale (trained on per-glyph-
                    # normalized data); size/position come from the shared
                    # glyph metrics table. A truncated glyph is placed the same
                    # way — there is no reference for how much of it is missing
                    # — so `completed` is what callers must surface to the user.
                    with_tp = [np.concatenate([s, np.zeros((len(s), 2))], axis=1)
                               for s in strokes]
                    out[c] = Generated(
                        char=c,
                        strokes=[s[:, :2] for s in place_glyph(with_tp, c)],
                        completed=completed,
                        score=content_similarity(strokes, self.content[c]),
                        n_strokes=len(strokes),
                        expected_strokes=expected_strokes(c),
                    )
        return out

    def generate(self, style_strokes: list[list[np.ndarray]], chars: str,
                 batch_size: int = 8, attempts: int = DEFAULT_ATTEMPTS,
                 rng: np.random.Generator | None = None) -> dict[str, Generated]:
        """Generate `chars` in the style of `style_strokes` (each entry is one
        character's strokes, any coordinate space with x,y in first columns).

        A character that comes out truncated, short of strokes, or unlike its
        content image is generated again from a fresh draw of style references
        — up to `attempts` times, and only for the characters that still need
        it. The best candidate by `Generated.rank` is kept.

        Returns {char: Generated} with strokes normalized to the 0–1000 box.
        Characters missing from the content dictionary, and ones that decoded
        to no strokes at all, are absent from the result.
        """
        rng = rng or np.random.default_rng()
        todo = [c for c in dict.fromkeys(chars) if self.supports(c)]
        best: dict[str, Generated] = {}
        for attempt in range(max(1, attempts)):
            pending = [c for c in todo if c not in best or not best[c].ok]
            if not pending:
                break
            if attempt:
                log.info("SDT retry %d: %d character(s) — %s",
                         attempt, len(pending), "".join(pending))
            style = self.build_style_batch(style_strokes, rng)   # (15, 64, 64)
            for c, g in self._run(style, pending, batch_size).items():
                if c not in best or g.rank > best[c].rank:
                    best[c] = g

        if todo:
            trunc = [c for c, g in best.items() if not g.completed]
            log.info("SDT generated %d/%d character(s); truncated %d (%.0f%%): %s",
                     len(best), len(todo), len(trunc),
                     100 * len(trunc) / len(todo), "".join(trunc) or "-")
        return best
