#!/data/data/com.termux/files/home/.local/bin/python
"""Refactor Python files from os/os.path to modern pathlib equivalents.

This script automatically transforms legacy os.path and os module calls into
their pathlib counterparts, handling common path operations, file system
operations, and adding necessary imports. It supports dry-run mode for previewing
changes and creates backups before modifying files.
"""

from __future__ import annotations

import ast
import traceback
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from dh import cprint, fsz, gsz


class PathlibTransformer(ast.NodeTransformer):
    """AST transformer that converts os/os.path calls to pathlib equivalents."""

    PATHLIB_MAPPINGS: dict[str, tuple[Any, str]] = {
        "exists": ("exists", "bool"),
        "isfile": ("is_file", "bool"),
        "isdir": ("is_dir", "bool"),
        "islink": ("is_symlink", "bool"),
        "isabs": ("is_absolute", "bool"),
        "is_mount": ("is_mount", "bool"),
        "abspath": ("resolve", "Path"),
        "realpath": ("resolve", "Path"),
        "basename": ("name", "str"),
        "dirname": ("parent", "Path"),
        "split": (None, "tuple"),
        "splitext": (None, "tuple"),
        "join": (None, "Path"),
        "normpath": ("resolve", "Path"),
        "normcase": (None, "str"),
        "relpath": (None, "Path"),
        "commonpath": (None, "Path"),
        "commonprefix": (None, "str"),
        "getsize": (("stat", "st_size"), "int"),
        "getmtime": (("stat", "st_mtime"), "float"),
        "getctime": (("stat", "st_ctime"), "float"),
        "getatime": (("stat", "st_atime"), "float"),
        "samefile": ("samefile", "bool"),
        "sameopenfile": (None, "bool"),
        "expanduser": ("expanduser", "Path"),
        "expandvars": ("expandvars", "Path"),
    }

    OS_MAPPINGS: dict[str, tuple[Any, str]] = {
        "remove": ("unlink", "None"),
        "unlink": ("unlink", "None"),
        "rmdir": ("rmdir", "None"),
        "rmtree": (None, "None"),
        "mkdir": ("mkdir", "None"),
        "makedirs": ("mkdir", "None"),
        "rename": ("rename", "None"),
        "replace": ("replace", "None"),
        "symlink": (None, "None"),
        "link": (None, "None"),
        "copy": (None, "None"),
        "copy2": (None, "None"),
        "copytree": (None, "None"),
        "listdir": (None, "list"),
        "scandir": (None, "iterator"),
        "walk": (None, "generator"),
        "chdir": ("chdir", "None"),
        "getcwd": ("cwd", "Path"),
        "getcwdb": (None, "bytes"),
        "chmod": ("chmod", "None"),
        "chown": ("chown", "None"),
        "lchown": (None, "None"),
        "open": (None, "file"),
        "fdopen": (None, "file"),
        "getpid": (None, "int"),
        "getppid": (None, "int"),
        "environ": (None, "dict"),
        "getenv": (None, "str"),
        "putenv": (None, "None"),
    }

    def __init__(self, path: Path) -> None:
        """Initialize the transformer with a file path.

        Args:
            path: Path to the file being transformed
        """
        self.path = path
        self.needs_path_import = False
        self.needs_shutil_import = False
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.os_var_name: str = "os"
        self.os_path_var_name: str = "os.path"
        self.pathlib_imports: set[str] = set()

    def visit_Import(self, node: ast.Import) -> ast.Import:
        """Visit import nodes to detect existing imports.

        Args:
            node: The Import AST node

        Returns:
            The modified Import node
        """
        for alias in node.names:
            if alias.name == "pathlib":
                self.needs_path_import = False
                if alias.asname:
                    self.pathlib_imports.add(alias.asname)
            elif alias.name == "shutil":
                self.needs_shutil_import = False
            elif alias.name == "os":
                self.os_var_name = alias.asname or "os"
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        """Visit import from nodes to detect existing imports.

        Args:
            node: The ImportFrom AST node

        Returns:
            The modified ImportFrom node
        """
        if node.module == "pathlib":
            self.needs_path_import = False
            for alias in node.names:
                self.pathlib_imports.add(alias.name)
        elif node.module == "shutil":
            self.needs_shutil_import = False
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        """Visit assignment nodes to detect os.path aliases.

        Args:
            node: The Assign AST node

        Returns:
            The modified AST node
        """
        if isinstance(node.value, ast.Attribute) and self._is_os_path(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.os_path_var_name = target.id
                    self.infos.append(f"Found alias: {target.id} = os.path")
        return self.generic_visit(node)

    def _is_os_path(self, node: ast.AST) -> bool:
        """Check if node represents os.path.

        Args:
            node: AST node to check

        Returns:
            True if node is os.path, False otherwise
        """
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (node.value.id == self.os_var_name)
            and (node.attr == "path")
        )

    def _is_os_call(self, node: ast.Call, func_name: str) -> bool:
        """Check if node is an os module call.

        Args:
            node: Call node to check
            func_name: Function name to match

        Returns:
            True if node matches the pattern, False otherwise
        """
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id == self.os_var_name)
            and (node.func.attr == func_name)
        )

    def _is_os_path_call(self, node: ast.Call, func_name: str) -> bool:
        """Check if node is an os.path call.

        Args:
            node: Call node to check
            func_name: Function name to match

        Returns:
            True if node matches the pattern, False otherwise
        """
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and (node.func.value.value.id == self.os_var_name)
            and (node.func.value.attr == "path")
            and (node.func.attr == func_name)
        ):
            return True
        return bool(
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id == self.os_path_var_name)
            and (node.func.attr == func_name)
        )

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Visit call nodes to transform os/os.path calls.

        Args:
            node: The Call AST node

        Returns:
            The transformed AST node
        """
        for func_name, (target, return_type) in self.PATHLIB_MAPPINGS.items():
            if self._is_os_path_call(node, func_name):
                return self._transform_path_call(node, func_name, target, return_type)
        for func_name, (target, return_type) in self.OS_MAPPINGS.items():
            if self._is_os_call(node, func_name):
                return self._transform_os_call(node, func_name, target, return_type)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == self.os_var_name
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            func_name = node.args[0].value
            if func_name in self.OS_MAPPINGS:
                self.warnings.append(
                    f"Dynamic os call 'os.{func_name}' found - manual review required"
                )
        return self.generic_visit(node)

    def _transform_path_call(
        self, node: ast.Call, func_name: str, target: Any, return_type: str
    ) -> ast.AST:
        """Transform os.path calls to pathlib equivalents.

        Args:
            node: The Call node to transform
            func_name: The os.path function name
            target: The pathlib target
            return_type: The return type

        Returns:
            The transformed AST node
        """
        self.infos.append(f"os.path.{func_name} -> pathlib equivalent")
        if func_name == "join":
            return self._transform_join(node)
        elif func_name == "split":
            return self._transform_split(node)
        elif func_name == "splitext":
            return self._transform_splitext(node)
        elif func_name == "relpath":
            return self._transform_relpath(node)
        elif func_name == "commonpath":
            return self._transform_commonpath(node)
        elif func_name == "commonprefix":
            return self._transform_commonprefix(node)
        elif func_name == "normcase":
            return self._transform_normcase(node)
        elif func_name in ["getsize", "getmtime", "getctime", "getatime"]:
            return self._transform_stat_call(node, target)
        elif target == "samefile":
            return self._transform_samefile(node)
        elif isinstance(target, str) and (not isinstance(target, tuple)):
            new_node = ast.Attribute(
                value=self._ensure_path(
                    node.args[0] if node.args else ast.Constant(value=".")
                ),
                attr=target,
                ctx=ast.Load(),
            )
            return ast.copy_location(new_node, node)
        return self.generic_visit(node)

    def _transform_os_call(
        self, node: ast.Call, func_name: str, target: Any, return_type: str
    ) -> ast.AST:
        """Transform os calls to pathlib equivalents.

        Args:
            node: The Call node to transform
            func_name: The os function name
            target: The pathlib target
            return_type: The return type

        Returns:
            The transformed AST node
        """
        if func_name == "makedirs":
            return self._transform_makedirs(node)
        elif func_name == "mkdir":
            return self._transform_mkdir(node)
        elif func_name == "listdir":
            return self._transform_listdir(node)
        elif func_name == "scandir":
            return self._transform_scandir(node)
        elif func_name == "walk":
            return self._transform_walk(node)
        elif func_name == "getcwd":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="Path", ctx=ast.Load()),
                    attr="cwd",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)
        elif func_name == "chdir":
            self.warnings.append(
                "os.chdir remains as os.chdir (use context manager with Path.cwd() if possible)"
            )
            return node
        elif func_name == "remove" or func_name == "unlink":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]), attr="unlink", ctx=ast.Load()
                ),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)
        elif func_name == "rmdir":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]), attr="rmdir", ctx=ast.Load()
                ),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)
        elif func_name == "rename" or func_name == "replace":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]),
                    attr=func_name,
                    ctx=ast.Load(),
                ),
                args=[self._ensure_path(node.args[1])],
                keywords=[],
            )
            return ast.copy_location(new_node, node)
        elif func_name == "chmod":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]), attr="chmod", ctx=ast.Load()
                ),
                args=node.args[1:],
                keywords=node.keywords,
            )
            return ast.copy_location(new_node, node)
        elif func_name == "chown":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]), attr="chown", ctx=ast.Load()
                ),
                args=node.args[1:],
                keywords=node.keywords,
            )
            return ast.copy_location(new_node, node)
        elif func_name == "symlink":
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(
                        node.args[1] if len(node.args) > 1 else node.args[0]
                    ),
                    attr="symlink_to",
                    ctx=ast.Load(),
                ),
                args=[self._ensure_path(node.args[0])],
                keywords=[],
            )
            return ast.copy_location(new_node, node)
        elif func_name in ["environ", "getenv", "putenv", "getpid", "getppid"]:
            return node
        elif func_name in ["rmtree", "copy", "copy2", "copytree"]:
            self.needs_shutil_import = True
            self.warnings.append(
                f"os.{func_name} -> Use shutil.{func_name} (added import)"
            )
            return node
        return self.generic_visit(node)

    def _ensure_path(self, node: ast.AST) -> ast.AST:
        """Wrap AST node in Path() call if needed.

        Args:
            node: AST node to potentially wrap

        Returns:
            Path-wrapped AST node
        """
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "Path":
                return node
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and (node.func.value.id in self.pathlib_imports)
            ):
                return node
        return ast.Call(
            func=ast.Name(id="Path", ctx=ast.Load()), args=[node], keywords=[]
        )

    def _transform_join(self, node: ast.Call) -> ast.AST:
        """Transform os.path.join to pathlib path joining.

        Args:
            node: The join call node

        Returns:
            The transformed AST node
        """
        if not node.args:
            return ast.Name(id="Path", ctx=ast.Load())
        result = self._ensure_path(node.args[0])
        for arg in node.args[1:]:
            result = ast.BinOp(
                left=result, op=ast.Div(), right=self._ensure_operand(arg)
            )
            ast.copy_location(result, node)
        return result

    def _ensure_operand(self, node: ast.AST) -> ast.AST:
        """Ensure operand is properly wrapped for path operations.

        Args:
            node: AST node to process

        Returns:
            The processed AST node
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return self._ensure_path(node)
        return node

    def _transform_split(self, node: ast.Call) -> ast.AST:
        """Transform os.path.split to pathlib equivalent.

        Args:
            node: The split call node

        Returns:
            The transformed AST node
        """
        if not node.args:
            return node
        path_arg = node.args[0]
        return ast.Tuple(
            elts=[
                ast.Call(
                    func=ast.Name(id="str", ctx=ast.Load()),
                    args=[
                        ast.Attribute(
                            value=self._ensure_path(path_arg),
                            attr="parent",
                            ctx=ast.Load(),
                        )
                    ],
                    keywords=[],
                ),
                ast.Attribute(
                    value=self._ensure_path(path_arg), attr="name", ctx=ast.Load()
                ),
            ],
            ctx=ast.Load(),
        )

    def _transform_splitext(self, node: ast.Call) -> ast.AST:
        """Transform os.path.splitext to pathlib equivalent.

        Args:
            node: The splitext call node

        Returns:
            The transformed AST node
        """
        if not node.args:
            return node
        path_arg = node.args[0]
        path_obj = self._ensure_path(path_arg)
        return ast.Tuple(
            elts=[
                ast.Attribute(value=path_obj, attr="stem", ctx=ast.Load()),
                ast.Attribute(value=path_obj, attr="suffix", ctx=ast.Load()),
            ],
            ctx=ast.Load(),
        )

    def _transform_relpath(self, node: ast.Call) -> ast.AST:
        """Transform os.path.relpath to pathlib equivalent.

        Args:
            node: The relpath call node

        Returns:
            The transformed AST node
        """
        path_arg = node.args[0]
        start_arg = node.args[1] if len(node.args) > 1 else ast.Constant(value=".")
        return ast.Call(
            func=ast.Attribute(
                value=ast.Call(
                    func=ast.Attribute(
                        value=self._ensure_path(path_arg),
                        attr="resolve",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                ),
                attr="relative_to",
                ctx=ast.Load(),
            ),
            args=[
                ast.Call(
                    func=ast.Attribute(
                        value=self._ensure_path(start_arg),
                        attr="resolve",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            ],
            keywords=[],
        )

    def _transform_commonpath(self, node: ast.Call) -> ast.AST:
        """Transform os.path.commonpath (requires manual implementation).

        Args:
            node: The commonpath call node

        Returns:
            The original node (manual review needed)
        """
        self.warnings.append(
            "os.path.commonpath - requires manual implementation with pathlib"
        )
        return node

    def _transform_commonprefix(self, node: ast.Call) -> ast.AST:
        """Transform os.path.commonprefix (requires manual implementation).

        Args:
            node: The commonprefix call node

        Returns:
            The original node (manual review needed)
        """
        self.warnings.append(
            "os.path.commonprefix - consider using os.path.commonpath or manual implementation"
        )
        return node

    def _transform_normcase(self, node: ast.Call) -> ast.AST:
        """Transform os.path.normcase (platform-specific, manual review).

        Args:
            node: The normcase call node

        Returns:
            The original node (manual review needed)
        """
        if not node.args:
            return node
        self.warnings.append(
            "os.path.normcase - platform-specific, manual review recommended"
        )
        return node

    def _transform_stat_call(self, node: ast.Call, target: tuple) -> ast.AST:
        """Transform stat-related calls to pathlib equivalents.

        Args:
            node: The stat call node
            target: Tuple of (stat method, stat attribute)

        Returns:
            The transformed AST node
        """
        if not node.args:
            return node
        stat_attr, stat_field = target
        return ast.Attribute(
            value=ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0]),
                    attr=stat_attr,
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            ),
            attr=stat_field,
            ctx=ast.Load(),
        )

    def _transform_samefile(self, node: ast.Call) -> ast.AST:
        """Transform os.path.samefile to pathlib equivalent.

        Args:
            node: The samefile call node

        Returns:
            The transformed AST node
        """
        if len(node.args) < 2:
            return node
        return ast.Call(
            func=ast.Attribute(
                value=self._ensure_path(node.args[0]), attr="samefile", ctx=ast.Load()
            ),
            args=[self._ensure_path(node.args[1])],
            keywords=[],
        )

    def _transform_makedirs(self, node: ast.Call) -> ast.AST:
        """Transform os.makedirs to pathlib equivalent.

        Args:
            node: The makedirs call node

        Returns:
            The transformed AST node
        """
        if not node.args:
            return node
        keywords = [ast.keyword(arg="parents", value=ast.Constant(value=True))]
        exist_ok_found = False
        for kw in node.keywords:
            if kw.arg == "exist_ok":
                keywords.append(kw)
                exist_ok_found = True
            elif kw.arg == "mode":
                keywords.append(ast.keyword(arg="mode", value=kw.value))
        if not exist_ok_found:
            keywords.append(ast.keyword(arg="exist_ok", value=ast.Constant(value=True)))
        return ast.Call(
            func=ast.Attribute(
                value=self._ensure_path(node.args[0]), attr="mkdir", ctx=ast.Load()
            ),
            args=[],
            keywords=keywords,
        )

    def _transform_mkdir(self, node: ast.Call) -> ast.AST:
        """Transform os.mkdir to pathlib equivalent.

        Args:
            node: The mkdir call node

        Returns:
            The transformed AST node
        """
        if not node.args:
            return node
        keywords = []
        for kw in node.keywords:
            if kw.arg == "mode":
                keywords.append(ast.keyword(arg="mode", value=kw.value))
        keywords.append(ast.keyword(arg="parents", value=ast.Constant(value=False)))
        keywords.append(ast.keyword(arg="exist_ok", value=ast.Constant(value=False)))
        return ast.Call(
            func=ast.Attribute(
                value=self._ensure_path(node.args[0]), attr="mkdir", ctx=ast.Load()
            ),
            args=[],
            keywords=keywords,
        )

    def _transform_listdir(self, node: ast.Call) -> ast.AST:
        """Transform os.listdir to pathlib equivalent.

        Args:
            node: The listdir call node

        Returns:
            The transformed AST node
        """
        path_arg = node.args[0] if node.args else ast.Constant(value=".")
        return ast.Call(
            func=ast.Name(id="list", ctx=ast.Load()),
            args=[
                ast.Call(
                    func=ast.Attribute(
                        value=self._ensure_path(path_arg),
                        attr="iterdir",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            ],
            keywords=[],
        )

    def _transform_scandir(self, node: ast.Call) -> ast.AST:
        """Transform os.scandir to pathlib equivalent.

        Args:
            node: The scandir call node

        Returns:
            The transformed AST node
        """
        path_arg = node.args[0] if node.args else ast.Constant(value=".")
        self.warnings.append(
            "os.scandir -> Path.iterdir() returns DirEntry-like objects, check attribute access"
        )
        return ast.Call(
            func=ast.Attribute(
                value=self._ensure_path(path_arg), attr="iterdir", ctx=ast.Load()
            ),
            args=[],
            keywords=[],
        )

    def _transform_walk(self, node: ast.Call) -> ast.AST:
        """Transform os.walk to pathlib equivalent (simplified).

        Args:
            node: The walk call node

        Returns:
            The transformed AST node
        """
        self.warnings.append(
            "os.walk - manual conversion recommended. Use Path.rglob() with custom logic"
        )
        if not node.args:
            return node
        path_arg = node.args[0]
        walk_code = f"(\n            (str(root), [d.name for d in root.iterdir() if d.is_dir()], \n             [f.name for f in root.iterdir() if f.is_file()])\n            for root in Path({
            ast.unparse(path_arg)
        }).rglob('*') if root.is_dir()\n        )"
        self.warnings.append(
            "os.walk converted to simplified generator - verify correctness"
        )
        try:
            walk_ast = ast.parse(walk_code, mode="eval")
            return walk_ast.body
        except:
            return node


def add_required_imports(
    tree: ast.AST, needs_pathlib: bool, needs_shutil: bool
) -> ast.AST:
    """Add necessary imports to the AST.

    Args:
        tree: The AST to modify
        needs_pathlib: Whether pathlib import is needed
        needs_shutil: Whether shutil import is needed

    Returns:
        The modified AST
    """
    imports_to_add = []
    if needs_pathlib:
        has_pathlib = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "pathlib":
                        has_pathlib = True
                        break
            elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
                has_pathlib = True
                break
        if not has_pathlib:
            imports_to_add.append(
                ast.ImportFrom(
                    module="pathlib", names=[ast.alias(name="Path")], level=0
                )
            )
    if needs_shutil:
        has_shutil = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "shutil":
                        has_shutil = True
                        break
            elif isinstance(node, ast.ImportFrom) and node.module == "shutil":
                has_shutil = True
                break
        if not has_shutil:
            imports_to_add.append(ast.Import(name=ast.alias(name="shutil")))
    if imports_to_add:
        insert_pos = 0
        for i, node in enumerate(tree.body):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                insert_pos = i + 1
            elif not isinstance(node, (ast.Expr, ast.Constant)) or not _is_docstring(
                node
            ):
                break
        for imp in reversed(imports_to_add):
            tree.body.insert(insert_pos, imp)
    return tree


def _is_docstring(node: ast.AST) -> bool:
    """Check if an AST node is a docstring.

    Args:
        node: The AST node to check

    Returns:
        True if node is a docstring, False otherwise
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def process_file(
    path: Path, dry_run: bool = False, verbose: bool = False
) -> tuple[str | None, bool, list[str], list[str]]:
    """Process a single Python file for pathlib refactoring.

    Args:
        path: Path to the Python file
        dry_run: Whether to simulate the refactoring without writing
        verbose: Whether to show detailed output

    Returns:
        Tuple of (new_content, success, warnings, infos)
    """
    try:
        original_content = path.read_text(encoding="utf-8")
        tree = ast.parse(original_content)
        transformer = PathlibTransformer(path)
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        new_tree = add_required_imports(
            new_tree, transformer.needs_path_import, transformer.needs_shutil_import
        )
        new_content = ast.unparse(new_tree)
        ast.parse(new_content)
        for info in transformer.infos:
            cprint(f"  ℹ️ {info}", "cyan", attrs=["dark"])
        for warning in transformer.warnings:
            cprint(f"  ⚠️ {warning}", "yellow")
        if transformer.infos or transformer.warnings:
            cprint(
                f"{('📝' if dry_run else '✓')} Refactored: {path.name}",
                "green" if not dry_run else "yellow",
            )
        return (new_content, True, transformer.warnings, transformer.infos)
    except SyntaxError as e:
        cprint(f"✗ Syntax error in {path.name}: {e}", "red")
        if verbose:
            traceback.print_exc()
        return (None, False, [], [])
    except Exception as e:
        cprint(f"✗ Error processing {path.name}: {e}", "red")
        if verbose:
            traceback.print_exc()
        return (None, False, [], [])


def get_files(directory: Path) -> list[Path]:
    """Recursively get all Python files in a directory.

    Args:
        directory: Directory to search

    Returns:
        List of Python file paths
    """
    return [p for p in directory.rglob("*.py") if p.is_file()]


def main() -> int:
    """Main entry point for the script.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Refactor Python files from os/path to pathlib",
        epilog="\nExamples:\n  %(prog)s                    # Process all Python files in current directory\n  %(prog)s script.py          # Process a single file\n  %(prog)s src/               # Process all Python files in src directory\n  %(prog)s --dry-run .        # Preview changes without modifying\n  %(prog)s --verbose file.py  # Show detailed output\n        ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to process")
    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    args = parser.parse_args()
    cwd = Path.cwd()
    before_size = gsz(cwd)
    files = []
    if args.paths:
        for path_str in args.paths:
            p = Path(path_str)
            if p.is_file() and p.suffix == ".py":
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
            elif p.suffix == ".py":
                files.append(p)
    else:
        files = get_files(cwd)
    python_files = [f for f in files if f.suffix == ".py"]
    if not python_files:
        cprint("No Python files found to process.", "yellow")
        return 0
    cprint(f"\n📁 Found {len(python_files)} Python files to process", "cyan")
    if args.dry_run:
        cprint("🔍 DRY RUN MODE - No files will be modified\n", "yellow")
    results = {}
    total_warnings = 0
    total_changes = 0
    with Pool(processes=8) as pool:
        async_results = [
            pool.apply_async(process_file, (f, args.dry_run, args.verbose))
            for f in python_files
        ]
        for async_result, path in zip(async_results, python_files):
            try:
                new_content, success, warnings, infos = async_result.get()
                results[path] = (new_content, success, warnings, infos)
                total_warnings += len(warnings)
                total_changes += len(infos)
            except Exception as e:
                cprint(f"✗ Failed to process {path.name}: {e}", "red")
                if args.verbose:
                    traceback.print_exc()
                results[path] = (None, False, [], [])
    modified_count = 0
    for path, (new_content, success, warnings, infos) in results.items():
        if success and new_content and (infos or warnings):
            if not args.dry_run:
                if not args.no_backup:
                    backup_path = path.with_suffix(path.suffix + ".bak")
                    backup_path.write_text(
                        path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    cprint(
                        f"  📦 Backup created: {backup_path.name}",
                        "white",
                        attrs=["dark"],
                    )
                path.write_text(new_content, encoding="utf-8")
                modified_count += 1
            else:
                cprint(f"  🔍 Would modify: {path.name}", "yellow")
    after_size = gsz(cwd)
    size_diff = before_size - after_size
    cprint("\n" + "=" * 40, "cyan")
    cprint("📊 REFACTORING SUMMARY", "cyan", attrs=["bold"])
    cprint(f"  Files processed: {len(python_files)}", "white")
    cprint(
        f"  Files modified: {modified_count}",
        "green" if modified_count > 0 else "white",
    )
    cprint(
        f"  Total changes: {total_changes}", "green" if total_changes > 0 else "white"
    )
    cprint(
        f"  Total warnings: {total_warnings}",
        "yellow" if total_warnings > 0 else "white",
    )
    cprint(f"  Space change: {fsz(size_diff)}", "cyan")
    if args.dry_run and modified_count > 0:
        cprint(
            "\n⚠️  This was a dry run. Run without --dry-run to apply changes.", "yellow"
        )
    elif not args.dry_run and modified_count > 0:
        cprint(f"\n✅ Successfully refactored {modified_count} file(s)", "green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
