"""Adapter around the vendored SDT model (third_party/SDT).

Turns the user's captured strokes into SDT style-reference images, runs the
pretrained Japanese checkpoint, and converts the predicted (dx, dy, pen-state)
sequences back into stroke arrays in our standard 0–1000 box.

SDT's row format is (dx, dy, s1, s2, s3): s1 = pen down, s2 = last point of a
stroke (pen up), s3 = end of character.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..metrics import place_glyph
from ..strokes import normalize_strokes

REPO = Path(__file__).resolve().parents[3]
SDT_ROOT = REPO / "third_party" / "SDT"
DATA_DIR = SDT_ROOT / "data" / "TUATHANDS_JAPANESE"
DEFAULT_CKPT = SDT_ROOT / "model_zoo" / "saved_weights" / "Japanese" / "checkpoint-iter147999.pth"

NUM_STYLE_IMGS = 15   # matches MODEL.NUM_IMGS of the Japanese config
IMG_SIZE = 64
MAX_SEQ_LEN = 120

def render_style_image(strokes: list[np.ndarray], size: int = IMG_SIZE,
                       supersample: int = 4, width: int = 5) -> np.ndarray:
    """Render normalized (0–1000) strokes as a white-background grayscale image
    matching the TUAT style-sample appearance (thin dark lines, uint8)."""
    big = size * supersample
    margin = 0.08
    scale = big * (1 - 2 * margin) / 1000.0
    off = big * margin
    canvas = Image.new("L", (big, big), 255)
    draw = ImageDraw.Draw(canvas)
    for s in strokes:
        pts = [(float(x) * scale + off, float(y) * scale + off) for x, y in s[:, :2]]
        if len(pts) == 1:
            pts = [pts[0], (pts[0][0] + 1, pts[0][1])]
        draw.line(pts, fill=0, width=width, joint="curve")
    return np.array(canvas.resize((size, size), Image.LANCZOS))


def seq_to_strokes(seq: np.ndarray) -> list[np.ndarray]:
    """Convert an SDT output sequence (T, 5) of (dx, dy, s1, s2, s3) rows into
    absolute-coordinate strokes (list of (N, 2) arrays)."""
    seq = np.asarray(seq, dtype=np.float64).copy()
    seq[:, 0] = np.cumsum(seq[:, 0])
    seq[:, 1] = np.cumsum(seq[:, 1])
    end = np.where(seq[:, 4] == 1)[0]
    if len(end):
        seq = seq[:end[0]]
    strokes, start = [], 0
    for i in range(len(seq)):
        if seq[i, 3] == 1:                       # pen up: last point of stroke
            strokes.append(seq[start:i + 1, :2])
            start = i + 1
    if start < len(seq):
        strokes.append(seq[start:, :2])
    return [s for s in strokes if len(s) >= 2]


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
        NUM_STYLE_IMGS characters are supplied."""
        if not style_strokes:
            raise ValueError("need at least one style character")
        rng = rng or np.random.default_rng(0)
        idx = np.arange(len(style_strokes))
        if len(idx) >= NUM_STYLE_IMGS:
            idx = rng.choice(idx, NUM_STYLE_IMGS, replace=False)
        else:
            idx = np.concatenate([idx, rng.choice(idx, NUM_STYLE_IMGS - len(idx), replace=True)])
        imgs = [render_style_image(normalize_strokes(style_strokes[i])) for i in idx]
        return np.stack(imgs).astype(np.float32) / 255.0

    def generate(self, style_strokes: list[list[np.ndarray]], chars: str,
                 batch_size: int = 8) -> dict[str, list[np.ndarray]]:
        """Generate `chars` in the style of `style_strokes` (each entry is one
        character's strokes, any coordinate space with x,y in first columns).

        Returns {char: strokes} with strokes normalized to the 0–1000 box.
        Characters missing from the content dictionary are skipped.
        """
        import torch
        model = self._load_model()
        style = self.build_style_batch(style_strokes)          # (15, 64, 64)
        style_t = torch.from_numpy(style).unsqueeze(1)          # (15, 1, 64, 64)

        todo = [c for c in dict.fromkeys(chars) if self.supports(c)]
        result: dict[str, list[np.ndarray]] = {}
        with torch.no_grad():
            for i in range(0, len(todo), batch_size):
                batch = todo[i:i + batch_size]
                bs = len(batch)
                img_list = style_t.unsqueeze(0).repeat(bs, 1, 1, 1, 1).to(self.device)
                char_imgs = np.stack([self.content[c] for c in batch]).astype(np.float32) / 255.0
                char_t = torch.from_numpy(char_imgs).unsqueeze(1).to(self.device)
                preds = model.inference(img_list, char_t, MAX_SEQ_LEN)
                sos = torch.tensor(bs * [[0, 0, 1, 0, 0]]).unsqueeze(1).to(preds)
                preds = torch.cat((sos, preds), 1).cpu().numpy()
                for c, seq in zip(batch, preds):
                    strokes = seq_to_strokes(seq)
                    if not strokes:
                        continue
                    with_tp = [np.concatenate(
                        [s, np.zeros((len(s), 2))], axis=1) for s in strokes]
                    # SDT output has no absolute scale (trained on per-glyph-
                    # normalized data); size/position come from the shared
                    # glyph metrics table.
                    result[c] = [s[:, :2] for s in place_glyph(with_tp, c)]
        return result
