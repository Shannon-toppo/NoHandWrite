"""M0 spike: run SDT Japanese few-shot generation on this machine (cuda/mps/cpu).

For each test sample, renders the generated character (left) next to the
ground-truth handwriting of the same writer (right) so the style imitation
quality can be judged visually.

Usage:
    uv run python scripts/m0_test_japanese.py --out /path/to/outdir [--batches 2]
"""
import argparse
import os
import sys

import torch
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDT = os.path.join(REPO, "third_party", "SDT")
sys.path.insert(0, SDT)
os.chdir(SDT)  # SDT configs use paths relative to the repo root

from parse_config import cfg, cfg_from_file, assert_and_infer_cfg  # noqa: E402
from data_loader.loader import ScriptDataset  # noqa: E402
from models.model import SDT_Generator  # noqa: E402
from utils.util import coords_render  # noqa: E402


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
    parser.add_argument("--batches", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=16)
    opt = parser.parse_args()

    cfg_from_file("configs/Japanese_TUATHANDS.yml")
    cfg.TRAIN.IMS_PER_BATCH = opt.batch_size
    cfg.DATA_LOADER.NUM_THREADS = 0
    assert_and_infer_cfg()

    dataset = ScriptDataset(cfg.DATA_LOADER.PATH, cfg.DATA_LOADER.DATASET,
                            cfg.TEST.ISTRAIN, cfg.MODEL.NUM_IMGS)
    loader = torch.utils.data.DataLoader(dataset, batch_size=opt.batch_size,
                                         shuffle=True, drop_last=False,
                                         collate_fn=dataset.collate_fn_,
                                         num_workers=0)

    device = pick_device()
    print(f"device: {device}")
    model = SDT_Generator(num_encoder_layers=cfg.MODEL.ENCODER_LAYERS,
                          num_head_layers=cfg.MODEL.NUM_HEAD_LAYERS,
                          wri_dec_layers=cfg.MODEL.WRI_DEC_LAYERS,
                          gly_dec_layers=cfg.MODEL.GLY_DEC_LAYERS).to(device)
    state = torch.load(opt.ckpt, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    print(f"loaded {opt.ckpt}")

    os.makedirs(opt.out, exist_ok=True)
    with torch.no_grad():
        for b, data in enumerate(loader):
            if b >= opt.batches:
                break
            img_list = data["img_list"].to(device)
            char_img = data["char_img"].to(device)
            preds = model.inference(img_list, char_img, 120)
            sos = torch.tensor(preds.shape[0] * [[0, 0, 1, 0, 0]]).unsqueeze(1).to(preds)
            preds = torch.cat((sos, preds), 1).cpu().numpy()
            coords = data["coords"].cpu().numpy()
            for i in range(len(preds)):
                gen = coords_render(preds[i], split=True, width=256, height=256,
                                    thickness=4, board=1)
                gt = coords_render(coords[i], split=True, width=256, height=256,
                                   thickness=4, board=1)
                char = dataset.char_dict[int(data["character_id"][i].item())]
                wid = int(data["writer_id"][i].item())
                combo = Image.new("RGB", (522, 276), "white")
                combo.paste(gen, (2, 10))
                combo.paste(gt, (264, 10))
                combo.save(os.path.join(opt.out, f"w{wid}_u{ord(char):04x}_{char}.png"))
            print(f"batch {b + 1}/{opt.batches} done")
    print(f"saved to {opt.out} (left: generated, right: ground truth)")


if __name__ == "__main__":
    main()
