#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class SourceLocation(NamedTuple):
    start: int
    end: int


@dataclass(frozen=True)
class CodeEdit:
    location: SourceLocation
    replacement: str
    description: str


class FuturesToPoolMigrator:
    EXECUTOR_CLASSES = {"ThreadPoolExecutor", "ProcessPoolExecutor"}
    HELPER_FUNCTIONS = {"as_completed", "wait", "FIRST_COMPLETED", "ALL_COMPLETED"}
    FUTURE_VARIABLES = {
        "future",
        "f",
        "fut",
        "done",
        "system_future",
        "user_future",
        "future1",
        "future2",
        "result_future",
    }

    def __init__(self, source_code: str):
        self.source = source_code
        self.tree = ast.parse(source_code)
        self.line_offsets = self._compute_line_offsets()
        self.edits: list[CodeEdit] = []
        self.pool_variables: set[str] = set()
        self.imported_executors: set[str] = set()
        self.imported_helpers: set[str] = set()
        self.requires_pool = False
        self.has_direct_concurrent_import = False

    def _compute_line_offsets(self) -> list[int]:
        offsets = [0]
        for line in self.source.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        return offsets

    def _get_location(self, node: ast.AST) -> SourceLocation:
        start = self._position_to_index(node.lineno, node.col_offset)
        end = self._position_to_index(node.end_lineno, node.end_col_offset)
        return SourceLocation(start, end)

    def _position_to_index(self, lineno: int, col_offset: int) -> int:
        line_start = self.line_offsets[lineno - 1]
        line_end = self.source.find("\n", line_start)
        if line_end == -1:
            line_end = len(self.source)
        line = self.source[line_start:line_end]
        prefix = line.encode("utf-8")[:col_offset].decode("utf-8")
        return line_start + len(prefix)

    def migrate(self) -> tuple[str, list[str]]:
        self._analyze_imports()
        self._remove_pool_import_if_exists()
        self._find_pool_variables()
        self._transform_executor_calls()
        self._transform_future_methods()
        self._ensure_max_workers()
        if not self.edits:
            return self.source, []
        return self._apply_edits(), [e.description for e in self.edits]

    def _analyze_imports(self) -> None:
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "concurrent.futures":
                self._handle_import_from(node)
            elif isinstance(node, ast.Import):
                self._handle_import(node)

    def _handle_import_from(self, node: ast.ImportFrom) -> None:
        executors = [
            alias.asname or alias.name
            for alias in node.names
            if alias.name in self.EXECUTOR_CLASSES
        ]
        helpers = [
            alias.asname or alias.name
            for alias in node.names
            if alias.name in self.HELPER_FUNCTIONS
        ]
        if not executors and not helpers:
            return
        self.imported_executors.update(executors)
        self.imported_helpers.update(helpers)
        self.requires_pool = bool(executors)
        replacements = []
        if executors:
            replacements.append("from multiprocessing.pool import Pool")
        if helpers:
            helper_imports = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in node.names
                if alias.name in self.HELPER_FUNCTIONS
            )
            replacements.append(f"from dh import {helper_imports}")
        if replacements:
            location = self._get_location(node)
            self._add_edit(location, "\n".join(replacements), "Update imports")

    def _handle_import(self, node: ast.Import) -> None:
        concurrent_aliases = [
            alias for alias in node.names if alias.name == "concurrent.futures"
        ]
        if concurrent_aliases:
            self.has_direct_concurrent_import = True
            self.requires_pool = True
            location = self._get_location(node)
            replacement = (
                "from multiprocessing.pool import Pool\nfrom dh import as_completed"
            )
            self._add_edit(location, replacement, "Replace concurrent.futures import")
            self.imported_helpers.add("as_completed")

    def _remove_pool_import_if_exists(self) -> None:
        if not self._has_top_level_pool_binding():
            return
        for edit in list(self.edits):
            if edit.description == "Update imports" and edit.replacement.startswith(
                "from multiprocessing.pool import Pool\n"
            ):
                replacement = edit.replacement.replace(
                    "from multiprocessing.pool import Pool\n", "", 1
                )
                self.edits.remove(edit)
                if replacement:
                    self._add_edit(edit.location, replacement, edit.description)

    def _has_top_level_pool_binding(self) -> bool:
        for node in self.tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                in {
                    "multiprocessing",
                    "multiprocessing.pool",
                }
                and any((alias.asname or alias.name) == "Pool" for alias in node.names)
            ):
                return True
            if isinstance(node, ast.Import):
                if any((alias.asname or alias.name) == "Pool" for alias in node.names):
                    return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == "Pool":
                    return True
        return False

    def _find_pool_variables(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.With):
                self._process_with_statement(node)
            elif isinstance(node, ast.AsyncWith):
                self._process_async_with_statement(node)

    def _process_with_statement(self, node: ast.With) -> None:
        for item in node.items:
            if not isinstance(item.context_expr, ast.Call):
                continue
            func = item.context_expr.func
            is_executor = (
                isinstance(func, ast.Name) and func.id in self.imported_executors
            ) or self._is_concurrent_executor(func)
            if is_executor and isinstance(item.optional_vars, ast.Name):
                self.pool_variables.add(item.optional_vars.id)

    def _process_async_with_statement(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if isinstance(item.context_expr, ast.Call) and isinstance(
                item.optional_vars, ast.Name
            ):
                func = item.context_expr.func
                if isinstance(func, ast.Name) and func.id in self.imported_executors:
                    self.pool_variables.add(item.optional_vars.id)

    def _is_concurrent_executor(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "futures"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "concurrent"
            and node.attr in self.EXECUTOR_CLASSES
        )

    def _transform_executor_calls(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if self._is_executor_constructor(func):
                self._transform_constructor(node)
                continue
            if self._is_concurrent_helper(func, "as_completed"):
                self._transform_as_completed(func)
                continue
            if isinstance(func, ast.Attribute):
                receiver = ast.unparse(func.value)
                if receiver in self.pool_variables and func.attr in {
                    "submit",
                    "map",
                    "shutdown",
                }:
                    self._transform_pool_method(node, receiver, func.attr)

    def _is_executor_constructor(self, func: ast.AST) -> bool:
        return (
            isinstance(func, ast.Name) and func.id in self.imported_executors
        ) or self._is_concurrent_executor(func)

    def _is_concurrent_helper(self, func: ast.AST, name: str) -> bool:
        return (
            isinstance(func, ast.Attribute)
            and func.attr == name
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "futures"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "concurrent"
        )

    def _transform_constructor(self, node: ast.Call) -> None:
        location = self._get_location(node)
        self._add_edit(
            location, "Pool(processes=MAX_WORKERS)", "Replace executor with Pool"
        )
        self.requires_pool = True

    def _transform_as_completed(self, func: ast.Attribute) -> None:
        location = self._get_location(func)
        self._add_edit(location, "as_completed", "Simplify as_completed call")

    def _transform_pool_method(
        self, node: ast.Call, receiver: str, method: str
    ) -> None:
        location = self._get_location(node)
        if method == "submit":
            replacement = self._build_submit_replacement(node, receiver)
        elif method == "map":
            replacement = self._build_map_replacement(node, receiver)
        elif method == "shutdown":
            replacement = f"{receiver}.terminate()"
        else:
            return
        if replacement:
            self._add_edit(location, replacement, f"Transform {method} call")

    def _build_submit_replacement(self, node: ast.Call, receiver: str) -> str | None:
        if not node.args:
            return None
        function = ast.unparse(node.args[0])
        args = self._format_args(node.args[1:])
        kwargs = self._format_kwargs(node.keywords)
        kwarg_part = f", kwds={kwargs}" if node.keywords else ""
        return f"{receiver}.apply_async({function}, args={args}{kwarg_part})"

    def _build_map_replacement(self, node: ast.Call, receiver: str) -> str | None:
        if len(node.args) < 2 or node.keywords:
            return None
        function = ast.unparse(node.args[0])
        iterables = [ast.unparse(arg) for arg in node.args[1:]]
        if len(iterables) == 1:
            work = (
                f"[{receiver}.apply_async({function}, args=(__pool_item,)) "
                f"for __pool_item in {iterables[0]}]"
            )
        else:
            work = (
                f"[{receiver}.apply_async({function}, args=__pool_args) "
                f"for __pool_args in zip({', '.join(iterables)})]"
            )
        return f"[__pool_result.get() for __pool_result in {work}]"

    def _transform_future_methods(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = ast.unparse(node.value)
            if receiver not in self.FUTURE_VARIABLES:
                continue
            location = self._get_location(node)
            if node.attr == "result":
                self._add_edit(
                    SourceLocation(location.start, location.end),
                    f"{receiver}.get",
                    "Future.result() -> AsyncResult.get()",
                )
            elif node.attr == "done":
                self._add_edit(
                    SourceLocation(location.start, location.end),
                    f"{receiver}.ready",
                    "Future.done() -> AsyncResult.ready()",
                )
            elif node.attr == "cancelled":
                self._add_edit(location, "False", "Pool jobs cannot be cancelled")
            elif node.attr == "cancel":
                self._add_edit(location, "None", "Pool jobs cannot be cancelled")

    def _ensure_max_workers(self) -> None:
        if not self.requires_pool:
            return
        if self._has_max_workers():
            self._update_max_workers()
        else:
            self._insert_max_workers()

    def _has_max_workers(self) -> bool:
        for node in self.tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "MAX_WORKERS":
                    return True
        return False

    def _update_max_workers(self) -> None:
        for node in self.tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "MAX_WORKERS":
                    location = self._get_location(node)
                    self._add_edit(location, "MAX_WORKERS = 8", "Set MAX_WORKERS to 8")
                    return

    def _insert_max_workers(self) -> None:
        insertion_point = self._find_import_end()
        self._add_edit(
            SourceLocation(insertion_point, insertion_point),
            "\nMAX_WORKERS = 8",
            "Add MAX_WORKERS constant",
        )

    def _find_import_end(self) -> int:
        imports = [
            node
            for node in self.tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        if imports:
            return max(self._get_location(node).end for node in imports)
        lines = self.source.splitlines(keepends=True)
        index = 0
        for i, line in enumerate(lines[:2]):
            if i == 0 and line.startswith("#!"):
                index += len(line)
            elif "coding" in line:
                index += len(line)
            else:
                break
        return index

    def _add_edit(
        self, location: SourceLocation, replacement: str, description: str
    ) -> None:
        new_edit = CodeEdit(location, replacement, description)
        for old_edit in list(self.edits):
            if self._overlaps(new_edit, old_edit):
                if self._contains(new_edit, old_edit):
                    self.edits.remove(old_edit)
                elif self._contains(old_edit, new_edit):
                    return
                else:
                    raise ValueError(f"Overlapping edits: {old_edit} and {new_edit}")
        self.edits.append(new_edit)

    @staticmethod
    def _overlaps(edit1: CodeEdit, edit2: CodeEdit) -> bool:
        return not (
            edit1.location.end <= edit2.location.start
            or edit1.location.start >= edit2.location.end
        )

    @staticmethod
    def _contains(edit1: CodeEdit, edit2: CodeEdit) -> bool:
        return (
            edit1.location.start <= edit2.location.start
            and edit1.location.end >= edit2.location.end
        )

    def _apply_edits(self) -> str:
        result = self.source
        for edit in sorted(
            self.edits, key=lambda e: (e.location.start, e.location.end), reverse=True
        ):
            result = (
                result[: edit.location.start]
                + edit.replacement
                + result[edit.location.end :]
            )
        return result

    @staticmethod
    def _format_args(args: list[ast.expr]) -> str:
        if not args:
            return "()"
        rendered = [ast.unparse(arg) for arg in args]
        if len(rendered) == 1:
            return f"({rendered[0]},)"
        return "(" + ", ".join(rendered) + ")"

    @staticmethod
    def _format_kwargs(keywords: list[ast.keyword]) -> str:
        parts = []
        for kw in keywords:
            value = ast.unparse(kw.value)
            if kw.arg is None:
                parts.append(f"**{value}")
            else:
                parts.append(f"{kw.arg!r}: {value}")
        return "{" + ", ".join(parts) + "}"


def uses_concurrent_futures(source: str) -> bool:
    try:
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "concurrent.futures":
                if any(
                    alias.name in FuturesToPoolMigrator.EXECUTOR_CLASSES
                    for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.Import):
                if any(alias.name == "concurrent.futures" for alias in node.names):
                    return True
    except SyntaxError:
        return False
    return False


def migrate_file(path: Path) -> tuple[bool, list[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return False, []
    if not uses_concurrent_futures(source):
        return False, []
    try:
        migrator = FuturesToPoolMigrator(source)
        new_source, changes = migrator.migrate()
        if new_source != source:
            path.write_text(new_source, encoding="utf-8")
            return True, changes
    except Exception as e:
        print(f"Error migrating {path}: {e}")
    return False, []


def main() -> int:
    current_dir = Path(".")
    python_files = sorted(current_dir.rglob("*.py"))
    if not python_files:
        print("No Python files found in current directory.")
        return 0
    print(
        f"Found {len(python_files)} Python files. Scanning for concurrent.futures usage..."
    )
    changed_count = 0
    total_changes = 0
    for path in python_files:
        try:
            changed, changes = migrate_file(path)
            if changed:
                changed_count += 1
                total_changes += len(changes)
                print(f"\n✓ {path}: {len(changes)} changes")
                unique_changes = list(dict.fromkeys(changes))
                for change in unique_changes:
                    print(f"  - {change}")
        except Exception as e:
            print(f"\n✗ Error processing {path}: {e}")
    print(f"\n{'=' * 60}")
    print(f"Migration complete!")
    print(f"Files modified: {changed_count}")
    print(f"Total changes: {total_changes}")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
