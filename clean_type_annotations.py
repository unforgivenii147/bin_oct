#!/data/data/com.termux/files/home/.local/bin/python
"""Strip type annotations from Python source files.

The script rewrites ``.py`` files in place using libcst, removing:

* parameter annotations,
* return annotations,
* PEP 695 type parameter lists on functions / classes,
* annotated assignments (``x: int`` and ``x: int = 0``).

Transformed source is validated with :func:`compile` before being written,
so a broken transformation never clobbers the original file.

Usage::

    python strip_annotations.py [PATH ...]

Each PATH may be a ``.py`` file or a directory (searched recursively). If
no paths are supplied, the current working directory is processed
recursively.
"""

import io
import multiprocessing as mp
import os
import sys
import tokenize
from collections.abc import Iterable, Sequence
from pathlib import Path

import libcst as cst


WORKERS = 8
SKIP_DIR_NAMES = frozenset({"__pycache__"})


# ---------------------------------------------------------------------------
# CST transformer
# ---------------------------------------------------------------------------


class TypeAnnotationRemover(cst.CSTTransformer):
    """Strip type annotations from a libcst module tree."""

    # -- parameters -----------------------------------------------------

    def leave_Param(self, original_node, updated_node):
        if updated_node.annotation is None:
            return updated_node
        return updated_node.with_changes(annotation=None)

    # -- functions / classes --------------------------------------------

    def leave_FunctionDef(self, original_node, updated_node):
        changes = {}
        if updated_node.returns is not None:
            changes["returns"] = None
        if getattr(updated_node, "type_parameters", None) is not None:
            changes["type_parameters"] = None
        if not changes:
            return updated_node
        return updated_node.with_changes(**changes)

    def leave_ClassDef(self, original_node, updated_node):
        if getattr(updated_node, "type_parameters", None) is not None:
            return updated_node.with_changes(type_parameters=None)
        return updated_node

    # -- annotated assignments ------------------------------------------

    def leave_AnnAssign(self, original_node, updated_node):
        if updated_node.value is None:
            # ``x: int`` -> drop the whole statement.
            return cst.RemoveFromParent()
        # ``x: int = value`` -> ``x = value``
        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
            semicolon=updated_node.semicolon,
        )

    # -- repair bodies emptied by removals ------------------------------

    def leave_SimpleStatementLine(self, original_node, updated_node):
        if not updated_node.body:
            return cst.RemoveFromParent()
        return updated_node

    def leave_SimpleStatementSuite(self, original_node, updated_node):
        # ``if x: y: int`` style suites.
        if not updated_node.body:
            return updated_node.with_changes(body=[cst.Pass()])
        return updated_node

    def leave_IndentedBlock(self, original_node, updated_node):
        # A class/if/for body must contain at least one statement.
        if not updated_node.body:
            return updated_node.with_changes(
                body=[cst.SimpleStatementLine(body=[cst.Pass()])]
            )
        return updated_node


# ---------------------------------------------------------------------------
# File IO helpers
# ---------------------------------------------------------------------------


def _read_source(path: Path) -> tuple[str, str]:
    """Read a file honouring PEP 263 encoding cookies.

    Returns ``(text, encoding)``. Reading the raw bytes once avoids a
    second syscall while still letting :mod:`tokenize` sniff the encoding.
    """
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding), encoding


def _atomic_write(path: Path, text: str, encoding: str) -> None:
    """Write ``text`` to ``path`` atomically, preserving its mode."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        try:
            os.chmod(tmp, path.stat().st_mode)
        except OSError:
            # Best effort — permissions are not worth failing the run.
            pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Per-file worker
# ---------------------------------------------------------------------------


def process_file(path_str: str) -> tuple[str, str | None, bool]:
    """Process a single file.

    Returns ``(path, error_or_None, changed)``. Errors are reported as
    strings so they pickle cleanly across worker processes.
    """
    path = Path(path_str)

    try:
        source, encoding = _read_source(path)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return path_str, f"read failed: {exc}", False

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path_str, f"parse failed: {exc}", False
    except Exception as exc:  # defensive: never let a worker die silently
        return path_str, f"parse failed: {exc!r}", False

    try:
        new_code = module.visit(TypeAnnotationRemover()).code
    except Exception as exc:  # defensive
        return path_str, f"transform failed: {exc!r}", False

    if new_code == source:
        return path_str, None, False

    # Validate BEFORE touching the file on disk.
    try:
        compile(new_code, str(path), "exec")
    except (SyntaxError, ValueError) as exc:
        return path_str, f"validation failed: {exc}", False

    try:
        _atomic_write(path, new_code, encoding)
    except OSError as exc:
        return path_str, f"write failed: {exc}", False

    return path_str, None, True


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path) -> Iterable[Path]:
    for candidate in root.rglob("*.py"):
        if not candidate.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in candidate.parts):
            continue
        yield candidate


def collect_files(inputs: Sequence[str]) -> list[Path]:
    roots: list[Path] = [Path(p) for p in inputs] if inputs else [Path.cwd()]
    seen: set[Path] = set()
    files: list[Path] = []

    for root in roots:
        if root.is_dir():
            candidates: Iterable[Path] = _iter_python_files(root)
        elif root.is_file():
            if root.suffix != ".py":
                print(f"warning: not a .py file: {root}", file=sys.stderr)
                continue
            candidates = (root,)
        else:
            print(f"warning: path not found: {root}", file=sys.stderr)
            continue

        for path in candidates:
            try:
                key = path.resolve()
            except OSError:
                key = path
            if key in seen:
                continue
            seen.add(key)
            files.append(path)

    # Deterministic ordering => predictable logs and chunk distribution.
    files.sort(key=lambda p: str(p))
    return files


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    files = collect_files(args)

    if not files:
        print("No Python files to process.", file=sys.stderr)
        return 0

    print(
        f"Processing {len(files)} file(s) with {WORKERS} worker(s)...",
        file=sys.stderr,
    )

    tasks = [(str(p),) for p in files]
    # Aim for a handful of chunks per worker to keep the queue balanced.
    chunksize = max(1, len(tasks) // (WORKERS * 4))

    with mp.Pool(processes=WORKERS) as pool:
        results = pool.starmap(process_file, tasks, chunksize=chunksize)

    changed = 0
    unchanged = 0
    errors = 0
    for path_str, error, was_changed in results:
        if error is not None:
            errors += 1
            print(f"ERROR {path_str}: {error}", file=sys.stderr)
        elif was_changed:
            changed += 1
        else:
            unchanged += 1

    print(
        f"Done: {changed} modified, {unchanged} unchanged, {errors} error(s).",
        file=sys.stderr,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
