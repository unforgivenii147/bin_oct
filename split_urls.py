#!/data/data/com.termux/files/home/.local/bin/python
"""
Extract URLs by file extension from a list of URLs.
Each extension gets its own output file (e.g., pdf_urls.txt, html_urls.txt).
"""

import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

# Extensions to look for (lowercase, without the leading dot)
EXTENSIONS = [
    "htm",
    "html",
    "js",
    "css",
    "pdf",
    "asp",
    "aspx",
    "php",
    "jsp",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "svg",
    "webp",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "txt",
    "csv",
    "xml",
    "json",
    "mp3",
    "mp4",
    "avi",
    "mov",
    "wav",
    "exe",
    "dmg",
    "apk",
]


def get_extension(url: str) -> str | None:
    """
    Return the file extension of a URL (lowercase, no dot),
    or None if no known extension matches.
    Handles query strings like '.asp?pagenum=1'.
    """
    # Strip trailing whitespace and quotes
    url = url.strip().strip('"').strip("'")
    if not url:
        return None

    # Parse the URL to drop query params and fragment
    parsed = urlparse(url)
    path = parsed.path or url  # fall back if url isn't well-formed

    # Get the last path segment
    last_segment = path.rstrip("/").split("/")[-1]

    # Look for the last "." in that segment
    if "." not in last_segment:
        return None

    # Everything after the last dot in the last path segment
    ext = last_segment.rsplit(".", 1)[-1].lower()

    return ext if ext in EXTENSIONS else None


def main():

    input_file = Path(sys.argv[1].strip())  # change if needed
    if not input_file.exists():
        print(f"Input file not found: {input_file}")
        return

    # Group URLs by extension
    buckets: dict[str, list[str]] = defaultdict(list)

    with input_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip()
            if not url:
                continue
            ext = get_extension(url)
            if ext:
                buckets[ext].append(url)

    # Write one file per extension in the current directory
    cwd = Path.cwd()
    if not buckets:
        print("No URLs with recognized extensions found.")
        return

    for ext, urls in sorted(buckets.items()):
        out_path = cwd / f"{ext}_urls.txt"
        out_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"{out_path.name}: {len(urls)} URLs")


if __name__ == "__main__":
    main()
