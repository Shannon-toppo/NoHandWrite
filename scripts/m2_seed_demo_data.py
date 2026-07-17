"""Seed demo data for the library view: post several jittered writings of a
character to the running server, simulating a person writing it 5 times.

Usage: uv run python scripts/m2_seed_demo_data.py [--url http://localhost:8765]
"""
import argparse
import json
import urllib.request

import numpy as np


def jitter(strokes, rng, offset=12.0, noise=2.5):
    out = []
    dx, dy = rng.normal(0, offset, 2)
    ang = rng.normal(0, 0.03)
    ca, sa = np.cos(ang), np.sin(ang)
    for s in strokes:
        pts = []
        for (x, y, t) in s:
            xr = ca * (x - 225) - sa * (y - 225) + 225
            yr = sa * (x - 225) + ca * (y - 225) + 225
            pts.append({"x": float(xr + dx + rng.normal(0, noise)),
                        "y": float(yr + dy + rng.normal(0, noise)),
                        "t": float(t), "p": 0.5})
        out.append(pts)
    return out


def base_strokes():
    """A rough 3-stroke 「大」 on a 450x450 canvas as (x, y, t) polylines."""
    horiz = [(90, 200, 0), (170, 196, 80), (260, 194, 160), (360, 198, 240)]
    down_left = [(225, 90, 400), (222, 160, 480), (205, 240, 560),
                 (170, 320, 640), (120, 390, 720)]
    down_right = [(228, 210, 900), (260, 280, 980), (300, 340, 1060), (350, 395, 1140)]
    return [horiz, down_left, down_right]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8765")
    parser.add_argument("--writer", default="demo")
    parser.add_argument("--times", type=int, default=5)
    opt = parser.parse_args()

    rng = np.random.default_rng(7)
    for i in range(opt.times):
        body = {
            "writer": opt.writer, "char": "大", "device": "synthetic",
            "canvas": [450, 450],
            "strokes": jitter(base_strokes(), rng),
        }
        req = urllib.request.Request(
            f"{opt.url}/api/samples", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            print(i + 1, res.status, res.read().decode())


if __name__ == "__main__":
    main()
