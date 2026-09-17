#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import pkgutil
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

BIN_DIR = Path.home() / "bin"
REPORT = Path.home() / "dh_usage.txt"
PACKAGE = "dh"


def get_stdlib_modules() -> set[str]:
    stdlib = set()
    for module_info in pkgutil.iter_modules():
        name = module_info.name
        if name.startswith("_"):
            continue
        stdlib.add(name)
    extra = {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "pathlib",
        "collections",
        "itertools",
        "functools",
        "typing",
        "argparse",
        "logging",
        "subprocess",
        "shutil",
        "tempfile",
        "hashlib",
        "base64",
        "uuid",
        "csv",
        "io",
        "textwrap",
        "string",
        "random",
        "statistics",
        "decimal",
        "fractions",
        "enum",
        "dataclasses",
        "abc",
        "copy",
        "pprint",
        "traceback",
        "warnings",
        "contextlib",
        "threading",
        "multiprocessing",
        "socket",
        "http",
        "urllib",
        "email",
        "xml",
        "html",
        "configparser",
        "ast",
        "inspect",
        "dis",
        "tokenize",
        "compileall",
        "zipfile",
        "tarfile",
        "gzip",
        "bz2",
        "lzma",
        "pickle",
        "shelve",
        "dbm",
        "sqlite3",
        "unittest",
        "doctest",
        "pdb",
        "profile",
        "cProfile",
        "webbrowser",
        "tkinter",
        "turtle",
    }
    stdlib.update(extra)
    return stdlib


def is_stdlib(module_name: str, stdlib_set: set[str]) -> bool:
    top_level = module_name.split(".")[0]
    return top_level in stdlib_set


def is_third_party(module_name: str, stdlib_set: set[str]) -> bool:
    top_level = module_name.split(".")[0]
    if top_level == PACKAGE:
        return False
    if top_level in stdlib_set:
        return False
    return not top_level.startswith("__")


def extract_imports(path: Path) -> dict[str, list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"   ⚠️  Skipping {path.name}: {e}")
        return {}
    imports: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                asname = alias.asname
                if mod not in imports:
                    imports[mod] = []
                if asname:
                    imports[mod].append(asname)
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            for alias in node.names:
                name = alias.name if alias.asname is None else alias.asname
                imports[mod].append(name)
    dh_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PACKAGE or alias.name.startswith(PACKAGE + "."):
                    name = alias.asname if alias.asname else alias.name
                    dh_names.add(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in dh_names:
                    imports[PACKAGE].append(func.attr)
            if isinstance(func, ast.Attribute) and isinstance(
                func.value, ast.Attribute
            ):
                root = func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in dh_names:
                    imports[PACKAGE].append(func.attr)
    return dict(imports)


def count_calls(path: Path, imports: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return {}
    local_to_import: dict[str, tuple[str, str]] = {}
    for mod, names in imports.items():
        for name in names:
            local_to_import[name] = (mod, name)
    call_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in local_to_import:
                mod, name = local_to_import[func.id]
                call_counts[mod][name] += 1
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                obj_name = func.value.id
                for mod, names in imports.items():
                    if mod == obj_name or mod.endswith("." + obj_name):
                        call_counts[mod][func.attr] += 1
    return dict(call_counts)


def generate_report(
    per_file_data: list[tuple[str, dict[str, dict[str, int]]]],
    stdlib_set: set[str],
) -> tuple[str, Counter, Counter, Counter]:
    lines: list[str] = []
    now = __import__("datetime").datetime.now()
    stdlib_counts: Counter = Counter()
    thirdparty_counts: Counter = Counter()
    dh_counts: Counter = Counter()
    stdlib_files: dict[str, set[str]] = defaultdict(set)
    thirdparty_files: dict[str, set[str]] = defaultdict(set)
    dh_files: dict[str, set[str]] = defaultdict(set)
    for fname, module_calls in per_file_data:
        for mod, func_calls in module_calls.items():
            total = sum(func_calls.values())
            top_level = mod.split(".")[0]
            if top_level == PACKAGE:
                dh_counts[mod] += total
                for func in func_calls:
                    dh_files[func].add(fname)
            elif is_stdlib(mod, stdlib_set):
                stdlib_counts[mod] += total
                for func in func_calls:
                    stdlib_files[func].add(fname)
            else:
                thirdparty_counts[mod] += total
                for func in func_calls:
                    thirdparty_files[func].add(fname)
    lines.append(f"{'=' * 40}")
    lines.append(f"  IMPORT USAGE REPORT — {now:%Y-%m-%d %H:%M}")
    lines.append(f"{'=' * 40}")
    lines.append(f"  Scanned directory: {BIN_DIR}")
    lines.append(f"  Files scanned: {len(per_file_data)}")
    lines.append("")
    lines.append(f"{'─' * 40}")
    lines.append("  SECTION 1: STANDARD LIBRARY MODULES")
    lines.append(f"{'─' * 40}")
    if stdlib_counts:
        lines.append(f"\n  {'Module':<35} {'Total Calls':<15} {'Files':<10}")
        lines.append("  " + "-" * 40)
        for mod in sorted(stdlib_counts, key=lambda m: -stdlib_counts[m]):
            files_used = len(stdlib_files.get(mod, set()))
            lines.append(f"  {mod:<35} {stdlib_counts[mod]:<15} {files_used:<10}")
        lines.append(f"\n  Total stdlib modules used: {len(stdlib_counts)}")
    else:
        lines.append("  (none)")
    lines.append(f"\n{'─' * 40}")
    lines.append("  SECTION 2: THIRD-PARTY PACKAGES")
    lines.append(f"{'─' * 40}")
    if thirdparty_counts:
        lines.append(f"\n  {'Package':<35} {'Total Calls':<15} {'Files':<10}")
        lines.append("  " + "-" * 40)
        for mod in sorted(thirdparty_counts, key=lambda m: -thirdparty_counts[m]):
            files_used = len(thirdparty_files.get(mod, set()))
            lines.append(f"  {mod:<35} {thirdparty_counts[mod]:<15} {files_used:<10}")
        lines.append(f"\n  Total third-party packages used: {len(thirdparty_counts)}")
    else:
        lines.append("  (none)")
    lines.append(f"\n{'─' * 40}")
    lines.append(f"  SECTION 3: CUSTOM '{PACKAGE}' PACKAGE")
    lines.append(f"{'─' * 40}")
    if dh_counts:
        lines.append(f"\n  {'Function':<35} {'Total Calls':<15} {'Files':<10}")
        lines.append("  " + "-" * 40)
        for func in sorted(dh_counts, key=lambda f: -dh_counts[f]):
            files_used = len(dh_files.get(func, set()))
            lines.append(f"  {func:<35} {dh_counts[func]:<15} {files_used:<10}")
        lines.append(f"\n  Total dh functions used: {len(dh_counts)}")
    else:
        lines.append("  (none)")
    lines.append(f"\n{'─' * 40}")
    lines.append("  SECTION 4: PER-FILE BREAKDOWN")
    lines.append(f"{'─' * 40}")
    for fname, module_calls in sorted(
        per_file_data, key=lambda x: -sum(sum(c.values()) for c in x[1].values())
    ):
        total_calls = sum(sum(c.values()) for c in module_calls.values())
        lines.append(f"\n  📄 {fname}  ({total_calls} total calls)")
        stdlib_in_file = {}
        thirdparty_in_file = {}
        dh_in_file = {}
        for mod, func_calls in module_calls.items():
            top_level = mod.split(".")[0]
            if top_level == PACKAGE:
                dh_in_file[mod] = func_calls
            elif is_stdlib(mod, stdlib_set):
                stdlib_in_file[mod] = func_calls
            else:
                thirdparty_in_file[mod] = func_calls
        if stdlib_in_file:
            lines.append("    [stdlib]")
            for mod in sorted(stdlib_in_file):
                funcs = stdlib_in_file[mod]
                total = sum(funcs.values())
                lines.append(f"      {mod:<30} {total} call(s)")
                for func, count in sorted(funcs.items(), key=lambda x: -x[1]):
                    if count > 0:
                        lines.append(f"        {func:<28} {count} time(s)")
        if thirdparty_in_file:
            lines.append("    [third-party]")
            for mod in sorted(thirdparty_in_file):
                funcs = thirdparty_in_file[mod]
                total = sum(funcs.values())
                lines.append(f"      {mod:<30} {total} call(s)")
                for func, count in sorted(funcs.items(), key=lambda x: -x[1]):
                    if count > 0:
                        lines.append(f"        {func:<28} {count} time(s)")
        if dh_in_file:
            lines.append(f"    [{PACKAGE}]")
            for mod in sorted(dh_in_file):
                funcs = dh_in_file[mod]
                total = sum(funcs.values())
                lines.append(f"      {mod:<30} {total} call(s)")
                for func, count in sorted(funcs.items(), key=lambda x: -x[1]):
                    if count > 0:
                        lines.append(f"        {func:<28} {count} time(s)")
    lines.append("")
    lines.append(f"{'=' * 40}")
    lines.append("  END OF REPORT")
    lines.append(f"{'=' * 40}")
    return "\n".join(lines), stdlib_counts, thirdparty_counts, dh_counts


def save_charts(
    stdlib_counts: Counter,
    thirdparty_counts: Counter,
    dh_counts: Counter,
    per_file_data: list[tuple[str, dict[str, dict[str, int]]]],
    stdlib_set: set[str],
) -> None:
    output_dir = Path.home()
    plt.style.use("seaborn-v0_8-darkgrid")
    if not stdlib_counts and not thirdparty_counts and not dh_counts:
        print("⚠️  No data to chart.")
        return
    print("\n📊 Generating matplotlib charts...")
    fig, ax = plt.subplots(figsize=(12, 6))
    top_stdlib = dict(sorted(stdlib_counts.items(), key=lambda x: -x[1])[:10])
    if top_stdlib:
        ax.barh(list(top_stdlib.keys()), list(top_stdlib.values()), color="#3498db")
        ax.set_xlabel("Total Calls")
        ax.set_title(
            "Top 10 Standard Library Modules by Usage", fontsize=14, fontweight="bold"
        )
        ax.invert_yaxis()
        plt.tight_layout()
        plt.savefig(output_dir / "01_stdlib_top10.png", dpi=100, bbox_inches="tight")
        plt.close()
        print("   ✅ Saved: 01_stdlib_top10.png")
    fig, ax = plt.subplots(figsize=(10, 8))
    category_counts = {
        "Standard Library": sum(stdlib_counts.values()),
        "Third-Party": sum(thirdparty_counts.values()),
        "Custom (dh)": sum(dh_counts.values()),
    }
    category_counts = {k: v for k, v in category_counts.items() if v > 0}
    if category_counts:
        colors = ["#3498db", "#e74c3c", "#2ecc71"]
        _wedges, _texts, autotexts = ax.pie(
            category_counts.values(),
            labels=category_counts.keys(),
            autopct="%1.1f%%",
            colors=colors[: len(category_counts)],
            startangle=90,
        )
        for autotext in autotexts:
            autotext.set_color("white")
            autotext.set_fontweight("bold")
        ax.set_title(
            "Import Usage Distribution by Category", fontsize=14, fontweight="bold"
        )
        plt.tight_layout()
        plt.savefig(
            output_dir / "02_category_distribution.png", dpi=100, bbox_inches="tight"
        )
        plt.close()
        print("   ✅ Saved: 02_category_distribution.png")
    fig, ax = plt.subplots(figsize=(12, 6))
    top_thirdparty = dict(sorted(thirdparty_counts.items(), key=lambda x: -x[1])[:10])
    if top_thirdparty:
        ax.barh(
            list(top_thirdparty.keys()), list(top_thirdparty.values()), color="#e74c3c"
        )
        ax.set_xlabel("Total Calls")
        ax.set_title(
            "Top 10 Third-Party Packages by Usage", fontsize=14, fontweight="bold"
        )
        ax.invert_yaxis()
        plt.tight_layout()
        plt.savefig(
            output_dir / "03_thirdparty_top10.png", dpi=100, bbox_inches="tight"
        )
        plt.close()
        print("   ✅ Saved: 03_thirdparty_top10.png")
    _fig, ax = plt.subplots(figsize=(12, 6))
    if dh_counts:
        ax.bar(list(dh_counts.keys()), list(dh_counts.values()), color="#2ecc71")
