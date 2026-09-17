#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def create_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Created: {path}")


def main():
    project_name = (
        input("Enter project name (e.g., my-cli-tool): ").strip().replace(" ", "-")
    )
    if not project_name:
        print("Project name cannot be empty.")
        sys.exit(1)
    pkg_name = project_name.replace("-", "_")
    author_name = input("Enter author name: ").strip() or "Your Name"
    author_email = input("Enter author email: ").strip() or "author@example.com"
    root = Path(project_name)
    if root.exists():
        print(f"Error: Directory '{project_name}' already exists.")
        sys.exit(1)
    print(f"\nScaffolding modern '{project_name}' layout with Typer CLI...")
    pyproject_content = f"""
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[project]
name = "{project_name}"
dynamic = ["version"]
description = "A standard library and CLI tool built with Typer."
readme = "README.md"
requires-python = ">=3.10"
authors = [
    {{ name = "{author_name}", email = "{author_email}" }}
]
classifiers = [
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
]
dependencies = [
    "typer>=0.12.0",
    "rich>=13.0.0",
]
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "black>=24.0.0",
    "flake8>=7.0.0",
]
[project.scripts]
{project_name} = "{pkg_name}.cli:app"
{project_name}-admin = "{pkg_name}.admin:app"
[tool.hatch.version]
path = "src/{pkg_name}/__init__.py"
[tool.black]
line-length = 88
target-version = ['py310']
"""
    init_content = '__version__ = "0.1.0"'
    cli_content = f"""
import typer
from rich import print
app = typer.Typer(help="Main CLI for {project_name}")
@app.command()
def hello(name: str = typer.Argument("World", help="The name to greet")):
    \"\"\"Greet someone politely.\"\"\"
    print(f"[bold green]Hello[/bold green] [cyan]{{name}}[/cyan]! Welcome to {project_name}.")
@app.command()
def version():
    \"\"\"Show tool version.\"\"\"
    from {pkg_name} import __version__
    print(f"{project_name} version: [yellow]{{__version__}}[/yellow]")
if __name__ == "__main__":
    app()
"""
    admin_content = f"""
import typer
from rich import print
app = typer.Typer(help="Administrative commands for {project_name}")
@app.command()
def setup():
    \"\"\"Initialize application system configs.\"\"\"
    print("[bold yellow]Initializing secure admin layout... Done.[/bold yellow]")
if __name__ == "__main__":
    app()
"""
    readme_content = f"""
A cookiecutter-pypackage styled boilerplate library including dual CLI entrypoints powered by Typer.
```bash
pip install .
```
For development installations:
```bash
pip install -e ".[dev]"
```
```bash
{project_name} hello --name Alice
```
```bash
{project_name}-admin setup
```
- Run tests: `pytest`
- Format code: `black .`
"""
    test_content = f"""
from typer.testing import CliRunner
from {pkg_name}.cli import app
runner = CliRunner()
def test_hello_endpoint():
    result = runner.invoke(app, ["hello", "Tester"])
    assert result.exit_code == 0
    assert "Hello Tester!" in result.stdout
"""
    create_file(root / "pyproject.toml", pyproject_content)
    create_file(root / "README.md", readme_content)
    create_file(root / "src" / pkg_name / "__init__.py", init_content)
    create_file(root / "src" / pkg_name / "cli.py", cli_content)
    create_file(root / "src" / pkg_name / "admin.py", admin_content)
    create_file(root / "tests" / "__init__.py", "")
    create_file(root / "tests" / "test_cli.py", test_content)
    print(
        f"\n[Success] Your library template '{project_name}' has been created successfully!"
    )
    print(f"Next steps:\n  cd {project_name}\n  pip install -e .[dev]\n  pytest")


if __name__ == "__main__":
    main()
