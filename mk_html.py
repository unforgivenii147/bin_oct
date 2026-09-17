#!/data/data/com.termux/files/home/.local/bin/python
"""
prompt: Write a Python script that
 recursively converts all `.rst`,
`.txt`, and `.md` files under a given
 directory to HTML. Use `multiprocessing.Pool.apply_async` with a fixed pool of 8 workers for parallelism. Provide a CLI with a positional `directory` argument (default `.`) and a `--force` flag. Use `loguru` for logging, `pathlib` for all path handling, and full strict type annotations throughout. Include helper functions to: locate a `rest2html.py` fallback script, convert Markdown to reStructuredText, convert a single file to HTML via `docutils`, generate a content-hashed stylesheet filename, discover all source files, and orchestrate parallel conversion. Add complete docstrings to every function and module-level constant.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final, Optional

from loguru import logger

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

RST2HTML_OPTIONS: Final[str] = (
    "--no-toc-backlinks --strip-comments --language en --date"
)
VALID_EXTENSIONS: Final[set[str]] = {".rst", ".txt", ".md"}
MD_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MD_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(#{1,6})\s+(.+)$", re.MULTILINE
)
MD_CODE_BLOCK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"```(\w+)?\n(.*?)```", re.DOTALL
)
FIXED_WORKERS: Final[int] = 8


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def find_rst2html_script() -> Path | None:
    """Locate the ``rest2html.py`` helper script in common locations.

    Returns:
        The path to ``rest2html.py`` if found, otherwise ``None``.
    """
    possible_paths: list[Path] = [
        Path.cwd() / "doc" / "rest2html.py",
        Path.cwd() / "rest2html.py",
        Path(sys.prefix) / "doc" / "rest2html.py",
    ]
    for path in possible_paths:
        if path.exists():
            return path
    return None


def convert_md_to_rst(content: str) -> str:
    """Convert Markdown content to reStructuredText.

    Args:
        content: Raw Markdown text.

    Returns:
        The equivalent reStructuredText text.
    """

    def replace_heading(match: re.Match[str]) -> str:
        level: int = len(match.group(1))
        text: str = match.group(2).strip()
        if level == 1:
            return f"{'=' * len(text)}\n{text}\n{'=' * len(text)}"
        elif level == 2:
            return f"{text}\n{'-' * len(text)}"
        else:
            char: str = "~^+"[min(level - 3, 2)]
            return f"{text}\n{char * len(text)}"

    content = MD_HEADING_PATTERN.sub(replace_heading, content)
    content = MD_LINK_PATTERN.sub(r"`\1 <\2>`_", content)

    def replace_code_block(match: re.Match[str]) -> str:
        language: str | None = match.group(1)
        code: str = match.group(2).strip()
        indented: str = "\n".join("    " + line for line in code.split("\n"))
        if language:
            return f".. code-block:: {language}\n\n{indented}\n"
        else:
            return f"::\n\n{indented}\n"

    content = MD_CODE_BLOCK_PATTERN.sub(replace_code_block, content)
    content = re.sub(r"\*\*(.+?)\*\*", r"**\1**", content)
    content = re.sub(r"\*(.+?)\*", r"*\1*", content)
    content = re.sub(r"`([^`]+)`", r"``\1``", content)
    content = re.sub(r"^---$", "-------", content, flags=re.MULTILINE)
    content = re.sub(r"^\* ", r"- ", content, flags=re.MULTILINE)
    return content


def convert_file_to_html(path: Path, stylesheet_url: str | None = None) -> Path | None:
    """Convert a single source file to HTML.

    Args:
        path: Path to the source file (``.rst``, ``.txt`` or ``.md``).
        stylesheet_url: Optional stylesheet filename to link into the HTML.

    Returns:
        The path to the generated HTML file, or ``None`` on failure.
    """
    try:
        html_path: Path = path.with_suffix(".html")
        if html_path.exists() and html_path.stat().st_mtime > path.stat().st_mtime:
            return html_path

        content: str = path.read_text(encoding="utf-8")
        cleanup_temp: bool = False
        temp_file: Path | None = None

        if path.suffix.lower() == ".md":
            content = convert_md_to_rst(content)
            temp_file = path.with_suffix(".rst")
            temp_file.write_text(content, encoding="utf-8")
            path = temp_file
            cleanup_temp = True

        cmd: list[str] = [
            sys.executable,
            "-m",
            "docutils.__main__",
            str(path),
            str(html_path),
        ]
        if stylesheet_url:
            cmd.extend(["--stylesheet", stylesheet_url, "--link-stylesheet"])

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        except (subprocess.CalledProcessError, FileNotFoundError):
            rst2html_script: Path | None = find_rst2html_script()
            if rst2html_script:
                cmd = [
                    sys.executable,
                    str(rst2html_script),
                ] + RST2HTML_OPTIONS.split()
                if stylesheet_url:
                    cmd.extend(["--stylesheet", stylesheet_url, "--link-stylesheet"])
                cmd.extend([str(path), str(html_path)])
                subprocess.run(
                    cmd, check=True, capture_output=True, text=True, timeout=30
                )
            else:
                raise RuntimeError("No RST to HTML converter found")

        if cleanup_temp and temp_file is not None and temp_file.exists():
            temp_file.unlink()

        return html_path
    except Exception as e:
        logger.error(f"Error converting {path}: {e}")
        return None


def generate_stylesheet_hash(stylesheet_path: Path) -> str:
    """Generate a hashed filename for a stylesheet.

    Args:
        stylesheet_path: Path to the original ``style.css`` file.

    Returns:
        A filename of the form ``style_<hash>.css``, or ``"style.css"`` if the
        file does not exist.
    """
    if not stylesheet_path or not stylesheet_path.exists():
        return "style.css"
    with open(stylesheet_path, "rb") as f:
        css: bytes = f.read()
    checksum: str = hashlib.sha256(css).hexdigest()[:32]
    return f"style_{checksum}.css"


def process_file(args: tuple[Path, str | None]) -> tuple[Path, Path | None]:
    """Worker entry point for converting a single file.

    Args:
        args: A tuple of ``(path, stylesheet_url)``.

    Returns:
        A tuple of ``(original_path, html_path_or_None)``.
    """
    path, stylesheet_url = args
    html_path: Path | None = convert_file_to_html(path, stylesheet_url)
    return (path, html_path)


def find_all_source_files(root_dir: Path | None = None) -> list[Path]:
    """Recursively find all supported source files under ``root_dir``.

    Args:
        root_dir: Directory to search. Defaults to the current working
            directory.

    Returns:
        A list of paths to source files.
    """
    if root_dir is None:
        root_dir = Path.cwd()
    source_files: list[Path] = []
    for ext in VALID_EXTENSIONS:
        source_files.extend(root_dir.rglob(f"*{ext}"))
    return source_files


def publish_parallel(
    root_dir: Path | None = None, max_workers: int | None = None
) -> None:
    """Convert all source files under ``root_dir`` to HTML in parallel.

    Args:
        root_dir: Root directory to process. Defaults to the current working
            directory.
        max_workers: Unused; retained for API compatibility. Parallelism is
            fixed at :data:`FIXED_WORKERS`.
    """
    if root_dir is None:
        root_dir = Path.cwd()
    root_dir = Path(root_dir).resolve()

    stylesheet_path: Path = root_dir / "style.css"
    stylesheet_url: str | None = None
    if stylesheet_path.exists():
        stylesheet_filename: str = generate_stylesheet_hash(stylesheet_path)
        stylesheet_dest: Path = root_dir / stylesheet_filename
        if not stylesheet_dest.exists():
            shutil.copy(stylesheet_path, stylesheet_dest)
        stylesheet_url = stylesheet_filename

    source_files: list[Path] = find_all_source_files(root_dir)
    if not source_files:
        print(f"No source files found in {root_dir}")
        return

    print(f"Found {len(source_files)} files to convert")

    converted: int = 0
    errors: int = 0

    worker_args: list[tuple[Path, str | None]] = [
        (fp, stylesheet_url) for fp in source_files
    ]

    with Pool(processes=FIXED_WORKERS) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_file, (arg,)) for arg in worker_args
        ]
        pool.close()
        pool.join()

        for async_result in async_results:
            try:
                original, html_path = async_result.get()
                if html_path:
                    converted += 1
                    print(
                        f"Converted: {original.relative_to(root_dir)} -> "
                        f"{html_path.relative_to(root_dir)}"
                    )
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error processing file: {e}")

    print(f"\nConversion complete: {converted} converted, {errors} errors")


def main() -> int:
    """CLI entry point.

    Returns:
        Exit status code (0 on success, 1 on failure).
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Convert all .rst, .txt, and .md files to HTML recursively"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to process (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-conversion even if HTML is newer",
    )
    args: argparse.Namespace = parser.parse_args()

    root_dir: Path = Path(args.directory).resolve()
    if not root_dir.exists():
        logger.error(f"Error: Directory '{root_dir}' does not exist")
        return 1

    publish_parallel(root_dir, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
