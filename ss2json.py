#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

fn = Path(sys.argv[1])
df = pd.read_csv(str(fn))
df_sorted = df.sort_values(by="score", ascending=False)
outfile = fn.with_suffix(".json")
df_sorted.to_json(str(outfile))
