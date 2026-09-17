#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

INPUT_FILE = sys.argv[1]


def normalize_url(u: str) -> str:
    u = u.strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.IGNORECASE):
        u = "https://" + u
    p = urlparse(u)
    scheme = "https"
    host = (p.netloc or "").lower()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{scheme}://{host}{path}"


def canonical_url(u: str) -> str:
    p = urlparse(u)
    host = p.netloc.lower()
    segs = [s for s in (p.path or "/").split("/") if s]
    if "github.com" in host:
        if len(segs) >= 2:
            owner, repo = segs[0], segs[1]
            return f"https://github.com/{owner}/{repo}"
        return "https://github.com/"
    return f"https://{host}/"


def prune_urls(urls: list[str]):
    seen = set()
    out = []
    for line in urls:
        n = normalize_url(line)
        if not n:
            continue
        c = canonical_url(n)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out)


def main() -> None:
    with open(INPUT_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    pruned = prune_urls(lines)
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(u + "\n" for u in pruned)


if __name__ == "__main__":
    raise SystemExit(main())
