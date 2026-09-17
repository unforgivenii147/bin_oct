#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def normalize_url(u: str) -> str:
    u = u.strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.IGNORECASE):
        u = "https://" + u
    try:
        p = urlparse(u)
        scheme = p.scheme or "https"
        host = (p.netloc or "").lower()
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return f"{scheme}://{host}{path}"
    except ValueError:
        print(f"Warning: Could not parse URL: {u}", file=sys.stderr)
        return ""


def get_canonical_root(normalized_url: str) -> str:
    try:
        p = urlparse(normalized_url)
        host = p.netloc.lower()
        path_segments = [s for s in p.path.split("/") if s]
        if host in ("github.com", "www.github.com"):
            if len(path_segments) >= 2:
                return f"https://github.com/{path_segments[0]}/{path_segments[1]}"
            else:
                return "https://github.com/"
        else:
            if not host:
                return normalized_url
            if not path_segments:
                return f"https://{host}/"
            return f"https://{host}/{path_segments[0]}"
    except ValueError:
        print(
            f"Warning: Could not parse URL for root: {normalized_url}", file=sys.stderr
        )
        return normalized_url


def prune_subaddresses(urls: list[str]) -> list[str]:
    if not urls:
        return []
    normalized_urls_map = {}
    for original_url in urls:
        normalized = normalize_url(original_url)
        if normalized:
            normalized_urls_map[original_url] = normalized
    best_by_root = {}
    for original_url, normalized in normalized_urls_map.items():
        root = get_canonical_root(normalized)
        if root not in best_by_root or len(normalized) < len(best_by_root[root]):
            best_by_root[root] = normalized
    candidates = sorted(best_by_root.values(), key=len)
    final_urls = []
    for cand_url in candidates:
        cand_parsed = urlparse(cand_url)
        cand_host = cand_parsed.netloc.lower()
        cand_path = cand_parsed.path.rstrip("/")
        if not cand_path:
            cand_path = "/"
        else:
            cand_path += "/"
        is_sub_address = False
        for kept_url in final_urls:
            kept_parsed = urlparse(kept_url)
            kept_host = kept_parsed.netloc.lower()
            kept_path = kept_parsed.path.rstrip("/")
            if not kept_path:
                kept_path = "/"
            else:
                kept_path += "/"
            if cand_host == kept_host and cand_path.startswith(kept_path):
                is_sub_address = True
                break
        if not is_sub_address:
            final_urls.append(cand_url)
    final_urls.sort()
    return final_urls


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python script_name.py <input_file>")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)
    try:
        lines = input_path.read_text(encoding="utf-8").splitlines()
        pruned_urls = prune_subaddresses(lines)
        input_path.write_text("\n".join(pruned_urls) + "\n", encoding="utf-8")
        print(
            f"Successfully pruned URLs in '{input_path}'. {len(lines) - len(pruned_urls)} URLs removed."
        )
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
