"""Build the expected stroke-count table used by the generation quality score.

Scans the TUAT Japanese training LMDB (real handwriting trajectories) and
records, per character, the median number of strokes across all writers.
Writers differ (連綿でくっつく人もいる) so the median is a rough canonical
value, not a dictionary 画数 — the scorer only uses it to spot candidates
that came out drastically short.

Run once; the result is committed as package data.

    uv run python scripts/build_stroke_counts.py
"""
from __future__ import annotations

import json
import pickle
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import lmdb

REPO = Path(__file__).resolve().parents[1]
LMDB_PATH = REPO / "third_party" / "SDT" / "data" / "TUATHANDS_JAPANESE" / "train"
OUT = REPO / "core" / "nohandwrite" / "generate" / "stroke_counts.json"


def main() -> int:
    if not LMDB_PATH.exists():
        print(f"missing training data: {LMDB_PATH}", file=sys.stderr)
        return 1
    env = lmdb.open(str(LMDB_PATH), readonly=True, lock=False,
                    readahead=False, meminit=False)
    counts: dict[str, list[int]] = defaultdict(list)
    with env.begin() as txn:
        total = int(txn.get(b"num_sample").decode())
        for i in range(total):
            raw = txn.get(str(i).encode())
            if raw is None:
                continue
            d = pickle.loads(raw)
            coords = d["coordinates"]
            # column 3 is s2 (last point of a stroke); a trajectory that ends
            # without one still has a final open stroke
            n = int((coords[:, 3] == 1).sum())
            if coords[-1, 3] != 1:
                n += 1
            if n:
                counts[d["tag_char"]].append(n)
            if i % 200000 == 0:
                print(f"{i}/{total}", file=sys.stderr)
    table = {c: int(statistics.median(v)) for c, v in sorted(counts.items())}
    OUT.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    print(f"{len(table)} characters -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
