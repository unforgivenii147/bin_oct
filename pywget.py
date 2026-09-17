#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import sys
import urllib
from pathlib import Path
from shutil import get_terminal_size

from tqdm import tqdm


def get_console_width() -> int:
    try:
        return get_terminal_size().columns
    except (OSError, AttributeError):
        return 80


def sanitize_filename(name: str) -> str:
    name = urllib.parse.unquote(name)
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:255].strip() or "downloaded_file"


def extract_filename(url: str, headers: dict[str, str] | None = None) -> str:
    if headers:
        cd = headers.get("Content-Disposition", "")
        if cd:
            match = re.search(
                r"filename\*?=(?:UTF-8" ')?"?([^";]+)"?',
                cd,
                re.IGNORECASE,
            )
            if match:
                return sanitize_filename(match.group(1))
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    filename = Path(path).name
    filename = filename.split("?")[0].split("#")[0]
    return sanitize_filename(filename) or "downloaded_file"


def filename_fix_existing(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent or Path()
    counter = 1
    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def download(
    url: str,
    output: str | None = None,
    timeout: float = 30.0,
    resume: bool = False,
    quiet: bool = False,
) -> str:
    output_path = Path(output) if output else None
    if output_path and output_path.is_dir():
        output_path /= extract_filename(url)
    remote_size = None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            remote_size = int(resp.headers.get("Content-Length", 0))
    except Exception:
        pass
    if not output_path:
        output_path = Path(extract_filename(url))
    output_path = filename_fix_existing(output_path)
    offset = 0
    if resume and output_path.exists():
        offset = output_path.stat().st_size
        if remote_size and offset >= remote_size:
            if not quiet:
                print(f"✅ Already complete: {output_path} ({offset} bytes)")
            return str(output_path)
    headers = {}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    with tqdm(
        total=remote_size or 0,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc="Downloading",
        leave=False,
        disable=quiet,
    ) as pbar:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                mode = "ab" if offset else "wb"
                with Path(output_path).open(mode) as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        pbar.update(len(chunk))
            if not quiet:
                print(f"\n✅ Saved to: {output_path}")
            return str(output_path)
        except urllib.error.HTTPError as e:
            msg = f"HTTP error {e.code}: {e.reason}"
            raise RuntimeError(msg)
        except urllib.error.URLError as e:
            msg = f"URL error: {e.reason}"
            raise RuntimeError(msg)
        except Exception as e:
            msg = f"Download failed: {e}"
            raise RuntimeError(msg)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Modern wget",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pywget.py https://example.com/file.zip
  python pywget.py https://example.com/file.zip -o mydir/
  python pywget.py https://example.com/file.zip --resume
  python pywget.py https://example.com/file.zip -q
        """,
    )
    parser.add_argument("url", help="URL to download")
    parser.add_argument("-o", "--output", help="Output file or directory")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume partial downloads"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress bar"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    args = parser.parse_args()
    try:
        download(
            args.url,
            output=args.output,
            timeout=args.timeout,
            resume=args.resume,
            quiet=args.quiet,
        )
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
