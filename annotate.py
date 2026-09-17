#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper


class TypeAnnotationTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = ()

    def __init__(self) -> None:
        self.added_any_import = False

    def visit_Module(self, node: cst.Module) -> bool:
        self.added_any_import = self._module_needs_any_import(node)
        return True

    def leave_Module(
        self,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        if not self.added_any_import:
            return updated_node
        any_import = cst.SimpleStatementLine(
            body=[
                cst.ImportFrom(
                    module=cst.Name("typing"),
                    names=[cst.ImportAlias(name=cst.Name("Any"))],
                )
            ]
        )
        body = list(updated_node.body)
        insert_at = 0
        if body and isinstance(body[0], cst.SimpleStatementLine):
            first_statement = body[0].body[0]
            if isinstance(first_statement, cst.Expr) and isinstance(
                first_statement.value, cst.SimpleString
            ):
                insert_at = 1
        body.insert(insert_at, any_import)
        return updated_node.with_changes(body=body)

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        params = updated_node.params
        updated_posonly = self._annotate_params(params.posonly_params)
        updated_params = self._annotate_params(params.params)
        updated_kwonly = self._annotate_params(params.kwonly_params)
        new_params = params.with_changes(
            posonly_params=updated_posonly,
            params=updated_params,
            kwonly_params=updated_kwonly,
        )
        returns = updated_node.returns
        if returns is None:
            returns = cst.Annotation(annotation=cst.Name("Any"))
        return updated_node.with_changes(
            params=new_params,
            returns=returns,
        )

    def _annotate_params(
        self,
        params: tuple[cst.Param, ...],
    ) -> tuple[cst.Param, ...]:
        result: list[cst.Param] = []
        for param in params:
            if param.annotation is None:
                result.append(
                    param.with_changes(
                        annotation=cst.Annotation(annotation=cst.Name("Any"))
                    )
                )
            else:
                result.append(param)
        return tuple(result)

    @staticmethod
    def _module_needs_any_import(node: cst.Module) -> bool:
        for statement in node.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small_statement in statement.body:
                if isinstance(small_statement, cst.ImportFrom) and (
                    isinstance(small_statement.module, cst.Name)
                    and small_statement.module.value == "typing"
                    and small_statement.names
                    and any(
                        isinstance(alias, cst.ImportAlias)
                        and isinstance(alias.name, cst.Name)
                        and alias.name.value == "Any"
                        for alias in small_statement.names
                    )
                ):
                    return False
        return True


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )


def validate_file(path: Path) -> None:
    compile_result = run_command(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(path),
        ]
    )
    if compile_result.returncode != 0:
        raise RuntimeError(
            f"Syntax validation failed:\n{compile_result.stdout}{compile_result.stderr}"
        )
    mypy_result = run_command(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            str(path),
        ]
    )
    if mypy_result.returncode != 0:
        raise RuntimeError(
            f"mypy validation failed:\n{mypy_result.stdout}{mypy_result.stderr}"
        )


def annotate_file(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        raise RuntimeError(f"Could not parse {path}: {error}") from error
    transformer = TypeAnnotationTransformer()
    updated_module = MetadataWrapper(module).visit(transformer)
    updated_source = updated_module.code
    if updated_source == source:
        print(f"No changes needed: {path}")
        return
    with tempfile.TemporaryDirectory(
        prefix=f".{path.stem}-annotation-",
        dir=path.parent,
    ) as temporary_directory:
        temporary_path = Path(temporary_directory) / path.name
        temporary_path.write_text(updated_source, encoding="utf-8")
        validate_file(temporary_path)
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)
        shutil.copy2(temporary_path, path)
        print(f"Updated: {path}")
        print(f"Backup:  {backup_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add Any annotations to unannotated Python functions."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Python file to update in place",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path: Path = args.input
    if not path.is_file():
        print(f"Error: file does not exist: {path}", file=sys.stderr)
        return 2
    if path.suffix != ".py":
        print(f"Error: expected a .py file: {path}", file=sys.stderr)
        return 2
    try:
        annotate_file(path)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
