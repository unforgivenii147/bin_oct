#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path
from zipfile import ZipFile

from dh import fsz


def get_wheel_unpacked_size(wheel_path: Path) -> tuple[Path, int, str | None]:
    try:
        if not wheel_path.exists():
            return wheel_path, 0, f"File not found: {wheel_path}"
        if not wheel_path.is_file():
            return wheel_path, 0, f"Not a file: {wheel_path}"
        total_size = 0
        try:
            with ZipFile(wheel_path, "r") as whl:
                for info in whl.filelist:
                    total_size += info.file_size
        except Exception as e:
            return wheel_path, 0, f"Failed to read wheel: {e!s}"
        return wheel_path, total_size, None
    except Exception as e:
        return wheel_path, 0, f"Unexpected error: {e!s}"


def find_wheel_files(directory: Path, recursive: bool = False) -> list[Path]:
    if recursive:
        return list(directory.rglob("*.whl"))
    else:
        return list(directory.glob("*.whl"))


def main():
    parser = argparse.ArgumentParser(
        description="Report the overall unpacked size of .whl files"
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="Scan subdirectories recursively"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel jobs (default: {cpu_count()})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed information for each wheel",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )
    parser.add_argument(
        "-s",
        "--sort",
        choices=["name", "size"],
        default="name",
        help="Sort output by name or size (default: name)",
    )
    args = parser.parse_args()
    if not args.directory.exists():
        print(f"❌ Error: Directory not found: {args.directory}", file=sys.stderr)
        sys.exit(1)
    if not args.directory.is_dir():
        print(f"❌ Error: Not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)
    print(f"🔍 Scanning directory: {args.directory}")
    if args.recursive:
        print("   (recursive mode)")
    wheels = find_wheel_files(args.directory, args.recursive)
    if not wheels:
        print("⚠️  No .whl files found!")
        sys.exit(0)
    print(f"✓ Found {len(wheels)} .whl file(s)\n")
    print(f"⚙️  Processing wheels ({args.jobs} workers)...\n")
    results = []
    errors = []
    with Pool(args.jobs) as pool:
        for wheel_path, size, error in pool.imap_unordered(
            get_wheel_unpacked_size, wheels
        ):
            if error:
                errors.append((wheel_path, error))
            else:
                results.append((wheel_path, size))
    if args.sort == "size":
        results.sort(key=lambda x: x[1], reverse=True)
    else:
        results.sort(key=lambda x: x[0].name)
    total_unpacked_size = sum(size for _, size in results)
    if args.json:
        output = {
            "directory": str(args.directory),
            "recursive": args.recursive,
            "summary": {
                "total_wheels": len(wheels),
                "processed": len(results),
                "errors": len(errors),
                "total_unpacked_size_bytes": total_unpacked_size,
                "total_unpacked_size_formatted": fsz(total_unpacked_size),
            },
            "wheels": [],
        }
        for wheel_path, size in results:
            output["wheels"].append(
                {
                    "name": wheel_path.name,
                    "path": str(wheel_path),
                    "size_bytes": size,
                    "size_formatted": fsz(size),
                }
            )
        if errors:
            output["errors"] = []
            for wheel_path, error in errors:
                output["errors"].append({"path": str(wheel_path), "error": error})
        print(json.dumps(output, indent=2))
    else:
        print("-" * 40)
        print(f"{'Wheel File':<50} {'Unpacked Size':>20}")
        print("-" * 40)
        for wheel_path, size in results:
            name = wheel_path.name
            if len(name) > 45:
                name = "..." + name[-42:]
            print(f"{name:<50} {fsz(size):>20}")
        print("-" * 40)
        print(f"{'TOTAL':<50} {fsz(total_unpacked_size):>20}")
        print("-" * 40)
        if args.verbose:
            print("\n📊 Summary:")
            print(f"   Total wheels found:      {len(wheels)}")
            print(f"   Successfully processed:  {len(results)}")
            print(f"   Errors:                  {len(errors)}")
            print(
                f"   Average size per wheel:  {fsz(total_unpacked_size // len(results)) if results else 'N/A'}"
            )
        if errors:
            print(f"\n⚠️  Errors ({len(errors)}):")
            for wheel_path, error in errors:
                print(f"   • {wheel_path.name}: {error}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
