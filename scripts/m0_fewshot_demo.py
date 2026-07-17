"""M0 spike: few-shot demo — take 15 style samples from one writer and
generate characters that writer never provided (e.g. 木 -> 林, 森).

Renders a montage: top row = the 15 style reference images, below = generated
characters.

Usage:
    uv run python scripts/m0_fewshot_demo.py --out DIR --chars 木林森検索芸術 [--writer-index 0]
"""
import argparse
import glob
import os
import pickle
import random
import sys

import numpy as np
import torch
from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDT = os.path.join(REPO, "third_party", "SDT")
sys.path.insert(0, SDT)
os.chdir(SDT)

from parse_config import cfg, cfg_from_file, assert_and_infer_cfg  # noqa: E402
from models.model import SDT_Generator  # noqa: E402
from utils.util import coords_render  # noqa: E402

DATA = "data/TUATHANDS_JAPANESE"


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ckpt", default="model_zoo/saved_weights/Japanese/checkpoint-iter147999.pth")
    parser.add_argument("--out", required=True)
    parser.add_argument("--chars", default="木林森")
    parser.add_argument("--writer-index", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    opt = parser.parse_args()
    random.seed(opt.seed)
    torch.manual_seed(opt.seed)

    cfg_from_file("configs/Japanese_TUATHANDS.yml")
    assert_and_infer_cfg()

    content = pickle.load(open(os.path.join(DATA, "Japanese_content.pkl"), "rb"))
    style_files = sorted(glob.glob(os.path.join(DATA, "test_style_samples", "*.pkl")))
    style_file = style_files[opt.writer_index]
    writer = os.path.basename(style_file).split(".")[0]
    style_samples = pickle.load(open(style_file, "rb"))
    num_img = cfg.MODEL.NUM_IMGS
    refs = random.sample(style_samples, num_img)
    img_list = np.expand_dims(np.array([r["img"] / 255.0 for r in refs]), 1)  # (N,1,H,W)

    device = pick_device()
    model = SDT_Generator(num_encoder_layers=cfg.MODEL.ENCODER_LAYERS,
                          num_head_layers=cfg.MODEL.NUM_HEAD_LAYERS,
                          wri_dec_layers=cfg.MODEL.WRI_DEC_LAYERS,
                          gly_dec_layers=cfg.MODEL.GLY_DEC_LAYERS).to(device)
    model.load_state_dict(torch.load(opt.ckpt, map_location="cpu"))
    model.eval()

    chars = [c for c in opt.chars if c in content]
    missing = [c for c in opt.chars if c not in content]
    if missing:
        print(f"not in content dict, skipped: {''.join(missing)}")

    bs = len(chars)
    img_batch = torch.Tensor(img_list).unsqueeze(0).repeat(bs, 1, 1, 1, 1).to(device)
    char_imgs = torch.Tensor(np.array([content[c] / 255.0 for c in chars])).unsqueeze(1).to(device)

    with torch.no_grad():
        preds = model.inference(img_batch, char_imgs, 120)
        sos = torch.tensor(bs * [[0, 0, 1, 0, 0]]).unsqueeze(1).to(preds)
        preds = torch.cat((sos, preds), 1).cpu().numpy()

    os.makedirs(opt.out, exist_ok=True)
    cell = 160
    ref_cell = 80
    cols = max(len(chars), num_img)
    sheet = Image.new("RGB", (max(num_img * ref_cell, len(chars) * cell),
                              30 + ref_cell + 30 + cell), "white")
    d = ImageDraw.Draw(sheet)
    d.text((5, 8), f"style references (writer {writer}, {num_img} samples):", fill="black")
    for i, r in enumerate(refs):
        im = Image.fromarray(r["img"].astype(np.uint8)).convert("RGB").resize((ref_cell, ref_cell))
        sheet.paste(im, (i * ref_cell, 30))
    d.text((5, 30 + ref_cell + 8), f"generated (never written by this writer): {''.join(chars)}", fill="black")
    for i in range(bs):
        im = coords_render(preds[i], split=True, width=cell, height=cell, thickness=2, board=5)
        sheet.paste(im.convert("RGB"), (i * cell, 30 + ref_cell + 30))
    out_path = os.path.join(opt.out, f"fewshot_w{writer}.png")
    sheet.save(out_path)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
