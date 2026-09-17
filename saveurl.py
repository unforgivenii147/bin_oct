#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from pywebcopy import save_webpage


def main() -> None:
    save_webpage(
        url=sys.argv[1],
        project_folder="./saved_pages/",
        project_name=sys.argv[1],
        bypass_robots=True,
        debug=True,
        open_in_browser=True,
        delay=None,
        threaded=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
