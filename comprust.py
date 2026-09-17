#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from compression_prompt import Compressor

if __name__ == "__main__":
    fn = Path(sys.argv[1])
    text = fn.read_text()
    c = Compressor()
    result = Compressor.compress(input_text=text)
    outf = fn.with_suffix(".compressed")
    outf.write_text(result.compressed_text)
