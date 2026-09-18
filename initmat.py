#!/data/data/com.termux/files/home/.local/bin/python
"""Initialize a maturin mixed Rust/Python project in the current directory.

Usage:
    python init_maturin_project.py [pkgname]

If pkgname is omitted, the current directory name is used.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def get_pkgname() -> str:
    raw = sys.argv[1] if len(sys.argv) > 1 else Path.cwd().name
    # Cargo allows '-', Python doesn't. Normalize to a safe identifier.
    pkgname = re.sub(r"[^0-9A-Za-z_]", "_", raw)
    if not pkgname.isidentifier():
        raise SystemExit(f"Invalid package name derived: {pkgname!r}")
    return pkgname


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  wrote {path.relative_to(Path.cwd())}")


def main() -> None:
    pkgname = get_pkgname()
    root = Path.cwd()
    print(f"Initializing maturin project '{pkgname}' in {root}\n")

    # ---- Rust side ---------------------------------------------------------
    write(
        root / "Cargo.toml",
        f"""[package]
name = "{pkgname}"
version = "0.1.0"
edition = "2021"

[lib]
name = "_{pkgname}"
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = {{ version = "0.22", features = ["extension-module"] }}
""",
    )

    write(
        root / "src" / "lib.rs",
        f"""use pyo3::prelude::*;

#[pyfunction]
fn sum_as_string(a: usize, b: usize) -> PyResult<String> {{
    Ok((a + b).to_string())
}}

#[pymodule]
fn _{pkgname}(m: &Bound<'_, PyModule>) -> PyResult<()> {{
    m.add_function(wrap_pyfunction!(sum_as_string, m)?)?;
    Ok(())
}}
""",
    )

    # ---- Python side -------------------------------------------------------
    write(
        root / "pyproject.toml",
        f"""[build-system]
requires = ["maturin>=1.5,<2.0"]
build-backend = "maturin"

[project]
name = "{pkgname}"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.8"
classifiers = [
    "Programming Language :: Rust",
    "Programming Language :: Python :: Implementation :: CPython",
]

[tool.maturin]
python-source = "python"
module-name = "{pkgname}._{pkgname}"
features = ["pyo3/extension-module"]
""",
    )

    write(
        root / "python" / pkgname / "__init__.py",
        f"""from ._{pkgname} import sum_as_string

__all__ = ["sum_as_string"]
""",
    )

    write(root / "python" / pkgname / "py.typed", "")

    # ---- Auxiliary files ---------------------------------------------------
    write(root / "README.md", f"# {pkgname}\n\nA maturin-based Rust/Python project.\n")

    write(
        root / ".gitignore",
        """/target
**/*.rs.bk
*.so
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
.maturin/
""",
    )

    write(
        root / "tests" / "test_pkgname.py",
        f"""from {pkgname} import sum_as_string


def test_sum_as_string():
    assert sum_as_string(1, 2) == "3"
""",
    )

    write(
        root / "benchmarks" / "bench.py",
        f"""import timeit

from {pkgname} import sum_as_string


def main() -> None:
    n = 100_000
    t = timeit.timeit(lambda: sum_as_string(1, 2), number=n)
    print(f"sum_as_string x{{n}}: {{t:.4f}}s")


if __name__ == "__main__":
    main()
""",
    )

    # ---- git ---------------------------------------------------------------
    print("\nInitializing git repository...")
    subprocess.run(["git", "init"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "\n`git commit` failed. Configure your identity first:\n"
            "    git config --global user.name  'Your Name'\n"
            "    git config --global user.email 'you@example.com'\n"
            "then re-run `git commit -m initial` in the project directory."
        )

    print(f"\nDone. Project '{pkgname}' initialized.")


if __name__ == "__main__":
    main()
