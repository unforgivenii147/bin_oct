#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import ast
import multiprocessing as mp
from pathlib import Path

import libcst as cst
from libcst import matchers as m


class CommentAndDocstringRemover(cst.CSTTransformer):
    def __init__(self):
        super().__init__()
        self.comments_removed = 0
        self.docstrings_removed = 0

    def visit_Comment(self, node: cst.Comment) -> bool:
        return True

    def leave_Comment(
        self, original_node: cst.Comment, updated_node: cst.Comment
    ) -> cst.FlattenSentinel[cst.Comment] | cst.RemovalSentinel | cst.Comment:
        self.comments_removed += 1
        return cst.RemoveFromParent()

    def _process_body_docstring(
        self, body_node: cst.IndentedBlock
    ) -> cst.IndentedBlock:
        if not body_node.body:
            return body_node
        first_stmt = body_node.body[0]
        if m.matches(
            first_stmt, m.SimpleStatementLine(body=[m.Expr(value=m.SimpleString())])
        ):
            self.docstrings_removed += 1
            remaining_stmts = list(body_node.body[1:])
            if not remaining_stmts:
                remaining_stmts = [cst.SimpleStatementLine(body=[cst.Pass()])]
            return body_node.with_changes(body=remaining_stmts)
        return body_node

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if isinstance(updated_node.body, cst.IndentedBlock):
            new_body = self._process_body_docstring(updated_node.body)
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        if isinstance(updated_node.body, cst.IndentedBlock):
            new_body = self._process_body_docstring(updated_node.body)
            return updated_node.with_changes(body=new_body)
        return updated_node


def process_file(path: Path) -> tuple[Path, int, int, str | None]:
    try:
        source_text = path.read_text(encoding="utf-8")
        try:
            cst_tree = cst.parse_module(source_text)
        except Exception as e:
            return path, 0, 0, f"CST Parse Error: {e}"
        lines = source_text.splitlines(keepends=True)
        has_shebang = len(lines) > 0 and lines[0].startswith("#!")
        shebang_line = lines[0] if has_shebang else ""
        transformer = CommentAndDocstringRemover()
        modified_tree = cst_tree.visit(transformer)
        modified_code = modified_tree.code
        if has_shebang and not modified_code.startswith("#!"):
            modified_code = shebang_line + modified_code
        c_count = transformer.comments_removed
        d_count = transformer.docstrings_removed
        if has_shebang and c_count > 0:
            c_count -= 1
        try:
            ast.parse(modified_code)
        except SyntaxError as e:
            return path, 0, 0, f"Resulting code failed AST validation: {e}"
        if c_count > 0 or d_count > 0:
            path.write_text(modified_code, encoding="utf-8")
        return path, c_count, d_count, None
    except Exception as e:
        return path, 0, 0, f"Unexpected error: {e}"


def collect_files(inputs: list[str]) -> list[Path]:
    files = set()
    if not inputs:
        return list(Path(".").rglob("*.py"))
    for item in inputs:
        p = Path(item)
        if p.is_file() and p.suffix == ".py":
            files.add(p)
        elif p.is_dir():
            files.update(p.rglob("*.py"))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="Recursively strip comments/docstrings in-place while preserving code formatting."
    )
    parser.add_argument("inputs", nargs="*", help="Files or directories to process")
    args = parser.parse_args()
    files = collect_files(args.inputs)
    if not files:
        print("No Python files found.")
        return
    print(
        f"Processing {len(files)} Python file(s) across 8 processes using LibCST...\n"
    )
    total_comments, total_docstrings, modified_files_count, error_count = 0, 0, 0, 0
    with mp.Pool(processes=8) as pool:
        async_results = [pool.apply_async(process_file, args=(f,)) for f in files]
        for res in async_results:
            path, c_count, d_count, error = res.get()
            if error:
                error_count += 1
                print(f"[ERROR] {path}: {error}")
            elif c_count > 0 or d_count > 0:
                modified_files_count += 1
                total_comments += c_count
                total_docstrings += d_count
                print(
                    f"[UPDATED] {path} -> Removed {c_count} comment(s), {d_count} docstring(s)"
                )
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  - Total files checked: {len(files)}")
    print(f"  - Files updated in-place: {modified_files_count}")
    print(f"  - Total comments removed: {total_comments}")
    print(f"  - Total docstrings removed: {total_docstrings}")
    if error_count > 0:
        print(f"  - Errors encountered: {error_count}")


if __name__ == "__main__":
    main()
