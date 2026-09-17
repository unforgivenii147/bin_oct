#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

EXECUTOR_CLASS_NAMES = {"ThreadPoolExecutor", "ProcessPoolExecutor"}
HELPER_NAMES = {"as_completed", "wait", "FIRST_COMPLETED", "ALL_COMPLETED"}
FUTURE_RESULT_RECEIVERS = {
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


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: str
    reason: str


def line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def position_to_index(
    source: str, offsets: list[int], lineno: int, byte_column: int
) -> int:
    line_start = offsets[lineno - 1]
    line_end = source.find("\n", line_start)
    if line_end == -1:
        line_end = len(source)
    line = source[line_start:line_end]
    prefix = line.encode("utf-8")[:byte_column].decode("utf-8")
    return line_start + len(prefix)


def node_span(source: str, offsets: list[int], node: ast.AST) -> tuple[int, int]:
    return (
        position_to_index(source, offsets, node.lineno, node.col_offset),
        position_to_index(source, offsets, node.end_lineno, node.end_col_offset),
    )


def has_top_level_pool_binding(tree: ast.Module) -> bool:
    for node in tree.body:
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
        if isinstance(node, ast.Import) and any(
            (alias.asname or alias.name) == "Pool" for alias in node.names
        ):
            return True
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == "Pool"
        ):
            return True
    return False


def top_level_max_workers(tree: ast.Module) -> list[ast.AST]:
    assignments: list[ast.AST] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
    for target in targets:
        if isinstance(target, ast.Name) and target.id == "MAX_WORKERS":
            assignments.append(node)
            break
    return assignments


def import_end_index(source: str, offsets: list[int], tree: ast.Module) -> int:
    imports = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    lines = []
    if not imports:
        lines = source.splitlines(keepends=True)
    index = 0
    for i, line in enumerate(lines[:2]):
        if i == 0 and line.startswith("#!"):
            index += len(line)
        elif "coding" in line:
            index += len(line)
        return index
    return max(node_span(source, offsets, node)[1] for node in imports)


def tuple_expression(args: list[ast.expr]) -> str:
    if not args:
        return "()"
    rendered = [ast.unparse(argument) for argument in args]
    if len(rendered) == 1:
        return f"({rendered[0]},)"
    return "(" + ", ".join(rendered) + ")"


def keyword_expression(keywords: list[ast.keyword]) -> str:
    parts: list[str] = []
    for keyword in keywords:
        value = ast.unparse(keyword.value)
        if keyword.arg is None:
            parts.append(f"**{value}")
        else:
            parts.append(f"{keyword.arg!r}: {value}")
    return "{" + ", ".join(parts) + "}"


def is_concurrent_attribute(node: ast.AST, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "futures"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "concurrent"
    )


def build_submit_replacement(call: ast.Call) -> str | None:
    if not call.args:
        return None
    receiver = ast.unparse(call.func.value)
    # type: ignore[union-attr]
    function = ast.unparse(call.args[0])
    args = tuple_expression(call.args[1:])
    keywords = keyword_expression(call.keywords)
    keyword_part = f", kwds={keywords}" if call.keywords else ""
    return f"{receiver}.apply_async({function}, args={args}{keyword_part})"


def build_map_replacement(call: ast.Call) -> str | None:
    if len(call.args) < 2 or call.keywords:
        return None
    receiver = ast.unparse(call.func.value)  # type: ignore[union-attr]
    function = ast.unparse(call.args[0])
    iterables = [ast.unparse(argument) for argument in call.args[1:]]
    if len(iterables) == 1:
        work = f"[{receiver}.apply_async({function}, args=(__pool_item,)) for __pool_item in {iterables[0]}]"
    else:
        work = f"[{receiver}.apply_async({function}, args=__pool_args) for __pool_args in zip({', '.join(iterables)})]"
    return f"[__pool_result.get() for __pool_result in {work}]"


def add_edit(edits: list[Edit], edit: Edit) -> None:
    for old in list(edits):
        overlaps = not (edit.end <= old.start or edit.start >= old.end)
        if not overlaps:
            continue
        if edit.start <= old.start and edit.end >= old.end:
            edits.remove(old)
            continue
        if old.start <= edit.start and old.end >= edit.end:
            return
        raise ValueError(f"Overlapping edits: {old} and {edit}")
        edits.append(edit)


def rewrite_source(source: str) -> tuple[str, list[str], bool]:
    tree = ast.parse(source)
    offsets = line_offsets(source)
    edits: list[Edit] = []
    imported_executor_names: set[str] = set(EXECUTOR_CLASS_NAMES)
    imported_helper_names: set[str] = set(HELPER_NAMES)
    requires_pool = False
    helpers_to_import: set[str] = set()
    has_direct_concurrent_import = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "concurrent.futures":
            executor_aliases = [
                alias.asname or alias.name
                for alias in node.names
                if alias.name in EXECUTOR_CLASS_NAMES
            ]
            helper_aliases = [
                alias.asname or alias.name
                for alias in node.names
                if alias.name in HELPER_NAMES
            ]
            imported_executor_names.update(executor_aliases)
            imported_helper_names.update(helper_aliases)
            requires_pool = requires_pool or bool(executor_aliases)
            helpers_to_import.update(
                alias.name for alias in node.names if alias.name in HELPER_NAMES
            )
            replacement_lines: list[str] = []
            if executor_aliases:
                replacement_lines.append("from multiprocessing.pool import Pool")
            if helper_aliases:
                imported = ", ".join(
                    f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                    for alias in node.names
                    if alias.name in HELPER_NAMES
                )
                replacement_lines.append(f"from dh import {imported}")
                start, end = node_span(source, offsets, node)
                add_edit(
                    edits,
                    Edit(
                        start,
                        end,
                        "\n".join(replacement_lines),
                        "replace futures import",
                    ),
                )
        elif isinstance(node, ast.Import):
            concurrent_aliases = [
                alias for alias in node.names if alias.name == "concurrent.futures"
            ]
            if concurrent_aliases:
                has_direct_concurrent_import = True
                start, end = node_span(source, offsets, node)
                add_edit(
                    edits,
                    Edit(
                        start,
                        end,
                        "from multiprocessing.pool import Pool\nfrom dh import as_completed",
                        "replace futures module import",
                    ),
                )
                requires_pool = True
                helpers_to_import.add("as_completed")
        pool_already_bound = has_top_level_pool_binding(tree)
        if pool_already_bound:
            for edit in list(edits):
                if (
                    edit.reason == "replace futures import"
                    and edit.replacement.startswith(
                        "from multiprocessing.pool import Pool\n"
                    )
                ):
                    replacement = edit.replacement.replace(
                        "from multiprocessing.pool import Pool\n", "", 1
                    )
                    edits.remove(edit)
                    edits.append(Edit(edit.start, edit.end, replacement, edit.reason))
    pool_variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    func = item.context_expr.func
                    is_executor = (
                        isinstance(func, ast.Name)
                        and func.id in imported_executor_names
                    ) or any(
                        is_concurrent_attribute(func, name)
                        for name in EXECUTOR_CLASS_NAMES
                    )
                    if is_executor and isinstance(item.optional_vars, ast.Name):
                        pool_variables.add(item.optional_vars.id)
        elif isinstance(node, ast.AsyncWith):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call) and isinstance(
                    item.optional_vars, ast.Name
                ):
                    func = item.context_expr.func
                    if (
                        isinstance(func, ast.Name)
                        and func.id in imported_executor_names
                    ):
                        pool_variables.add(item.optional_vars.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_executor_constructor = (
            isinstance(func, ast.Name) and func.id in imported_executor_names
        ) or any(is_concurrent_attribute(func, name) for name in EXECUTOR_CLASS_NAMES)
        if is_executor_constructor:
            start, end = node_span(source, offsets, node)
            add_edit(
                edits,
                Edit(
                    start, end, "Pool(processes=MAX_WORKERS)", "fixed pool constructor"
                ),
            )
            requires_pool = True
            continue
        if is_concurrent_attribute(func, "as_completed"):
            start, end = node_span(source, offsets, func)
            add_edit(
                edits, Edit(start, end, "as_completed", "unqualify completion helper")
            )
            helpers_to_import.add("as_completed")
            continue
        if not isinstance(func, ast.Attribute):
            continue
        receiver = ast.unparse(func.value)
        if func.attr in {"submit", "map", "shutdown"} and receiver in pool_variables:
            start, end = node_span(source, offsets, node)
            if func.attr == "submit":
                replacement = build_submit_replacement(node)
            elif func.attr == "map":
                replacement = build_map_replacement(node)
            else:
                replacement = f"{receiver}.terminate()"
            if replacement is not None:
                add_edit(edits, Edit(start, end, replacement, f"convert {func.attr}"))
                continue
        if func.attr == "result" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, func)
            add_edit(edits, Edit(start, end, f"{receiver}.get", "AsyncResult get"))
        elif func.attr == "done" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, func)
            add_edit(edits, Edit(start, end, f"{receiver}.ready", "AsyncResult ready"))
        elif func.attr == "cancelled" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, node)
            add_edit(edits, Edit(start, end, "False", "Pool jobs cannot be cancelled"))
        elif func.attr == "cancel" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, node)
            add_edit(edits, Edit(start, end, "None", "Pool jobs cannot be cancelled"))
    if requires_pool:
        assignments = top_level_max_workers(tree)
        if assignments:
            for assignment in assignments:
                start, end = node_span(source, offsets, assignment)
                add_edit(
                    edits, Edit(start, end, "MAX_WORKERS = 8", "fix worker constant")
                )
        else:
            insertion = import_end_index(source, offsets, tree)
            add_edit(
                edits,
                Edit(
                    insertion, insertion, "\nMAX_WORKERS = 8", "insert worker constant"
                ),
            )
    if not edits:
        return source, [], requires_pool
    output = source
    for edit in sorted(
        edits, key=lambda current: (current.start, current.end), reverse=True
    ):
        output = output[: edit.start] + edit.replacement + output[edit.end :]
    return output, [edit.reason for edit in edits], requires_pool


def has_executor_import(source: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "concurrent.futures":
            if any(alias.name in EXECUTOR_CLASS_NAMES for alias in node.names):
                return True
        if isinstance(node, ast.Import) and any(
            alias.name == "concurrent.futures" for alias in node.names
        ):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(".")])
    parser.add_argument("-w", "--write", action="store_true")
    args = parser.parse_args()
    paths: list[Path] = []
    for root in args.paths:
        if root.is_file():
            paths.append(root)
        else:
            paths.extend(sorted(root.glob("*.py")))
            changed = 0
            errors: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if not has_executor_import(source):
            continue
        try:
            output, reasons, _ = rewrite_source(source)
            ast.parse(output)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        if output != source:
            changed += 1
            print(f"{path}: {len(reasons)} edits ({', '.join(sorted(set(reasons)))})")
            if args.write:
                path.write_text(output, encoding="utf-8")
                print(f"migrated executor modules: {changed}")
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
