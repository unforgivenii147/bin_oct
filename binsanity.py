#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import concurrent.futures
import subprocess
from pathlib import Path

from binaryornot import is_binary
from dh import should_skip


def get_filez(root_dir: str | Path):
    from os import walk as os_walk

    visited_dirs: set[Path] = set()
    root_dir = Path(root_dir)
    if root_dir.is_dir():
        for dirpath, dirnames, filenames in os_walk(root_dir, topdown=True):
            base_path = Path(dirpath)
            for dirname in list(dirnames):
                full_path = base_path / dirname
                resolved_path = full_path.resolve()
                if should_skip(full_path) or resolved_path in visited_dirs:
                    dirnames.remove(dirname)
                visited_dirs.add(resolved_path)
            for filename in filenames:
                path = Path(dirpath) / filename
                if not should_skip(path):
                    yield path
    else:
        yield root_dir


def is_executable(path: Path) -> bool:
    return path.is_file() and path.stat().st_mode & 73 != 0


def is_elf(path: Path) -> bool:
    if not is_binary(str(path)):
        return False
    try:
        header = path.read_bytes()[:4]
        if header[:4] == b"\x7fELF":
            return True
        if header[:2] == b"#!":
            return False
    except OSError:
        pass
    return False


def get_binary_files(directory: Path) -> list[Path]:
    binaries = []
    try:
        for path in get_filez(directory):
            if ".git" in path.parts or path.is_symlink():
                continue
            if path.is_file() and is_executable(path) and is_elf(path):
                binaries.append(path)
    except PermissionError:
        pass
    return binaries


def test_executable(path: Path) -> tuple[Path, str | None]:
    test_args = ["--help", "-h", "--version", "-v", "--info"]
    for test_arg in test_args:
        try:
            result = subprocess.run(
                [str(path), test_arg], capture_output=True, text=True, timeout=2
            )
            if result.stderr:
                error_lower = result.stderr.lower()
                if any(
                    pattern in error_lower
                    for pattern in [
                        "error while loading shared libraries",
                        "cannot open shared object file",
                        "no such file",
                        "not found",
                        "failed to load",
                    ]
                ):
                    return (path, result.stderr.strip()[:200])
            if result.returncode == 0:
                return (path, None)
        except subprocess.TimeoutExpired:
            return (path, None)
        except FileNotFoundError:
            return (path, "File not found")
        except PermissionError:
            return (path, "Permission denied")
        except OSError as e:
            if "exec format error" in str(e):
                return (path, "Exec format error (wrong architecture)")
            return (path, str(e))
    try:
        result = subprocess.run([str(path)], capture_output=True, text=True, timeout=1)
        if result.stderr:
            error_lower = result.stderr.lower()
            if any(
                pattern in error_lower
                for pattern in [
                    "error while loading shared libraries",
                    "cannot open shared object file",
                    "no such file",
                ]
            ):
                return (path, result.stderr.strip()[:200])
        return (path, None)
    except subprocess.TimeoutExpired:
        return (path, None)
    except Exception as e:
        return (path, str(e)[:200])


def main() -> None:
    output_dir = Path.home() / "tmp"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "err"
    cwd = Path.cwd()
    binaries = get_binary_files(cwd)
    if not binaries:
        print("No executable binaries found in current directory")
        output_file.write_text("No executable binaries found in current directory\n")
        return
    print(f"Found {len(binaries)} binaries to test")
    print("Testing binaries in parallel...")
    failed_binaries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        future_to_binary = {
            executor.submit(test_executable, binary): binary for binary in binaries
        }
        for i, future in enumerate(
            concurrent.futures.as_completed(future_to_binary), 1
        ):
            binary = future_to_binary[future]
            try:
                path, error_msg = future.result()
                if error_msg:
                    failed_binaries.append((path, error_msg))
                    print(f"  [{i}/{len(binaries)}] ❌ {binary.name} - FAILED")
                else:
                    print(f"  [{i}/{len(binaries)}] ✅ {binary.name} - OK")
            except Exception as e:
                failed_binaries.append((binary, f"Test exception: {str(e)[:100]}"))
                print(f"  [{i}/{len(binaries)}] ⚠️ {binary.name} - ERROR")
    out_dir = cwd / "err"
    out_dir.mkdir(exist_ok=True)
    for path, _ in failed_binaries:
        new_path = out_dir / path.name
        path.rename(new_path)
    output_file.write_text(
        f"Binary Analysis Results\nDirectory: {cwd}\nTotal binaries tested: {
            len(binaries)
        }\nFailed binaries: {len(failed_binaries)}\n{'=' * 40}\n\n"
        + (
            "\n".join(
                (
                    f"Binary: {path}\nError:  {error_msg}\n{'-' * 40}"
                    for path, error_msg in failed_binaries
                )
            )
            if failed_binaries
            else "✓ All binaries tested successfully!\n"
        )
    )
    print("\n" + "=" * 35)
    print(f"Failed: {len(failed_binaries)}")
    print(f"Success: {len(binaries) - len(failed_binaries)}")
    if failed_binaries:
        for path, error_msg in failed_binaries:
            print(f"  • {path.name}")
            print(f"    → {error_msg[:100]}")
    else:
        print("\n✅ All binaries are working correctly!")
        print(f"Report written to: {output_file}")
    print("-" * 40)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
