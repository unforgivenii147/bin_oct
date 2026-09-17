#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

HTML_TEMPLATE = """<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="style.css" />
    <script src="script.js"></script>
    <title>html template</title>
  </head>
  <body>
    <div>
      <h2>Heading2</h2>
    </div>
  </body>
</html>
"""
if __name__ == "__main__":
    file_name = Path(sys.argv[1]) or Path("index.html")
    file_name.write_text(HTML_TEMPLATE, encoding="utf-8")
