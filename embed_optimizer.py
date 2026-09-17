#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import base64
import contextlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from dh import fsz
from joblib import Parallel, delayed
from loguru import logger

DEFAULT_WORKERS = 4
SOURCE_EXTENSIONS: set[str] = {".css", ".html", ".htm", ".js"}
TOOL_TIMEOUT = 300
TOOL_COMMANDS: dict[str, object] = {
    "png": lambda p: ["pngq", str(p)],
    "jpg": lambda p: ["jpegoptim", str(p)],
    "webp_to_jpg": lambda i, o: ["to_jpg", str(i), str(o)],
    "svg": lambda p: ["svgo", "-i", str(p), "-o", str(p)],
    "js": lambda p: ["ter_ser", str(p)],
    "css": lambda p: ["ccss", str(p)],
}
MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "text/css": ".css",
    "application/javascript": ".js",
    "text/javascript": ".js",
}
EXT_TO_TYPE: dict[str, str] = {
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".webp": "webp",
    ".svg": "svg",
    ".css": "css",
    ".js": "js",
}
TYPE_TO_NEW_MIME: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
    "css": "text/css",
    "js": "application/javascript",
}
DATA_URI_RE = re.compile(
    r"data:"
    r"(?P<mime>"
    r"image/(?:png|jpe?g|webp|svg\+xml)"
    r"|text/css"
    r"|(?:application|text)/javascript"
    r")"
    r";base64,"
    r"(?P<data>[A-Za-z0-9+/=]+)",
)


def run_tool(cmd: list[str], desc: str) -> bool:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error(
                f"{desc} failed (rc={result.returncode}): {result.stderr.strip()[:300]}"
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"{desc} timed out after {TOOL_TIMEOUT}s")
        return False
    except FileNotFoundError:
        logger.error(f"{desc}: '{cmd[0]}' not found in PATH")
        return False
    except Exception as e:
        logger.error(f"{desc}: {e}")
        return False


def optimize_resource(mime: str, data: bytes) -> tuple[bytes | None, str | None]:
    ext = MIME_TO_EXT.get(mime)
    if ext is None:
        logger.warning(f"Unsupported MIME type: {mime}")
        return None, None
    rtype = EXT_TO_TYPE.get(ext)
    if rtype is None:
        return None, None
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    tmp_file = Path(tmp_path)
    tmp_file.write_bytes(data)
    files_to_clean: list[Path] = [tmp_file]
    result_file = tmp_file
    new_mime = TYPE_TO_NEW_MIME.get(rtype, mime)
    try:
        if rtype == "png":
            if not run_tool(TOOL_COMMANDS["png"](tmp_file), "pngq"):
                return None, None
        elif rtype == "jpg":
            if not run_tool(TOOL_COMMANDS["jpg"](tmp_file), "jpegoptim"):
                return None, None
        elif rtype == "webp":
            jpg_file = tmp_file.with_suffix(".jpg")
            if not run_tool(TOOL_COMMANDS["webp_to_jpg"](tmp_file, jpg_file), "to_jpg"):
                return None, None
            if not jpg_file.exists():
                logger.error(f"to_jpg did not produce output: {jpg_file}")
                return None, None
            files_to_clean.append(jpg_file)
            if not run_tool(TOOL_COMMANDS["jpg"](jpg_file), "jpegoptim"):
                return None, None
            result_file = jpg_file
            new_mime = "image/jpeg"
        elif rtype == "svg":
            if not run_tool(TOOL_COMMANDS["svg"](tmp_file), "svgo"):
                return None, None
        elif rtype == "css":
            if not run_tool(TOOL_COMMANDS["css"](tmp_file), "ccss"):
                return None, None
        elif rtype == "js" and not run_tool(TOOL_COMMANDS["js"](tmp_file), "ter_ser"):
            return None, None
        if not result_file.exists():
            logger.error(f"Result file missing after optimization: {result_file}")
            return None, None
        optimized = result_file.read_bytes()
        return optimized, new_mime
    finally:
        for f in files_to_clean:
            with contextlib.suppress(Exception):
                f.unlink(missing_ok=True)


def process_file(path: Path) -> dict:
    stats: dict = {
        "file": str(path),
        "original_size": 0,
        "new_size": 0,
        "resources_found": 0,
        "resources_optimized": 0,
        "space_freed": 0,
        "error": None,
    }
    try:
        original_bytes = path.read_bytes()
        original_size = len(original_bytes)
        stats["original_size"] = original_size
        text = original_bytes.decode("utf-8", errors="replace")
        matches = list(DATA_URI_RE.finditer(text))
        stats["resources_found"] = len(matches)
        if not matches:
            return stats
        parts: list[str] = []
        offset = 0
        optimized_count = 0
        for match in matches:
            parts.append(text[offset : match.start()])
            mime = match.group("mime")
            b64_data = match.group("data")
            try:
                raw = base64.b64decode(b64_data)
            except Exception as e:
                logger.warning(f"Base64 decode failed in {path.name}: {e}")
                parts.append(match.group(0))
                offset = match.end()
                continue
            is_webp = MIME_TO_EXT.get(mime) == ".webp"
            optimized, new_mime = optimize_resource(mime, raw)
            if optimized is not None and (is_webp or len(optimized) < len(raw)):
                new_b64 = base64.b64encode(optimized).decode("ascii")
                parts.append(f"data:{new_mime};base64,{new_b64}")
                optimized_count += 1
            else:
                parts.append(match.group(0))
                if optimized is not None and not is_webp:
                    logger.debug(
                        f"No size improvement for {mime} in {path.name} ({len(optimized)} >= {len(raw)})"
                    )
            offset = match.end()
        parts.append(text[offset:])
        if optimized_count > 0:
            new_text = "".join(parts)
            new_bytes = new_text.encode("utf-8")
            new_size = len(new_bytes)
            path.write_bytes(new_bytes)
            stats["new_size"] = new_size
            stats["resources_optimized"] = optimized_count
            stats["space_freed"] = original_size - new_size
        else:
            stats["new_size"] = original_size
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
        stats["error"] = str(e)
    return stats


def find_source_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS:
            files.append(p)
        elif p.is_dir():
            for ext in SOURCE_EXTENSIONS:
                files.extend(p.rglob(f"*{ext}"))
                files.extend(p.rglob(f"*{ext.upper()}"))
        else:
            logger.warning(f"Path not found: {p}")
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(f)
    return unique


def print_file_stats(stats: dict) -> None:
    name = Path(stats["file"]).name
    if stats["error"]:
        print(f"  ✗ {name} — ERROR: {stats['error']}")
        return
    found = stats["resources_found"]
    opt = stats["resources_optimized"]
    freed = stats["space_freed"]
    if found == 0:
        print(f"  · {name} — no embedded resources")
    elif opt == 0:
        print(f"  · {name} — {found} resource(s), none optimized")
    else:
        print(f"  ✓ {name} — {opt}/{found} optimized, freed {fsz(freed)}")


def print_summary(all_stats: list[dict]) -> None:
    total = len(all_stats)
    errors = sum(1 for s in all_stats if s["error"])
    total_found = sum(s["resources_found"] for s in all_stats)
    total_opt = sum(s["resources_optimized"] for s in all_stats)
    total_freed = sum(s["space_freed"] for s in all_stats)
    print("\n" + "=" * 40)
    print("Summary")
    print("-" * 40)
    print(f"  Files processed      : {total}")
    print(f"  Errors               : {errors}")
    print(f"  Resources found      : {total_found}")
    print(f"  Resources optimized  : {total_opt}")
    print(f"  Total space freed    : {fsz(total_freed)}")
    print("=" * 40)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract, optimize, and re-embed base64 resources in CSS/HTML/JS files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                     Process current dir recursively
  %(prog)s ./src/ ./assets/    Process specific directories
  %(prog)s a.css b.html        Process specific files
  %(prog)s -j 8 ./assets/      Use 8 parallel workers
  %(prog)s --dry-run           List files without processing
""",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Files or directories (default: current directory, recursive)",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be processed",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "WARNING",
        format="<level>{level:<7}</level> | {message}",
    )
    input_paths = args.inputs if args.inputs else [Path.cwd()]
    source_files = find_source_files(input_paths)
    if not source_files:
        print("No CSS/HTML/JS files found.")
        return
    print(f"Found {len(source_files)} file(s) to process.\n")
    if args.dry_run:
        for f in source_files:
            print(f"  {f}")
        return
    results = Parallel(n_jobs=args.workers, prefer="threads")(
        delayed(process_file)(f) for f in source_files
    )
    for s in results:
        print_file_stats(s)
    print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main())
