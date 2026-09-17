#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import zlib


def main():
    if len(sys.argv) < 2:
        print("Usage: python decompress_zlib.py <input.zlib> [output.file]")
        sys.exit(1)
    in_fname = sys.argv[1]
    out_fname = sys.argv[2] if len(sys.argv) > 2 else in_fname + ".decompressed"
    try:
        with open(in_fname, "rb") as fin, open(out_fname, "wb") as fout:
            decomp = zlib.decompressobj()
            for chunk in iter(lambda: fin.read(16384), b""):
                if not chunk:
                    break
                out = decomp.decompress(chunk)
                if out:
                    fout.write(out)
            rem = decomp.flush()
            if rem:
                fout.write(rem)
    except zlib.error as e:
        print(f"zlib decompression error: {e}")
        sys.exit(2)
    except FileNotFoundError:
        print(f"File not found: {in_fname}")
        sys.exit(3)


if __name__ == "__main__":
    raise SystemExit(main())
