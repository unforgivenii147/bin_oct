#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that converts Jupyter notebooks (.ipynb) into
standalone Python scripts. The generated script should:

- Recursively discover .ipynb files from CLI-provided paths (files or
  directories), defaulting to the current working directory.
- For each notebook, write a sibling .py file, skipping outputs that already
  exist.
- Convert markdown cells into comment blocks; lift top-level `import ...` /
  `from ...` statements into a header; hoist `os.environ` and `sys.path`
  lines immediately after their matching `import os` / `import sys`
  statements; and comment out IPython magics and shell escapes (`%`, `!`,
  `%%`) as `# [MAGIC] ...` lines, honoring backslash continuations.
- Wrap the remaining body inside an `if __name__ == '__main__':` block.
- Process files concurrently with multiprocessing.Pool.apply_async using a
  fixed pool of 8 workers (no CLI flag controls parallelism).
- Use loguru for all logging output.
- Include complete type annotations, docstrings on all functions, and this
  module-level docstring.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import List, Optional

import nbformat
from loguru import logger
from nbformat import NotebookNode

POOL_SIZE: int = 8
MAGIC_PREFIXES: tuple[str, ...] = ("%", "!", "%%")
IMPORT_PREFIXES: tuple[str, ...] = ("import ", "from ")


def is_import_line(line: str) -> bool:
    """Return True if ``line`` begins a top-level import statement."""
    return line.startswith(IMPORT_PREFIXES)


def strip_magics(source: str) -> str:
    """Comment out IPython magics and shell escapes in ``source``.

    Lines starting with ``%``, ``!`` or ``%%`` are replaced with a
    ``# [MAGIC] ...`` comment, and backslash line continuations that follow
    are also commented out.
    """
    lines: list[str] = source.split("\n")
    result: list[str] = []
    i: int = 0
    while i < len(lines):
        line: str = lines[i]
        stripped: str = line.lstrip()
        if stripped.startswith(MAGIC_PREFIXES):
            result.append(f"# [MAGIC] {line.rstrip()}")
            while i < len(lines) - 1 and line.rstrip().endswith("\\"):
                i += 1
                line = lines[i]
                result.append(f"# [MAGIC] {line.rstrip()}")
        else:
            result.append(line)
        i += 1
    return "\n".join(result)


def nb2py(notebook: NotebookNode) -> str:
    """Convert a parsed notebook into a standalone Python script."""
    imports: list[str] = []
    os_mods: list[str] = []
    sys_mods: list[str] = []
    main_code: list[str] = []

    cell: NotebookNode
    for cell in notebook.cells:
        if cell.cell_type == "markdown":
            md_text: str = str(cell.source).replace("\n", "\n# ")
            main_code.append(f"# {md_text}\n")
        elif cell.cell_type == "code":
            cell_code: str = str(cell.source)
            line: str
            for line in cell_code.split("\n"):
                if line.strip().startswith("!nb2py"):
                    continue
                if is_import_line(line):
                    imports.append(line)
                    continue
                if line.startswith("os.environ"):
                    os_mods.append(line)
                    continue
                if line.startswith("sys.path"):
                    sys_mods.append(line)
                    continue
                cleaned: str = strip_magics(line)
                main_code.append(cleaned)

    idx: int
    line = ""
    for idx, line in enumerate(imports):
        if "import os" in line or "from os import" in line:
            for mod in sorted(os_mods, reverse=True):
                imports.insert(idx + 1, mod)
            break
    for idx, line in enumerate(imports):
        if "import sys" in line or "from sys import" in line:
            for mod in sorted(sys_mods, reverse=True):
                imports.insert(idx + 1, mod)
            break

    imports_str: str = "\n".join(imports) + "\n\n"
    main_str: str = "\n".join(main_code)
    indent: str = "    "
    main_indented: str = "\n".join(f"{indent}{ln}" for ln in main_str.split("\n"))
    return f"{imports_str}if __name__ == '__main__':\n{main_indented}"


def process_file(path: Path) -> str | None:
    """Convert a single ``.ipynb`` file to a sibling ``.py`` file.

    Args:
        path: Path to the notebook to convert.

    Returns:
        A status message if the notebook was exported, or ``None`` if the
        target ``.py`` file already existed.
    """
    path = Path(path)
    fo: Path = path.with_suffix(".py")
    if fo.exists():
        return None
    with path.open(encoding="utf-8") as f:
        nb: NotebookNode = nbformat.read(f, as_version=4)
    py_code: str = nb2py(nb)
    with fo.open("w", encoding="utf-8") as out:
        out.write(py_code)
    return f"Exported → {fo.name}"


def _collect_files(args: Sequence[str]) -> list[Path]:
    """Resolve CLI arguments into a list of ``.ipynb`` files.

    Args:
        args: Raw CLI arguments. If empty, all ``.ipynb`` files under the
            current working directory are returned.

    Returns:
        A list of candidate notebook paths.
    """
    if not args:
        return list(Path.cwd().rglob("*.ipynb"))

    files: list[Path] = []
    arg: str
    for arg in args:
        p: Path = Path(arg)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*.ipynb"))
    return files


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point: convert notebooks to Python scripts in parallel.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    args: list[str] = list(argv) if argv is not None else sys.argv[1:]
    files: list[Path] = _collect_files(args)

    if not files:
        logger.info("No .ipynb files found")
        return 0

    logger.info(
        "Found {} notebook(s) to convert using {} workers", len(files), POOL_SIZE
    )

    with Pool(processes=POOL_SIZE) as pool:
        results = [pool.apply_async(process_file, (f,)) for f in files]
        result: AsyncResult[str | None]  # noqa: F821
        for result in results:
            message: str | None = result.get()
            if message:
                logger.info("{}", message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
