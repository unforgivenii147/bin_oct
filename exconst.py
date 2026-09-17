#!/data/data/com.termux/files/home/.local/bin/python
"""Extract uppercase module-level constant assignments from Python files using libcst: gather target .py files, parse them in a multiprocessing pool of 8 workers, and report each constant with loguru."""

import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final, NamedTuple

import libcst as cst
from loguru import logger

MAX_WORKERS: Final[int] = 8


class Constant(NamedTuple):
    """A named constant discovered in a source file."""

    name: str
    value: str
    file: Path


def _node_to_source(node: cst.BaseExpression) -> str:
    """Render a CST expression node back to source code."""
    module: cst.Module = cst.Module([cst.SimpleStatementLine([cst.Expr(node)])])
    return module.code.strip()


class ConstantExtractor(cst.CSTVisitor):
    """A CST visitor that collects uppercase assignments as :class:`Constant` records."""

    file_path: Path
    constants: list[Constant]

    def __init__(self, file_path: Path) -> None:
        """Store the file path and initialise an empty constant list."""
        self.file_path = file_path
        self.constants = []

    def visit_Assign(self, node: cst.Assign) -> None:
        """Record uppercase targets assigned at module scope."""
        for target in node.targets:
            if isinstance(target.target, cst.Name):
                name: str = target.target.value
                if name.isupper() and not name.startswith("_"):
                    value: str = _node_to_source(node.value)
                    self.constants.append(Constant(name, value, self.file_path))


def extract_from_file(file_path: Path) -> tuple[Path, list[Constant]]:
    """Parse a Python file and return its path paired with discovered constants.

    Returns an empty list on syntax or decoding errors.
    """
    try:
        source: str = file_path.read_text(encoding="utf-8")
        tree: cst.Module = cst.parse_module(source)
        extractor: ConstantExtractor = ConstantExtractor(file_path)
        tree.walk(extractor)
        return file_path, extractor.constants
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning("Skipping {}: {}", file_path, e)
        return file_path, []


def get_python_files(paths: list[Path]) -> list[Path]:
    """Expand the given paths into a deduplicated list of Python source files."""
    python_files: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            if path not in seen:
                seen.add(path)
                python_files.append(path)
        elif path.is_dir():
            for py_file in path.glob("**/*.py"):
                if py_file not in seen:
                    seen.add(py_file)
                    python_files.append(py_file)
    return python_files


def main() -> None:
    """CLI entry point: find uppercase constants across Python files in parallel."""
    input_paths: list[Path] = (
        [Path(arg) for arg in sys.argv[1:]] if len(sys.argv) > 1 else [Path.cwd()]
    )
    python_files: list[Path] = get_python_files(input_paths)

    if not python_files:
        logger.info("No Python files found")
        return

    constants: dict[Path, list[Constant]] = {}

    with Pool(processes=MAX_WORKERS) as pool:
        for file_path, file_constants in pool.imap_unordered(
            extract_from_file, python_files
        ):
            if file_constants:
                constants[file_path] = file_constants

    for file_path in sorted(constants.keys()):
        logger.info("{}:", file_path)
        for const in sorted(constants[file_path], key=lambda c: c.name):
            logger.info("  {} = {}", const.name, const.value)

    total: int = sum(len(consts) for consts in constants.values())
    logger.info("Total constants found: {}", total)


if __name__ == "__main__":
    raise SystemExit(main())
