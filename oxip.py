#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from multiprocessing import Pool, cpu_count
from pathlib import Path

from dh import get_files
from rich.progress import Progress


def optimize_png(path) -> int:
    path = Path(path)
    try:
        original_size = path.stat().st_size
        subprocess.run(
            ["oxipng", "-o", "max", "--quiet", "--strip", "safe", str(path), "--force"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        optimized_size = path.stat().st_size
        return original_size - optimized_size
    except subprocess.CalledProcessError:
        return 0


def main() -> None:
    cwd = Path.cwd()
    png_files = get_files(cwd, ext=[".png"])
    if not png_files:
        print("No PNG files found in the current directory or subdirectories.")
        return
    with Progress() as progress:
        task = progress.add_task("[cyan]Optimizing PNGs...", total=len(png_files))
        min(cpu_count(), 8)
        with Pool(8) as pool:
            for _ in pool.imap_unordered(optimize_png, png_files):
                progress.update(task, advance=1)
    total_space_freed = sum(optimize_png(path) for path in png_files) / (1024 * 1024)
    print(f"\n[bold green]Total space freed: {total_space_freed:.2f} MB[/bold green]")


if __name__ == "__main__":
    raise SystemExit(main())
