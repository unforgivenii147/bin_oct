#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from dh import fsz, runcmd
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

SO_PATTERN = re.compile(r"\.so(\.\d+)*$")
console = Console()


def process_file(path: Path) -> None:
    """Strip a single .so file"""
    _ret, _, _ = runcmd(["strip", str(path)], show_output=True)


def process_whl(whl_path: Path) -> None:
    """Process all .so files inside a .whl archive"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        with ZipFile(whl_path, "r") as zf:
            zf.extractall(tmpdir)
        so_files = [p for p in tmpdir.rglob("*") if SO_PATTERN.search(p.name)]
        for so_file in so_files:
            process_file(so_file)
        with ZipFile(whl_path, "w") as zf:
            for path in tmpdir.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmpdir))


def collect_files(cwd: Path, args: list[str]) -> list[Path]:
    """Collect .so files from args or recursively from cwd"""
    if args:
        return [Path(p) for p in args]
    so_files = [p for p in cwd.rglob("*") if SO_PATTERN.search(p.name) and p.is_file()]
    return so_files


def show_summary(files: list[Path]) -> None:
    """Display total count and size of .so files"""
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    console.print(
        f"[bold cyan]Total number of .so files:[/] [bold yellow]{len(files)}[/]"
    )
    console.print(
        f"[bold cyan]Total size of .so files:[/] [bold yellow]{fsz(total_size)}[/]"
    )


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = collect_files(cwd, args)
    so_files = [f for f in files if f.suffix in (".so",) or SO_PATTERN.search(f.name)]

    # Show summary at start
    console.print("[bold green]Starting .so stripping process...[/]")
    show_summary(so_files)

    # Process with progress bar
    with Progress(
        TextColumn("[bold blue]{task.description}[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[bold]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Stripping .so files...[/]", total=len(so_files))
        for so_file in so_files:
            process_file(so_file)
            progress.update(task, advance=1)

    console.print(
        f"[bold green]Done![/] Processed [bold yellow]{len(so_files)}[/] .so files."
    )
    show_summary(so_files)
