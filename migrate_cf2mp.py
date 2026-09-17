#!/data/data/com.termux/files/home/.local/bin/python
"""
Migrate concurrent.futures usage to multiprocessing.pool.apply_async.
Recursively processes Python files in the current directory.
"""

import ast
from pathlib import Path


class ExecutorCollector(ast.NodeVisitor):
    """Collect executor variable names and future variable names."""

    def __init__(self):
        self.executor_vars = set()  # variables that hold executor objects
        self.future_vars = set()  # variables that hold Future objects

    def _is_executor_constructor(self, node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name) and func.id in (
            "ProcessPoolExecutor",
            "ThreadPoolExecutor",
        ):
            return True
        return bool(
            isinstance(func, ast.Attribute)
            and func.attr in ("ProcessPoolExecutor", "ThreadPoolExecutor")
        )

    def visit_Assign(self, node):
        # Check if value is executor constructor
        if self._is_executor_constructor(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.executor_vars.add(target.id)
        # Check if value is a submit call (future)
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "submit"
        ):
            # base may be an executor var, but we can add the target as future
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.future_vars.add(target.id)
        # Continue visiting children
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if self._is_executor_constructor(item.context_expr):
                if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                    self.executor_vars.add(item.optional_vars.id)
                else:
                    # default name 'executor'
                    self.executor_vars.add("executor")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # If we see executor.submit(...) as an attribute, we can add the base as executor
        # but only if it's likely an executor (we can't be sure). We'll rely on assignments.
        self.generic_visit(node)


class FuturesToPoolMigrator(ast.NodeTransformer):
    """Transform concurrent.futures usage to multiprocessing.pool."""

    def __init__(self, executor_vars, future_vars):
        self.executor_vars = executor_vars
        self.future_vars = future_vars
        self.imports_futures = False
        self.imports_multiprocessing = False
        self.has_mp_alias = False
        self.needs_migration = False
        self.executor_to_pool = {}  # mapping original executor var -> new pool var
        self.pool_counter = 0

    def _get_pool_name(self, executor_var):
        """Generate a unique pool variable name."""
        if executor_var and executor_var != "executor":
            if executor_var == "pool":
                base = "pool"
            elif executor_var.endswith("_pool"):
                base = executor_var
            else:
                base = f"{executor_var}_pool"
        else:
            base = "pool"
        if base in self.executor_to_pool.values():
            self.pool_counter += 1
            base = f"{base}_{self.pool_counter}"
        return base

    def _is_executor_constructor(self, node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name) and func.id in (
            "ProcessPoolExecutor",
            "ThreadPoolExecutor",
        ):
            return True
        return bool(
            isinstance(func, ast.Attribute)
            and func.attr in ("ProcessPoolExecutor", "ThreadPoolExecutor")
        )

    def visit_Import(self, node):
        new_aliases = []
        for alias in node.names:
            if alias.name == "concurrent.futures":
                self.imports_futures = True
                self.needs_migration = True
            elif alias.name == "multiprocessing":
                self.imports_multiprocessing = True
                if alias.asname == "mp":
                    self.has_mp_alias = True
                new_aliases.append(alias)
            else:
                new_aliases.append(alias)
        if new_aliases:
            node.names = new_aliases
            return node
        return None

    def visit_ImportFrom(self, node):
        if node.module == "concurrent.futures":
            self.imports_futures = True
            self.needs_migration = True
            return None
        elif node.module == "multiprocessing":
            self.imports_multiprocessing = True
            for alias in node.names:
                if alias.name == "Pool" and alias.asname == "mp":
                    self.has_mp_alias = True
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        if self._is_executor_constructor(node.value):
            self.needs_migration = True
            for target in node.targets:
                if isinstance(target, ast.Name):
                    executor_var = target.id
                    if executor_var not in self.executor_to_pool:
                        pool_var = self._get_pool_name(executor_var)
                        self.executor_to_pool[executor_var] = pool_var
                    pool_var = self.executor_to_pool[executor_var]
                    new_assign = ast.Assign(
                        targets=[ast.Name(id=pool_var, ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="mp", ctx=ast.Load()),
                                attr="Pool",
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        ),
                    )
                    ast.copy_location(new_assign, node)
                    ast.fix_missing_locations(new_assign)
                    return new_assign
        # If the assignment is from a submit call, we might want to keep it as is
        # (the future variable will be handled by .result() -> .get())
        return node

    def visit_With(self, node):
        executor_items = []
        other_items = []
        for item in node.items:
            if self._is_executor_constructor(item.context_expr):
                executor_items.append(item)
            else:
                other_items.append(item)

        if not executor_items:
            return self.generic_visit(node)

        self.needs_migration = True

        if len(executor_items) > 1:
            print(
                "Warning: Multiple executor context managers in one with statement; only first will be migrated."
            )
        item = executor_items[0]

        if item.optional_vars and isinstance(item.optional_vars, ast.Name):
            executor_var = item.optional_vars.id
        else:
            executor_var = "executor"

        pool_var = self._get_pool_name(executor_var)
        self.executor_to_pool[executor_var] = pool_var

        pool_assign = ast.Assign(
            targets=[ast.Name(id=pool_var, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="mp", ctx=ast.Load()), attr="Pool", ctx=ast.Load()
                ),
                args=[],
                keywords=[],
            ),
        )
        ast.copy_location(pool_assign, node)

        transformed_body = []
        for stmt in node.body:
            transformed = self.visit(stmt)
            if transformed is not None:
                if isinstance(transformed, list):
                    transformed_body.extend(transformed)
                else:
                    transformed_body.append(transformed)

        close_call = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=pool_var, ctx=ast.Load()),
                    attr="close",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )
        join_call = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=pool_var, ctx=ast.Load()),
                    attr="join",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )
        ast.copy_location(close_call, node)
        ast.copy_location(join_call, node)

        try_finally = ast.Try(
            body=transformed_body,
            handlers=[],
            orelse=[],
            finalbody=[close_call, join_call],
        )
        ast.copy_location(try_finally, node)

        if other_items:
            new_with = ast.With(items=other_items, body=[try_finally])
            ast.copy_location(new_with, node)
            return [pool_assign, new_with]
        else:
            return [pool_assign, try_finally]

    def visit_Call(self, node):
        self.generic_visit(node)

        # Transform executor.submit() -> pool.apply_async()
        if isinstance(node.func, ast.Attribute) and node.func.attr == "submit":
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in self.executor_vars:
                self.needs_migration = True
                # Map to pool variable if not already
                if base.id not in self.executor_to_pool:
                    self.executor_to_pool[base.id] = self._get_pool_name(base.id)
                pool_var = self.executor_to_pool[base.id]

                if not node.args:
                    func_arg = ast.Constant(value=None)
                else:
                    func_arg = node.args[0]
                remaining_args = node.args[1:]
                args_tuple = ast.Tuple(elts=remaining_args, ctx=ast.Load())

                kwds_entries = []
                for kw in node.keywords:
                    if kw.arg is not None:
                        kwds_entries.append(ast.keyword(arg=kw.arg, value=kw.value))
                    else:
                        # **kwargs unsupported
                        return node
                if kwds_entries:
                    kwds_dict = ast.Dict(
                        keys=[ast.Constant(value=k.arg) for k in kwds_entries],
                        values=[k.value for k in kwds_entries],
                    )
                    new_call = ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=pool_var, ctx=ast.Load()),
                            attr="apply_async",
                            ctx=ast.Load(),
                        ),
                        args=[func_arg, args_tuple],
                        keywords=[ast.keyword(arg="kwds", value=kwds_dict)],
                    )
                else:
                    new_call = ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=pool_var, ctx=ast.Load()),
                            attr="apply_async",
                            ctx=ast.Load(),
                        ),
                        args=[func_arg, args_tuple],
                        keywords=[],
                    )
                ast.copy_location(new_call, node)
                ast.fix_missing_locations(new_call)
                return new_call

        # Transform future.result() -> future.get()
        if isinstance(node.func, ast.Attribute) and node.func.attr == "result":
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in self.future_vars:
                self.needs_migration = True
                new_func = ast.Attribute(value=base, attr="get", ctx=ast.Load())
                node.func = new_func
                ast.fix_missing_locations(node)
                return node

        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        # Transform executor.map() -> pool.map()
        if node.attr == "map":
            base = node.value
            if isinstance(base, ast.Name) and base.id in self.executor_vars:
                self.needs_migration = True
                if base.id not in self.executor_to_pool:
                    self.executor_to_pool[base.id] = self._get_pool_name(base.id)
                pool_var = self.executor_to_pool[base.id]
                node.value = ast.Name(id=pool_var, ctx=ast.Load())
                ast.fix_missing_locations(node)
                return node
        return node


def _find_import_insert_index(module_node):
    """Return index to insert import after docstring and __future__ imports."""
    index = 0
    if (
        module_node.body
        and isinstance(module_node.body[0], ast.Expr)
        and isinstance(module_node.body[0].value, ast.Constant)
        and isinstance(module_node.body[0].value.value, str)
    ):
        index = 1
    while index < len(module_node.body):
        node = module_node.body[index]
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            index += 1
        else:
            break
    return index


def migrate_file(path: Path) -> bool:
    """Migrate a single Python file, return True if changes were made."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        # Pass 1: collect executor and future variable names
        collector = ExecutorCollector()
        collector.visit(tree)

        # Pass 2: transform
        transformer = FuturesToPoolMigrator(
            collector.executor_vars, collector.future_vars
        )
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)

        if not transformer.needs_migration:
            return False

        # Ensure 'mp' alias for multiprocessing is available
        if not transformer.has_mp_alias:
            import_node = ast.Import(
                names=[ast.alias(name="multiprocessing", asname="mp")]
            )
            if isinstance(new_tree, ast.Module):
                insert_idx = _find_import_insert_index(new_tree)
                new_tree.body.insert(insert_idx, import_node)
                ast.fix_missing_locations(new_tree)

        new_source = ast.unparse(new_tree)

        # Validate syntax
        try:
            compile(new_source, str(path), "exec")
        except SyntaxError as e:
            print(f"ERROR: Invalid syntax after migration in {path}: {e}")
            return False

        # Write in-place
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_source)
        return True

    except Exception as e:
        print(f"ERROR processing {path}: {e}")
        return False


def main():
    current_dir = Path(".")
    python_files = list(current_dir.rglob("*.py"))
    this_script = Path(__file__).resolve()
    python_files = [f for f in python_files if f.resolve() != this_script]

    if not python_files:
        print("No Python files found.")
        return

    print(f"Found {len(python_files)} Python files")
    migrated = 0
    for path in python_files:
        print(f"Processing {path}...", end=" ")
        try:
            with open(path, "r", encoding="utf-8") as f:
                compile(f.read(), str(path), "exec")
        except SyntaxError as e:
            print(f"SKIP (syntax error in original): {e}")
            continue

        if migrate_file(path):
            migrated += 1
            print("MIGRATED")
        else:
            print("no change")

    print(f"\nDone. Migrated {migrated} file(s).")


if __name__ == "__main__":
    main()
