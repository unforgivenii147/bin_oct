#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pyppeteer import launch


async def main():
    url = sys.argv[1]
    browser = await launch()
    page = await browser.newPage()
    await page.goto(url)
    await page.screenshot({"path": "example.png"})
    content = await page.evaluate("document.body.textContent", force_expr=True)
    outfile = Path(url).with_suffix(".txt")
    Path(outfile).write_text(content, encoding="utf-8")
    dimensions = await page.evaluate("""() => {
        return {
            width: document.documentElement.clientWidth,
            height: document.documentElement.clientHeight,
            deviceScaleFactor: window.devicePixelRatio,
        }
    }""")
    print(dimensions)
    await browser.close()


asyncio.get_event_loop().run_until_complete(main())
