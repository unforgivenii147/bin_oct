#!/data/data/com.termux/files/home/.local/bin/python
import ast
from collections.abc import Callable, Iterable
from os import scandir as os_scandir
from pathlib import Path
from typing import Any

from joblib import Parallel, delayed
from dh import cprint, get_pyfiles
from xxhash import xxh64_hexdigest


class TypeAnnotationStripper(ast.NodeTransformer):
    """AST Node Transformer to remove type annotations for exact logic comparison."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.annotation = None
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        if node.value is not None:
            # Convert `variable: type = value` -> `variable = value`
            new_node = ast.Assign(targets=[node.target], value=node.value)
            return ast.copy_location(new_node, node)
        # If no value (e.g., just `variable: type`), replace with `pass` to avoid empty body syntax errors
        pass_node = ast.Pass()
        return ast.copy_location(pass_node, node)


def mpf(
    func: Callable[..., Any],
    items: Iterable[Any],
    workers: int | None = None,  # Fixed: added missing workers parameter
) -> list[Any]:
    n_jobs = -1 if workers is None else workers
    items_list = list(items)
    return Parallel(n_jobs=n_jobs)(delayed(func)(item) for item in items_list)


def process_file(path: str | Path) -> tuple[str, str] | None:
    p = Path(path)
    try:
        code = p.read_text(encoding="utf-8")
        parsed = ast.parse(code)

        # Strip type annotations for pure logic comparison
        stripper = TypeAnnotationStripper()
        parsed = stripper.visit(parsed)
        ast.fix_missing_locations(parsed)

        unparsed = ast.unparse(parsed)
        digest = xxh64_hexdigest(unparsed.encode("utf-8"))
        return digest, str(p)
    except Exception:
        # Safely ignore files that raise SyntaxError or UnicodeDecodeError
        return None


def main() -> None:
    cwd: Path = Path.cwd()
    files: list[Path] = list(get_pyfiles(cwd))

    file_dict: dict[str, list[str]] = {}

    # Run in parallel and filter out None results from un-parsable files
    raw_results = mpf(process_file, files)
    results: list[tuple[str, str]] = [res for res in raw_results if res is not None]

    for digest, path in results:
        file_dict.setdefault(digest, []).append(path)

    for digest, paths in file_dict.items():
        if len(paths) > 1:
            print(f"files with hash: {digest}")
            for path in paths:
                print(f"  - {path}")

    deleted: int = 0
    for paths in file_dict.values():
        if len(paths) <= 1:
            continue

        # Keep the first file, delete the duplicates
        for path in paths[1:]:
            file_path = Path(path)
            if file_path.exists():
                try:
                    file_path.unlink()
                    print(f"{path} removed")
                    deleted += 1
                except OSError as e:
                    print(f"Failed to remove {path}: {e}")

    if deleted:
        cprint(f"{deleted} files removed.", "cyan")
    else:
        cprint("No duplicate files found.", "green")


if __name__ == "__main__":
    raise SystemExit(main())
