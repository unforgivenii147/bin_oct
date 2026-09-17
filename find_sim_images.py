#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import imagehash
from PIL import Image


def find_similar_images(userpaths, hashfunc=imagehash.average_hash) -> None:
    def is_image(filename):
        f = filename.lower()
        return (
            f.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg")) or ".jpg" in f
        )

    image_filenames = []
    for userpath in userpaths:
        image_filenames += [path for path in Path(userpath).iterdir() if is_image(path)]
    images = {}
    for img in sorted(image_filenames):
        try:
            hash = hashfunc(Image.open(img))
        except Exception as e:
            print("Problem:", e, "with", img)
            continue
        if hash in images:
            print(img, "  already exists as", " ".join(images[hash]))
            if "dupPictures" in img:
                print("rm -v", img)
        images[hash] = [*images.get(hash, []), img]


if __name__ == "__main__":
    import sys

    def usage():
        sys.stderr.write(f"""SYNOPSIS: {sys.argv[0]} [ahash|phash|dhash|...] [<directory>]
Identifies similar images in the directory.
Method:
  ahash:          Average hash
  phash:          Perceptual hash
  dhash:          Difference hash
  whash-haar:     Haar wavelet hash
  whash-db4:      Daubechies wavelet hash
  colorhash:      HSV color hash
  crop-resistant: Crop-resistant hash
(C) Johannes Buchner, 2013-2017
""")
        sys.exit(1)

    hashmethod = sys.argv[1] if len(sys.argv) > 1 else usage()
    if hashmethod == "ahash":
        hashfunc = imagehash.average_hash
    elif hashmethod == "phash":
        hashfunc = imagehash.phash
    elif hashmethod == "dhash":
        hashfunc = imagehash.dhash
    elif hashmethod == "whash-haar":
        hashfunc = imagehash.whash
    elif hashmethod == "whash-db4":

        def hashfunc(img):
            return imagehash.whash(img, mode="db4")

    elif hashmethod == "colorhash":
        hashfunc = imagehash.colorhash
    elif hashmethod == "crop-resistant":
        hashfunc = imagehash.crop_resistant_hash
    else:
        usage()
    userpaths = sys.argv[2:] if len(sys.argv) > 2 else "."
    find_similar_images(userpaths=userpaths, hashfunc=hashfunc)
