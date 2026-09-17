#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dh import cprint


class TransformationType(Enum):
    SIMPLE_REPLACE = "simple"
    FUNCTION_CALL = "function"
    JOIN_OPERATOR = "join"
    CONTEXT_DEPENDENT = "context"


@dataclass
class Transformation:
    pattern: str
    replacement: Callable[[re.Match], str]
    type: TransformationType
    requires_import: bool = True
    description: str = ""


class PathlibRefactorer:
    def __init__(self) -> None:
        self.transformations: list[Transformation] = []
        self._setup_transformations()
        self.used_transformations: set[str] = set()

    def _setup_transformations(self) -> None:
        simple_replacements = {
            "\\bos\\.getcwd\\s*\\(\\s*\\)": "Path.cwd()",
            "\\bos\\.path\\.abspath\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).resolve()",
            "\\bos\\.path\\.realpath\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).resolve()",
            "\\bos\\.path\\.basename\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).name",
            "\\bos\\.path\\.dirname\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).parent",
            "\\bos\\.path\\.exists\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).exists()",
            "\\bos\\.path\\.isdir\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).is_dir()",
            "\\bos\\.path\\.isfile\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).is_file()",
            "\\bos\\.path\\.getmtime\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).stat().st_mtime",
            "\\bos\\.path\\.getsize\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).stat().st_size",
            "\\bos\\.path\\.expanduser\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).expanduser()",
            "\\bos\\.path\\.expandvars\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).expandvars()",
        }
        for pattern, replacement in simple_replacements.items():
            self.transformations.append(
                Transformation(
                    pattern=pattern,
                    replacement=lambda m, r=replacement: re.sub(
                        r"\\\\(\\d+)", lambda x: m.group(int(x.group(1))), r
                    ),
                    type=TransformationType.SIMPLE_REPLACE,
                    description=f"Replace {pattern}",
                )
            )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.path\\.join\\s*\\(\\s*([^)]+)\\s*\\)",
                replacement=self._transform_join,
                type=TransformationType.JOIN_OPERATOR,
                description="Convert os.path.join to Path / operator",
            )
        )
        self.transformations.append(
            Transformation(
                pattern=r"\bos\.path\.split\s*\(\s*([^)]+)\s*\)",
                replacement=lambda m: (
                    f"(str(Path({m.group(1)}).parent), Path({m.group(1)}).name)"
                ),
                type=TransformationType.FUNCTION_CALL,
                description="Convert os.path.split to tuple of parent/name",
            )
        )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.path\\.relpath\\s*\\(\\s*([^,]+)(?:,\\s*([^)]+))?\\s*\\)",
                replacement=lambda m: (
                    f"Path({m.group(1)}).resolve().relative_to(Path({m.group(2) if m.group(2) else '.'}).resolve())"
                ),
                type=TransformationType.FUNCTION_CALL,
                description="Convert os.path.relpath to relative_to",
            )
        )
        file_ops = {
            "\\bos\\.remove\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).unlink()",
            "\\bos\\.unlink\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).unlink()",
            "\\bos\\.rmdir\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).rmdir()",
            "\\bos\\.mkdir\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).mkdir(parents=False, exist_ok=False)",
            "\\bos\\.stat\\s*\\(\\s*([^)]+)\\s*\\)": "Path(\\1).stat()",
        }
        for pattern, replacement in file_ops.items():
            self.transformations.append(
                Transformation(
                    pattern=pattern,
                    replacement=lambda m, r=replacement: re.sub(
                        r"\\\\(\\d+)", lambda x: m.group(int(x.group(1))), r
                    ),
                    type=TransformationType.SIMPLE_REPLACE,
                    description=f"Replace {pattern}",
                )
            )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.makedirs\\s*\\(\\s*([^,]+)(?:,\\s*([^)]+))?\\s*\\)",
                replacement=self._transform_makedirs,
                type=TransformationType.CONTEXT_DEPENDENT,
                description="Convert os.makedirs to mkdir(parents=True)",
            )
        )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.rename\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)",
                replacement=lambda m: f"Path({m.group(1)}).rename({m.group(2)})",
                type=TransformationType.FUNCTION_CALL,
                description="Convert os.rename to Path.rename",
            )
        )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.replace\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)",
                replacement=lambda m: f"Path({m.group(1)}).replace({m.group(2)})",
                type=TransformationType.FUNCTION_CALL,
                description="Convert os.replace to Path.replace",
            )
        )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.listdir\\s*\\(\\s*([^)]*)\\s*\\)",
                replacement=lambda m: (
                    f"list(Path({m.group(1) if m.group(1) else '.'}).iterdir())"
                ),
                type=TransformationType.FUNCTION_CALL,
                description="Convert os.listdir to Path.iterdir()",
            )
        )
        self.transformations.append(
            Transformation(
                pattern="\\bos\\.walk\\s*\\(\\s*([^)]+)\\s*\\)",
                replacement=self._transform_walk,
                type=TransformationType.CONTEXT_DEPENDENT,
                description="Convert os.walk to Path.rglob (limited support)",
            )
        )

    def _transform_join(self, match: re.Match) -> str:
        args = [arg.strip() for arg in match.group(1).split(",") if arg.strip()]
        if not args:
            return "Path()"
        if len(args) == 1:
            return f"Path({args[0]})"
        return " / ".join([f"Path({args[0]})", *args[1:]])

    def _transform_makedirs(self, match: re.Match) -> str:
        path_arg = match.group(1)
        rest_args = match.group(2) if match.group(2) else ""
        if "exist_ok" in rest_args:
            return f"Path({path_arg}).mkdir(parents=True, {rest_args})"
        else:
            return f"Path({path_arg}).mkdir(parents=True, exist_ok=True)"

    def _transform_walk(self, match: re.Match) -> str:
        path_arg = match.group(1)
        return f"((str(p), [d.name for d in p.iterdir() if d.is_dir()], [f.name for f in p.iterdir() if f.is_file()]) for p in Path({path_arg}).rglob('*') if p.is_dir())"

    def apply_transformations(self, source: str) -> tuple[str, set[str]]:
        result = source
        applied = set()
        for trans in self.transformations:
            try:
                new_result = re.sub(trans.pattern, trans.replacement, result)
                if new_result != result:
                    applied.add(trans.description)
                    result = new_result
            except Exception as e:
                cprint(
                    f"  ⚠️ Transformation failed: {trans.description} - {e}", "yellow"
                )
        return result, applied

    def add_pathlib_import(self, source: str) -> str:
        if "from pathlib import Path" in source or "import pathlib" in source:
            return source
        lines = source.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                insert_idx = i + 1
            elif stripped and not stripped.startswith("#"):
                break
        lines.insert(insert_idx, "from pathlib import Path\n")
        return "".join(lines)

    def refactor_file(
        self, path: Path, dry_run: bool = False, create_backup: bool = True
    ) -> dict:
        result = {
            "path": path,
            "success": False,
            "changed": False,
            "transformations_applied": set(),
            "error": None,
            "backup_path": None,
        }
        try:
            original = path.read_text(encoding="utf-8")
            refactored, applied = self.apply_transformations(original)
            if applied:
                refactored = self.add_pathlib_import(refactored)
                try:
                    compile(refactored, path.name, "exec")
                    result["success"] = True
                    result["changed"] = True
                    result["transformations_applied"] = applied
                    if not dry_run:
                        if create_backup:
                            backup = path.with_suffix(path.suffix + ".bak")
                            backup.write_text(original, encoding="utf-8")
                            result["backup_path"] = backup
                        path.write_text(refactored, encoding="utf-8")
                except SyntaxError as e:
                    result["error"] = f"Syntax error after refactoring: {e}"
                    result["success"] = False
            else:
                result["success"] = True
                result["changed"] = False
        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
        return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Refactor Python files from os/path to pathlib"
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to process")
    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )
    args = parser.parse_args()
    if args.paths:
        files = []
        for path_str in args.paths:
            p = Path(path_str)
            if p.is_file() and p.suffix == ".py":
                files.append(p)
            elif p.is_dir():
                files.extend(get_pyfiles(p))
    else:
        files = get_pyfiles(Path.cwd())
    if not files:
        cprint("No Python files found to process.", "yellow")
        return 0
    cprint(f"\n📁 Found {len(files)} Python files to process", "cyan")
    if args.dry_run:
        cprint("🔍 DRY RUN MODE - No files will be modified\n", "yellow")
    refactorer = PathlibRefactorer()
    results = []
    for path in files:
        if args.verbose:
            cprint(f"\nProcessing: {path.name}", "white")
        result = refactorer.refactor_file(
            path, dry_run=args.dry_run, create_backup=not args.no_backup
        )
        results.append(result)
        if result["error"]:
            cprint(f"  ❌ Error: {result['error']}", "red")
        elif result["changed"]:
            cprint(f"  ✅ Refactored: {path.name}", "green")
            if args.verbose:
                for trans in result["transformations_applied"]:
                    cprint(f"     • {trans}", "cyan", attrs=["dark"])
            if result["backup_path"]:
                cprint(
                    f"     📦 Backup: {result['backup_path'].name}",
                    "white",
                    attrs=["dark"],
                )
        elif args.verbose:
            cprint("  ⏭️  No changes needed", "white", attrs=["dark"])
    changed = [r for r in results if r["changed"]]
    errors = [r for r in results if r["error"]]
    cprint("\n" + "=" * 40, "cyan")
    cprint("📊 SUMMARY", "cyan", attrs=["bold"])
    cprint(f"  Total files: {len(files)}", "white")
    cprint(f"  Modified: {len(changed)}", "green" if changed else "white")
    cprint(f"  Errors: {len(errors)}", "red" if errors else "white")
    if args.dry_run and changed:
        cprint(
            "\n⚠️  This was a dry run. Run without --dry-run to apply changes.", "yellow"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
