#!/data/data/com.termux/files/home/.local/bin/python
"""
Extract Python code blocks from documentation and metadata files (PKGINFO,
METADATA, PKG-INFO, or `.md` / `.txt` / `.html`) and save each block as its own
`.py` file under `./extracted_code/`. Recognizes fenced ```python blocks,
standalone ```...``` fenced snippets, `>>>` REPL sessions, and (for
package-metadata files with no other matches) bare inline `import`/`def`/`class`
statements. Uses a fixed multiprocessing.Pool of 8 workers; logging via loguru.
"""

import re
import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

TARGET_NAMES: Final[frozenset[str]] = frozenset({"PKGINFO", "METADATA", "PKG-INFO"})
TARGET_EXTENSIONS: Final[frozenset[str]] = frozenset({".md", ".txt", ".html"})

MAX_WORKERS: Final[int] = 8
OUTPUT_DIR: Final[Path] = Path("extracted_code")

PY_CODE_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"```python\s*\n(.*?)```" r"\"\"\"(.*?)\"\"\"",
    re.DOTALL | re.IGNORECASE,
)
INLINE_PY: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\n)((?:import\s+\w+|from\s+\w+\s+import|def\s+\w+|class\s+\w+).*?)"
    r"(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
REPL_SESSION: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\n)((?:>>>|\.\.\.).*?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)

ProcessResult = tuple[Path, list[Path]]


def _is_target(file_path: Path) -> bool:
    """
    Decide whether ``file_path`` is a file we should scan for code blocks.

    Args:
        file_path: Candidate file path.

    Returns:
        ``True`` if the filename is in :data:`TARGET_NAMES` or its suffix is in
        :data:`TARGET_EXTENSIONS`.
    """
    if file_path.name in TARGET_NAMES:
        return True
    return file_path.suffix.lower() in TARGET_EXTENSIONS


def find_target_files(paths: list[str]) -> list[Path]:
    """
    Expand CLI paths into a list of target files.

    Args:
        paths: Raw path strings from the command line; files are checked
            directly, directories are searched recursively.

    Returns:
        A de-duplicated, sorted list of matching file paths.
    """
    found: set[Path] = set()

    for p in paths:
        path: Path = Path(p)
        if path.is_file():
            if _is_target(path):
                found.add(path)
        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and _is_target(candidate):
                    found.add(candidate)

    return sorted(found)


def parse_repl_block(block: str) -> str:
    """
    Convert an interactive ``>>>`` / ``...`` session into plain Python source.

    Continuation lines belonging to the REPL result are prefixed with ``#`` so
    they remain valid Python comments rather than becoming syntax errors.

    Args:
        block: A REPL session string including the ``>>>``/``...`` prompts.

    Returns:
        The reconstructed Python source with prompts stripped.
    """
    lines: list[str] = block.strip().split("\n")
    result_lines: list[str] = []
    in_code: bool = False

    for line in lines:
        stripped: str = line.strip()
        if stripped.startswith((">>>", "...")):
            code: str = stripped[3:].strip()
            result_lines.append(code)
            in_code = True
        elif in_code and stripped:
            result_lines.append(f"# {stripped}")
        elif not stripped:
            result_lines.append("")

    return "\n".join(result_lines)


def extract_python_blocks(file_path: Path) -> list[str]:
    """
    Scan a file and return every Python block it contains.

    Applies, in order:
      1. The :data:`PY_CODE_BLOCK` fenced-code regex.
      2. The :data:`REPL_SESSION` regex (dedicated ``>>>`` blocks).
      3. For metadata files with no other matches, the :data:`INLINE_PY` regex.

    Args:
        file_path: File to scan.

    Returns:
        A list of extracted Python source snippets. Empty if the file cannot
        be read or contains no recognizable blocks.
    """
    try:
        content: str = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []

    blocks: list[str] = []

    for match in PY_CODE_BLOCK.finditer(content):
        code: str = match.group(1).strip()
        if code:
            if ">>>" in code:
                code = parse_repl_block(code)
            blocks.append(code)

    for match in REPL_SESSION.finditer(content):
        code = parse_repl_block(match.group(1))
        if code.strip():
            blocks.append(code)

    if not blocks and file_path.name in TARGET_NAMES:
        for match in INLINE_PY.finditer(content):
            code = match.group(1).strip()
            if code and ("import" in code or "def " in code or "class " in code):
                blocks.append(code)

    return blocks


def process_file(file_path: Path, output_dir: Path) -> ProcessResult:
    """
    Extract all Python blocks from a file and write each to its own ``.py`` file.

    Output files are named ``{stem}_{idx:03d}.py`` and carry a header comment
    naming the source file and block index.

    Args:
        file_path: Source file to scan.
        output_dir: Directory to write extracted files into.

    Returns:
        A tuple ``(source_path, saved_paths)`` where ``saved_paths`` is the
        list of ``.py`` files written for this source.
    """
    blocks: list[str] = extract_python_blocks(file_path)
    saved: list[Path] = []

    for idx, code in enumerate(blocks, 1):
        stem: str = file_path.stem.replace(" ", "_")
        out_name: str = f"{stem}_{idx:03d}.py"
        out_path: Path = output_dir / out_name

        header: str = (
            f"# Source: {file_path}\n# Block: {idx}\n# Extracted: {file_path.name}\n\n"
        )
        out_path.write_text(header + code + "\n", encoding="utf-8")
        saved.append(out_path)

    return file_path, saved


def main() -> None:
    """Parse CLI paths, find targets, and extract Python blocks in parallel."""
    input_paths: list[str] = sys.argv[1:] if len(sys.argv) > 1 else ["."]

    OUTPUT_DIR.mkdir(exist_ok=True)

    target_files: list[Path] = find_target_files(input_paths)
    if not target_files:
        print("No target files found.")
        return

    print(f"Found {len(target_files)} target files. Processing...")

    results: list[ProcessResult] = []

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[ProcessResult]] = [
            pool.apply_async(process_file, (f, OUTPUT_DIR)) for f in target_files
        ]
        for async_res in async_results:
            file_path, saved = async_res.get()
            results.append((file_path, saved))
            print(f"  ✓ {file_path}: {len(saved)} block(s) extracted")

    total_blocks: int = sum(len(saved) for _, saved in results)
    print(f"Done! Extracted {total_blocks} Python block(s) to '{OUTPUT_DIR}/'")
    print("Reference headers in each file indicate the source.")


if __name__ == "__main__":
    raise SystemExit(main())
