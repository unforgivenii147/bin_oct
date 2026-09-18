#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import shutil
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path


# re functions whose FIRST positional argument is a regex pattern.
RE_FUNCTIONS: frozenset[str] = frozenset(
    {
        "compile",
        "search",
        "match",
        "fullmatch",
        "split",
        "findall",
        "finditer",
        "sub",
        "subn",
    }
)

# Characters that may appear as a string-literal prefix (r, b, f, u, …).
STRING_PREFIX_CHARS: frozenset[str] = frozenset("rRbBuUfF")


def needs_raw_string(value: str, quote_char: str) -> bool:
    """True iff `value` (the *parsed* content of a string literal) can be
    re-emitted as a raw literal delimited by `quote_char` with the SAME value.

    The whole point: if the parsed value contains a real backslash, then a
    normal literal had to write it as `\\\\`. A raw literal can write it as
    `\\`, which is what we want for regexes.

    Rules:
      • value must contain at least one backslash   (otherwise nothing to gain)
      • value must not END in a backslash           (would escape the quote)
      • delimiter must not appear in value          (else we can't use it)
      • no literal newlines                         (single-line raw only)
    """
    if "\\" not in value:  # parsed value has no backslash
        return False
    if value.endswith("\\"):  # r"foo\"  → the \" would break
        return False
    if quote_char in value:  # delimiter appears → can't use it
        return False
    if "\n" in value or "\r" in value:  # real newline in value
        return False
    return True


def extract_and_convert_strings(content: str) -> str | None:
    """Rewrite regex string literals in `content` as raw strings.

    Returns the new source, or `None` if nothing changed / parse failed.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    # ── 1. Walk the AST, collect every re.<fn>(<str-literal>, ...) site ─────
    conversions: list[tuple[int, int, int, str]] = []  # (line, col, end, value)

    class RegexStringVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "re"
                and func.attr in RE_FUNCTIONS
                and node.args
            ):
                arg = node.args[0]
                # Only plain string literals. (f-strings are JoinedStr,
                # bytes are Constant[bytes] — both filtered out here.)
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.end_col_offset is not None
                ):
                    conversions.append(
                        (arg.lineno, arg.col_offset, arg.end_col_offset, arg.value)
                    )
            self.generic_visit(node)

    RegexStringVisitor().visit(tree)

    if not conversions:
        return None

    # ── 2. Apply edits right-to-left per line so earlier offsets stay valid ──
    lines = content.split("\n")
    converted = False

    # Sort so that, on the same line, we process the rightmost first.
    conversions.sort(key=lambda c: (c[0], -c[1]))

    for lineno, col_start, col_end, value in conversions:
        li = lineno - 1
        if not (0 <= li < len(lines)):
            continue

        line = lines[li]
        original = line[col_start:col_end]

        # ── parse prefix (r / b / f / u combinations) ───────────────────
        i = 0
        while i < len(original) and original[i] in STRING_PREFIX_CHARS:
            i += 1
        prefix = original[:i]

        # Already raw → skip.  Bytes → not our problem.  f-string → skip.
        if "r" in prefix.lower() or "b" in prefix.lower() or "f" in prefix.lower():
            continue

        if i >= len(original):
            continue
        quote = original[i]  # ' or "
        if quote not in ("'", '"'):
            continue
        # Leave triple-quoted literals alone (different rules).
        if original[i : i + 3] in ('"""', "'''"):
            continue

        # ── decide ──────────────────────────────────────────────────────
        if not needs_raw_string(value, quote):
            continue

        new_literal = f"r{quote}{value}{quote}"
        lines[li] = line[:col_start] + new_literal + line[col_end:]
        converted = True

    if not converted:
        return None
    return "\n".join(lines)


def validate_python_file(content: str) -> bool:
    """Return True iff `content` parses as valid Python."""
    try:
        ast.parse(content)
        return True
    except SyntaxError:
        return False


def process_file(path: Path, create_backup: bool = True) -> tuple[Path, bool, str]:
    """Convert one file. Returns (path, success, human-readable message)."""
    try:
        original_content = path.read_text(encoding="utf-8")
    except Exception as e:
        return (path, False, f"Failed to read: {e}")

    # Cheap pre-filter: without any `re.` there can be no target calls.
    if "re." not in original_content:
        return (path, True, "No re calls found")

    converted_content = extract_and_convert_strings(original_content)
    if converted_content is None:
        return (path, True, "No changes needed")

    # Never write broken code.
    if not validate_python_file(converted_content):
        return (path, False, "Validation failed - syntax error after conversion")

    try:
        if create_backup:
            backup_path = path.with_suffix(path.suffix + ".backup")
            shutil.copy2(path, backup_path)
        path.write_text(converted_content, encoding="utf-8")
        return (path, True, "✓ Converted and saved")
    except Exception as e:
        return (path, False, f"Failed to write: {e}")


def collect_python_files(inputs: list[Path]) -> list[Path]:
    """Recursively collect .py files, skipping virtualenvs / caches."""
    skip_dirs = {".venv", "venv", "env", "__pycache__", ".git", "node_modules"}
    python_files: set[Path] = set()

    for input_path in inputs:
        if not input_path.exists():
            print(f"Warning: Path does not exist: {input_path}", file=sys.stderr)
            continue
        if input_path.is_file():
            if input_path.suffix == ".py":
                python_files.add(input_path)
        elif input_path.is_dir():
            for py_file in input_path.rglob("*.py"):
                if any(part in skip_dirs for part in py_file.parts):
                    continue
                python_files.add(py_file)

    return sorted(python_files)


def parse_arguments() -> tuple[list[Path], bool, int]:
    """Return (paths, create_backup, num_workers)."""
    args = sys.argv[1:]

    create_backup = True
    if "--no-backup" in args:
        create_backup = False
        args.remove("--no-backup")

    num_workers = min(cpu_count(), 4)
    if "--workers" in args:
        i = args.index("--workers")
        if i + 1 < len(args):
            try:
                num_workers = int(args[i + 1])
            except ValueError:
                pass
            args.pop(i + 1)  # value
            args.pop(i)  # flag

    paths = [Path(a).resolve() for a in args] if args else [Path.cwd()]
    return (paths, create_backup, num_workers)


def main() -> int:
    paths, create_backup, num_workers = parse_arguments()
    python_files = collect_python_files(paths)

    if not python_files:
        print("No Python files found")
        return 1

    print(f"Found {len(python_files)} Python files")
    print(f"Processing with {num_workers} workers")
    print(f"Backup: {'Enabled' if create_backup else 'Disabled'}")
    print(f"Target re functions: {', '.join(sorted(RE_FUNCTIONS))}\n")

    results: list[tuple[Path, bool, str]] = []
    total = len(python_files)

    if num_workers > 1:
        with Pool(processes=num_workers) as pool:
            results = pool.starmap(
                process_file, [(f, create_backup) for f in python_files]
            )
    else:
        for i, path in enumerate(python_files, 1):
            if i % 100 == 0:
                print(f"Progress: {i}/{total}", flush=True)
            results.append(process_file(path, create_backup))

    successful = sum(1 for _, ok, _ in results if ok)
    changed = sum(1 for _, ok, m in results if ok and "Converted" in m)

    print("\n" + "=" * 40)
    for path, ok, message in results:
        mark = "✓" if ok else "✗"
        try:
            shown: Path | str = path.relative_to(Path.cwd())
        except ValueError:
            shown = path
        print(f"{mark} {shown}: {message}")
    print("-" * 40)

    print("\nSummary:")
    print(f"  Total files: {len(python_files)}")
    print(f"  Processed successfully: {successful}")
    print(f"  Files converted: {changed}")
    if not create_backup:
        print("\n⚠️  Backup disabled. Use --no-backup with caution.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
