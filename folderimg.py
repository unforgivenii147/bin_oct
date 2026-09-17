#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

import dh
from PIL import Image

PHASH_W = 0.5
DHASH_W = 0.3
AHASH_W = 0.2
MAX_SCORE = 10.0
OUT_PREFIX = "group_"


def compute_hashes(path: Path):
    try:
        with Image.open(path) as img:
            return {
                "phash": dh.phash(img),
                "dhash": dh.dhash(img),
                "ahash": dh.average_hash(img),
            }
    except Exception as e:
        print(f"[SKIP] {path.name}: {e}")
        return None


def similarity_score(h1, h2) -> float:
    return (
        (h1["phash"] - h2["phash"]) * PHASH_W
        + (h1["dhash"] - h2["dhash"]) * DHASH_W
        + (h1["ahash"] - h2["ahash"]) * AHASH_W
    )


def main() -> None:
    cwd = Path.cwd()
    images = [p for p in cwd.iterdir() if dh.is_image(p)]
    if not images:
        print("No images found.")
        return
    hashes = {}
    for img in images:
        h = compute_hashes(img)
        if h:
            hashes[img] = h
    groups = []
    for img, h in hashes.items():
        assigned = False
        for group in groups:
            _ref_img, ref_hash = group[0]
            score = similarity_score(h, ref_hash)
            if score <= MAX_SCORE:
                group.append((img, h))
                assigned = True
                break
        if not assigned:
            groups.append([(img, h)])
    for idx, group in enumerate(groups, start=1):
        if len(group) > 1:
            folder = cwd / f"{OUT_PREFIX}{idx:03d}"
            folder.mkdir(exist_ok=True)
            for img, _ in group:
                shutil.move(str(img), folder / img.name)
    print(f"Done. Created {len(groups)} groups.")


if __name__ == "__main__":
    raise SystemExit(main())
